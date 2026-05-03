import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from PIL import Image
import io, json
from datetime import datetime

# --- CONFIG ---
st.set_page_config(page_title="Workforce AI Pro", layout="wide")

# Connect to Gemini
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# Connect to Supabase
@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()
DEPT_LIST = ["Civil", "Electrical", "Mechanical", "Security", "Plumbing", "General"]

# --- AUTH ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Admin Login")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if pwd == st.secrets["ADMIN_PASSWORD"]:
            st.session_state.auth = True
            st.rerun()
    st.stop()

# --- SIDEBAR ---
st.sidebar.title("🏢 Workforce OS")
selected_dept = st.sidebar.selectbox("Department", DEPT_LIST)
menu = st.sidebar.radio("Navigation", ["📈 Dashboard", "📝 AI Enrollment", "📅 Attendance", "💰 Payroll & Export"])

# --- AI OCR ALGORITHM ---
def scan_id_card(image_file):
    img = Image.open(image_file)
    prompt = "Extract Name, Father's Name, and 12-digit Aadhar Number from this card. Output ONLY valid JSON."
    response = ai_model.generate_content([prompt, img])
    # Clean string to get JSON
    clean_json = response.text.replace('```json', '').replace('```', '').strip()
    return json.loads(clean_json)

# --- 1. AI ENROLLMENT ---
if menu == "📝 AI Enrollment":
    st.header(f"Enrollment - {selected_dept}")
    
    # Photo Upload (for records AND for AI scanning)
    uploaded_photo = st.file_uploader("Upload Aadhar Card Photo", type=['jpg', 'png', 'jpeg'])
    
    if uploaded_photo and st.button("✨ Auto-Fill with AI"):
        with st.spinner("Gemini is reading the card..."):
            st.session_state.scanned = scan_id_card(uploaded_photo)
            st.success("Extracted successfully!")

    with st.form("enroll_form", clear_on_submit=True):
        sc = st.session_state.get('scanned', {})
        u_name = st.text_input("Full Name", value=sc.get('Name', sc.get('name', '')))
        u_father = st.text_input("Father's Name", value=sc.get("Father's Name", sc.get('father_name', '')))
        u_aadhar = st.text_input("Aadhar No", value=sc.get("Aadhar Number", sc.get('aadhar', '')))
        
        c1, c2, c3 = st.columns(3)
        u_bank = c1.text_input("Bank Name")
        u_acc = c2.text_input("Account No")
        u_ifsc = c3.text_input("IFSC Code")
        u_wage = st.number_input("Daily Wage (₹)", value=500)
        
        if st.form_submit_button("💾 Save Employee"):
            # 1. Upload Photo to Storage
            path = f"aadhar/{u_aadhar}.jpg"
            db.storage.from_("staff_files").upload(path, uploaded_photo.getvalue())
            photo_url = db.storage.from_("staff_files").get_public_url(path)
            
            # 2. Insert into SQL
            db.table("staff_master").insert({
                "name": u_name, "father_name": u_father, "aadhar_no": u_aadhar,
                "department": selected_dept, "bank_name": u_bank, "account_no": u_acc,
                "ifsc": u_ifsc, "daily_wage": u_wage, "photo_url": photo_url
            }).execute()
            st.success(f"Registered {u_name}!")
            st.session_state.scanned = {} # Clear AI cache

# --- 2. ATTENDANCE ---
elif menu == "📅 Attendance":
    st.header(f"Daily Log: {selected_dept}")
    date_str = str(st.date_input("Date", datetime.now()))
    
    res = db.table("staff_master").select("id, name").eq("department", selected_dept).execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        df['Status'] = "Present"
        edited = st.data_editor(df, use_container_width=True, hide_index=True)
        
        if st.button("Sync Attendance"):
            batch = [{"staff_id": r['id'], "date": date_str, "status": r['Status']} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.success("Cloud Updated!")

# --- 3. PAYROLL MATH & EXPORT ---
elif menu == "💰 Payroll & Export":
    st.header(f"Payroll - {selected_dept}")
    
    # Query Data
    res = db.table("staff_master").select("*, attendance(status), advances(amount)").eq("department", selected_dept).execute()
    
    rows = []
    for r in res.data:
        # Math Engine
        presents = sum(1 for a in r['attendance'] if a['status'] == 'Present')
        halfs = sum(1 for a in r['attendance'] if a['status'] == 'Half-Day')
        adv_total = sum(adv['amount'] for adv in r['advances'])
        
        earnings = (presents * r['daily_wage']) + (halfs * (r['daily_wage']/2))
        net_pay = earnings - adv_total
        
        rows.append({
            "Name": r['name'], "Aadhar": r['aadhar_no'], "Acc No": r['account_no'],
            "IFSC": r['ifsc'], "Total Days": presents + (halfs*0.5), "Advances": adv_total, "NET PAYABLE": net_pay
        })
    
    pay_df = pd.DataFrame(rows)
    st.dataframe(pay_df, use_container_width=True)
    
    # Export
    csv = pay_df.to_csv(index=False).encode('utf-8')
    st.download_button(f"📥 Download {selected_dept} Bank File", data=csv, file_name=f"{selected_dept}_Payroll.csv")
