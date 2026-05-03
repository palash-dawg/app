import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
from datetime import datetime, timedelta

# --- BRANDING & CONNECTION ---
st.set_page_config(page_title="KBP ENERGY PVT LTD", layout="wide")
db = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- MODULE: IMAGE COMPRESSOR ---
def compress_worker_photo(uploaded_file):
    img = Image.open(uploaded_file).convert("RGB")
    quality, img_io = 80, io.BytesIO()
    while True:
        img_io.seek(0); img_io.truncate(0)
        img.save(img_io, format="JPEG", quality=quality, optimize=True)
        if img_io.tell() / 1024 <= 100 or quality <= 5: break
        quality -= 5
        if quality < 30: img = img.resize((int(img.width * 0.9), int(img.height * 0.9)))
    return img_io.getvalue()

# --- MODULE: DATA ENGINE ---
def get_processed_data():
    res = db.table("staff_master").select("*, attendance(status, date), advances(id, amount, date)").order("created_at").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        df = df.sort_values(by="created_at").reset_index(drop=True)
        df.insert(0, 'Emp ID', range(1, len(df) + 1))
        
        def calc_net(row):
            presents = sum(1 for a in row['attendance'] if a['status'] == 'Present')
            halfs = sum(1 for a in row['attendance'] if a['status'] == 'Half-Day')
            advs = sum(adv['amount'] for adv in row['advances']) if isinstance(row['advances'], list) else 0
            return (presents * row['daily_wage']) + (halfs * (row['daily_wage'] / 2)) - advs
        
        df['Net Payout'] = df.apply(calc_net, axis=1)
    return df

