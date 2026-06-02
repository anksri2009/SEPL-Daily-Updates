import streamlit as st
import sqlite3
import hashlib
import pandas as pd
import os
import base64

# ==========================================
# 0. GLOBAL ASSETS & CONFIGURATION
# ==========================================
st.set_page_config(page_title="Sabhiv Enterprise Portal", page_icon="🏢", layout="wide", initial_sidebar_state="expanded")

def get_image_as_base64(file_path):
    """Converts a local image to a base64 string for HTML/CSS rendering."""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        return f"data:image/png;base64,{base64.b64encode(data).decode()}"
    except FileNotFoundError:
        # Safe fallback URL if logo.png is accidentally deleted or moved
        return "https://cdn-icons-png.flaticon.com/512/2942/2942245.png"

# This will load your local logo.png file
LOGO_SRC = get_image_as_base64("logo.png")

# Inject Custom CSS for Watermark, Centering, and Enterprise Look
st.markdown(f"""
    <style>
    /* Global Watermark Background */
    .stApp::before {{
        content: "";
        background-image: url('{LOGO_SRC}');
        background-size: 400px; /* Size of the watermark */
        background-position: center;
        background-repeat: no-repeat;
        background-attachment: fixed;
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        opacity: 0.04; /* 4% opacity makes it a subtle watermark */
        z-index: 0;
        pointer-events: none; /* Ensures the watermark doesn't block mouse clicks */
    }}

    /* Ensure content stays above the watermark */
    [data-testid="stAppViewContainer"] > .main {{ z-index: 1; }}
    
    /* Global Typography and Background */
    .main-header {{ font-size: 2.5rem; color: #1e3a8a; font-weight: 800; padding-bottom: 0px; text-align: center; }}
    .sub-header {{ font-size: 1.1rem; color: #64748b; padding-top: 0px; margin-bottom: 2rem; text-align: center; }}
    
    /* Center the login box and its contents */
    .login-box {{ 
        margin: auto; 
        padding: 2rem; 
        border-radius: 10px; 
        background-color: rgba(255, 255, 255, 0.95); /* Slight transparency */
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); 
        text-align: center;
    }}
    
    /* Styling Metrics */
    div[data-testid="stMetricValue"] {{ color: #1e3a8a; font-weight: 700; }}
    
    /* Better Expander Headers */
    .streamlit-expanderHeader {{ font-weight: 600 !important; color: #1e3a8a !important; }}
    </style>
""", unsafe_allow_html=True)


