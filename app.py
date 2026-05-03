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

# --- MODULE: SEQUENTIAL ID LOGIC & DATA FETCH ---
def get_processed_data():
    """Fetches staff and assigns a serial 'Emp ID' based on joining date."""
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
page = st.sidebar.radio("Navigation", ["Worker Management", "Attendance Log", "Financials & Export"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]; st.rerun()

# --- PAGE 1: WORKER MANAGEMENT (Registration & Deletion) ---
if page == "Worker Management":
    st.header("📝 Worker Management")
    
    if role != "Finance":
        with st.expander("➕ Register New Worker"):
            with st.form("reg_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name, father = c1.text_input("Full Name*"), c2.text_input("Father's Name*")
                aadhar, acc = c1.text_input("Aadhar Number*"), c2.text_input("Account No*")
                wage = st.number_input("Daily Wage (₹)", value=500)
                photo = st.file_uploader("ID Photo", type=['jpg','png'])

                if st.form_submit_button("Add Worker"):
                    dup = db.table("staff_master").select("id").or_(f"aadhar_no.eq.{aadhar},account_no.eq.{acc}").execute()
                    if dup.data: st.error("🚨 DUPLICATE Aadhar or Account!")
                    elif not name or not aadhar or not acc: st.error("Fill mandatory fields.")
                    else:
                        url = ""
                        if photo:
                            img = compress_worker_photo(photo)
                            path = f"ids/{aadhar}.jpg"; db.storage.from_("staff_files").upload(path, img, {"content-type": "image/jpeg"})
                            url = db.storage.from_("staff_files").get_public_url(path)
                        db.table("staff_master").insert({"name": name, "father_name": father, "aadhar_no": aadhar, "account_no": acc, "daily_wage": wage, "photo_url": url, "department": role}).execute()
                        st.success("Worker Registered. IDs Shuffled."); st.rerun()

    # --- DELETE EMPLOYEE SECTION ---
    st.subheader("📋 Worker Directory")
    df = get_processed_data()
    if not df.empty:
        for index, row in df.iterrows():
            c1, c2, c3 = st.columns([1, 4, 1])
            c1.write(f"**ID: {row['Emp ID']}**")
            c2.write(f"{row['name']} | Aadhar: {row['aadhar_no']}")
            if role == "Admin":
                if c3.button("🗑️ Delete", key=f"del_{row['id']}"):
                    db.table("staff_master").delete().eq("id", row['id']).execute()
                    st.toast(f"Deleted {row['name']}"); st.rerun()
    else: st.info("No workers registered.")

# --- PAGE 2: ATTENDANCE (MARK ALL EXCEPT... & REDO) ---
elif page == "Attendance Log":
    st.header("📅 Daily Attendance Log")
    df = get_processed_data()
    today = str(datetime.now().date())
    
    if not df.empty:
        c1, c2, c3 = st.columns([1, 1, 1])
        # Mark All Except Algorithm Logic
        if c1.button("✅ Mark All Present"): st.session_state.att_state = True
        if c2.button("❌ Mark All Absent"): st.session_state.att_state = False
        
        # Redo Attendance Logic
        if c3.button("🔄 Redo Today (Clear Logs)"):
            db.table("attendance").delete().eq("date", today).execute()
            st.warning("Today's logs cleared. You can start over."); st.rerun()

        if 'att_state' not in st.session_state: st.session_state.att_state = True
        
        df['Attend'] = st.session_state.att_state
        st.write("---")
        st.info("💡 **Algorithm:** Click 'Mark All Present', then **untick** only the workers who are absent.")
        
        edited = st.data_editor(df[['Emp ID', 'name', 'Attend']], use_container_width=True, hide_index=True)
        
        if st.button("💾 Save Attendance"):
            batch = []
            for _, r in edited.iterrows():
                actual_id = df[df['Emp ID'] == r['Emp ID']]['id'].values[0]
                batch.append({"staff_id": actual_id, "date": today, "status": "Present" if r['Attend'] else "Absent"})
            db.table("attendance").upsert(batch).execute()
            st.success("Attendance Synced.")

# --- PAGE 3: FINANCIALS & EXPORT (DELETE TRANSACTIONS) ---
elif page == "Financials & Export":
    st.header("💰 Financial Center")
    df = get_processed_data()
    
    if not df.empty:
        with st.expander("💸 Delete Advances/Transactions"):
            # Flatten transactions for a specific delete list
            all_advs = []
            for _, r in df.iterrows():
                if isinstance(r['advances'], list):
                    for a in r['advances']:
                        all_advs.append({"Trans ID": a['id'], "Name": r['name'], "Amount": a['amount'], "Date": a['date']})
            
            if all_advs:
                adv_df = pd.DataFrame(all_advs)
                for _, trans in adv_df.iterrows():
                    tc1, tc2, tc3 = st.columns([3, 2, 1])
                    tc1.write(f"{trans['Name']} - ₹{trans['Amount']}")
                    tc2.write(f"Date: {trans['Date']}")
                    if tc3.button("🗑️", key=f"trans_{trans['Trans ID']}"):
                        db.table("advances").delete().eq("id", trans['Trans ID']).execute()
                        st.rerun()
            else: st.write("No transactions found.")

        st.divider()
        # Export Logic (Admin gets 3 options, others 1)
        if role == "Admin":
            st.subheader("Master Exports")
            col1, col2, col3 = st.columns(3)
            col1.download_button("📥 HR CSV", df[['Emp ID','name','father_name','aadhar_no']].to_csv(index=False), "HR_Report.csv")
            col2.download_button("📥 Finance CSV", df[['Emp ID','name','account_no','ifsc','Net Payout']].to_csv(index=False), "Finance_Report.csv")
            col3.download_button("📥 Full Master CSV", df.to_csv(index=False), "Full_Master_Report.csv")
        elif role == "HR":
            st.download_button("📥 Export HR CSV", df[['Emp ID','name','father_name','aadhar_no']].to_csv(index=False), "HR_Report.csv")
        elif role == "Finance":
            st.download_button("📥 Export Finance CSV", df[['Emp ID','name','account_no','ifsc','Net Payout']].to_csv(index=False), "Finance_Report.csv")
        
        st.dataframe(df, use_container_width=True, hide_index=True)
