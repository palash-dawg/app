import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
from datetime import datetime, timedelta

# --- 1. BRANDING & DB CONFIG ---
st.set_page_config(page_title="KBP ENERGY PVT LTD - Site OS", layout="wide", page_icon="⚡")

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()

# --- 2. UTILITY: 100KB COMPRESSOR ---
def compress_photo(uploaded_file):
    img = Image.open(uploaded_file).convert("RGB")
    quality, img_io = 80, io.BytesIO()
    while True:
        img_io.seek(0); img_io.truncate(0)
        img.save(img_io, format="JPEG", quality=quality, optimize=True)
        if img_io.tell() / 1024 <= 100 or quality <= 5: break
        quality -= 5
        if quality < 30: img = img.resize((int(img.width * 0.8), int(img.height * 0.8)))
    return img_io.getvalue()

# --- 3. CORE ENGINE: SEQUENTIAL IDs & MATH ---
def get_master_data():
    """Fetches staff and calculates serial Emp IDs and Payouts."""
    res = db.table("staff_master").select("*, attendance(status, date), advances(id, amount, date)").order("created_at").execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        # Filter for active workers (those who haven't left) for specific UI parts
        # But we keep all in the master DF for HR Export
        df = df.sort_values(by="created_at").reset_index(drop=True)
        df.insert(0, 'Emp ID', range(1, len(df) + 1))
        
        def calc_net(row):
            presents = sum(1 for a in row['attendance'] if a['status'] == 'Present')
            halfs = sum(1 for a in row['attendance'] if a['status'] == 'Half-Day')
            advs = sum(adv['amount'] for adv in row['advances']) if isinstance(row['advances'], list) else 0
            return (presents * row['daily_wage']) + (halfs * (row['daily_wage'] / 2)) - advs
        
        df['Net Payout'] = df.apply(calc_net, axis=1)
    return df

