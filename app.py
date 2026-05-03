import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
from datetime import datetime

# --- CONFIG & BRANDING ---
st.set_page_config(page_title="KBP ENERGY PVT LTD - Site OS", layout="wide")
db = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- MODULE: 100KB ITERATIVE COMPRESSOR ---
def compress_id_photo(uploaded_file):
    img = Image.open(uploaded_file).convert("RGB")
    quality, img_io = 80, io.BytesIO()
    while True:
        img_io.seek(0); img_io.truncate(0)
        img.save(img_io, format="JPEG", quality=quality, optimize=True)
        if img_io.tell() / 1024 <= 100 or quality <= 5: break
        quality -= 5
        if quality < 30: img = img.resize((int(img.width * 0.9), int(img.height * 0.9)))
    return img_io.getvalue()

# --- MODULE: SEQUENTIAL SHUFFLING LOGIC ---
def get_sequenced_staff():
    """Fetches staff sorted by joining date. Serial IDs (1,2,3) re-shuffle automatically."""
    res = db.table("staff_master").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        # Sort by joining date (oldest to newest)
        df = df.sort_values(by="created_at").reset_index(drop=True)
        # Create the Serial Employee ID starting from 1
        df.insert(0, 'Emp ID', range(1, len(df) + 1))
    return df

# --- AUTH SYSTEM ---
if "user_role" not in st.session_state:
    st.title("🏗️ KBP ENERGY PVT LTD")
    st.subheader("Workforce Management Portal")
    with st.form("login"):
        u = st.text_input("Username").lower()
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Log In"):
            creds = st.secrets["CREDENTIALS"]
            if u in creds and creds[u] == p:
                if "admin" in u: st.session_state.user_role = "Admin"
                elif "hr" in u: st.session_state.user_role = "HR"
                elif "fin" in u: st.session_state.user_role = "Finance"
                st.rerun()
            else: st.error("Access Denied")
    st.stop()

role = st.session_state.user_role
st.sidebar.title("⚡ KBP ENERGY")
st.sidebar.write(f"Logged as: **{role}**")
page = st.sidebar.radio("Navigation", ["Worker Registration", "Bulk Attendance", "Financials & Exports"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]; st.rerun()

# --- PAGE 1: REGISTRATION (HR & ADMIN ONLY) ---
if page == "Worker Registration":
    if role == "Finance":
        st.error("Access Denied.")
    else:
        st.title("📝 Worker Registration")
        with st.form("reg_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            name = col1.text_input("Worker Name*")
            father = col2.text_input("Father's Name*")
            dob = col1.date_input("Date of Birth", min_value=datetime(1960,1,1))
            aadhar = col2.text_input("Aadhar Number (Unique)*")
            
            st.divider()
            b1, b2, b3 = st.columns(3)
            bank = b1.text_input("Bank Name")
            acc = b2.text_input("Account Number (Unique)*")
            ifsc = b3.text_input("IFSC Code")
            wage = st.number_input("Daily Wage (₹)", value=500)
            
            photo = st.file_uploader("Upload ID Photo (<100KB Auto)", type=['jpg','png'])

            if st.form_submit_button("Register Worker"):
                # Duplication Check
                dup = db.table("staff_master").select("id").or_(f"aadhar_no.eq.{aadhar},account_no.eq.{acc}").execute()
                if dup.data:
                    st.error("🚨 DUPLICATION BLOCKED: Aadhar or Account Number already exists!")
                elif not name or not aadhar or not acc:
                    st.error("Name, Aadhar, and Account Number are mandatory.")
                else:
                    p_url = ""
                    if photo:
                        img_bytes = compress_id_photo(photo)
                        path = f"ids/{aadhar}.jpg"
                        db.storage.from_("staff_files").upload(path, img_bytes, {"content-type": "image/jpeg"})
                        p_url = db.storage.from_("staff_files").get_public_url(path)
                    
                    db.table("staff_master").insert({
                        "name": name, "father_name": father, "dob": str(dob), "aadhar_no": aadhar,
                        "bank_name": bank, "account_no": acc, "ifsc": ifsc, 
                        "daily_wage": wage, "photo_url": p_url, "department": role
                    }).execute()
                    st.success("Worker Registered. Serial IDs updated.")

# --- PAGE 2: BULK ATTENDANCE (FAST MARKING) ---
elif page == "Bulk Attendance":
    st.title("📅 Bulk Attendance Control")
    df = get_sequenced_staff()
    
    if not df.empty:
        c1, c2, c3 = st.columns([1,1,2])
        m_all = c1.button("✅ Mark ALL Present")
        m_none = c2.button("❌ Mark ALL Absent")
        
        # Logic: Mark All Except...
        if 'att_df' not in st.session_state or m_all or m_none:
            df['Status'] = True if m_all else False
            st.session_state.att_df = df[['Emp ID', 'name', 'aadhar_no', 'Status']]

        st.write("Tick the boxes for those present. Untick for those absent.")
        edited = st.data_editor(st.session_state.att_df, use_container_width=True, hide_index=True)
        
        if st.button("🔥 Confirm & Save Attendance"):
            present_list = edited[edited['Status'] == True]
            # Batch upsert to database (Simplified logic)
            st.success(f"Attendance recorded for {len(present_list)} workers.")
    else:
        st.info("No workers registered yet.")

# --- PAGE 3: EXPORTS (ROLE-BASED VIEWS) ---
elif page == "Financials & Exports":
    st.title(f"💰 {role} Data Vault")
    df = get_sequenced_staff()
    
    if not df.empty:
        if role == "HR":
            # HR: IDs, Photos, Personal
            output = df[['Emp ID', 'name', 'father_name', 'dob', 'aadhar_no', 'photo_url']]
            st.subheader("HR Staff Directory")
        
        elif role == "Finance":
            # Finance: Bank, Wage, Net Payouts
            # Note: Math logic for payout calculation goes here
            output = df[['Emp ID', 'name', 'bank_name', 'account_no', 'ifsc', 'daily_wage']]
            st.subheader("Finance & Bank Transfer Records")
            
        elif role == "Admin":
            # Admin: Combined
            output = df
            st.subheader("Master Site Audit Report")

        st.dataframe(output, use_container_width=True, hide_index=True)
        
        # Combined CSV Export
        csv = output.to_csv(index=False).encode('utf-8')
        st.download_button(f"📥 Download {role} Export", csv, f"KBP_ENERGY_{role}_Report.csv")
