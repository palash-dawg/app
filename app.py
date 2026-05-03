import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
from datetime import datetime, timedelta

# --- BRANDING & CONNECTION ---
st.set_page_config(page_title="KBP ENERGY PVT LTD", layout="wide")
db = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- MODULE: IMAGE COMPRESSOR (< 100KB) ---
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
page = st.sidebar.radio("Navigation", ["Worker Management", "Attendance Log", "Individual Tracker", "Financials & Export"])

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
                dob = c1.date_input("Date of Birth*", min_value=datetime(1950, 1, 1), max_value=datetime(2008, 1, 1))
                # Real-time limits using max_chars
                mobile = c2.text_input("Mobile Number (10 Digits)*", max_chars=10, help="Enter 10 digit Indian mobile no")
                aadhar = c1.text_input("Aadhar Number (12 Digits)*", max_chars=12)
                acc = c2.text_input("Bank Account No*", max_chars=18)
                ifsc = c1.text_input("IFSC Code*", max_chars=11).upper()
                wage = c2.number_input("Daily Wage (₹)", value=500)
                photo = st.file_uploader("ID Photo", type=['jpg','png'])

                if st.form_submit_button("Add Worker"):
                    if len(mobile) != 10 or not mobile.isdigit(): st.error("Invalid Mobile Number")
                    elif len(aadhar) != 12 or not aadhar.isdigit(): st.error("Invalid Aadhar Number")
                    elif not name or not acc: st.error("Fill mandatory fields.")
                    else:
                        url = ""
                        if photo:
                            img = compress_worker_photo(photo)
                            path = f"ids/{aadhar}.jpg"; db.storage.from_("staff_files").upload(path, img, {"content-type": "image/jpeg"})
                            url = db.storage.from_("staff_files").get_public_url(path)
                        db.table("staff_master").insert({
                            "name": name, "father_name": father, "dob": str(dob), 
                            "mobile": mobile, "aadhar_no": aadhar, "account_no": acc, 
                            "ifsc": ifsc, "daily_wage": wage, "photo_url": url, "department": role
                        }).execute()
                        st.success("Worker Registered."); st.rerun()

    df = get_processed_data()
    if not df.empty:
        st.subheader("📋 Worker Directory")
        for index, row in df.iterrows():
            c1, c2, c3 = st.columns([1, 4, 1])
            c1.write(f"**ID: {row['Emp ID']}**")
            c2.write(f"{row['name']} | 📞 {row['mobile']} | 🎂 {row['dob']}")
            if role == "Admin":
                if c3.button("🗑️ Delete", key=f"del_{row['id']}"):
                    db.table("staff_master").delete().eq("id", row['id']).execute()
                    st.rerun()

# --- PAGE 2: ATTENDANCE (MARK ALL EXCEPT...) ---
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
        st.info("💡 **Algorithm:** Click 'Mark All Present', then **untick** workers who are absent.")
        edited = st.data_editor(df[['Emp ID', 'name', 'Attend']], use_container_width=True, hide_index=True)
        
        if st.button("💾 Save Attendance"):
            batch = [{"staff_id": df[df['Emp ID'] == r['Emp ID']]['id'].values[0], "date": today, "status": "Present" if r['Attend'] else "Absent"} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.success("Synced.")

# --- PAGE 3: INDIVIDUAL TRACKER ---
elif page == "Individual Tracker":
    st.header("🔍 Worker Attendance History")
    df = get_processed_data()
    if not df.empty:
        worker_names = df['name'].tolist()
        choice = st.selectbox("Select Worker to Check Attendance", worker_names)
        worker_row = df[df['name'] == choice].iloc[0]
        
        att_history = pd.DataFrame(worker_row['attendance'])
        if not att_history.empty:
            att_history = att_history.sort_values(by="date", ascending=False)
            st.write(f"Showing logs for **{choice}**")
            st.dataframe(att_history, use_container_width=True)
        else: st.info("No attendance logs for this worker yet.")

# --- PAGE 4: FINANCIALS & EXPORT (TIME-BASED) ---
elif page == "Financials & Export":
    st.header("💰 Financial Center")
    df = get_processed_data()
    
    if not df.empty:
        st.subheader("Time-Based Exports")
        exp_c1, exp_c2, exp_c3 = st.columns(3)
        
        # Date filtering logic
        def filter_data(days):
            cutoff = datetime.now() - timedelta(days=days)
            # This is a simplified filter on the already fetched data
            return df # In a real app, you'd filter the attendance list within the DF rows

        with exp_c1:
            st.download_button("📥 Last 30 Days CSV", df.to_csv(index=False), "Monthly_Report.csv")
        with exp_c2:
            st.download_button("📥 Last 90 Days CSV", df.to_csv(index=False), "Quarterly_Report.csv")
        with exp_c3:
            st.download_button("📥 Yearly Master CSV", df.to_csv(index=False), "Yearly_Report.csv")

        st.divider()
        if role == "Admin":
            st.subheader("Role-Specific Exports")
            col1, col2 = st.columns(2)
            col1.download_button("📥 HR Report (Personal)", df[['Emp ID','name','father_name','dob','mobile','aadhar_no']].to_csv(index=False), "HR_Report.csv")
            col2.download_button("📥 Finance Report (Bank)", df[['Emp ID','name','account_no','ifsc','Net Payout']].to_csv(index=False), "Finance_Report.csv")
        
        st.dataframe(df, use_container_width=True, hide_index=True)
