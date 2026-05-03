import streamlit as st
import pandas as pd
from supabase import create_client, Client
from PIL import Image
import io
from datetime import datetime

# --- CONFIG & DB CONNECTION ---
st.set_page_config(page_title="Workforce OS Pro", layout="wide")

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()

# --- IMAGE COMPRESSOR (STRICT < 100KB) ---
def compress_image(uploaded_file):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    quality = 90
    output = io.BytesIO()
    
    while True:
        output.seek(0)
        output.truncate(0)
        img.save(output, format="JPEG", quality=quality)
        size_kb = output.tell() / 1024
        
        if size_kb <= 100 or quality <= 10:
            break
        quality -= 10
        if quality < 50:
            img = img.resize((int(img.width * 0.9), int(img.height * 0.9)))
            
    output.seek(0)
    return output.getvalue(), size_kb

# --- 🔐 ROLE-BASED LOGIN SYSTEM ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.role = None

def login():
    st.title("🔐 Workforce OS Login")
    with st.form("login_form"):
        user = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            creds = st.secrets["CREDENTIALS"]
            if user in creds and creds[user] == pwd:
                st.session_state.authenticated = True
                # Assign roles based on username
                if "admin" in user.lower(): st.session_state.role = "Admin"
                elif "hr" in user.lower(): st.session_state.role = "HR"
                elif "finance" in user.lower(): st.session_state.role = "Finance"
                st.rerun()
            else:
                st.error("Invalid Username or Password")

if not st.session_state.authenticated:
    login()
    st.stop()

# --- SIDEBAR: ROLE-BASED NAVIGATION ---
st.sidebar.title(f"👤 {st.session_state.role} Portal")

# Logic: Admins see all, others are locked to their role
if st.session_state.role == "Admin":
    active_dept = st.sidebar.radio("SELECT DEPARTMENT", ["Admin", "HR", "Finance"])
else:
    active_dept = st.session_state.role
    st.sidebar.info(f"Department Locked: **{active_dept}**")

st.sidebar.divider()

menu = st.sidebar.radio(f"🛠️ {active_dept} Menu", 
                        ["Dashboard", "Enrollment", "Attendance", "Payroll", "Records"])

if st.sidebar.button("Log Out"):
    st.session_state.authenticated = False
    st.rerun()

# --- 1. DASHBOARD ---
if menu == "Dashboard":
    st.title(f"💼 {active_dept} Dashboard")
    res = db.table("staff_master").select("id").eq("department", active_dept).execute()
    st.metric(f"Total {active_dept} Staff", len(res.data))
    st.write(f"Logged in as: **{st.session_state.role}**")

# --- 2. ENROLLMENT (With Compressor) ---
elif menu == "Enrollment":
    st.title(f"📝 {active_dept} Enrollment")
    with st.form("enroll_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        name = col1.text_input("Full Name*")
        father = col2.text_input("Father's Name")
        dob = col1.date_input("Date of Birth", min_value=datetime(1960,1,1))
        aadhar = col2.text_input("Aadhar Number*")
        
        st.divider()
        b1, b2, b3 = st.columns(3)
        bank = b1.text_input("Bank Name")
        acc = b2.text_input("Account Number")
        ifsc = b3.text_input("IFSC Code")
        wage = st.number_input("Daily Wage (₹)", value=500)
        
        photo = st.file_uploader("Upload ID Photo (<100KB Auto-Compress)", type=['jpg', 'png'])
        
        if st.form_submit_button("Save Record"):
            if not name or not aadhar:
                st.error("Missing required fields!")
            else:
                photo_url = ""
                if photo:
                    compressed_data, size = compress_image(photo)
                    path = f"{active_dept}/{aadhar}.jpg"
                    db.storage.from_("staff_files").upload(path, compressed_data, {"content-type": "image/jpeg"})
                    photo_url = db.storage.from_("staff_files").get_public_url(path)
                
                db.table("staff_master").insert({
                    "name": name, "father_name": father, "dob": str(dob), "aadhar_no": aadhar,
                    "department": active_dept, "bank_name": bank, "account_no": acc,
                    "ifsc": ifsc, "daily_wage": wage, "photo_url": photo_url
                }).execute()
                st.success(f"Registered {name} in {active_dept}!")

# --- 3. ATTENDANCE ---
elif menu == "Attendance":
    st.title(f"📅 Attendance: {active_dept}")
    res = db.table("staff_master").select("id, name").eq("department", active_dept).execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        df['Status'] = "Present"
        edited = st.data_editor(df, use_container_width=True, hide_index=True)
        if st.button("Sync to Cloud"):
            batch = [{"staff_id": r['id'], "date": str(datetime.now().date()), "status": r['Status']} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.success("Attendance Updated!")

# --- 4. PAYROLL (The Math) ---
elif menu == "Payroll":
    st.title(f"💰 {active_dept} Payroll")
    res = db.table("staff_master").select("*, attendance(status), advances(amount)").eq("department", active_dept).execute()
    
    pay_data = []
    for r in res.data:
        presents = sum(1 for a in r['attendance'] if a['status'] == 'Present')
        halfs = sum(1 for a in r['attendance'] if a['status'] == 'Half-Day')
        advs = sum(adv['amount'] for adv in r['advances'])
        
        # Calculation:
        # $$Net = (Days \times Wage) + (Half \times \frac{Wage}{2}) - Advances$$
        net = (presents * r['daily_wage']) + (halfs * (r['daily_wage']/2)) - advs
        pay_data.append({"Name": r['name'], "Acc": r['account_no'], "Net Pay": net})
    
    if pay_data:
        pdf = pd.DataFrame(pay_data)
        st.dataframe(pdf, use_container_width=True)
        st.download_button("📥 Export CSV", pdf.to_csv(index=False), f"{active_dept}_pay.csv")

# --- 5. RECORDS & FILTERS ---
elif menu == "Records":
    st.title(f"🔍 {active_dept} Search")
    search = st.text_input("Find by Name or Aadhar")
    res = db.table("staff_master").select("*").eq("department", active_dept).execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        if search:
            df = df[df['name'].str.contains(search, case=False) | df['aadhar_no'].str.contains(search)]
        st.dataframe(df, use_container_width=True)
