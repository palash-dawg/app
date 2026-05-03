import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
from datetime import datetime, timedelta

# --- 1. BRANDING & DB CONNECTION ---
st.set_page_config(page_title="KBP ENERGY PVT LTD", layout="wide", page_icon="⚡")

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()

# --- 2. IMAGE COMPRESSOR (< 100KB) ---
def compress_worker_photo(uploaded_file):
    img = Image.open(uploaded_file).convert("RGB")
    quality, img_io = 80, io.BytesIO()
    while True:
        img_io.seek(0); img_io.truncate(0)
        img.save(img_io, format="JPEG", quality=quality, optimize=True)
        size_kb = img_io.tell() / 1024
        if size_kb <= 100 or quality <= 5: break
        quality -= 5
        if quality < 30: img = img.resize((int(img.width * 0.8), int(img.height * 0.8)))
    return img_io.getvalue()

# --- 3. THE BRAIN: SEQUENTIAL ID & DATA ENGINE ---
def get_sequenced_data():
    """Fetches all staff, sorts by joining date, and assigns serial Emp IDs."""
    # Fetching staff, attendance, and advances in one go
    res = db.table("staff_master").select("*, attendance(status, date), advances(amount, id)").order("created_at").execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        # SHUFFLE LOGIC: Re-sort by joining date and assign 1, 2, 3...
        df = df.sort_values(by="created_at").reset_index(drop=True)
        df.insert(0, 'Emp ID', range(1, len(df) + 1))
        
        # Payroll Math Logic
        def calculate_payout(row):
            presents = sum(1 for a in row['attendance'] if a['status'] == 'Present')
            halfs = sum(1 for a in row['attendance'] if a['status'] == 'Half-Day')
            advs = sum(adv['amount'] for adv in row['advances']) if isinstance(row['advances'], list) else 0
            # Net = (Full * Wage) + (Half * Wage/2) - Advances
            return (presents * row['daily_wage']) + (halfs * (row['daily_wage']/2)) - advs
        
        df['Net Payout'] = df.apply(calculate_payout, axis=1)
    return df

# --- 4. AUTH GATEKEEPER ---
if "user_role" not in st.session_state:
    st.title("🏗️ KBP ENERGY PVT LTD")
    st.info("Site Workforce Management System")
    with st.form("login"):
        u = st.text_input("Username").lower()
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Log In"):
            creds = st.secrets["CREDENTIALS"]
            if u in creds and creds[u] == p:
                st.session_state.user_role = "Admin" if "admin" in u else ("HR" if "hr" in u else "Finance")
                st.rerun()
            else: st.error("Invalid Credentials")
    st.stop()

