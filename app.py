import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
import random
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

# --- 1. BRANDING & DB CONFIG ---
st.set_page_config(page_title="KBP ENERGY PVT LTD - Site OS", layout="wide", page_icon="⚡")

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()

# --- 2. GOOGLE BACKUP SYSTEM ---
def init_google():
    """Initializes Google Credentials for Drive and Sheets."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)

def sync_to_sheets(row_data):
    """Appends a new worker row to the Google Sheet live backup."""
    try:
        creds = init_google()
        client = gspread.authorize(creds)
        sheet = client.open("KBP_WORKFORCE_BACKUP").sheet1
        row_data.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        sheet.append_row(row_data)
        st.toast("⚡ Backed up to Google Sheets")
    except Exception as e:
        st.warning(f"Google Sheets backup failed: {e}")

def upload_csv_to_drive(df):
    """Creates a Payroll Summary AND a Day-by-Day Calendar Grid in Google Sheets."""
    try:
        creds = init_google()
        client = gspread.authorize(creds)
        spreadsheet = client.open("KBP_FULL_SNAPSHOT")
        
        # --- PART 1: MASTER SUMMARY (Payroll Totals) ---
        try:
            summary_sheet = spreadsheet.worksheet("Master_Summary")
        except:
            summary_sheet = spreadsheet.add_worksheet(title="Master_Summary", rows="1000", cols="20")
            
        # Remove 'department' as requested
        export_df = df.drop(columns=['department']) if 'department' in df.columns else df
        safe_df = export_df.fillna("").astype(str)
        summary_data = [safe_df.columns.values.tolist()] + safe_df.values.tolist()
        
        summary_sheet.clear()
        summary_sheet.update('A1', summary_data)

        # --- PART 2: CALENDAR GRID (Day-by-Day) ---
        try:
            grid_sheet = spreadsheet.worksheet("Attendance_Grid")
        except:
            grid_sheet = spreadsheet.add_worksheet(title="Attendance_Grid", rows="1000", cols="40")

        raw_att = []
        for _, row in df.iterrows():
            att_list = row.get('attendance') or []
            for entry in att_list:
                if entry:
                    raw_att.append({
                        "Name": row['name'],
                        "Date": entry.get('date'),
                        "Status": entry.get('status')[0] # 'P', 'A', or 'H'
                    })
        
        if raw_att:
            att_df = pd.DataFrame(raw_att)
            # Pivot names to rows and dates to columns
            pivot_df = att_df.pivot(index='Name', columns='Date', values='Status').fillna("-")
            pivot_df.reset_index(inplace=True)
            
            grid_data = [pivot_df.columns.values.tolist()] + pivot_df.values.tolist()
            grid_sheet.clear()
            grid_sheet.update('A1', grid_data)
        
        st.success("✅ Double-Tab Backup (Summary + Grid) Synced Successfully!")
    except Exception as e:
        st.error(f"Google Drive Backup Failed: {e}")

# --- 3. DATA ENGINE ---
@st.cache_data(ttl=600)
def get_master_data():
    try:
        res = db.table("staff_master").select("*, attendance(status, date), advances(amount)").order("created_at").execute()
    except Exception as e:
        st.error(f"🚨 DATABASE ERROR: {e}")
        return pd.DataFrame()
    
    if not res.data:
        return pd.DataFrame(columns=['id', 'Emp ID', 'name', 'father_name', 'dob', 'mobile_no', 'aadhar_no', 'account_no', 'ifsc', 'daily_wage', 'photo_url', 'department', 'leave_date', 'created_at', 'Net Payout'])
        
    df = pd.DataFrame(res.data)
    if not df.empty:
        df = df.sort_values(by="created_at").reset_index(drop=True)
        df.insert(0, 'Emp ID', range(1, len(df) + 1))
        
        def fast_calc(row):
            att = row.get('attendance') or []
            presents = sum(1 for x in att if x and x.get('status') == 'Present')
            halfs = sum(1 for x in att if x and x.get('status') == 'Half-Day')
            advs = sum(a.get('amount', 0) for a in row.get('advances', [])) if isinstance(row.get('advances'), list) else 0
            return (presents * row.get('daily_wage', 0)) + (halfs * (row.get('daily_wage', 0) / 2)) - advs
        
        df['Net Payout'] = df.apply(fast_calc, axis=1)
    return df

# --- 4. PHOTO COMPRESSOR ---
def compress_photo(uploaded_file):
    img = Image.open(uploaded_file).convert("RGB")
    quality, img_io = 80, io.BytesIO()
    while True:
        img_io.seek(0); img_io.truncate(0)
        img.save(img_io, format="JPEG", quality=quality, optimize=True)
        if img_io.tell() / 1024 <= 100 or quality <= 5: break
        quality -= 5
    return img_io.getvalue()

# --- AUTH & NAVIGATION ---
if "user_role" not in st.session_state:
    st.title("🏗️ KBP ENERGY PVT LTD")
    with st.form("login"):
        u, p = st.text_input("Username").lower(), st.text_input("Password", type="password")
        if st.form_submit_button("Log In"):
            creds = st.secrets["CREDENTIALS"]
            if u in creds and creds[u] == p:
                st.session_state.user_role = "Admin" if "admin" in u else ("HR" if "hr" in u else "Finance")
                st.rerun()
            else: st.error("Access Denied")
    st.stop()

role = st.session_state.user_role
st.sidebar.title("⚡ KBP ENERGY")
page = st.sidebar.radio("Navigation", ["Worker Management", "Attendance Log", "Attendance Reports", "Export Center"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]; st.cache_data.clear(); st.rerun()

# --- PAGES (LOGIC) ---
if page == "Worker Management":
    st.header("📝 Registration & Directory")
    if role != "Finance":
        with st.expander("➕ Enroll New Staff"):
            with st.form("enroll_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name, father = c1.text_input("Full Name*"), c2.text_input("Father's Name*")
                dob, mobile = c1.date_input("Date of Birth"), c2.text_input("Mobile No*", max_chars=10)
                aadhar, acc = c1.text_input("Aadhar No*"), c2.text_input("Bank Acc*")
                ifsc, wage = c1.text_input("IFSC*"), c2.number_input("Daily Wage (₹)", value=500)
                photo = st.file_uploader("Upload ID Photo", type=['jpg','png'])

                if st.form_submit_button("Register Worker"):
                    img_url = ""
                    if photo:
                        img_bytes = compress_photo(photo)
                        path = f"ids/{aadhar}.jpg"
                        db.storage.from_("staff_files").upload(path, img_bytes, {"content-type": "image/jpeg"})
                        img_url = db.storage.from_("staff_files").get_public_url(path)
                    try:
                        db.table("staff_master").insert({"name": name, "father_name": father, "dob": str(dob), "mobile_no": mobile, "aadhar_no": aadhar, "account_no": acc, "ifsc": ifsc, "daily_wage": wage, "photo_url": img_url, "department": role}).execute()
                        sync_to_sheets([name, father, str(dob), mobile, aadhar, acc, ifsc, wage])
                        st.success("Registered!")
                    except Exception as e: st.error(f"Error: {e}")
                    st.cache_data.clear(); st.rerun()

    df = get_master_data()
    if not df.empty:
        active_df = df[df['leave_date'].isna()]
        for _, row in active_df.iterrows():
            with st.container():
                dc1, dc2, dc3 = st.columns([1, 4, 1])
                dc1.write(f"#{row['Emp ID']}")
                dc2.write(f"**{row['name']}**")
                if dc3.button("Mark Left", key=f"l_{row['id']}"):
                    db.table("staff_master").update({"leave_date": str(datetime.now().date())}).eq("id", row['id']).execute()
                    st.cache_data.clear(); st.rerun()
            st.divider()

elif page == "Attendance Log":
    st.header("📅 Daily Log")
    df = get_master_data()
    if not df.empty:
        active_df = df[df['leave_date'].isna()].copy()
        today = str(datetime.now().date())
        active_df['Attend'] = True
        edited = st.data_editor(active_df[['Emp ID', 'name', 'Attend']], use_container_width=True, hide_index=True)
        if st.button("💾 Save Attendance"):
            batch = [{"staff_id": active_df[active_df['Emp ID'] == r['Emp ID']]['id'].values[0], "date": today, "status": "Present" if r['Attend'] else "Absent"} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.cache_data.clear(); st.success("Synced.")

elif page == "Attendance Reports":
    st.header("📊 Reporting")
    df = get_master_data()
    if not df.empty:
        st.dataframe(df[['Emp ID', 'name', 'Net Payout']], use_container_width=True)

elif page == "Export Center":
    st.header("📥 Exports & Backups")
    df = get_master_data()
    
    if not df.empty:
        c1, c2 = st.columns(2)
        c1.download_button("📥 Export HR CSV", df[['Emp ID','name','aadhar_no']].to_csv(index=False), "HR_Master.csv")
        c2.download_button("📥 Export Finance CSV", df[['Emp ID','name','account_no','Net Payout']].to_csv(index=False), "Finance_Payouts.csv")
        
        if role == "Admin":
            st.divider()
            st.subheader("☁️ Cloud Backup")
            if st.button("🚀 Backup Full Master to Google Drive"):
                with st.spinner("Creating Summary & Grid..."):
                    upload_csv_to_drive(df)
    
    if role == "Admin":
        st.divider()
        st.subheader("🛠️ Developer Tools")
        colA, colB = st.columns(2)
        if colA.button("🧹 Clean Up Trial Data"):
            db.table("staff_master").delete().ilike("name", "%(Trial)").execute()
            st.cache_data.clear(); st.rerun()
        
        if colB.button("🪄 Generate 100 Workers + Attendance"):
            with st.spinner("Generating..."):
                workers_db = []
                for i in range(1, 101):
                    workers_db.append({"name": f"Worker {i} (Trial)", "aadhar_no": str(i), "daily_wage": 500, "department": "Admin"})
                res = db.table("staff_master").insert(workers_db).execute()
                
                att_db = []
                for w in res.data:
                    for d in range(1, 11):
                        date = str((datetime.now() - timedelta(days=d)).date())
                        att_db.append({"staff_id": w['id'], "date": date, "status": "Present"})
                db.table("attendance").insert(att_db).execute()
                st.cache_data.clear(); st.rerun()
