import streamlit as st
import pandas as pd
from supabase import create_client
from PIL import Image
import io
from datetime import datetime, timedelta

# --- 1. BRANDING & DB CONFIG ---
st.set_page_config(page_title="KBP ENERGY PVT LTD - Site OS", layout="wide", page_icon="⚡")

@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

db = init_db()

# --- 2. SPEED BOOST: SMART CACHING ---
@st.cache_data(ttl=600) # Cache data for 10 minutes to stop lag
def get_master_data():
    """Fetches staff and calculates serial Emp IDs and Payouts using vectorized math."""
    res = db.table("staff_master").select("*, attendance(status, date), advances(amount)").order("created_at").execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        # Sequential Shuffle Logic
        df = df.sort_values(by="created_at").reset_index(drop=True)
        df.insert(0, 'Emp ID', range(1, len(df) + 1))
        
        # High-Speed Vectorized Payroll Math
        # Instead of row-by-row, we count in bulk
        def fast_calc(row):
            att = row['attendance']
            presents = sum(1 for x in att if x['status'] == 'Present')
            halfs = sum(1 for x in att if x['status'] == 'Half-Day')
            advs = sum(a['amount'] for a in row['advances']) if isinstance(row['advances'], list) else 0
            return (presents * row['daily_wage']) + (halfs * (row['daily_wage'] / 2)) - advs
        
        df['Net Payout'] = df.apply(fast_calc, axis=1)
    return df

# --- 3. UTILITY: COMPRESSOR ---
def compress_photo(uploaded_file):
    img = Image.open(uploaded_file).convert("RGB")
    quality, img_io = 80, io.BytesIO()
    while True:
        img_io.seek(0); img_io.truncate(0)
        img.save(img_io, format="JPEG", quality=quality, optimize=True)
        if img_io.tell() / 1024 <= 100 or quality <= 5: break
        quality -= 5
        if quality < 30: img = img.resize((int(img.width * 0.8), int(img.height * 0.8)))
    return img_io.getvalue()

# --- AUTHENTICATION ---
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
st.sidebar.title("⚡ KBP ENERGY")
page = st.sidebar.radio("Navigation", ["Worker Management", "Attendance Log", "Attendance Reports", "Export Center"])

if st.sidebar.button("Logout"):
    del st.session_state["user_role"]; st.cache_data.clear(); st.rerun()