role = st.session_state.user_role
st.sidebar.title("⚡ KBP ENERGY")
st.sidebar.write(f"Access Level: **{role}**")
page = st.sidebar.radio("Navigation", ["Worker Management", "Attendance Log", "Attendance History", "Export Center"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]; st.rerun()

# --- PAGE 1: WORKER MANAGEMENT (Enrollment & Deletion) ---
if page == "Worker Management":
    st.header("📝 Worker Management")
    
    if role != "Finance":
        with st.expander("➕ Enroll New Worker"):
            with st.form("enroll_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name = c1.text_input("Full Name*")
                father = c2.text_input("Father's Name*")
                dob = c1.date_input("Date of Birth", min_value=datetime(1960,1,1))
                # INDIAN DATA LIMITS (Immediate Validation)
                mobile = c2.text_input("Mobile No (10 Digits)*", max_chars=10)
                aadhar = c1.text_input("Aadhar No (12 Digits)*", max_chars=12)
                acc = c2.text_input("Bank Account No (Max 18)*", max_chars=18)
                ifsc = c1.text_input("IFSC Code (11 Chars)*", max_chars=11)
                wage = c2.number_input("Daily Wage Rate (₹)", value=500)
                photo = st.file_uploader("Upload ID Photo", type=['jpg','png'])

                if st.form_submit_button("Save to Site Cloud"):
                    # Check for duplicates before saving
                    dup = db.table("staff_master").select("id").or_(f"aadhar_no.eq.{aadhar},account_no.eq.{acc}").execute()
                    if dup.data: st.error("🚨 DUPLICATION: Aadhar or Account already exists!")
                    elif len(mobile) < 10 or len(aadhar) < 12: st.error("Check Mobile/Aadhar length.")
                    else:
                        img_url = ""
                        if photo:
                            img_bytes = compress_worker_photo(photo)
                            path = f"ids/{aadhar}.jpg"
                            db.storage.from_("staff_files").upload(path, img_bytes, {"content-type": "image/jpeg"})
                            img_url = db.storage.from_("staff_files").get_public_url(path)
                        
                        db.table("staff_master").insert({
                            "name": name, "father_name": father, "dob": str(dob), "mobile_no": mobile,
                            "aadhar_no": aadhar, "account_no": acc, "ifsc": ifsc, "daily_wage": wage,
                            "photo_url": img_url, "department": role
                        }).execute()
                        st.success("Worker Registered. IDs Shuffled."); st.rerun()

    df = get_sequenced_data()
    if not df.empty:
        st.subheader("📋 Active Worker Directory")
        for _, row in df.iterrows():
            c1, c2, c3 = st.columns([1, 4, 1])
            c1.write(f"**Emp ID: {row['Emp ID']}**")
            c2.write(f"**{row['name']}** | Mob: {row.get('mobile_no', 'N/A')} | Aadhar: {row['aadhar_no']}")
            if role == "Admin":
                if c3.button("🗑️", key=f"del_{row['id']}"):
                    db.table("staff_master").delete().eq("id", row['id']).execute()
                    st.rerun()

# --- PAGE 2: ATTENDANCE LOG (MARK ALL EXCEPT ALGORITHM) ---
elif page == "Attendance Log":
    st.header("📅 Daily Attendance Log")
    df = get_sequenced_data()
    today = str(datetime.now().date())
    
    if not df.empty:
        col1, col2, col3 = st.columns([1,1,1])
        if col1.button("✅ Mark ALL Present"): st.session_state.att_bulk = True
        if col2.button("❌ Mark ALL Absent"): st.session_state.att_bulk = False
        if col3.button("🔄 Redo Today"):
            db.table("attendance").delete().eq("date", today).execute()
            st.rerun()

        if 'att_bulk' not in st.session_state: st.session_state.att_bulk = True
        
        df['Attend'] = st.session_state.att_bulk
        st.info("💡 **ALGORITHM:** Use buttons to mark all, then **untick** specific people who are missing.")
        
        # Interactive Editor
        edited = st.data_editor(df[['Emp ID', 'name', 'Attend']], use_container_width=True, hide_index=True)
        
        if st.button("💾 Commit Attendance to Cloud"):
            batch = []
            for _, r in edited.iterrows():
                # Find real DB ID
                actual_id = df[df['Emp ID'] == r['Emp ID']]['id'].values[0]
                batch.append({"staff_id": actual_id, "date": today, "status": "Present" if r['Attend'] else "Absent"})
            db.table("attendance").upsert(batch).execute()
            st.success("Attendance Logs Synced Successfully.")

# --- PAGE 3: ATTENDANCE HISTORY (INDIVIDUAL CHECK) ---
elif page == "Attendance History":
    st.header("👤 Personal Attendance Auditor")
    df = get_sequenced_data()
    if not df.empty:
        worker_name = st.selectbox("Search Worker", df['name'].tolist())
        worker_id = df[df['name'] == worker_name]['id'].values[0]
        
        range_sel = st.radio("History Period:", ["Last Month", "Last 3 Months", "Full Year"], horizontal=True)
        days_back = 30 if "Month" in range_sel else (90 if "3" in range_sel else 365)
        start_dt = (datetime.now() - timedelta(days=days_back)).date()
        
        history = db.table("attendance").select("*").eq("staff_id", worker_id).gte("date", str(start_dt)).order("date").execute()
        
        if history.data:
            h_df = pd.DataFrame(history.data)
            st.write(f"Showing records for **{worker_name}** since {start_dt}")
            st.dataframe(h_df[['date', 'status']], use_container_width=True, hide_index=True)
        else:
            st.info("No logs found for this period.")

# --- PAGE 4: EXPORT CENTER (TRIPLE-TIER DOWNLOADS) ---
elif page == "Export Center":
    st.header("📥 Data Export Center")
    df = get_sequenced_data()
    
    if not df.empty:
        st.write("Selected period for calculation: **Last 30 Days**")
        
        hr_data = df[['Emp ID', 'name', 'father_name', 'dob', 'mobile_no', 'aadhar_no']]
        fin_data = df[['Emp ID', 'name', 'bank_name', 'account_no', 'ifsc', 'daily_wage', 'Net Payout']]
        
        if role == "Admin":
            st.subheader("Admin Control Panel")
            c1, c2, c3 = st.columns(3)
            c1.download_button("📥 HR Directory (CSV)", hr_data.to_csv(index=False), "KBP_HR_Report.csv")
            c2.download_button("📥 Finance/Bank (CSV)", fin_data.to_csv(index=False), "KBP_Finance_Report.csv")
            c3.download_button("📥 Full Master Backup", df.to_csv(index=False), "KBP_Full_Master.csv")
            st.dataframe(df, use_container_width=True)
            
        elif role == "HR":
            st.subheader("HR Management Data")
            st.dataframe(hr_data, use_container_width=True)
            st.download_button("📥 Export Worker List", hr_data.to_csv(index=False), "KBP_HR_Report.csv")
            
        elif role == "Finance":
            st.subheader("Financial & Banking Data")
            st.dataframe(fin_data, use_container_width=True)
            st.download_button("📥 Export Bank CSV", fin_data.to_csv(index=False), "KBP_Finance_Report.csv")
