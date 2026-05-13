import streamlit as st
import sqlite3
import hashlib
import pandas as pd
import os

# ==========================================
# 0. UI HELPERS (LOGO CONFIGURATION)
# ==========================================
def display_logo(width=150):
    """Checks if a logo file exists and displays it. Otherwise shows a placeholder."""
    # You can change "logo.png" to the name of your actual image file (e.g., "logo.jpg")
    if os.path.exists("logo.png"):
        st.image("logo.png", width=width)
    else:
        # Fallback if the file isn't found yet
        st.info("🖼️ Add 'logo.png' to your folder to see it here.")

# ==========================================
# 1. DATABASE CONFIGURATION & SCHEMA
# ==========================================
def get_db_connection():
    """Connects to SQLite with Write-Ahead Logging for concurrency."""
    conn = sqlite3.connect('sabhiv_enterprise.db', timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes schema, triggers, and seed data."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Updated Tables: Added full_name to users, added statuses table
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, pwd TEXT, role TEXT, full_name TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY, project_id INTEGER, user_id INTEGER, 
                    name TEXT, status TEXT, updated_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY, task_id INTEGER, old_status TEXT, 
                    new_status TEXT, ts TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS statuses (
                    id INTEGER PRIMARY KEY, label TEXT UNIQUE, icon TEXT)''')

    # Trigger for Automated Audit Log
    c.execute('''CREATE TRIGGER IF NOT EXISTS log_update AFTER UPDATE OF status ON tasks
                 BEGIN
                    INSERT INTO history (task_id, old_status, new_status, ts)
                    VALUES (OLD.id, OLD.status, NEW.status, CURRENT_TIMESTAMP);
                 END;''')

    # Seed Data (Idempotent)
    pwd = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute('INSERT OR IGNORE INTO users (username, pwd, role, full_name) VALUES (?, ?, ?, ?)', 
              ("admin", pwd, "manager", "System Admin"))
    
    # Default Status Options
    default_statuses = [
        ("Payment Received", "payments"),
        ("Invoice Sent", "receipt_long"),
        ("In Progress", "pending"),
        ("Completed", "check_circle")
    ]
    for label, icon in default_statuses:
        c.execute('INSERT OR IGNORE INTO statuses (label, icon) VALUES (?, ?)', (label, icon))

    conn.commit()
    conn.close()

# ==========================================
# 2. CALLBACKS (STATE MUTATION)
# ==========================================
def update_status(task_id, new_status):
    conn = get_db_connection()
    conn.execute('UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (new_status, task_id))
    conn.commit()
    conn.close()
    st.toast(f"Status changed to {new_status}!", icon="✅")

# ==========================================
# 3. INTERFACE LAYERS
# ==========================================
def team_view(user_id, full_name):
    # Add logo to the top of the team view
    display_logo(width=200)
    st.title("🏢 Sabhiv Enterprise Pvt Ltd")
    st.subheader(f"Welcome, {full_name} (Team Portal)")
    st.divider()

    conn = get_db_connection()

    # --- TOP ROW: Add Task & Add Status ---
    col1, col2 = st.columns(2)
    
    with col1:
        with st.expander("➕ Create a New Task", expanded=False):
            p_name = st.text_input("Project Name (e.g., SMMS App)")
            t_name = st.text_input("Task Name (e.g., Design UI)")
            if st.button("Add Task", use_container_width=True):
                if p_name and t_name:
                    # Create project if it doesn't exist
                    conn.execute('INSERT OR IGNORE INTO projects (name) VALUES (?)', (p_name,))
                    p_id = conn.execute('SELECT id FROM projects WHERE name=?', (p_name,)).fetchone()['id']
                    
                    # Create the task
                    conn.execute('''INSERT INTO tasks (project_id, user_id, name, status, updated_at) 
                                    VALUES (?, ?, ?, 'Created', CURRENT_TIMESTAMP)''', (p_id, user_id, t_name))
                    conn.commit()
                    st.success("Task created successfully!")
                    st.rerun()

    with col2:
        with st.expander("🎨 Add a New Status Option", expanded=False):
            s_label = st.text_input("Status Label (e.g., Waiting on Client)")
            # Common material icons for the user to choose from
            icon_choices = ["pending_actions", "done_all", "bug_report", "build", "warning", "schedule", "group"]
            s_icon = st.selectbox("Select an Icon", icon_choices)
            if st.button("Add Custom Status", use_container_width=True):
                if s_label:
                    try:
                        conn.execute('INSERT INTO statuses (label, icon) VALUES (?, ?)', (s_label, s_icon))
                        conn.commit()
                        st.success(f"Status '{s_label}' added globally!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("This status already exists.")

    # --- BOTTOM ROW: Task Grid ---
    st.markdown("### 📋 Your Active Tasks")
    tasks = conn.execute('''SELECT t.id, t.name, t.status, p.name as p_name 
                            FROM tasks t JOIN projects p ON t.project_id = p.id 
                            WHERE t.user_id=? ORDER BY t.updated_at DESC''', (user_id,)).fetchall()
    
    statuses = conn.execute('SELECT label, icon FROM statuses').fetchall()

    if not tasks:
        st.info("You don't have any tasks yet. Create one above!")

    for task in tasks:
        with st.container(border=True):
            st.markdown(f"**Project:** {task['p_name']} | **Task:** {task['name']}")
            st.caption(f"Current Status: **{task['status']}**")
            
            # Dynamic grid of icon buttons based on the user-defined statuses
            cols = st.columns(min(len(statuses), 5)) 
            for i, status in enumerate(statuses):
                col_idx = i % 5 # Wrap to next row if more than 5 statuses
                cols[col_idx].button(
                    label=status['label'], 
                    icon=f":material/{status['icon']}:", 
                    key=f"t_{task['id']}_{i}",
                    on_click=update_status, 
                    args=(task['id'], status['label']),
                    use_container_width=True
                )
    conn.close()

def manager_view():
    # Add logo to the top of the manager view
    display_logo(width=200)
    st.title("🏢 Sabhiv Enterprise Pvt Ltd")
    st.subheader("Executive Dashboard")
    conn = get_db_connection()
    
    # KPI Row
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Active Tasks", len(pd.read_sql_query('SELECT id FROM tasks', conn)))
    m2.metric("Total Projects", len(pd.read_sql_query('SELECT id FROM projects', conn)))
    m3.metric("Registered Team Members", len(pd.read_sql_query("SELECT id FROM users WHERE role='team_member'", conn)))

    # Real-time Pipeline
    st.markdown("### Global Project Pipeline")
    df = pd.read_sql_query('''SELECT p.name as "Project Name", t.name as "Task", u.full_name as "Assigned To", 
                                     t.status as "Status", t.updated_at as "Last Update"
                              FROM tasks t 
                              JOIN projects p ON t.project_id = p.id
                              JOIN users u ON t.user_id = u.id''', conn)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Audit Trail
    st.markdown("### Historical Audit Trail")
    history = pd.read_sql_query('''SELECT u.full_name as "User", t.name as "Task", 
                                          h.old_status as "Old Status", h.new_status as "New Status", h.ts as "Timestamp"
                                   FROM history h 
                                   JOIN tasks t ON h.task_id = t.id 
                                   JOIN users u ON t.user_id = u.id
                                   ORDER BY h.ts DESC''', conn)
    st.dataframe(history, use_container_width=True, hide_index=True)
    conn.close()

# ==========================================
# 4. ROUTING & AUTHENTICATION
# ==========================================
def main():
    # Set page config (adds a tiny logo to the browser tab if you have a favicon)
    st.set_page_config(page_title="Sabhiv Enterprise Tracker", page_icon="🏢", layout="wide")
    init_db()

    if "auth" not in st.session_state:
        st.session_state.auth = False

    if not st.session_state.auth:
        # Show logo on the login page
        display_logo(width=200)
        st.title("Sabhiv Enterprise Pvt Ltd")
        st.markdown("Welcome to the Operations Portal.")
        
        tab1, tab2 = st.tabs(["Login", "Sign Up (New User)"])
        
        with tab1:
            with st.form("Login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Access System", use_container_width=True):
                    hp = hashlib.sha256(p.encode()).hexdigest()
                    conn = get_db_connection()
                    user = conn.execute('SELECT * FROM users WHERE username=? AND pwd=?', (u, hp)).fetchone()
                    conn.close()
                    
                    if user:
                        st.session_state.auth = True
                        st.session_state.role = user['role']
                        st.session_state.uid = user['id']
                        st.session_state.full_name = user['full_name']
                        st.rerun()
                    else:
                        st.error("Access Denied: Invalid Credentials")
                        
        with tab2:
            with st.form("Signup"):
                new_name = st.text_input("Your Full Name (e.g., John Doe)")
                new_user = st.text_input("Choose a Username")
                new_pwd = st.text_input("Choose a Password", type="password")
                if st.form_submit_button("Create Account", use_container_width=True):
                    if new_name and new_user and new_pwd:
                        hp = hashlib.sha256(new_pwd.encode()).hexdigest()
                        conn = get_db_connection()
                        try:
                            conn.execute('INSERT INTO users (username, pwd, role, full_name) VALUES (?, ?, ?, ?)', 
                                         (new_user, hp, 'team_member', new_name))
                            conn.commit()
                            st.success("Account created! You can now log in via the Login tab.")
                        except sqlite3.IntegrityError:
                            st.error("That username is already taken. Please choose another.")
                        finally:
                            conn.close()

    else:
        # Sidebar for Logout & Context
        with st.sidebar:
            # Show a smaller version of the logo in the sidebar
            display_logo(width=100)
            st.divider()
            st.write(f"Logged in as: **{st.session_state.full_name}**")
            st.button("Logout", icon=":material/logout:", on_click=lambda: st.session_state.clear(), use_container_width=True)
            
        # Role-based Routing
        if st.session_state.role == "manager":
            manager_view()
        else:
            team_view(st.session_state.uid, st.session_state.full_name)

if __name__ == "__main__":
    main()
