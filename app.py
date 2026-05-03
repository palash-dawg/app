import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from PIL import Image
import io, json
from datetime import datetime

# --- CONFIG ---
st.set_page_config(page_title="Workforce OS Pro", layout="wide")

# Connect to Gemini & Supabase
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
ai_model = genai.GenerativeModel('gemini-1.5-flash')

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()
DEPARTMENTS = ["Civil", "Electrical", "Mechanical", "Security", "Plumbing", "General"]

# --- HELPER: CLEAN AI JSON ---
def clean_ai_json(text):
    """Fixes the 'unterminated string' and formatting bugs from AI responses"""
    clean = text.replace('```json', '').replace('```', '').strip()
    return json.loads(clean)

# --- 🧠 AI COMMAND CENTER ---
def handle_ai_command(prompt):
    context = f"""
    Tables: staff_master(id, name, father_name, dob, aadhar_no, department, daily_wage, account_no, ifsc), attendance, advances.
    Task: Translate '{prompt}' into a JSON with keys: 'action' (query/navigate), 'sql' (the query), 'msg' (human message).
    Return ONLY JSON.
    """
    res = ai_model.generate_content(context)
    return clean_ai_json(res.text)

# --- TOP UI: AI COMMAND BOX ---
st.title("🏗️ Workforce OS Pro")
cmd = st.text_input("💬 AI Command (e.g., 'Who is in Civil?' or 'Show bank details for Security')")

if cmd:
    try:
        res_cmd = handle_ai_command(cmd)
        if res_cmd['action'] == "query":
            data = db.rpc('run_sql', {'sql_query': res_cmd['sql']}).execute()
            st.write(res_cmd['msg'])
            st.dataframe(pd.DataFrame(data.data))
    except Exception as e:
        st.error(f"AI Error: {e}")

st.divider()

# --- SIDEBAR ---
st.sidebar.title("🏢 Admin Panel")
selected_dept = st.sidebar.selectbox("Department", DEPARTMENTS)
menu = st.sidebar.radio("Go To", ["🏠 Dashboard", "📝 AI Enrollment", "📅 AI Attendance", "💰 Payroll & Export"])

# --- 1. AI ENROLLMENT ---
if menu == "📝 AI Enrollment":
    st.header(f"Enrollment - {selected_dept}")
    photo = st.file_uploader("Scan Aadhar Card", type=['jpg', 'png', 'jpeg'])
    
    if photo and st.button("✨ Auto-Fill with AI"):
        with st.spinner("AI Reading..."):
            img = Image.open(photo)
            ai_res = ai_model.generate_content(["Extract Name, Father, DOB (YYYY-MM-DD), Aadhar into JSON.", img])
            st.session_state.scanned = clean_ai_json(ai_res.text)
            st.success("Scanned!")

    with st.form("enroll_form"):
        sc = st.session_state.get('scanned', {})
        name = st.text_input("Name", value=sc.get('name', ''))
        father = st.text_input("Father Name", value=sc.get('father_name', ''))
        dob = st.text_input("DOB (YYYY-MM-DD)", value=sc.get('dob', '1995-01-01'))
        aadhar = st.text_input("Aadhar", value=sc.get('aadhar', ''))
        
        c1, c2 = st.columns(2)
        bank = c1.text_input("Bank Name")
        acc = c1.text_input("Account No")
        ifsc = c2.text_input("IFSC")
        wage = c2.number_input("Daily Wage", value=500)
        
        if st.form_submit_button("Save to DB"):
            db.table("staff_master").insert({
                "name": name, "father_name": father, "dob": dob, "aadhar_no": aadhar,
                "department": selected_dept, "bank_name": bank, "account_no": acc, 
                "ifsc": ifsc, "daily_wage": wage
            }).execute()
            st.success("Saved!")

# --- 2. AI ATTENDANCE ---
elif menu == "📅 AI Attendance":
    st.header(f"Attendance: {selected_dept}")
    res = db.table("staff_master").select("id, name").eq("department", selected_dept).execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        df['Status'] = "Present"
        edited = st.data_editor(df, use_container_width=True, hide_index=True)
        if st.button("Sync Attendance"):
            batch = [{"staff_id": r['id'], "date": str(datetime.now().date()), "status": r['Status']} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.success("Synced!")

# --- 3. PAYROLL & DEPT EXPORT ---
elif menu == "💰 Payroll & Export":
    st.header(f"Payroll: {selected_dept}")
    # Calculation Logic
    res = db.table("staff_master").select("*, attendance(status), advances(amount)").eq("department", selected_dept).execute()
    
    pay_data = []
    for r in res.data:
        presents = sum(1 for a in r['attendance'] if a['status'] == 'Present')
        halfs = sum(1 for a in r['attendance'] if a['status'] == 'Half-Day')
        advs = sum(adv['amount'] for adv in r['advances'])
        net = (presents * r['daily_wage']) + (halfs * (r['daily_wage']/2)) - advs
        pay_data.append({"Name": r['name'], "DOB": r['dob'], "Acc": r['account_no'], "IFSC": r['ifsc'], "Net Pay": net})
    
    pay_df = pd.DataFrame(pay_data)
    st.dataframe(pay_df, use_container_width=True)
    
    csv = pay_df.to_csv(index=False).encode('utf-8')
    st.download_button(f"📥 Export {selected_dept} CSV", csv, f"{selected_dept}_Payroll.csv")
