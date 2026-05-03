import streamlit as st
import pandas as pd
from supabase import create_client, Client
from PIL import Image
import io
from datetime import datetime

# --- CONFIG ---
st.set_page_config(page_title="Workforce OS Pro", layout="wide")

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()

# --- IMAGE COMPRESSOR ALGORITHM (Target < 100KB) ---
def compress_image(uploaded_file):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    # Initial quality and reduction step
    quality = 90
    output = io.BytesIO()
    
    while True:
        output.seek(0)
        output.truncate(0)
        img.save(output, format="JPEG", quality=quality)
        size_kb = output.tell() / 1024
        
        if size_kb <= 100 or quality <= 10:
            break
        quality -= 10 # Reduce quality iteratively
        if quality < 50: # Start resizing if quality reduction isn't enough
            img = img.resize((int(img.width * 0.9), int(img.height * 0.9)))
            
    output.seek(0)
    return output.getvalue(), size_kb

# --- SIDEBAR: DEPARTMENT & PAGE LOCK ---
st.sidebar.title("🏢 Corporate HQ")
active_dept = st.sidebar.radio("SELECT DEPARTMENT", ["Finance", "HR", "Admin"])

st.sidebar.divider()

menu = st.sidebar.radio(f"🛠️ {active_dept} Menu", 
                        ["Dashboard", "Enrollment", "Attendance", "Payroll", "Records & Filters"])

# --- 1. DASHBOARD ---
if menu == "Dashboard":
    st.title(f"💼 {active_dept} Overview")
    res = db.table("staff_master").select("id").eq("department", active_dept).execute()
    count = len(res.data)
    
    c1, c2 = st.columns(2)
    c1.metric(f"Total {active_dept} Staff", count)
    c2.info(f"System is optimized. Images are auto-compressed to <100KB.")

# --- 2. ENROLLMENT (Manual Entry + Compressor) ---
elif menu == "Enrollment":
    st.title(f"📝 {active_dept} Enrollment")
    
    with st.form("enroll_form", clear_on_submit=True):
        st.subheader("Personal Details")
        col1, col2 = st.columns(2)
        name = col1.text_input("Full Name*")
        father = col2.text_input("Father's Name")
        dob = col1.date_input("Date of Birth", min_value=datetime(1960,1,1))
        aadhar = col2.text_input("Aadhar Number*")
        
        st.divider()
        st.subheader("Bank & Wage")
        b1, b2, b3 = st.columns(3)
        bank = b1.text_input("Bank Name")
        acc = b2.text_input("Account Number")
        ifsc = b3.text_input("IFSC Code")
        wage = st.number_input("Daily Wage Rate (₹)", value=500)
        
        st.divider()
        photo = st.file_uploader("Upload Aadhar Photo (Auto-Compress to <100KB)", type=['jpg', 'jpeg', 'png'])
        
        if st.form_submit_button("Submit Application"):
            if not name or not aadhar:
                st.error("Name and Aadhar are required!")
            else:
                photo_url = None
                if photo:
                    compressed_data, final_size = compress_image(photo)
                    file_path = f"{active_dept}/{aadhar}.jpg"
                    db.storage.from_("staff_files").upload(file_path, compressed_data, {"content-type": "image/jpeg"})
                    photo_url = db.storage.from_("staff_files").get_public_url(file_path)
                    st.toast(f"Compressed to {final_size:.1f} KB", icon="📉")
                
                db.table("staff_master").insert({
                    "name": name, "father_name": father, "dob": str(dob), "aadhar_no": aadhar,
                    "department": active_dept, "bank_name": bank, "account_no": acc,
                    "ifsc": ifsc, "daily_wage": wage, "photo_url": photo_url
                }).execute()
                st.success(f"Registered {name} successfully.")

# --- 3. ATTENDANCE ---
elif menu == "Attendance":
    st.title(f"📅 Daily Log: {active_dept}")
    date_sel = st.date_input("Attendance Date", datetime.now())
    
    res = db.table("staff_master").select("id, name").eq("department", active_dept).execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        df['Status'] = "Present"
        edited_df = st.data_editor(df, use_container_width=True, hide_index=True)
        
        if st.button("Save Attendance"):
            batch = [{"staff_id": r['id'], "date": str(date_sel), "status": r['Status']} for _, r in edited_df.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.success("Attendance synced.")

# --- 4. PAYROLL (Math Ready) ---
elif menu == "Payroll":
    st.title(f"💰 {active_dept} Payroll")
    month = st.selectbox("Select Month", ["Current Month", "All Time"])
    
    # Query Data
    res = db.table("staff_master").select("*, attendance(status), advances(amount)").eq("department", active_dept).execute()
    
    pay_data = []
    for r in res.data:
        presents = sum(1 for a in r['attendance'] if a['status'] == 'Present')
        halfs = sum(1 for a in r['attendance'] if a['status'] == 'Half-Day')
        advs = sum(adv['amount'] for adv in r['advances'])
        
        # Payroll Algorithm
        # $$Net\ Payable = (Presents \times Wage) + (HalfDays \times \frac{Wage}{2}) - Advances$$
        earnings = (presents * r['daily_wage']) + (halfs * (r['daily_wage'] / 2))
        net = earnings - advs
        
        pay_data.append({
            "Name": r['name'], "Daily Wage": r['daily_wage'], 
            "Presents": presents, "Half-Days": halfs, "Advances": advs, "Net Payable": net
        })
    
    if pay_data:
        pdf = pd.DataFrame(pay_data)
        st.table(pdf)
        csv = pdf.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Export Payout CSV", csv, f"{active_dept}_payroll.csv")

# --- 5. RECORDS & FILTERS ---
elif menu == "Records & Filters":
    st.title(f"🔍 {active_dept} Personnel Records")
    
    # Filter Logic
    search = st.text_input("Search by Name or Aadhar")
    
    res = db.table("staff_master").select("*").eq("department", active_dept).execute()
    master_df = pd.DataFrame(res.data)
    
    if not master_df.empty:
        if search:
            master_df = master_df[master_df['name'].str.contains(search, case=False) | master_df['aadhar_no'].str.contains(search)]
        
        st.dataframe(master_df, use_container_width=True)
