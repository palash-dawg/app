import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from PIL import Image
import io, json
from datetime import datetime

# --- SYSTEM INITIALIZATION ---
st.set_page_config(page_title="Workforce OS Pro", layout="wide")

# Connect to Gemini & Supabase
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
ai_model = genai.GenerativeModel('gemini-1.5-flash')

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()
DEPARTMENTS = ["Finance", "HR", "Admin"]

# --- AI HELPER: SAFE JSON PARSING ---
def safe_ai_json(text):
    """Prevents app crashes by cleaning AI text into valid JSON."""
    try:
        clean = text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean)
    except Exception:
        return {"error": "AI response was not in valid format. Try again."}

# --- 🧠 AI COMMAND CENTER ALGORITHM ---
def handle_command(user_prompt):
    context = f"""
    Context: Workforce DB with tables 'staff_master', 'attendance', 'advances'.
    Departments: Finance, HR, Admin.
    Command: '{user_prompt}'
    Task: Convert to JSON: {{"action": "query", "sql": "PostgreSQL Query", "msg": "Friendly message"}}.
    Return ONLY raw JSON.
    """
    res = ai_model.generate_content(context)
    return safe_ai_json(res.text)

# --- TOP UI: AI COMMAND BAR ---
st.title("🏗️ Workforce OS Pro")
ai_cmd = st.text_input("💬 AI Command Center", placeholder="e.g., 'Who in HR is missing bank details?' or 'Show total wages for Finance'")

if ai_cmd:
    try:
        cmd_result = handle_command(ai_cmd)
        if cmd_result.get('action') == "query":
            # Run the AI-generated SQL through our Supabase RPC
            query_res = db.rpc('run_sql', {'sql_query': cmd_result['sql']}).execute()
            st.success(cmd_result.get('msg', 'Command Executed'))
            if query_res.data:
                st.dataframe(pd.DataFrame(query_res.data), use_container_width=True)
            else:
                st.info("Query returned no results.")
    except Exception as e:
        st.error(f"AI Error: {e}")

st.divider()

# --- SIDEBAR & NAVIGATION ---
st.sidebar.title("🛡️ Admin Panel")
selected_dept = st.sidebar.selectbox("Active Department", DEPARTMENTS)
menu = st.sidebar.radio("Navigation", ["🏠 Dashboard", "📝 AI Enrollment", "📅 AI Attendance", "💰 Payroll & Export"])

# --- 1. AI ENROLLMENT (OCR + DOB) ---
if menu == "📝 AI Enrollment":
    st.header(f"Enrollment - {selected_dept}")
    id_card = st.file_uploader("Upload ID Card for AI Scan", type=['jpg', 'jpeg', 'png'])
    
    if id_card and st.button("✨ Auto-Scan with Gemini"):
        with st.spinner("AI Reading Card..."):
            img = Image.open(id_card)
            scan_res = ai_model.generate_content(["Extract Name, Father Name, DOB (YYYY-MM-DD), and Aadhar No into JSON.", img])
            st.session_state.scanned = safe_ai_json(scan_res.text)
            st.success("Details Extracted!")

    with st.form("staff_form", clear_on_submit=True):
        sc = st.session_state.get('scanned', {})
        name = st.text_input("Full Name", value=sc.get('name', ''))
        father = st.text_input("Father Name", value=sc.get('father_name', ''))
        dob = st.text_input("Date of Birth (YYYY-MM-DD)", value=sc.get('dob', '1995-01-01'))
        aadhar = st.text_input("Aadhar No", value=sc.get('aadhar', ''))
        
        c1, c2 = st.columns(2)
        bank = c1.text_input("Bank Name")
        acc = c1.text_input("Account Number")
        ifsc = c2.text_input("IFSC Code")
        wage = c2.number_input("Daily Wage (₹)", value=500)
        
        if st.form_submit_button("💾 Save Employee to Cloud"):
            # Upload Photo to Bucket
            path = f"ids/{aadhar}.jpg"
            db.storage.from_("staff_files").upload(path, id_card.getvalue())
            photo_url = db.storage.from_("staff_files").get_public_url(path)

            db.table("staff_master").insert({
                "name": name, "father_name": father, "dob": dob, "aadhar_no": aadhar,
                "department": selected_dept, "bank_name": bank, "account_no": acc,
                "ifsc": ifsc, "daily_wage": wage, "photo_url": photo_url
            }).execute()
            st.success(f"Registered {name} in {selected_dept}")
            st.session_state.scanned = {}

# --- 2. AI ATTENDANCE (With Audit) ---
elif menu == "📅 AI Attendance":
    st.header(f"Attendance Log: {selected_dept}")
    res = db.table("staff_master").select("id, name").eq("department", selected_dept).execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        df['Status'] = "Present"
        edited = st.data_editor(df, use_container_width=True, hide_index=True)
        
        if st.button("✅ Sync & AI Audit"):
            # AI Check for fraud/patterns
            audit = ai_model.generate_content(f"Audit this attendance: {edited.to_json()}. Find anomalies.").text
            st.info(f"AI Audit Note: {audit}")
            
            batch = [{"staff_id": r['id'], "date": str(datetime.now().date()), "status": r['Status']} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.success("Synced to Database!")

# --- 3. PAYROLL MATH & EXPORT ---
elif menu == "💰 Payroll & Export":
    st.header(f"Financials: {selected_dept}")
    
    # Complex Fetch: Staff + Attendance + Advances
    res = db.table("staff_master").select("*, attendance(status), advances(amount)").eq("department", selected_dept).execute()
    
    pay_data = []
    for r in res.data:
        presents = sum(1 for a in r['attendance'] if a['status'] == 'Present')
        halfs = sum(1 for a in r['attendance'] if a['status'] == 'Half-Day')
        advs = sum(adv['amount'] for adv in r['advances'])
        
        # CLEAR PAYROLL MATH
        # Net = (FullDays * Wage) + (HalfDays * Wage/2) - Advances
        earnings = (presents * r['daily_wage']) + (halfs * (r['daily_wage'] / 2))
        net = earnings - advs
        
        pay_data.append({
            "Name": r['name'], "DOB": r['dob'], "Aadhar": r['aadhar_no'],
            "Bank": r['bank_name'], "Account": r['account_no'], "Net Payable": net
        })
    
    final_df = pd.DataFrame(pay_data)
    st.dataframe(final_df, use_container_width=True)
    
    csv = final_df.to_csv(index=False).encode('utf-8')
    st.download_button(f"📥 Export {selected_dept} CSV", csv, f"{selected_dept}_Payroll.csv")
