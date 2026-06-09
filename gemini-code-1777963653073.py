import streamlit as st
import hashlib
import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import os
import base64

# ==========================================
# 0. GLOBAL ASSETS & CONFIGURATION
# ==========================================
st.set_page_config(page_title="Sabhiv Enterprise Portal", page_icon="🏢", layout="wide", initial_sidebar_state="expanded")

def get_image_as_base64(file_path):
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        return f"data:image/png;base64,{base64.b64encode(data).decode()}"
    except FileNotFoundError:
        return "https://cdn-icons-png.flaticon.com/512/2942/2942245.png"

LOGO_SRC = get_image_as_base64("logo.png")

st.markdown(f"""
    <style>
    .stApp::before {{
        content: ""; background-image: url('{LOGO_SRC}'); background-size: 400px; 
        background-position: center; background-repeat: no-repeat; background-attachment: fixed;
        position: absolute; top: 0; left: 0; right: 0; bottom: 0; opacity: 0.04; z-index: 0; pointer-events: none; 
    }}
    [data-testid="stAppViewContainer"] > .main {{ z-index: 1; }}
    .main-header {{ font-size: 2.5rem; color: #1e3a8a; font-weight: 800; padding-bottom: 0px; text-align: center; }}
    .sub-header {{ font-size: 1.1rem; color: #64748b; padding-top: 0px; margin-bottom: 2rem; text-align: center; }}
    .login-box {{ 
        margin: auto; padding: 2rem; border-radius: 10px; background-color: rgba(255, 255, 255, 0.95); 
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center;
    }}
    div[data-testid="stMetricValue"] {{ color: #1e3a8a; font-weight: 700; }}
    .streamlit-expanderHeader {{ font-weight: 600 !important; color: #1e3a8a !important; }}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. CLOUD DATABASE CONNECTION (POSTGRESQL)
# ==========================================
# Fails gracefully if the user forgets to set up the Streamlit Secret
if "DATABASE_URL" not in st.secrets:
    st.error("⚠️ DATABASE_URL secret is missing! Please add it to your Streamlit Cloud Secrets.")
    st.stop()

# Streamlit's native way to connect to a cloud SQL database
conn = st.connection("postgresql", type="sql", url=st.secrets["DATABASE_URL"])

def init_db():
    """Builds the Postgres schema. Ensures permanent cloud storage."""
    with conn.session as s:
        s.execute(text('''CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE, pwd TEXT, role TEXT, full_name TEXT)'''))
        s.execute(text('CREATE TABLE IF NOT EXISTS projects (id SERIAL PRIMARY KEY, name TEXT UNIQUE)'))
        # ON DELETE CASCADE ensures if admin deletes a user, their tasks don't crash the database
        s.execute(text('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, project_id INTEGER REFERENCES projects(id), user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, name TEXT, status TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE, old_status TEXT, new_status TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS statuses (id SERIAL PRIMARY KEY, label TEXT UNIQUE, icon TEXT)'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS user_records (id SERIAL PRIMARY KEY, user_identifier TEXT, user_data TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

        # Seed Data
        pwd = hashlib.sha256("admin123".encode()).hexdigest()
        s.execute(text('INSERT INTO users (username, pwd, role, full_name) VALUES (:u, :p, :r, :f) ON CONFLICT (username) DO NOTHING'), {"u": "admin", "p": pwd, "r": "manager", "f": "System Admin"})
        
        default_statuses = [("Payment Received", "payments"), ("Invoice Sent", "receipt_long"), ("In Progress", "pending"), ("Completed", "check_circle")]
        for label, icon in default_statuses:
            s.execute(text('INSERT INTO statuses (label, icon) VALUES (:l, :i) ON CONFLICT (label) DO NOTHING'), {"l": label, "i": icon})
        s.commit()

# ==========================================
# 2. DATA FETCHING (LIVE NO-CACHE QUERIES)
# ==========================================
def get_global_pipeline():
    return conn.query('SELECT p.name as "Project Name", t.name as "Task", u.full_name as "Assigned To", t.status as "Status", t.updated_at as "Last Update" FROM tasks t JOIN projects p ON t.project_id = p.id JOIN users u ON t.user_id = u.id ORDER BY t.updated_at DESC', ttl=0)

def get_all_user_data():
    return conn.query('SELECT user_identifier as "User", user_data as "Stored Data", timestamp as "Timestamp" FROM user_records ORDER BY timestamp DESC', ttl=0)

def get_personal_user_data(user_id):
    return conn.query('SELECT user_data as "Stored Data", timestamp as "Timestamp" FROM user_records WHERE user_identifier=:uid ORDER BY timestamp DESC', params={"uid": user_id}, ttl=0)

# ==========================================
# 3. STATE MUTATIONS (CALLBACKS)
# ==========================================
def save_user_data(user_id, data_payload):
    with conn.session as s:
        s.execute(text('INSERT INTO user_records (user_identifier, user_data) VALUES (:uid, :data)'), {"uid": user_id, "data": data_payload})
        s.commit()

def update_status(task_id, new_status, old_status):
    with conn.session as s:
        s.execute(text('UPDATE tasks SET status=:s, updated_at=CURRENT_TIMESTAMP WHERE id=:id'), {"s": new_status, "id": task_id})
        s.execute(text('INSERT INTO history (task_id, old_status, new_status) VALUES (:id, :old, :new)'), {"id": task_id, "old": old_status, "new": new_status})
        s.commit()
    st.toast(f"Status updated to {new_status}! Saved to Cloud.", icon="✅")

def admin_delete_user(target_user_id, target_username):
    with conn.session as s:
        s.execute(text('DELETE FROM users WHERE id=:id'), {"id": int(target_user_id)})
        s.commit()
    st.toast(f"User '{target_username}' has been permanently deleted from the cloud.", icon="🗑️")

# ==========================================
# 4. INTERFACE LAYERS
# ==========================================
def team_view(user_id, full_name):
    st.markdown(f'<img src="{LOGO_SRC}" style="display: block; margin: 0 auto; width: 60px;">', unsafe_allow_html=True)
    st.markdown('<p class="main-header">Team Workspace</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="sub-header">Welcome back, {full_name}. Here are your active assignments.</p>', unsafe_allow_html=True)
    
    tab_tasks, tab_history, tab_storage = st.tabs(["📋 Task Manager", "🕒 My Task History Log", "💾 Personal Notes & Storage"])
    
    with tab_tasks:
        col1, col2 = st.columns(2)
        with col1:
            with st.expander("➕ Create a New Task", expanded=False):
                with st.form("new_task_form", clear_on_submit=True):
                    p_name = st.text_input("Project Name", placeholder="e.g., Q3 Marketing Campaign")
                    t_name = st.text_input("Task Description", placeholder="e.g., Draft social media posts")
                    if st.form_submit_button("Add Task", use_container_width=True):
                        if p_name and t_name:
                            with conn.session as s:
                                s.execute(text('INSERT INTO projects (name) VALUES (:n) ON CONFLICT (name) DO NOTHING'), {"n": p_name})
                                p_id = s.execute(text('SELECT id FROM projects WHERE name=:n'), {"n": p_name}).fetchone()[0]
                                new_task_id = s.execute(text('''INSERT INTO tasks (project_id, user_id, name, status) VALUES (:pid, :uid, :n, 'Created') RETURNING id'''), {"pid": p_id, "uid": int(user_id), "n": t_name}).fetchone()[0]
                                s.execute(text('''INSERT INTO history (task_id, old_status, new_status) VALUES (:tid, 'None', 'Created')'''), {"tid": new_task_id})
                                s.commit()
                            st.success("Task created and permanently logged to Cloud!")
                            st.rerun()

        with col2:
            with st.expander("🎨 Add a New Status Option", expanded=False):
                with st.form("new_status_form", clear_on_submit=True):
                    s_label = st.text_input("Status Label", placeholder="e.g., Pending Review")
                    s_icon = st.selectbox("Select an Icon", ["pending_actions", "done_all", "bug_report", "build", "warning", "schedule", "group"])
                    if st.form_submit_button("Save Status Global", use_container_width=True):
                        if s_label:
                            try:
                                with conn.session as s:
                                    s.execute(text('INSERT INTO statuses (label, icon) VALUES (:l, :i)'), {"l": s_label, "i": s_icon})
                                    s.commit()
                                st.success(f"Status '{s_label}' added!")
                                st.rerun()
                            except IntegrityError:
                                st.error("This status already exists.")

        st.divider()
        st.markdown("### 📋 Your Active Tasks")
        tasks = conn.query('SELECT t.id, t.name, t.status, p.name as p_name FROM tasks t JOIN projects p ON t.project_id = p.id WHERE t.user_id=:uid ORDER BY t.updated_at DESC', params={"uid": int(user_id)}, ttl=0)
        statuses = conn.query('SELECT label, icon FROM statuses', ttl=0)

        if tasks.empty: 
            st.info("You are all caught up! No active tasks at the moment.")
        else:
            for index, task in tasks.iterrows():
                with st.container(border=True):
                    col_info, col_actions = st.columns([1, 2])
                    with col_info:
                        st.markdown(f"**{task['p_name']}**")
                        st.markdown(f"↳ {task['name']}")
                        st.caption(f"Current Phase: :blue[{task['status']}]")
                    with col_actions:
                        st.write("Update Phase:")
                        cols = st.columns(len(statuses)) 
                        for i, status in statuses.iterrows():
                            cols[i].button(
                                label=status['label'], icon=f":material/{status['icon']}:", key=f"t_{task['id']}_{i}",
                                on_click=update_status, args=(int(task['id']), status['label'], task['status']), use_container_width=True,
                                type="primary" if task['status'] == status['label'] else "secondary"
                            )
    
    with tab_history:
        st.markdown("### 🕒 Your Permanent Task History")
        user_history = conn.query('''SELECT p.name as "Project", t.name as "Task", h.old_status as "Previous State", h.new_status as "New State", h.ts as "Timestamp" FROM history h JOIN tasks t ON h.task_id = t.id JOIN projects p ON t.project_id = p.id WHERE t.user_id = :uid ORDER BY h.ts DESC''', params={"uid": int(user_id)}, ttl=0)
        if not user_history.empty:
            st.dataframe(user_history, use_container_width=True, hide_index=True)
        else:
            st.info("No task history recorded yet.")
                        
    with tab_storage:
        st.markdown("### Secure Cloud Storage")
        with st.form("user_data_form", clear_on_submit=True):
            user_notes = st.text_area("Enter data, links, or permanent notes:")
            if st.form_submit_button("Save to Cloud"):
                if user_notes.strip():
                    save_user_data(full_name, user_notes)
                    st.success("Record securely saved to the database!")
                    st.rerun()
                else:
                    st.warning("Please enter some data before saving.")
        st.divider()
        st.markdown("#### Your Saved Records")
        historical_data = get_personal_user_data(full_name)
        if not historical_data.empty:
            st.dataframe(historical_data, use_container_width=True, hide_index=True)
        else:
            st.info("No personal data stored yet.")

def manager_view():
    st.markdown(f'<img src="{LOGO_SRC}" style="display: block; margin: 0 auto; width: 60px;">', unsafe_allow_html=True)
    st.markdown('<p class="main-header">Executive Dashboard</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Real-time overview of enterprise operations.</p>', unsafe_allow_html=True)
    
    tab_dash, tab_storage, tab_users = st.tabs(["📊 Global Pipeline", "💾 Master Cloud Records", "👥 User Management"])
    
    with tab_dash:
        df_pipeline = get_global_pipeline()
        projects_count = len(conn.query('SELECT id FROM projects', ttl=0))
        users_count = len(conn.query("SELECT id FROM users WHERE role='team_member'", ttl=0))
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Active Tasks", len(df_pipeline))
        m2.metric("Total Projects", projects_count)
        m3.metric("Team Members", users_count)
        m4.metric("Completed Tasks", len(df_pipeline[df_pipeline["Status"] == "Completed"]) if not df_pipeline.empty else 0)

        st.divider()
        col_chart, col_data = st.columns([1, 2])
        with col_chart:
            st.markdown("**Tasks by Status**")
            if not df_pipeline.empty:
                status_counts = df_pipeline["Status"].value_counts().reset_index()
                status_counts.columns = ["Status", "Count"]
                st.bar_chart(status_counts, x="Status", y="Count", height=300, color="#1e3a8a")
            else: st.info("No data available yet.")

        with col_data:
            st.markdown("**Global Project Pipeline**")
            st.dataframe(df_pipeline, use_container_width=True, hide_index=True, height=300)

        st.divider()
        st.markdown("**Enterprise Master Audit Trail (Cloud Log)**")
        history = conn.query('''SELECT u.full_name as "User", p.name as "Project", t.name as "Task", h.old_status as "Old Status", h.new_status as "New Status", h.ts as "Timestamp" FROM history h JOIN tasks t ON h.task_id = t.id JOIN projects p ON t.project_id = p.id JOIN users u ON t.user_id = u.id ORDER BY h.ts DESC LIMIT 200''', ttl=0)
        st.dataframe(history, use_container_width=True, hide_index=True)
        
    with tab_storage:
        st.markdown("### Enterprise Data Logs")
        all_data = get_all_user_data()
        if not all_data.empty:
            st.dataframe(all_data, use_container_width=True, hide_index=True)
        else:
            st.info("The storage database is currently empty.")
            
    with tab_users:
        st.markdown("### Registered Team Members")
        registered_users = conn.query("SELECT id, username, full_name, role FROM users WHERE username != 'admin'", ttl=0)
        
        if not registered_users.empty:
            for index, row in registered_users.iterrows():
                with st.container(border=True):
                    u_col1, u_col2 = st.columns([4, 1])
                    with u_col1:
                        st.markdown(f"👤 **{row['full_name']}** (Username: `{row['username']}`)")
                        st.caption(f"System Role: {str(row['role']).capitalize()}")
                    with u_col2:
                        st.button(
                            "Delete User", key=f"del_user_{row['id']}", on_click=admin_delete_user, 
                            args=(int(row['id']), row['username']), type="primary", use_container_width=True
                        )
        else:
            st.info("No team members have registered yet.")

# ==========================================
# 5. CORE ROUTING & AUTHENTICATION
# ==========================================
def main():
    init_db()

    if "auth" not in st.session_state:
        st.session_state.update({"auth": False, "role": None, "uid": None, "full_name": None})

    if not st.session_state.auth:
        _, center_col, _ = st.columns([1, 1.5, 1])
        with center_col:
            st.markdown(f'''
                <div class="login-box">
                    <img src="{LOGO_SRC}" width="80" style="margin-bottom: 10px;">
                    <h2 style="color: #1e3a8a; margin-top: 0;">Sabhiv Enterprise Pvt Ltd</h2>
                    <p style="color:gray; margin-bottom:20px;">Please authenticate to access the system.</p>
                </div>
            ''', unsafe_allow_html=True)
            
            tab1, tab2 = st.tabs(["🔒 Secure Login", "📝 Employee Registration"])
            with tab1:
                with st.form("Login"):
                    u = st.text_input("Username")
                    p = st.text_input("Password", type="password")
                    if st.form_submit_button("Access Portal", use_container_width=True):
                        hp = hashlib.sha256(p.encode()).hexdigest()
                        df = conn.query('SELECT * FROM users WHERE username=:u AND pwd=:p', params={"u": u, "p": hp}, ttl=0)
                        if not df.empty:
                            user = df.iloc[0]
                            st.session_state.update({"auth": True, "role": user['role'], "uid": int(user['id']), "full_name": user['full_name']})
                            st.rerun()
                        else: st.error("Access Denied: Invalid Credentials")
                            
            with tab2:
                with st.form("Signup"):
                    new_name = st.text_input("Full Legal Name")
                    new_user = st.text_input("Desired Username")
                    new_pwd = st.text_input("Password", type="password")
                    if st.form_submit_button("Submit Registration", use_container_width=True):
                        if new_name and new_user and new_pwd:
                            hp = hashlib.sha256(new_pwd.encode()).hexdigest()
                            try:
                                with conn.session as s:
                                    s.execute(text('INSERT INTO users (username, pwd, role, full_name) VALUES (:u, :p, :r, :f)'), {"u": new_user, "p": hp, "r": 'team_member', "f": new_name})
                                    s.commit()
                                st.success("Registration successful! Your account is permanently saved in the Cloud. Proceed to Login.")
                            except IntegrityError: 
                                st.error("Username taken. Please choose another.")

    else:
        with st.sidebar:
            st.markdown(f'<img src="{LOGO_SRC}" width="60" style="margin-bottom: 10px;">', unsafe_allow_html=True)
            st.markdown(f"**{st.session_state.full_name}**")
            st.caption(f"Role: {str(st.session_state.role).capitalize()}")
            st.divider()
            st.button("Secure Logout", icon=":material/logout:", on_click=lambda: st.session_state.clear(), use_container_width=True)
            
        if st.session_state.role == "manager":
            manager_view()
        else:
            team_view(st.session_state.uid, st.session_state.full_name)

if __name__ == "__main__":
    main()
