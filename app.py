import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
from datetime import datetime

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

# --- MODULE: SEQUENTIAL ID LOGIC ---
def get_processed_data():
    """Fetches staff and assigns a serial 'Emp ID' based on joining date."""
    res = db.table("staff_master").select("*, attendance(status), advances(amount)").order("created_at").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        df = df.sort_values(by="created_at").reset_index(drop=True)
        df.insert(0, 'Emp ID', range(1, len(df) + 1))
        
        # Calculate Net Payouts for Finance/Admin
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
page = st.sidebar.radio("Navigation", ["Registration", "Attendance Log", "Data Export"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]; st.rerun()

# --- PAGE 1: REGISTRATION ---
if page == "Registration":
    if role == "Finance":
        st.error("Finance does not have permission to register workers.")
    else:
        st.header("📝 New Worker Registration")
        with st.form("reg_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name, father = c1.text_input("Full Name*"), c2.text_input("Father's Name*")
            dob, aadhar = c1.date_input("DOB", min_value=datetime(1960,1,1)), c2.text_input("Aadhar Number*")
            
            st.divider()
            b1, b2, b3 = st.columns(3)
            bank, acc, ifsc = b1.text_input("Bank"), b2.text_input("Account No*"), b3.text_input("IFSC")
            wage = st.number_input("Daily Wage (₹)", value=500)
            photo = st.file_uploader("ID Photo", type=['jpg','png'])

            if st.form_submit_button("Add Worker"):
                # Duplication Check
                dup = db.table("staff_master").select("id").or_(f"aadhar_no.eq.{aadhar},account_no.eq.{acc}").execute()
                if dup.data:
                    st.error("🚨 DUPLICATE FOUND: Aadhar or Account already exists!")
                elif not name or not aadhar or not acc:
                    st.error("Please fill Name, Aadhar, and Account.")
                else:
                    url = ""
                    if photo:
                        img = compress_worker_photo(photo)
                        path = f"ids/{aadhar}.jpg"
                        db.storage.from_("staff_files").upload(path, img, {"content-type": "image/jpeg"})
                        url = db.storage.from_("staff_files").get_public_url(path)
                    
                    db.table("staff_master").insert({
                        "name": name, "father_name": father, "dob": str(dob), "aadhar_no": aadhar,
                        "bank_name": bank, "account_no": acc, "ifsc": ifsc, 
                        "daily_wage": wage, "photo_url": url, "department": role
                    }).execute()
                    st.success("Worker Registered. ID Sequence Shuffled.")

# --- PAGE 2: ATTENDANCE (MARK ALL EXCEPT...) ---
elif page == "Attendance Log":
    st.header("📅 Daily Attendance Log")
    df = get_processed_data()
    
    if not df.empty:
        st.subheader("Selection Tools")
        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button("✅ Mark All Present"): st.session_state.att_val = True
        if c2.button("❌ Mark All Absent"): st.session_state.att_val = False
        
        # Default state
        if 'att_val' not in st.session_state: st.session_state.att_val = True
        
        df['Attend'] = st.session_state.att_val
        st.write("Instruction: Use buttons to mark all, then **untick** specific people (the 'Except' list).")
        
        edited = st.data_editor(df[['Emp ID', 'name', 'Attend']], use_container_width=True, hide_index=True)
        
        if st.button("💾 Save Today's Attendance"):
            batch = []
            for _, r in edited.iterrows():
                # Find the actual ID from the original DF using Emp ID
                actual_id = df[df['Emp ID'] == r['Emp ID']]['id'].values[0]
                batch.append({
                    "staff_id": actual_id, 
                    "date": str(datetime.now().date()), 
                    "status": "Present" if r['Attend'] else "Absent"
                })
            db.table("attendance").upsert(batch).execute()
            st.success(f"Log saved for {len(batch)} workers.")

# --- PAGE 3: EXPORTS (ROLE-BASED POWERS) ---
elif page == "Data Export":
    st.header(f"📥 {role} Export Center")
    df = get_processed_data()
    
    if not df.empty:
        # Define Column Groups
        hr_cols = ['Emp ID', 'name', 'father_name', 'dob', 'aadhar_no', 'photo_url']
        fin_cols = ['Emp ID', 'name', 'bank_name', 'account_no', 'ifsc', 'daily_wage', 'Net Payout']
        
        # --- ADMIN VIEW ---
        if role == "Admin":
            st.subheader("Master Controls")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.write("**HR Data**")
                st.download_button("Download HR CSV", df[hr_cols].to_csv(index=False), "HR_Report.csv")
            
            with col2:
                st.write("**Financial Data**")
                st.download_button("Download Financial CSV", df[fin_cols].to_csv(index=False), "Finance_Report.csv")
                
            with col3:
                st.write("**Master Data**")
                st.download_button("Download ALL Data", df.to_csv(index=False), "Full_Master_Report.csv")
            
            st.dataframe(df, use_container_width=True, hide_index=True)

        # --- HR VIEW ---
        elif role == "HR":
            st.subheader("Personal Records")
            st.dataframe(df[hr_cols], use_container_width=True, hide_index=True)
            st.download_button("📥 Export HR CSV", df[hr_cols].to_csv(index=False), "KBP_HR_Report.csv")

        # --- FINANCE VIEW ---
        elif role == "Finance":
            st.subheader("Financial Records")
            st.dataframe(df[fin_cols], use_container_width=True, hide_index=True)
            st.download_button("📥 Export Finance CSV", df[fin_cols].to_csv(index=False), "KBP_Finance_Report.csv")
    else:
        st.info("No data available to export.")
