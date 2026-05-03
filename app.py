import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
from datetime import datetime

# --- CONFIG ---
st.set_page_config(page_title="Site Workforce OS", layout="wide")

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()

# --- MODULE: 100KB IMAGE COMPRESSOR ---
def compress_site_photo(uploaded_file):
    img = Image.open(uploaded_file).convert("RGB")
    quality = 80
    img_io = io.BytesIO()
    
    while True:
        img_io.seek(0)
        img_io.truncate(0)
        img.save(img_io, format="JPEG", quality=quality, optimize=True)
        size_kb = img_io.tell() / 1024
        
        if size_kb <= 100 or quality <= 5:
            break
        quality -= 5
        if quality < 30: # Shrink dimensions if quality reduction isn't enough
            img = img.resize((int(img.width * 0.9), int(img.height * 0.9)))
            
    return img_io.getvalue(), size_kb

# --- MODULE: LOGIN & ROLE CHECK ---
if "user_role" not in st.session_state:
    st.title("🚧 Construction Site Portal")
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
            else: st.error("Wrong Username or Password")
    st.stop()

role = st.session_state.user_role
st.sidebar.title(f"Role: {role}")
page = st.sidebar.radio("Navigation", ["Dashboard", "Worker Registration", "Attendance", "Financials & Payouts"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]
    st.rerun()

# --- PAGE: DASHBOARD ---
if page == "Dashboard":
    st.title(f"📈 Site Overview - {role}")
    res = db.table("staff_master").select("id").execute()
    st.metric("Total Workers on Site", len(res.data))
    st.info(f"Logged in as {role}. Data access is restricted to your permissions.")

# --- PAGE: WORKER REGISTRATION (HR & ADMIN ONLY) ---
elif page == "Worker Registration":
    if role == "Finance":
        st.error("Finance role does not have permission to register workers.")
    else:
        st.title("📝 New Worker Registration")
        with st.form("reg_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Worker Full Name*")
            father = c2.text_input("Father's Name")
            dob = c1.date_input("Date of Birth", min_value=datetime(1960,1,1))
            aadhar = c2.text_input("Aadhar Number*")
            
            # Admin can see bank fields during reg, HR might not depending on your choice
            # Here we include it for convenience but mask it later
            st.divider()
            b1, b2, b3 = st.columns(3)
            bank = b1.text_input("Bank Name")
            acc = b2.text_input("Account Number")
            ifsc = b3.text_input("IFSC")
            wage = st.number_input("Daily Wage (₹)", value=500)
            
            photo = st.file_uploader("Worker ID Photo (Auto-Compress <100KB)", type=['jpg','png','jpeg'])
            
            if st.form_submit_button("Save to Site Database"):
                if not name or not aadhar:
                    st.error("Missing mandatory fields!")
                else:
                    url = ""
                    if photo:
                        img_bytes, kb = compress_site_photo(photo)
                        path = f"site_ids/{aadhar}.jpg"
                        db.storage.from_("staff_files").upload(path, img_bytes, {"content-type": "image/jpeg"})
                        url = db.storage.from_("staff_files").get_public_url(path)
                    
                    db.table("staff_master").insert({
                        "name": name, "father_name": father, "dob": str(dob), "aadhar_no": aadhar,
                        "bank_name": bank, "account_no": acc, "ifsc": ifsc, 
                        "daily_wage": wage, "photo_url": url, "department": "General"
                    }).execute()
                    st.success(f"Worker {name} Registered!")

# --- PAGE: ATTENDANCE (EVERYONE) ---
elif page == "Attendance":
    st.title("📅 Daily Attendance Log")
    workers = db.table("staff_master").select("id, name").execute()
    df = pd.DataFrame(workers.data)
    
    if not df.empty:
        df['Status'] = "Present"
        edited = st.data_editor(df, use_container_width=True, hide_index=True)
        if st.button("Save Log"):
            log = [{"staff_id": r['id'], "date": str(datetime.now().date()), "status": r['Status']} for _, r in edited.iterrows()]
            db.table("attendance").upsert(log).execute()
            st.success("Attendance Synced.")
    else: st.warning("No workers found. Register them first.")

# --- PAGE: FINANCIALS & PAYOUTS (FINANCE & ADMIN FOCUS) ---
elif page == "Financials & Payouts":
    st.title("💰 Financial Records & Exports")
    
    # 1. PERMISSION FILTERING
    if role == "HR":
        # HR only sees personal details for the export
        res = db.table("staff_master").select("name, father_name, dob, aadhar_no").execute()
        df_display = pd.DataFrame(res.data)
        st.subheader("Worker Directory (HR View)")
        st.dataframe(df_display, use_container_width=True)
        st.download_button("📥 Export HR Directory", df_display.to_csv(index=False), "HR_Worker_List.csv")
    
    elif role == "Finance":
        # Finance sees Bank Details and calculated Payouts
        res = db.table("staff_master").select("name, bank_name, account_no, ifsc, daily_wage, attendance(status)").execute()
        pay_rows = []
        for r in res.data:
            p = sum(1 for a in r['attendance'] if a['status'] == 'Present')
            h = sum(1 for a in r['attendance'] if a['status'] == 'Half-Day')
            net = (p * r['daily_wage']) + (h * (r['daily_wage']/2))
            pay_rows.append({"Worker": r['name'], "Bank": r['bank_name'], "Acc No": r['account_no'], "IFSC": r['ifsc'], "Net Payable": net})
        
        df_fin = pd.DataFrame(pay_rows)
        st.subheader("Payout Summary (Finance View)")
        st.dataframe(df_fin, use_container_width=True)
        st.download_button("📥 Export Bank Transfer File", df_fin.to_csv(index=False), "Bank_Payouts.csv")

    elif role == "Admin":
        # Admin sees EVERYTHING combined
        res = db.table("staff_master").select("*, attendance(status)").execute()
        admin_rows = []
        for r in res.data:
            p = sum(1 for a in r['attendance'] if a['status'] == 'Present')
            h = sum(1 for a in r['attendance'] if a['status'] == 'Half-Day')
            net = (p * r['daily_wage']) + (h * (r['daily_wage']/2))
            r['Net Payout'] = net
            admin_rows.append(r)
        
        df_admin = pd.DataFrame(admin_rows)
        st.subheader("Master Records (Full View)")
        st.dataframe(df_admin, use_container_width=True)
        st.download_button("📥 Export Master Site Report", df_admin.to_csv(index=False), "Master_Site_Report.csv")