# --- PAGE: WORKER MANAGEMENT (PAGINATED FOR SPEED) ---
if page == "Worker Management":
    st.header("📝 Registration & Directory")
    
    if role != "Finance":
        with st.expander("➕ Enroll New Staff"):
            with st.form("enroll_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name, father = c1.text_input("Full Name*"), c2.text_input("Father's Name*")
                dob = c1.date_input("Date of Birth", min_value=datetime(1960,1,1))
                mobile = c2.text_input("Mobile No*", max_chars=10)
                aadhar = c1.text_input("Aadhar No*", max_chars=12)
                acc, ifsc = c2.text_input("Bank Acc*", max_chars=18), c1.text_input("IFSC*", max_chars=11)
                wage = c2.number_input("Daily Wage (₹)", value=500)
                photo = st.file_uploader("Upload ID Photo", type=['jpg','png'])

                if st.form_submit_button("Register"):
                    img_url = ""
                    if photo:
                        img_bytes = compress_photo(photo)
                        path = f"ids/{aadhar}.jpg"
                        db.storage.from_("staff_files").upload(path, img_bytes, {"content-type": "image/jpeg"})
                        img_url = db.storage.from_("staff_files").get_public_url(path)
                    
                    db.table("staff_master").insert({"name": name, "father_name": father, "dob": str(dob), "mobile_no": mobile, "aadhar_no": aadhar, "account_no": acc, "ifsc": ifsc, "daily_wage": wage, "photo_url": img_url, "department": role}).execute()
                    st.cache_data.clear(); st.success("Registered!"); st.rerun()

    # SPEED BOOST: PAGINATION
    df = get_master_data()
    if not df.empty:
        active_df = df[df['leave_date'].isna()]
        st.subheader(f"📋 Active Directory ({len(active_df)} workers)")
        
        # Pagination Logic: 20 per page
        items_per_page = 20
        total_pages = (len(active_df) // items_per_page) + 1
        curr_page = st.number_input("Page", min_value=1, max_value=total_pages, step=1)
        start_idx = (curr_page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        
        page_data = active_df.iloc[start_idx:end_idx]
        
        for _, row in page_data.iterrows():
            dc1, dc2, dc3, dc4 = st.columns([0.5, 3, 1.5, 1])
            dc1.write(f"#{row['Emp ID']}")
            dc2.write(f"**{row['name']}** | Mob: {row.get('mobile_no','N/A')}")
            if dc3.button("Mark Left", key=f"l_{row['id']}"):
                db.table("staff_master").update({"leave_date": str(datetime.now().date())}).eq("id", row['id']).execute()
                st.cache_data.clear(); st.rerun()
            if role == "Admin" and dc4.button("🗑️", key=f"d_{row['id']}"):
                db.table("staff_master").delete().eq("id", row['id']).execute()
                st.cache_data.clear(); st.rerun()

# --- PAGE: ATTENDANCE LOG (MARK ALL EXCEPT) ---
elif page == "Attendance Log":
    st.header("📅 Daily Log")
    df = get_master_data()
    active_df = df[df['leave_date'].isna()]
    today = str(datetime.now().date())
    
    if not active_df.empty:
        tc1, tc2, tc3 = st.columns([1,1,1])
        if tc1.button("✅ Mark ALL Present"): st.session_state.att_bulk = True
        if tc2.button("❌ Mark ALL Absent"): st.session_state.att_bulk = False
        if tc3.button("🔄 Reset Today"):
            db.table("attendance").delete().eq("date", today).execute()
            st.cache_data.clear(); st.rerun()

        if 'att_bulk' not in st.session_state: st.session_state.att_bulk = True
        active_df['Attend'] = st.session_state.att_bulk
        
        # We use a limited view for editing to keep it fast
        edited = st.data_editor(active_df[['Emp ID', 'name', 'Attend']], use_container_width=True, hide_index=True)
        
        if st.button("💾 Save Attendance"):
            batch = [{"staff_id": active_df[active_df['Emp ID'] == r['Emp ID']]['id'].values[0], "date": today, "status": "Present" if r['Attend'] else "Absent"} for _, r in edited.iterrows()]
            db.table("attendance").upsert(batch).execute()
            st.cache_data.clear(); st.success("Synced.")

# --- PAGE: ATTENDANCE REPORTS (TEAM SUMMARY) ---
elif page == "Attendance Reports":
    st.header("📊 Reporting")
    df = get_master_data()
    
    tab1, tab2 = st.tabs(["👤 Individual Audit", "👥 Team Summary"])
    
    with tab1:
        worker = st.selectbox("Search Worker", df['name'].tolist())
        w_id = df[df['name'] == worker]['id'].values[0]
        # Only fetch what's needed here to avoid lag
        logs = db.table("attendance").select("*").eq("staff_id", w_id).order("date", desc=True).limit(100).execute()
        st.dataframe(pd.DataFrame(logs.data)[['date', 'status']], use_container_width=True)

    with tab2:
        period = st.radio("Period:", ["30 Days", "90 Days", "Full Year"], horizontal=True)
        days = 30 if "30" in period else (90 if "90" in period else 365)
        st.write(f"Showing performance summary for last {days} days.")
        
        # Bulk Calculation Logic (Aggregated for Speed)
        summary_list = []
        cutoff = (datetime.now() - timedelta(days=days)).date()
        for _, row in df.iterrows():
            att = [a for a in row['attendance'] if datetime.strptime(a['date'], '%Y-%m-%d').date() >= cutoff]
            p = sum(1 for x in att if x['status'] == 'Present')
            a = sum(1 for x in att if x['status'] == 'Absent')
            summary_list.append({"Emp ID": row['Emp ID'], "Name": row['name'], "Presents": p, "Absents": a, "Rate": f"{round((p/(p+a))*100,1)}%" if (p+a)>0 else "0%"})
        
        summary_df = pd.DataFrame(summary_list)
        st.dataframe(summary_df, use_container_width=True)
        st.download_button("📥 Export Report", summary_df.to_csv(index=False), f"Summary_{period}.csv")

# --- PAGE: EXPORT CENTER ---
elif page == "Export Center":
    st.header("📥 Exports")
    df = get_master_data()
    if not df.empty:
        c1, c2 = st.columns(2)
        if role == "Admin" or role == "HR":
            c1.download_button("📥 Export HR (With Leave Date)", df[['Emp ID','name','mobile_no','dob','leave_date','aadhar_no']].to_csv(index=False), "HR_Master.csv")
        if role == "Admin" or role == "Finance":
            c2.download_button("📥 Export Finance (Bank File)", df[['Emp ID','name','account_no','ifsc','Net Payout']].to_csv(index=False), "Finance_Payouts.csv")