# ==========================================
# 1. DATABASE CONNECTION & CACHING
# ==========================================
@st.cache_resource
def get_db_connection():
    conn = sqlite3.connect('sabhiv_enterprise.db', timeout=15, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL;') 
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Original Tables
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, pwd TEXT, role TEXT, full_name TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, project_id INTEGER, user_id INTEGER, name TEXT, status TEXT, updated_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, task_id INTEGER, old_status TEXT, new_status TEXT, ts TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS statuses (id INTEGER PRIMARY KEY, label TEXT UNIQUE, icon TEXT)''')

    # NEW TABLE: Plug-and-Play User Data Storage
    c.execute('''CREATE TABLE IF NOT EXISTS user_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_identifier TEXT, 
                    user_data TEXT, 
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TRIGGER IF NOT EXISTS log_update AFTER UPDATE OF status ON tasks
                 BEGIN INSERT INTO history (task_id, old_status, new_status, ts) VALUES (OLD.id, OLD.status, NEW.status, CURRENT_TIMESTAMP); END;''')

    pwd = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute('INSERT OR IGNORE INTO users (username, pwd, role, full_name) VALUES (?, ?, ?, ?)', ("admin", pwd, "manager", "System Admin"))
    
    default_statuses = [("Payment Received", "payments"), ("Invoice Sent", "receipt_long"), ("In Progress", "pending"), ("Completed", "check_circle")]
    for label, icon in default_statuses:
        c.execute('INSERT OR IGNORE INTO statuses (label, icon) VALUES (?, ?)', (label, icon))
    conn.commit()

# ==========================================
# 2. CACHED DATA FETCHING & STORAGE FUNCTIONS
# ==========================================
@st.cache_data(ttl=300) 
def get_global_pipeline():
    conn = get_db_connection()
    return pd.read_sql_query('''SELECT p.name as "Project Name", t.name as "Task", u.full_name as "Assigned To", t.status as "Status", t.updated_at as "Last Update" FROM tasks t JOIN projects p ON t.project_id = p.id JOIN users u ON t.user_id = u.id ORDER BY t.updated_at DESC''', conn)

def save_user_data(user_id, data_payload):
    """Inserts a new user record into the HDD database."""
    conn = get_db_connection()
    conn.execute('INSERT INTO user_records (user_identifier, user_data) VALUES (?, ?)', (user_id, data_payload))
    conn.commit()

def get_all_user_data():
    """Retrieves all stored records for manager view."""
    conn = get_db_connection()
    return pd.read_sql_query('SELECT user_identifier as "User", user_data as "Stored Data", timestamp as "Timestamp" FROM user_records ORDER BY timestamp DESC', conn)

def get_personal_user_data(user_id):
    """Retrieves specific stored records for an individual user."""
    conn = get_db_connection()
    return pd.read_sql_query('SELECT user_data as "Stored Data", timestamp as "Timestamp" FROM user_records WHERE user_identifier=? ORDER BY timestamp DESC', conn, params=(user_id,))


# ==========================================
# 3. STATE MUTATIONS (CALLBACKS)
# ==========================================
def update_status(task_id, new_status):
    conn = get_db_connection()
    conn.execute('UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (new_status, task_id))
    conn.commit()
    get_global_pipeline.clear() 
    st.toast(f"Status successfully updated to {new_status}!", icon="✅")

# ==========================================
# 4. INTERFACE LAYERS
# ==========================================
def team_view(user_id, full_name):
    st.markdown(f'<img src="{LOGO_SRC}" style="display: block; margin: 0 auto; width: 60px;">', unsafe_allow_html=True)
    st.markdown('<p class="main-header">Team Workspace</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="sub-header">Welcome back, {full_name}. Here are your active assignments.</p>', unsafe_allow_html=True)
    
    # Use tabs to organize the upgraded app layout
    tab_tasks, tab_storage = st.tabs(["📋 Task Manager", "💾 Personal Notes & Storage"])
    
    with tab_tasks:
        conn = get_db_connection()

        col1, col2 = st.columns(2)
        with col1:
            with st.expander("➕ Create a New Task", expanded=False):
                with st.form("new_task_form", clear_on_submit=True):
                    p_name = st.text_input("Project Name", placeholder="e.g., Q3 Marketing Campaign")
                    t_name = st.text_input("Task Description", placeholder="e.g., Draft social media posts")
                    if st.form_submit_button("Add Task", use_container_width=True):
                        if p_name and t_name:
                            conn.execute('INSERT OR IGNORE INTO projects (name) VALUES (?)', (p_name,))
                            p_id = conn.execute('SELECT id FROM projects WHERE name=?', (p_name,)).fetchone()['id']
                            conn.execute('''INSERT INTO tasks (project_id, user_id, name, status, updated_at) VALUES (?, ?, ?, 'Created', CURRENT_TIMESTAMP)''', (p_id, user_id, t_name))
                            conn.commit()
                            get_global_pipeline.clear()
                            st.success("Task created!")
                            st.rerun()

        with col2:
            with st.expander("🎨 Add a New Status Option", expanded=False):
                with st.form("new_status_form", clear_on_submit=True):
                    s_label = st.text_input("Status Label", placeholder="e.g., Pending Review")
                    s_icon = st.selectbox("Select an Icon", ["pending_actions", "done_all", "bug_report", "build", "warning", "schedule", "group"])
                    if st.form_submit_button("Save Status Global", use_container_width=True):
                        if s_label:
                            try:
                                conn.execute('INSERT INTO statuses (label, icon) VALUES (?, ?)', (s_label, s_icon))
                                conn.commit()
                                st.success(f"Status '{s_label}' added!")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error("This status already exists.")

        st.divider()
        st.markdown("### 📋 Your Active Tasks")
        tasks = conn.execute('''SELECT t.id, t.name, t.status, p.name as p_name FROM tasks t JOIN projects p ON t.project_id = p.id WHERE t.user_id=? ORDER BY t.updated_at DESC''', (user_id,)).fetchall()
        statuses = conn.execute('SELECT label, icon FROM statuses').fetchall()

        if not tasks: st.info("You are all caught up! No active tasks at the moment.")

        for task in tasks:
            with st.container(border=True):
                col_info, col_actions = st.columns([1, 2])
                with col_info:
                    st.markdown(f"**{task['p_name']}**")
                    st.markdown(f"↳ {task['name']}")
                    st.caption(f"Current Phase: :blue[{task['status']}]")
                with col_actions:
                    st.write("Update Phase:")
                    cols = st.columns(len(statuses)) 
                    for i, status in enumerate(statuses):
                        cols[i].button(
                            label=status['label'], icon=f":material/{status['icon']}:", key=f"t_{task['id']}_{i}",
                            on_click=update_status, args=(task['id'], status['label']), use_container_width=True,
                            type="primary" if task['status'] == status['label'] else "secondary"
                        )
                        
    with tab_storage:
        st.markdown("### Secure Local Storage")
        st.write("Information entered here is permanently saved to the master HDD database.")
        with st.form("user_data_form", clear_on_submit=True):
            user_notes = st.text_area("Enter data, links, or permanent notes:")
            if st.form_submit_button("Save to HDD"):
                if user_notes.strip():
                    save_user_data(full_name, user_notes)
                    st.success("Record securely saved to the database file!")
                    st.rerun()
                else:
                    st.warning("Please enter some data before saving.")
        
        st.divider()
        st.markdown("#### Your Saved Records")
        historical_data = get_personal_user_data(full_name)
        
        if not historical_data.empty:
            st.dataframe(historical_data, use_container_width=True, hide_index=True)
            st.caption(f"Local database path: `{os.path.abspath('sabhiv_enterprise.db')}`")
        else:
            st.info("No personal data stored yet.")

def manager_view():
    st.markdown(f'<img src="{LOGO_SRC}" style="display: block; margin: 0 auto; width: 60px;">', unsafe_allow_html=True)
    st.markdown('<p class="main-header">Executive Dashboard</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Real-time overview of enterprise operations.</p>', unsafe_allow_html=True)
    
    # Use tabs for executive overview vs data review
    tab_dash, tab_storage = st.tabs(["📊 Global Pipeline", "💾 Master HDD Records"])
    
    with tab_dash:
        conn = get_db_connection()
        df_pipeline = get_global_pipeline()
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Active Tasks", len(df_pipeline))
        m2.metric("Total Projects", len(pd.read_sql_query('SELECT id FROM projects', conn)))
        m3.metric("Team Members", len(pd.read_sql_query("SELECT id FROM users WHERE role='team_member'", conn)))
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
        st.markdown("**Historical Audit Trail**")
        history = pd.read_sql_query('''SELECT u.full_name as "User", t.name as "Task", h.old_status as "Old Status", h.new_status as "New Status", h.ts as "Timestamp" FROM history h JOIN tasks t ON h.task_id = t.id JOIN users u ON t.user_id = u.id ORDER BY h.ts DESC LIMIT 50''', conn)
        st.dataframe(history, use_container_width=True, hide_index=True)
        
    with tab_storage:
        st.markdown("### Enterprise Data Logs")
        st.write("This secure view displays all information stored to the local drive by any enterprise user.")
        
        all_data = get_all_user_data()
        if not all_data.empty:
            st.dataframe(all_data, use_container_width=True, hide_index=True)
            st.caption(f"Master database active at: `{os.path.abspath('sabhiv_enterprise.db')}`")
        else:
            st.info("The storage database is currently empty.")

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
                        conn = get_db_connection()
                        user = conn.execute('SELECT * FROM users WHERE username=? AND pwd=?', (u, hp)).fetchone()
                        if user:
                            st.session_state.update({"auth": True, "role": user['role'], "uid": user['id'], "full_name": user['full_name']})
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
                            conn = get_db_connection()
                            try:
                                conn.execute('INSERT INTO users (username, pwd, role, full_name) VALUES (?, ?, ?, ?)', (new_user, hp, 'team_member', new_name))
                                conn.commit()
                                st.success("Registration successful! Proceed to Secure Login.")
                            except sqlite3.IntegrityError: st.error("Username taken. Please contact IT.")

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