# --- AUTH GATE ---
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
st.sidebar.title("KBP ENERGY")
st.sidebar.write(f"Role: **{role}**")
page = st.sidebar.radio("Navigation", ["Worker Management", "Attendance Log", "Attendance History", "Export Center"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]; st.rerun()

# --- PAGE 1: WORKER MANAGEMENT ---
if page == "Worker Management":
    st.header("📝 Worker Management")
    if role != "Finance":
        with st.expander("➕ Register New Worker"):
            with st.form("reg_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name = c1.text_input("Full Name*")
                father = c2.text_input("Father's Name*")
                
                # INDIAN DATA LIMITS (Real-time char limits)
                mobile = c1.text_input("Mobile Number (10 Digits)*", max_chars=10)
                aadhar = c2.text_input("Aadhar Number (12 Digits)*", max_chars=12)
                
                dob = c1.date_input("Date of Birth", min_value=datetime(1960,1,1))
                acc = c2.text_input("Account No (9-18 Digits)*", max_chars=18)
                
                ifsc = c1.text_input("IFSC Code (11 Chars)*", max_chars=11)
                wage = c2.number_input("Daily Wage (₹)", value=500)
                
                photo = st.file_uploader("ID Photo", type=['jpg','png'])

                if st.form_submit_button("Add Worker"):
                    dup = db.table("staff_master").select("id").or_(f"aadhar_no.eq.{aadhar},account_no.eq.{acc}").execute()
                    if dup.data: st.error("🚨 DUPLICATE FOUND: Aadhar or Account exists!")
                    elif len(mobile) != 10: st.error("Mobile must be 10 digits.")
                    elif len(aadhar) != 12: st.error("Aadhar must be 12 digits.")
                    else:
                        url = ""
                        if photo:
                            img = compress_worker_photo(photo)
                            path = f"ids/{aadhar}.jpg"
                            db.storage.from_("staff_files").upload(path, img, {"content-type": "image/jpeg"})
                            url = db.storage.from_("staff_files").get_public_url(path)
                        db.table("staff_master").insert({"name": name, "father_name": father, "mobile_no": mobile, "aadhar_no": aadhar, "account_no": acc, "ifsc": ifsc, "dob": str(dob), "daily_wage": wage, "photo_url": url, "department": role}).execute()
                        st.success("Worker Registered. ID Sequence Shuffled."); st.rerun()

    df = get_processed_data()
    if not df.empty:
        st.subheader("📋 Worker Directory")
        for _, row in df.iterrows():
            c1, c2, c3 = st.columns([1, 4, 1])
            c1.write(f"**ID: {row['Emp ID']}**")
            c2.write(f"{row['name']} | Mob: {row['mobile_no']} | Aadhar: {row['aadhar_no']}")
            if role == "Admin" and c3.button("🗑️", key=f"del_{row['id']}"):
                db.table("staff_master").delete().eq("id", row['id']).execute()
                st.rerun()

# --- PAGE 2: ATTENDANCE LOG (MARK ALL EXCEPT...) ---
elif page == "Attendance Log":
    st.header("📅 Daily Attendance Log")
    df = get_processed_data()
    today = str(datetime.now().date())
    
    if not df.empty:
        c1, c2, c3 = st.columns([1, 1, 1])
        if c1.button("✅ Mark All Present"): st.session_state.att_state = True
        if c2.button("❌ Mark All Absent"): st.session_state.att_state = False
        if c3.button("🔄 Redo Today"):
            db.table("attendance").delete().eq("date", today).execute()
            st.rerun()

        if 'att_state' not in st.session_state: st.session_state.att_state = True
        df['Attend'] = st.session_state.att_state
        
        st.info("💡 **Mark All Except:** Use buttons above, then **untick** workers who are absent.")
        edited = st.data_editor(df[['Emp ID', 'name', 'Attend']], use_container_width=True, hide_index=True)
        
        if st.button("💾 Save Attendance"):
            batch = []
            for _, r in edited.iterrows():
                actual_id = df[df['Emp ID'] == r['Emp ID']]['id'].values[0]
                batch.append({"staff_id": actual_id, "date": today, "status": "Present" if r['Attend'] else "Absent"})
            db.table("attendance").upsert(batch).execute()
            st.success("Attendance Synced.")

# --- PAGE 3: INDIVIDUAL ATTENDANCE HISTORY ---
elif page == "Attendance History":
    st.header("👤 Individual Attendance Tracker")
    df = get_processed_data()
    if not df.empty:
        worker_choice = st.selectbox("Select Worker", df['name'].tolist())
        worker_id = df[df['name'] == worker_choice]['id'].values[0]
        
        time_range = st.radio("View History For:", ["Last Month", "Last 3 Months", "This Year"], horizontal=True)
        days = 30 if "Month" in time_range else (90 if "3" in time_range else 365)
        start_date = (datetime.now() - timedelta(days=days)).date()
        
        history = db.table("attendance").select("*").eq("staff_id", worker_id).gte("date", str(start_date)).order("date").execute()
        
        if history.data:
            h_df = pd.DataFrame(history.data)
            st.write(f"Attendance for **{worker_choice}** since {start_date}")
            st.dataframe(h_df[['date', 'status']], use_container_width=True)
        else:
            st.info("No records found for this period.")

# --- PAGE 4: EXPORT CENTER (TIME-BASED EXPORTS) ---
elif page == "Export Center":
    st.header("📥 Data Export Center")
    df = get_processed_data()
    
    if not df.empty:
        period = st.radio("Export Period:", ["Current Month", "Last 3 Months", "Yearly"], horizontal=True)
        days = 30 if "Month" in period else (90 if "3" in period else 365)
        start_date = (datetime.now() - timedelta(days=days)).date()
        
        # Filter Logic for Export
        hr_cols = ['Emp ID', 'name', 'mobile_no', 'dob', 'aadhar_no']
        fin_cols = ['Emp ID', 'name', 'bank_name', 'account_no', 'ifsc', 'Net Payout']
        
        if role == "Admin":
            c1, c2, c3 = st.columns(3)
            c1.download_button("HR Report (CSV)", df[hr_cols].to_csv(index=False), f"KBP_HR_{period}.csv")
            c2.download_button("Finance Report (CSV)", df[fin_cols].to_csv(index=False), f"KBP_FIN_{period}.csv")
            c3.download_button("Full Master Report", df.to_csv(index=False), "KBP_Master.csv")
        elif role == "HR":
            st.download_button("Export Worker Details", df[hr_cols].to_csv(index=False), "KBP_HR.csv")
        elif role == "Finance":
            st.download_button("Export Banking Details", df[fin_cols].to_csv(index=False), "KBP_FIN.csv")
        
        st.dataframe(df, use_container_width=True)