# --- 4. AUTHENTICATION ---
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
st.sidebar.write(f"Role: **{role}**")
page = st.sidebar.radio("Navigation", ["Worker Management", "Attendance Log", "Attendance Reports", "Export Center"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]; st.rerun()

# --- 5. PAGE: WORKER MANAGEMENT (Enrollment & Deactivation) ---
if page == "Worker Management":
    st.header("📝 Registration & Directory")
    
    if role != "Finance":
        with st.expander("➕ Enroll New Staff"):
            with st.form("enroll_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name, father = c1.text_input("Full Name*"), c2.text_input("Father's Name*")
                dob = c1.date_input("Date of Birth", min_value=datetime(1960,1,1))
                
                # --- INDIAN DATA LIMITS ---
                mobile = c2.text_input("Mobile No*", max_chars=10)
                aadhar = c1.text_input("Aadhar No*", max_chars=12)
                acc = c2.text_input("Bank Account No*", max_chars=18)
                ifsc = c1.text_input("IFSC Code*", max_chars=11)
                
                wage = c2.number_input("Daily Wage (₹)", value=500)
                photo = st.file_uploader("Upload ID Photo", type=['jpg','png'])

                if st.form_submit_button("Register Worker"):
                    dup = db.table("staff_master").select("id").or_(f"aadhar_no.eq.{aadhar},account_no.eq.{acc}").execute()
                    if dup.data: st.error("🚨 DUPLICATION: Aadhar or Account already registered!")
                    else:
                        img_url = ""
                        if photo:
                            img_bytes = compress_photo(photo)
                            path = f"ids/{aadhar}.jpg"; db.storage.from_("staff_files").upload(path, img_bytes, {"content-type": "image/jpeg"})
                            img_url = db.storage.from_("staff_files").get_public_url(path)
                        
                        db.table("staff_master").insert({
                            "name": name, "father_name": father, "dob": str(dob), "mobile_no": mobile,
                            "aadhar_no": aadhar, "account_no": acc, "ifsc": ifsc, "daily_wage": wage,
                            "photo_url": img_url, "department": role
                        }).execute()
                        st.success("Worker Registered!"); st.rerun()

    df = get_master_data()
    if not df.empty:
        st.subheader("📋 Active Directory")
        for _, row in df.iterrows():
            if row.get('leave_date') is None: # Only show active ones in this view
                dc1, dc2, dc3, dc4 = st.columns([0.5, 3, 1.5, 1])
                dc1.write(f"#{row['Emp ID']}")
                dc2.write(f"**{row['name']}** | Aadhar: {row['aadhar_no']}")
                
                # Button to mark worker as Left
                if dc3.button("Mark as Left", key=f"left_{row['id']}"):
                    today = str(datetime.now().date())
                    db.table("staff_master").update({"leave_date": today}).eq("id", row['id']).execute()
                    st.rerun()

                if role == "Admin":
                    if dc4.button("🗑️ Delete", key=f"del_{row['id']}"):
                        db.table("staff_master").delete().eq("id", row['id']).execute()
                        st.rerun()

# --- 6. PAGE: ATTENDANCE LOG (MARK ALL EXCEPT ALGORITHM) ---
elif page == "Attendance Log":
    st.header("📅 Daily Log")
    df = get_master_data()
    # Filter only active staff (those who haven't left)
    active_df = df[df['leave_date'].isna()]
    today = str(datetime.now().date())
    
    if not active_df.empty:
        tc1, tc2, tc3 = st.columns([1,1,1])
        if tc1.button("✅ Mark ALL Present"): st.session_state.att_bulk = True
        if tc2.button("❌ Mark ALL Absent"): st.session_state.att_bulk = False
        if tc3.button("🔄 Reset Today"):
            db.table("attendance").delete().eq("date", today).execute()
            st.rerun()

        if 'att_bulk' not in st.session_state: st.session_state.att_bulk = True
        active_df['Attend'] = st.session_state.att_bulk
        
        st.info("💡 **Mark All Except:** Select all, then **untick** those who are absent.")
        edited = st.data_editor(active_df[['Emp ID', 'name', 'Attend']], use_container_width=True, hide_index=True)
        
        if st.button("💾 Save Attendance"):
            batch = [{"staff_id": active_df[active_df['Emp ID'] == r['Emp ID']]['id'].values[0], "date": today, "status": "Present" if r['Attend'] else "Absent"} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.success("Synced.")
    else: st.warning("No active workers to mark.")

# --- 7. PAGE: ATTENDANCE REPORTS (INDIVIDUAL + TEAM SUMMARY) ---
elif page == "Attendance Reports":
    st.header("📊 Attendance Reporting")
    df = get_master_data()
    
    tab1, tab2 = st.tabs(["👤 Individual Audit", "👥 Team Summary Report"])
    
    with tab1:
        worker = st.selectbox("Select Worker", df['name'].tolist())
        w_id = df[df['name'] == worker]['id'].values[0]
        t_range = st.radio("History:", ["30 Days", "90 Days", "Full Year"], horizontal=True, key="ind")
        days = 30 if "30" in t_range else (90 if "90" in t_range else 365)
        start_dt = (datetime.now() - timedelta(days=days)).date()
        
        logs = db.table("attendance").select("*").eq("staff_id", w_id).gte("date", str(start_dt)).order("date").execute()
        if logs.data:
            st.dataframe(pd.DataFrame(logs.data)[['date', 'status']], use_container_width=True, hide_index=True)
        else: st.info("No logs found.")

    with tab2:
        st.subheader("Team Performance Summary")
        period = st.radio("Summary Period:", ["30 Days", "90 Days", "Full Year"], horizontal=True, key="team")
        p_days = 30 if "30" in period else (90 if "90" in period else 365)
        p_start = (datetime.now() - timedelta(days=p_days)).date()
        
        # Calculate Bulk Stats
        summary_list = []
        for _, row in df.iterrows():
            att_records = [a for a in row['attendance'] if datetime.strptime(a['date'], '%Y-%m-%d').date() >= p_start]
            presents = sum(1 for a in att_records if a['status'] == 'Present')
            absents = sum(1 for a in att_records if a['status'] == 'Absent')
            summary_list.append({
                "Emp ID": row['Emp ID'],
                "Name": row['name'],
                "Total Presents": presents,
                "Total Absents": absents,
                "Attendance %": round((presents / (presents + absents)) * 100, 1) if (presents + absents) > 0 else 0
            })
        summary_df = pd.DataFrame(summary_list)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
        st.download_button(f"📥 Download Team {period} Report", summary_df.to_csv(index=False), f"Team_Attendance_{period}.csv")

# --- 8. PAGE: EXPORT CENTER (TIME-BASED + LEAVE DATE) ---
elif page == "Export Center":
    st.header("📥 Data Exports")
    df = get_master_data()
    
    if not df.empty:
        # HR Columns now include Leave Date
        hr_cols = ['Emp ID', 'name', 'mobile_no', 'dob', 'aadhar_no', 'leave_date']
        fin_cols = ['Emp ID', 'name', 'bank_name', 'account_no', 'ifsc', 'Net Payout']
        
        if role == "Admin":
            c1, c2, c3 = st.columns(3)
            c1.download_button("Export HR Master (With Leave Date)", df[hr_cols].to_csv(index=False), "KBP_HR_Master.csv")
            c2.download_button("Export Finance/Bank Report", df[fin_cols].to_csv(index=False), "KBP_Finance_Bank.csv")
            c3.download_button("Full Master Backup", df.to_csv(index=False), "KBP_Master_Full.csv")
        elif role == "HR":
            st.download_button("Export HR Records", df[hr_cols].to_csv(index=False), "KBP_HR_Records.csv")
        elif role == "Finance":
            st.download_button("Export Bank Payouts", df[fin_cols].to_csv(index=False), "KBP_Finance_Records.csv")
        
        st.dataframe(df, use_container_width=True)
