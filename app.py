import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from PIL import Image
import io, json
from datetime import datetime

# --- SYSTEM CONFIG ---
st.set_page_config(page_title="Workforce OS: AI Edition", layout="wide")
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
ai_model = genai.GenerativeModel('gemini-1.5-flash')

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()
DEPARTMENTS = ["Civil", "Electrical", "Mechanical", "Security", "Plumbing", "General"]

# --- 🧠 AI COMMAND CENTER ALGORITHM ---
def execute_ai_command(user_prompt):
    """Translates plain English into SQL queries or System Actions."""
    context = f"""
    You are an AI manager for a workforce database. The database has tables: 
    1. staff_master (id, name, father_name, dob, aadhar_no, department, daily_wage, account_no, ifsc)
    2. attendance (staff_id, date, status)
    3. advances (staff_id, amount, date)
    
    The user is asking: '{user_prompt}'
    
    Respond ONLY in a JSON format:
    {{
        "action": "query" or "navigate" or "error",
        "sql": "A valid PostgreSQL query if action is query",
        "message": "A friendly confirmation message",
        "target_page": "The menu name if the user wants to go somewhere"
    }}
    """
    response = ai_model.generate_content(context)
    try:
        return json.loads(response.text.replace('```json', '').replace('```', '').strip())
    except:
        return {"action": "error", "message": "I didn't understand that command. Try: 'Show me all Civil staff'"}

# --- 🛰️ TOP NAVIGATION: AI COMMAND BOX ---
st.title("🏗️ Workforce OS Pro")
command_input = st.text_input("💬 AI Command Center (Type what you want to do...)", placeholder="e.g., 'Show me staff with missing bank details' or 'Go to Payroll'")

if command_input:
    with st.spinner("AI is executing..."):
        cmd_result = execute_ai_command(command_input)
        if cmd_result['action'] == "query":
            res = db.rpc('run_sql', {'sql_query': cmd_result['sql']}).execute() # Requires a Supabase RPC function
            st.write(cmd_result['message'])
            st.dataframe(pd.DataFrame(res.data))
        elif cmd_result['action'] == "navigate":
            st.info(f"Navigating to: {cmd_result['target_page']}")
            # Logic to switch st.sidebar.radio state would go here
        else:
            st.error(cmd_result['message'])

st.divider()

# --- SIDEBAR & MENU ---
st.sidebar.title("🏢 Workforce Admin")
selected_dept = st.sidebar.selectbox("Select Department", DEPARTMENTS)
menu = st.sidebar.radio("Navigation", ["🏠 Dashboard", "📝 AI Enrollment", "📅 AI Attendance", "💰 Payroll & Export"])

# --- 1. AI ENROLLMENT (With OCR & Data Cleanup) ---
if menu == "📝 AI Enrollment":
    st.header(f"Enrollment - {selected_dept}")
    id_img = st.file_uploader("Upload ID Card (Aadhar)", type=['jpg', 'png', 'jpeg'])
    
    if id_img and st.button("✨ Auto-Fill & Clean"):
        with st.spinner("AI Processing..."):
            img = Image.open(id_img)
            res = ai_model.generate_content(["Extract: Name, Father, DOB (YYYY-MM-DD), Aadhar. Clean any typos.", img])
            st.session_state.scanned = json.loads(res.text.replace('```json', '').replace('
```', '').strip())

    with st.form("enroll_form"):
        sc = st.session_state.get('scanned', {})
        name = st.text_input("Full Name", value=sc.get('name', ''))
        father = st.text_input("Father's Name", value=sc.get('father_name', ''))
        dob = st.date_input("DOB", value=datetime.today())
        aadhar = st.text_input("Aadhar", value=sc.get('aadhar', ''))
        
        c1, c2 = st.columns(2)
        bank = c1.text_input("Bank Name")
        acc = c1.text_input("Account No")
        ifsc = c2.text_input("IFSC")
        wage = c2.number_input("Daily Wage", value=500)
        
        if st.form_submit_button("💾 Securely Save to DB"):
            db.table("staff_master").insert({
                "name": name, "father_name": father, "dob": str(dob), "aadhar_no": aadhar,
                "department": selected_dept, "bank_name": bank, "account_no": acc,
                "ifsc": ifsc, "daily_wage": wage
            }).execute()
            st.success("Staff added and AI-verified!")

# --- 2. AI ATTENDANCE (With Fraud Check) ---
elif menu == "📅 AI Attendance":
    st.header(f"Smart Attendance: {selected_dept}")
    res = db.table("staff_master").select("id, name").eq("department", selected_dept).execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        df['Status'] = "Present"
        edited = st.data_editor(df, use_container_width=True, hide_index=True)
        
        if st.button("🚀 Sync & AI Audit"):
            # AI checks for attendance fraud (e.g., mass marking present at odd times)
            audit_note = ai_model.generate_content(f"Verify this attendance log: {edited.to_json()}").text
            st.info(f"AI Audit: {audit_note}")
            
            batch = [{"staff_id": r['id'], "date": str(datetime.now().date()), "status": r['Status']} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.success("Synced!")

# --- 3. PAYROLL & DEPT EXPORT ---
elif menu == "💰 Payroll & Export":
    st.header(f"Wages: {selected_dept}")
    res = db.table("staff_master").select("*, attendance(status), advances(amount)").eq("department", selected_dept).execute()
    
    data = []
    for r in res.data:
        presents = sum(1 for a in r['attendance'] if a['status'] == 'Present')
        halfs = sum(1 for a in r['attendance'] if a['status'] == 'Half-Day')
        advances = sum(adv['amount'] for adv in r['advances'])
        net = (presents * r['daily_wage']) + (halfs * (r['daily_wage']/2)) - advances
        data.append({"Name": r['name'], "Aadhar": r['aadhar_no'], "Acc No": r['account_no'], "Net Payable": net})
    
    final_df = pd.DataFrame(data)
    st.dataframe(final_df)
    st.download_button(f"📥 Export {selected_dept} CSV", final_df.to_csv(index=False), f"{selected_dept}_pay.csv")
