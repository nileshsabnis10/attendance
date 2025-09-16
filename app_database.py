# SGU Monthly Attendance — Supabase Database Version (with Electives & Course Reports)
# Requires: streamlit, supabase, pandas, xlsxwriter, plotly
# -----------------------------------------------------------------------------
# Patched: Consolidated all recent features and fixes into a final, optimized single file.
# Timestamp: 2025-09-16
# Filename: app_final_v7.2.py
# -----------------------------------------------------------------------------
# Version: 7.2
# -----------------------------------------------------------------------------

import io
from datetime import datetime
import pandas as pd
import streamlit as st
import plotly.express as px
from supabase import create_client, Client

# ───────────────────────── App Config & Constants ─────────────────────────
st.set_page_config(page_title="SGU Attendance (DB)", page_icon="📚", layout="wide")
APP_TITLE = "SGU Monthly Attendance"
APP_SUBTITLE = "Creative Minds"
__version__ = "7.2"
CLASS_CHOICES = ["First Year", "Second Year", "Third Year", "Fourth Year"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
STATUS_LOCKED = "LOCKED"
STATUS_DRAFT = "DRAFT"

# ───────────────────────── Supabase Connection ─────────────────────────
@st.cache_resource(show_spinner="Connecting to the database...")
def get_supabase_client() -> Client:
    url = st.secrets.get("supabase", {}).get("url")
    key = st.secrets.get("supabase", {}).get("key")
    if not url or not key:
        st.error("Supabase URL and Key are not configured in secrets.toml.")
        st.stop()
    return create_client(url, key)

supabase = get_supabase_client()

# ───────────────────────── Secrets & State Management ─────────────────────────
ADMIN_USER = st.secrets.get("admin", {}).get("username")
ADMIN_PASS = st.secrets.get("admin", {}).get("password")
DANGER_ZONE_PASSWORD = st.secrets.get("danger_zone", {}).get("password", None)

def is_danger_unlocked() -> bool:
    return bool(st.session_state.get("DANGER_ZONE_ACTIVE", False))

def lock_danger_zone():
    st.session_state["DANGER_ZONE_ACTIVE"] = False

def try_unlock_danger_zone(pw: str) -> bool:
    ok = (DANGER_ZONE_PASSWORD is not None and pw == DANGER_ZONE_PASSWORD)
    st.session_state["DANGER_ZONE_ACTIVE"] = ok
    return ok

# ───────────────────────── Database Helper Functions ─────────────────────────
def log_action(user_id: str, action: str, details: dict):
    """Logs an action to the audit_log table."""
    try:
        supabase.table('audit_log').insert({"user_id": user_id, "action": action, "details": details}).execute()
    except Exception as e:
        print(f"Failed to log action: {e}")

@st.cache_data(show_spinner="Fetching departments...")
def get_departments() -> list:
    try: return supabase.table('departments').select('id, name').execute().data or []
    except Exception as e: st.error(f"DB Error (get_departments): {e}"); return []

@st.cache_data(show_spinner="Loading student roster...")
def load_roster(department_id: int, class_name: str, section: str) -> pd.DataFrame:
    try:
        response = supabase.table('students').select('*').eq('department_id', department_id).eq('class_name', class_name).eq('section', section).eq('is_active', True).order('PRN').execute()
        return pd.DataFrame(response.data)
    except Exception as e: st.error(f"DB Error (load_roster): {e}"); return pd.DataFrame()

@st.cache_data(show_spinner="Fetching courses...")
def get_courses(department_id: int, class_name: str, section: str) -> pd.DataFrame:
    try:
        response = supabase.table('courses').select('*').eq('department_id', department_id).eq('class_name', class_name).eq('section', section).execute()
        return pd.DataFrame(response.data)
    except Exception as e: st.error(f"DB Error (get_courses): {e}"); return pd.DataFrame()

@st.cache_data(show_spinner="Fetching sections...")
def get_sections_for_class(department_id: int, class_name: str) -> list:
    try:
        response = supabase.table('students').select('section').eq('department_id', department_id).eq('class_name', class_name).execute()
        if response.data:
            return sorted(list(set([item['section'] for item in response.data])))
        return []
    except Exception as e: st.error(f"DB Error (get_sections_for_class): {e}"); return []

@st.cache_data(show_spinner="Fetching enrolled students...")
def get_enrolled_students(course: dict) -> list:
    try:
        response = supabase.table('student_course_enrollment').select('student_id').eq('course_code', course['course_code']).eq('department_id', course['department_id']).eq('class_name', course['class_name']).eq('section', course['section']).execute()
        return [item['student_id'] for item in response.data]
    except Exception as e: st.error(f"DB Error (get_enrolled_students): {e}"); return []

def update_course_enrollment(course_details: dict, student_ids: list):
    match_criteria = {'course_code': course_details['course_code'], 'department_id': course_details['department_id'], 'class_name': course_details['class_name'], 'section': course_details['section']}
    supabase.table('student_course_enrollment').delete().match(match_criteria).execute()
    if student_ids:
        records = [{**match_criteria, 'student_id': sid} for sid in student_ids]
        supabase.table('student_course_enrollment').insert(records).execute()
    get_enrolled_students.clear()

@st.cache_data(show_spinner="Authenticating faculty...")
def authenticate_faculty(faculty_id: str, pin: str):
    if not faculty_id or not pin or not pin.isdigit() or len(pin) != 4: return None
    try:
        response = supabase.table('faculty').select('faculty_id, name, email, phone_number').eq('faculty_id', faculty_id).single().execute()
        user_data = response.data
        if user_data and user_data.get("phone_number"):
            phone = str(user_data["phone_number"])
            if len(phone) >= 4 and phone[-4:] == pin:
                return {"FacultyID": user_data["faculty_id"], "Name": user_data["name"], "Email": user_data.get("email")}
        return None
    except Exception: return None

@st.cache_data(show_spinner="Fetching faculty dashboard data...")
def get_all_assigned_courses_for_faculty(faculty_id: str) -> pd.DataFrame:
    try:
        response = supabase.table('courses').select('*, departments!courses_department_id_fkey(name)').eq('assigned_faculty_id', faculty_id).execute()
        df = pd.DataFrame(response.data)
        if not df.empty and 'departments' in df.columns:
            df['department_name'] = df['departments'].apply(lambda x: x.get('name', 'N/A') if isinstance(x, dict) else 'N/A')
            df = df.drop(columns=['departments'])
        return df
    except Exception as e: st.error(f"DB Error (get_all_assigned_courses): {e}"); return pd.DataFrame()

@st.cache_data(show_spinner="Fetching report statuses...")
def get_attendance_status_summary(courses_df: pd.DataFrame) -> pd.DataFrame:
    if courses_df.empty: return pd.DataFrame()
    try:
        response = supabase.table('attendance').select('course_code, department_id, class_name, section, month_yyyy_mm, status').in_('course_code', courses_df['course_code'].tolist()).in_('department_id', courses_df['department_id'].tolist()).in_('class_name', courses_df['class_name'].tolist()).in_('section', courses_df['section'].tolist()).execute()
        return pd.DataFrame(response.data)
    except Exception as e: st.error(f"DB Error (get_attendance_status_summary): {e}"); return pd.DataFrame()

@st.cache_data(show_spinner="Fetching attendance records...")
def get_attendance_records(course_code: str, month_key: str, department_id: int, class_name: str, section: str) -> pd.DataFrame:
    try:
        response = supabase.table('attendance').select('*').eq('course_code', course_code).eq('month_yyyy_mm', month_key).eq('department_id', department_id).eq('class_name', class_name).eq('section', section).execute()
        return pd.DataFrame(response.data)
    except Exception as e: st.error(f"DB Error (get_attendance_records): {e}"); return pd.DataFrame()

def month_key(month_name: str, year=None) -> str:
    year = year or datetime.now().year
    month_map = {name: f"{i+1:02d}" for i, name in enumerate(MONTH_NAMES)}
    return f"{year}{month_map.get(month_name, '01')}"

def export_excel_file(df: pd.DataFrame, title: str, sheet_name: str, color: str) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]
        header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': color, 'font_color': 'white', 'border': 1})
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        worksheet.autofit()
    output.seek(0)
    return output.getvalue()

# ───────────────────────── UI Rendering ─────────────────────────
st.markdown(f"## {APP_TITLE}"); st.caption(f"{APP_SUBTITLE} | v{__version__}"); st.divider()

with st.sidebar:
    st.header("🔐 Admin Controls")
    is_admin = st.session_state.get("IS_ADMIN", False)
    if not is_admin:
        u = st.text_input("Admin Username", key="admin_user")
        p = st.text_input("Admin Password", type="password", key="admin_pass")
        if st.button("Login as Admin"):
            is_admin_check = (u == ADMIN_USER and p == ADMIN_PASS)
            st.session_state["IS_ADMIN"] = is_admin_check
            st.rerun() if is_admin_check else st.error("Invalid credentials.")
    else:
        if st.button("Logout Admin"):
            st.session_state.pop("IS_ADMIN", None); lock_danger_zone(); st.rerun()
    st.caption(f"Admin Status: **{'🟢 ON' if is_admin else '🔴 OFF'}**")

with st.expander("📌 Select Class Configuration", expanded=not st.session_state.get('class_config')):
    departments_list = get_departments()
    if departments_list:
        dept_names = [d['name'] for d in departments_list]
        sel_dept_name = st.selectbox("Department", dept_names)
        sel_dept_id = next((d['id'] for d in departments_list if d['name'] == sel_dept_name), None)
        sel_class = st.selectbox("Class", CLASS_CHOICES)
        sel_section = ""
        if sel_dept_id and sel_class:
            sections = get_sections_for_class(sel_dept_id, sel_class)
            sel_section = st.selectbox("Section / Batch", sections) if sections else ""
        if all([sel_dept_id, sel_class, sel_section]):
            st.session_state['class_config'] = {"department_id": sel_dept_id, "department_name": sel_dept_name, "class_name": sel_class, "section": sel_section.strip()}
        else:
            st.session_state['class_config'] = None

st.divider()

# ───────────────────────── Main App Logic ─────────────────────────
tab_entry, tab_reports, tab_admin = st.tabs(["📝 Attendance Entry", "📈 Reports", "🛠️ Admin Tools"])

with tab_entry:
    identity = st.session_state.get("IDENTITY")
    if not identity:
        st.markdown("### Faculty Login")
        c1, c2, c3 = st.columns([1, 1, 1])
        fac_id = c1.text_input("Faculty ID")
        fac_pin = c2.text_input("PIN (Last 4 of Phone)", type="password", max_chars=4)
        with c3:
            st.write(" ")
            if st.button("Login Faculty", use_container_width=True):
                identity_check = authenticate_faculty(fac_id, fac_pin)
                st.session_state["IDENTITY"] = identity_check
                st.rerun() if identity_check else st.error("Invalid credentials.")
    else:
        st.success(f"Logged in: **{identity['Name']}**")
        if st.button("Logout Faculty"):
            st.session_state.pop("IDENTITY", None)
            st.session_state.pop("faculty_course_selection", None)
            st.rerun()

        if 'faculty_course_selection' not in st.session_state:
            st.session_state.faculty_course_selection = None

        if st.session_state.faculty_course_selection is None:
            st.markdown("#### Your Assigned Courses Dashboard")
            courses_df = get_all_assigned_courses_for_faculty(identity['FacultyID'])
            if courses_df.empty:
                st.warning("You have no courses assigned. Please contact an administrator.")
            else:
                status_df = get_attendance_status_summary(courses_df)
                today = datetime.now()
                recent_months = [{"display_name": f"{MONTH_NAMES[(today.month - 1 - i) % 12]} {(today.year if today.month > i else today.year - 1)}", "month_yyyy_mm": month_key(MONTH_NAMES[(today.month - 1 - i) % 12], (today.year if today.month > i else today.year - 1))} for i in range(3)]
                
                merged_df = courses_df.copy()
                if not status_df.empty:
                    merged_df = pd.merge(courses_df, status_df, on=['course_code', 'department_id', 'class_name', 'section'], how='left')
                else:
                    merged_df['month_yyyy_mm'] = None; merged_df['status'] = None

                for _, course_row in courses_df.iterrows():
                    with st.container(border=True):
                        st.subheader(f"{course_row['course_name']} ({course_row['course_code']})")
                        st.caption(f"{course_row['department_name']} — {course_row['class_name']} / {course_row['section']}")
                        stat_cols = st.columns(len(recent_months))
                        for i, month_info in enumerate(recent_months):
                            with stat_cols[i]:
                                entry = merged_df[(merged_df['course_code'] == course_row['course_code']) & (merged_df['section'] == course_row['section']) & (merged_df['month_yyyy_mm'] == month_info['month_yyyy_mm'])]
                                status = entry['status'].iloc[0] if not entry.empty and pd.notna(entry['status'].iloc[0]) else "Not Started"
                                color = {STATUS_LOCKED: "green", STATUS_DRAFT: "orange"}.get(status, "grey")
                                st.caption(month_info['display_name'])
                                st.markdown(f"**:{color}[{status}]**")
                        if st.button("Enter / Edit Attendance", key=f"entry_{course_row['course_code']}_{course_row['section']}"):
                            st.session_state.faculty_course_selection = course_row.to_dict(); st.rerun()
        else:
            course = st.session_state.faculty_course_selection
            st.subheader(f"📝 Attendance Entry: {course['course_name']}")
            if st.button("‹ Back to Dashboard"):
                st.session_state.faculty_course_selection = None; st.rerun()
            
            roster_df = load_roster(course['department_id'], course['class_name'], course['section'])
            if not roster_df.empty:
                with st.expander("🪢 Manage Enrollment for this Course"):
                    enrolled_ids = get_enrolled_students(course)
                    options = roster_df.set_index('student_id')['name'].to_dict()
                    selected_ids = st.multiselect("Enrolled Students", options.keys(), default=enrolled_ids, format_func=lambda id: f"{options.get(id, 'Unknown')} ({id})", key=f"faculty_enroll_{course['course_code']}")
                    if st.button("Update Enrollment", key=f"update_enroll_{course['course_code']}"):
                        try:
                            update_course_enrollment(course, selected_ids)
                            st.toast("✅ Enrollment updated successfully!")
                        except Exception as e: st.error(f"Error updating enrollment: {e}")

                enrolled_ids = get_enrolled_students(course)
                students_to_show = roster_df[roster_df['student_id'].isin(enrolled_ids)].copy() if enrolled_ids else roster_df.copy()
                if not students_to_show.empty:
                    c1, c2 = st.columns(2)
                    month_name = c1.selectbox("Month", MONTH_NAMES, index=datetime.now().month - 1)
                    lectures_held = c2.number_input("Total Lectures Held", min_value=0, value=20)
                    mk = month_key(month_name)
                    attendance_df = get_attendance_records(course['course_code'], mk, course['department_id'], course['class_name'], course['section'])
                    entry_df = students_to_show[['student_id', 'PRN', 'name']].copy().rename(columns={'student_id': 'StudentID', 'name': 'Name'})
                    entry_df['LecturesHeld'] = lectures_held
                    entry_df['Attended'] = 0; entry_df['Status'] = STATUS_DRAFT; entry_df['Remarks'] = ''
                    if not attendance_df.empty:
                        db_vals = attendance_df.rename(columns={'student_id': 'StudentID', 'attended': 'Attended', 'lectures_held': 'LecturesHeld', 'status': 'Status', 'remarks': 'Remarks'})
                        entry_df = entry_df.merge(db_vals[['StudentID', 'Attended', 'LecturesHeld', 'Status', 'Remarks']], on='StudentID', how='left', suffixes=('', '_db'))
                        for col in ['Attended', 'LecturesHeld', 'Status', 'Remarks']:
                            entry_df[col] = entry_df[f'{col}_db'].fillna(entry_df[col])
                            if col in ['Attended', 'LecturesHeld']: entry_df[col] = pd.to_numeric(entry_df[col], errors='coerce').fillna(0).astype(int)
                        entry_df.drop(columns=[c for c in entry_df.columns if '_db' in c], inplace=True)
                    
                    entry_df['Percentage'] = entry_df.apply(lambda r: (r['Attended'] / r['LecturesHeld'] * 100) if r['LecturesHeld'] > 0 else 0, axis=1)
                    is_locked = STATUS_LOCKED in entry_df['Status'].unique()
                    df_for_display = entry_df
                    
                    if not is_locked:
                        edited_df = st.data_editor(entry_df, column_config={"Percentage": st.column_config.ProgressColumn("Attendance %", format="%.1f%%", min_value=0, max_value=100)}, disabled=["StudentID", "PRN", "Name", "Status", "Percentage"], use_container_width=True, height=600)
                        df_for_display = edited_df
                        b1, b2 = st.columns(2)
                        if b1.button("💾 Save as Draft", use_container_width=True): st.session_state.status_to_set = STATUS_DRAFT
                        if b2.button("✅ Submit & Lock", use_container_width=True, type="primary"): st.session_state.confirm_lock = True
                        if st.session_state.get('confirm_lock'):
                            st.warning("Are you sure? This cannot be undone by you.", icon="⚠️")
                            cl1, cl2, _ = st.columns([1,1,3])
                            if cl1.button("Yes, Confirm Lock", use_container_width=True, type="primary"):
                                st.session_state.status_to_set = STATUS_LOCKED; del st.session_state['confirm_lock']
                            if cl2.button("Cancel", use_container_width=True): del st.session_state['confirm_lock']; st.rerun()
                        if 'status_to_set' in st.session_state:
                            status_to_set = st.session_state.pop('status_to_set')
                            errors = [f"For **{r['Name']}**, attended ({r['Attended']}) cannot exceed lectures held ({r['LecturesHeld']})." for _, r in edited_df.iterrows() if r['Attended'] > r['LecturesHeld']]
                            if errors:
                                for e in errors: st.warning(e)
                            else:
                                upsert_data = [{'student_id': r['StudentID'], 'course_code': course['course_code'], 'department_id': course['department_id'], 'class_name': course['class_name'], 'section': course['section'], 'month_yyyy_mm': mk, 'lectures_held': r['LecturesHeld'], 'attended': r['Attended'], 'status': status_to_set, 'updated_by_faculty_id': identity['FacultyID'], 'remarks': r['Remarks'], 'updated_at': datetime.utcnow().isoformat()} for _, r in edited_df.iterrows()]
                                with st.spinner(f"Saving attendance as {status_to_set}..."):
                                    try:
                                        supabase.table('attendance').upsert(upsert_data).execute()
                                        if status_to_set == STATUS_LOCKED:
                                            log_action(identity['FacultyID'], "LOCK_ATTENDANCE", {'course': course['course_code'], 'month': mk})
                                        st.toast(f"Attendance saved as {status_to_set}!", icon="✅")
                                        get_attendance_records.clear(); get_attendance_status_summary.clear(); st.rerun()
                                    except Exception as e: st.error(f"DB Error: {e}")
                    else:
                        st.success("This month's attendance is LOCKED.")
                        st.dataframe(entry_df, use_container_width=True)

                    if not df_for_display.empty:
                        st.divider()
                        excel_data = export_excel_file(
                            df=df_for_display[['StudentID', 'PRN', 'Name', 'LecturesHeld', 'Attended', 'Percentage', 'Status', 'Remarks']],
                            title=f"Attendance Report - {course['course_name']} ({month_name})",
                            sheet_name="Attendance",
                            color="#4B5563"
                        )
                        st.download_button(
                            label="⬇️ Download This View (Excel)",
                            data=excel_data,
                            file_name=f"Attendance_{course['course_code']}_{month_name}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )

with tab_reports:
    st.header("📊 Class Analytics")
    identity = st.session_state.get("IDENTITY")
    is_admin = st.session_state.get("IS_ADMIN")
    class_config = st.session_state.get("class_config")

    if not identity and not is_admin:
        st.info("Please log in to view reports.")
    elif not class_config:
        st.warning("Please select a class configuration to view reports.")
    else:
        st.markdown("### Course Performance")
        rep_month_course = st.selectbox("Select Month", MONTH_NAMES, index=datetime.now().month-1, key="course_month_select")
        mk_course = month_key(rep_month_course)
        try:
            response = supabase.rpc('get_course_wise_summary', {'p_department_id': class_config['department_id'], 'p_class_name': class_config['class_name'], 'p_section': class_config['section'], 'p_month_key': mk_course}).execute()
            course_summary_df = pd.DataFrame(response.data)
            if course_summary_df.empty:
                st.warning(f"No attendance data for {rep_month_course} to generate course report.")
            else:
                course_summary_df['average_attendance'] = pd.to_numeric(course_summary_df['average_attendance'])
                fig = px.bar(course_summary_df, x='course_name', y='average_attendance', title=f"Average Attendance per Course for {rep_month_course}", labels={'course_name': 'Course', 'average_attendance': 'Average Attendance (%)'}, text='average_attendance')
                fig.update_traces(texttemplate='%{text:.2f}%', textposition='outside'); fig.update_layout(yaxis_range=[0,100])
                st.plotly_chart(fig, use_container_width=True)
        except Exception as e: st.error(f"Error generating course report: {e}")
        st.divider()
        st.markdown("### Student Performance")
        try:
            response = supabase.rpc('get_full_class_history', {'p_department_id': class_config['department_id'], 'p_class_name': class_config['class_name'], 'p_section': class_config['section']}).execute()
            history_df = pd.DataFrame(response.data)
            if history_df.empty:
                st.warning("No attendance history found for this class.")
            else:
                history_df['attendance_percent'] = pd.to_numeric(history_df['attendance_percent'])
                st.markdown("#### Student Attendance Trend Over Time")
                student_list = sorted(history_df['name'].unique())
                default_students = student_list[:3] if len(student_list) > 0 else []
                selected_students = st.multiselect("Select students to compare:", student_list, default=default_students)
                if selected_students:
                    trend_df = history_df[history_df['name'].isin(selected_students)]
                    fig_trend = px.line(trend_df, x='month_yyyy_mm', y='attendance_percent', color='name', markers=True, title="Monthly Attendance Percentage per Student", labels={'month_yyyy_mm': 'Month', 'attendance_percent': 'Attendance %', 'name': 'Student Name'})
                    st.plotly_chart(fig_trend, use_container_width=True)
                st.divider()
                st.markdown("#### Class Performance Distribution")
                month_list = sorted(history_df['month_yyyy_mm'].unique())
                sel_month_dist = st.selectbox("Select Month for Distribution Analysis:", month_list, index=len(month_list)-1 if month_list else 0)
                if sel_month_dist:
                    month_df = history_df[history_df['month_yyyy_mm'] == sel_month_dist]
                    bins = [0, 50, 75, 101]; labels = ['Below 50% (High Risk)', '50% - 75% (At Risk)', 'Above 75% (Good Standing)']
                    month_df['performance_category'] = pd.cut(month_df['attendance_percent'], bins=bins, labels=labels, right=False)
                    performance_counts = month_df['performance_category'].value_counts().reset_index()
                    performance_counts.columns = ['performance_category', 'count']
                    fig_pie = px.pie(performance_counts, names='performance_category', values='count', title=f"Student Attendance Distribution for {sel_month_dist}", color='performance_category', color_discrete_map={'Below 50% (High Risk)': '#EF4444', '50% - 75% (At Risk)': '#F59E0B', 'Above 75% (Good Standing)': '#10B981'})
                    st.plotly_chart(fig_pie, use_container_width=True)
        except Exception as e: st.error(f"An error occurred while generating student analytics: {e}")

with tab_admin:
    st.header("🛠️ Admin Tools")
    if not st.session_state.get("IS_ADMIN"):
        st.error("You must be an admin to access these tools.")
    else:
        class_config = st.session_state.get("class_config")
        departments = get_departments()
        admin_tabs = ["🏢 Department", "🎓 Class/Section", "🪢 Enrollment", "📂 Bulk Data", "🚨 Reports", "🔓 Unlock", "⚠️ Danger Zone"]
        tab_dept, tab_class, tab_enroll, tab_bulk, tab_reports_admin, tab_unlock, tab_danger = st.tabs(admin_tabs)

        with tab_dept:
            st.markdown("### 🏢 Department Management")
            with st.form("add_department_form"):
                new_dept_name = st.text_input("New Department Name")
                if st.form_submit_button("Add Department"):
                    if new_dept_name:
                        try:
                            supabase.table('departments').insert({"name": new_dept_name.strip()}).execute()
                            st.toast(f"Added '{new_dept_name.strip()}'.", icon="✅"); get_departments.clear(); st.rerun()
                        except Exception as e:
                            if '23505' in str(e): st.warning(f"The department '{new_dept_name.strip()}' already exists.")
                            else: st.error(f"Unexpected error: {e}")
                    else: st.warning("Please enter a department name.")

        with tab_class:
            st.markdown("### 🎓 Class & Section Management")
            if not departments: st.info("No departments exist. Please add one first.")
            else:
                with st.form("add_class_section_form"):
                    dept_names = [d['name'] for d in departments]
                    sel_dept_name = st.selectbox("Target Department", dept_names)
                    sel_dept_id = next((d['id'] for d in departments if d['name'] == sel_dept_name), None)
                    sel_class_name = st.selectbox("Target Class Name", CLASS_CHOICES)
                    new_sec_name = st.text_input("New Section Name to Create", placeholder="e.g., A or B")
                    if st.form_submit_button("Create New Section"):
                        if all([new_sec_name, sel_dept_id, sel_class_name]):
                            try:
                                sec_to_add = new_sec_name.strip()
                                ph_id = f"{sel_class_name.replace(' ', '_').upper()}-{sec_to_add.upper()}_PLACEHOLDER"
                                supabase.table('students').upsert({'student_id': ph_id, 'PRN': ph_id, 'name': 'Admin Placeholder', 'department_id': sel_dept_id, 'class_name': sel_class_name, 'section': sec_to_add, 'is_active': False}).execute()
                                st.toast(f"Created section '{sec_to_add}'.", icon="✅"); get_sections_for_class.clear(); st.rerun()
                            except Exception as e: st.error(f"Unexpected error: {e}")
                        else: st.warning("Please ensure all fields are filled.")

        with tab_enroll:
            st.markdown("### 🪢 Enrollment Management")
            if not class_config: st.info("Select a class configuration at the top to manage enrollments.")
            else:
                courses = get_courses(class_config['department_id'], class_config['class_name'], class_config['section'])
                if courses.empty: st.warning("No courses found. Add them via Bulk Data.")
                else:
                    course = st.selectbox("Select Course for Enrollment", courses.to_dict('records'), format_func=lambda c: f"{c['course_name']} ({c['course_code']})")
                    roster = load_roster(class_config['department_id'], class_config['class_name'], class_config['section'])
                    if not roster.empty:
                        enrolled = get_enrolled_students(course)
                        with st.form("enrollment_form"):
                            st.write(f"Select students for **{course['course_name']}**.")
                            options = roster.set_index('student_id')['name'].to_dict()
                            sel_ids = st.multiselect("Enrolled Students", options.keys(), default=enrolled, format_func=lambda id: f"{options.get(id, 'Unknown')} ({id})")
                            if st.form_submit_button("Update Enrollment"):
                                try:
                                    update_course_enrollment(course, sel_ids)
                                    st.toast("Enrollment updated.", icon="✅"); st.rerun()
                                except Exception as e: st.error(f"Error: {e}")

        with tab_bulk:
            st.markdown("### 📂 Bulk Data Management")
            if not class_config: st.info("Select a class configuration at the top to use bulk upload.")
            else:
                sub_tab1, sub_tab2 = st.tabs(["Download Templates", "Upload Data"])
                with sub_tab1:
                    c1, c2, c3 = st.columns(3)
                    c1.download_button("⬇️ Students", pd.DataFrame({'student_id':['S001'],'PRN':['1'],'name':['John Doe']}).to_csv(index=False).encode(), 'students_template.csv', use_container_width=True)
                    c2.download_button("⬇️ Faculty", pd.DataFrame({'faculty_id':['F001'],'name':['Dr. Alan Turing'],'phone_number':['9876543210']}).to_csv(index=False).encode(), 'faculty_template.csv', use_container_width=True)
                    c3.download_button("⬇️ Courses", pd.DataFrame({'course_code':['CS101'],'course_name':['Intro to Code'],'assigned_faculty_id':['F001']}).to_csv(index=False).encode(), 'courses_template.csv', use_container_width=True)
                with sub_tab2:
                    st.info(f"New records will be added to: **{class_config['department_name']} / {class_config['class_name']} / {class_config['section']}**")
                    upload_type = st.radio("Select data type to upload:", ["Students", "Faculty", "Courses"])
                    uploaded_file = st.file_uploader("Upload CSV file", type="csv", key=f"uploader_{upload_type}")
                    if st.button(f"Process {upload_type} Upload"):
                        if uploaded_file:
                            try:
                                df = pd.read_csv(uploaded_file); df.fillna('', inplace=True)
                                id_col_map = {"Students": "student_id", "Faculty": "faculty_id", "Courses": "course_code"}
                                id_col = id_col_map.get(upload_type)
                                if id_col and id_col in df.columns and df[id_col].duplicated().any():
                                    duplicates = df[df[id_col].duplicated()][id_col].astype(str).tolist()
                                    st.error(f"Upload failed. Duplicate IDs found: {', '.join(duplicates)}")
                                    st.stop()
                                table = upload_type.lower()
                                records = df.to_dict('records')
                                if table != 'faculty':
                                    for r in records: r.update({'department_id': class_config['department_id']})
                                    if table in ['students', 'courses']:
                                        for r in records: r.update({'class_name': class_config['class_name'], 'section': class_config['section']})
                                with st.spinner(f"Uploading {len(df)} records to '{table}'..."):
                                    supabase.table(table).upsert(records).execute()
                                    st.toast(f"Uploaded {len(df)} records.", icon="🎉"); st.rerun()
                                    if table == 'students': load_roster.clear(); get_sections_for_class.clear()
                                    if table == 'courses': get_courses.clear()
                            except Exception as e: st.error(f"Error: {e}")
                        else: st.warning("Please upload a file first.")

        with tab_reports_admin:
            st.markdown("### 🚨 Class Reports")
            if not class_config: st.info("Select a class at the top to generate reports.")
            else:
                c1, c2 = st.columns(2)
                rep_month = c1.selectbox("Report Month", MONTH_NAMES, index=datetime.now().month-1, key="admin_month_select")
                threshold = c2.number_input("Defaulter Threshold % (<)", 0.0, 100.0, 75.0)
                if st.button("Generate Report Data", use_container_width=True):
                    with st.spinner("Fetching report data..."):
                        try:
                            response = supabase.rpc('get_detailed_monthly_summary', {'p_department_id': class_config['department_id'], 'p_class_name': class_config['class_name'], 'p_section': class_config['section'], 'p_month_key': month_key(rep_month)}).execute()
                            st.session_state.detailed_summary_df = pd.DataFrame(response.data)
                        except Exception as e:
                            st.error(f"Failed to generate report: {e}"); st.session_state.detailed_summary_df = None
                if 'detailed_summary_df' in st.session_state and st.session_state.detailed_summary_df is not None:
                    summary_df = st.session_state.detailed_summary_df
                    if summary_df.empty: st.warning("No attendance data found for the selected month.")
                    else:
                        st.markdown("#### Course-Wise Monthly Summary")
                        pivot_df = summary_df.pivot_table(index=['PRN', 'name'], columns='course_name', values='attended', aggfunc='first').reset_index().fillna('-')
                        lectures_map = summary_df.groupby('course_name')['lectures_held'].first()
                        new_column_names = {col: f"{col} ({lectures_map.get(col, 0)})" for col in pivot_df.columns if col not in ['PRN', 'name']}
                        pivot_df.rename(columns=new_column_names, inplace=True)
                        st.dataframe(pivot_df, use_container_width=True)
                        st.download_button("⬇️ Download Summary", export_excel_file(pivot_df, f"Summary-{class_config['section']}-{rep_month}", "Summary", "#1E40AF"), f"Summary_{class_config['section']}_{rep_month}.xlsx", use_container_width=True)
                        st.markdown("#### Defaulter List (Overall %)")
                        agg_df = summary_df.groupby(['student_id', 'PRN', 'name']).agg(total_held=('lectures_held', 'sum'), total_attended=('attended', 'sum')).reset_index()
                        agg_df['percent'] = agg_df.apply(lambda r: (r['total_attended'] / r['total_held'] * 100) if r['total_held'] > 0 else 0, axis=1)
                        defaulters_df = agg_df[agg_df['percent'] < threshold].copy()
                        if defaulters_df.empty: st.success(f"No defaulters found below {threshold}%.")
                        else:
                            st.dataframe(defaulters_df, use_container_width=True)
                            st.download_button("⬇️ Download Defaulter List", export_excel_file(defaulters_df, f"Defaulters-{class_config['section']}-{rep_month}", "Defaulters", "#B91C1C"), f"Defaulters_{class_config['section']}_{rep_month}.xlsx", use_container_width=True)

        with tab_unlock:
            st.markdown("### 🔓 Unlock Locked Attendance")
            if class_config:
                courses = get_courses(class_config['department_id'], class_config['class_name'], class_config['section'])
                if not courses.empty:
                    sel_course = st.selectbox("Course to Unlock", courses.to_dict('records'), format_func=lambda c: f"{c['course_name']} ({c['course_code']})")
                    sel_month = st.selectbox("Month to Unlock", MONTH_NAMES, index=datetime.now().month-1)
                    if st.button("Check Status", use_container_width=True): st.session_state.unlock_target = {'course': sel_course, 'month': sel_month, 'config': class_config}
                if 'unlock_target' in st.session_state:
                    target, cfg = st.session_state.unlock_target, st.session_state.unlock_target['config']
                    mk = month_key(target['month'])
                    recs = get_attendance_records(target['course']['course_code'], mk, cfg['department_id'], cfg['class_name'], cfg['section'])
                    if not recs.empty and STATUS_LOCKED in recs['status'].unique():
                        st.success(f"Status for {target['course']['course_name']} ({target['month']}) is **LOCKED**.")
                        if st.button("🔓 Unlock These Records", type="primary"): st.session_state.confirm_unlock = True
                    elif not recs.empty: st.info(f"Records are already in {STATUS_DRAFT} state.")
                    else: st.warning("No records found for this course/month.")
            if st.session_state.get('confirm_unlock'):
                st.warning("Are you sure?", icon="⚠️")
                cu1, cu2, _ = st.columns([1,1,3])
                if cu1.button("Yes, Confirm Unlock", type="primary"):
                    try:
                        target, cfg = st.session_state.unlock_target, st.session_state.unlock_target['config']
                        mk = month_key(target['month'])
                        with st.spinner("Unlocking records..."):
                            supabase.table('attendance').update({'status': STATUS_DRAFT}).match({'course_code': target['course']['course_code'], 'month_yyyy_mm': mk, 'department_id': cfg['department_id'], 'class_name': cfg['class_name'], 'section': cfg['section']}).execute()
                            log_action(st.session_state.get("admin_user"), "UNLOCK_ATTENDANCE", {'course': target['course']['course_code'], 'month': mk})
                            st.toast("✅ Unlocked!")
                        get_attendance_records.clear(); del st.session_state['unlock_target']; del st.session_state['confirm_unlock']; st.rerun()
                    except Exception as e: st.error(f"Failed to unlock: {e}")
                if cu2.button("Cancel"): del st.session_state['confirm_unlock']; st.rerun()

        with tab_danger:
            st.markdown("### ⚠️ Danger Zone")
            with st.expander("Show Irreversible Actions", expanded=True):
                if not DANGER_ZONE_PASSWORD:
                    st.error("Danger Zone password not set in secrets. This section is disabled.")
                else:
                    if not is_danger_unlocked():
                        st.info("This area contains actions that permanently delete data. Enter the password to proceed.")
                        dz_pw = st.text_input("Enter Danger Zone Password", type="password", key="dz_pw")
                        if st.button("🔓 Unlock Danger Zone", type="primary"):
                            if try_unlock_danger_zone(dz_pw): st.rerun()
                            else: st.error("Incorrect password.")
                    else:
                        st.success("Danger Zone is UNLOCKED.")
                        if st.button("🔒 Lock Danger Zone"): lock_danger_zone(); st.rerun()
                        st.error("The following actions are permanent and cannot be undone.", icon="🚨")
                        if st.button("Permanently Delete All Students", type="primary", disabled=not is_danger_unlocked()):
                            try:
                                supabase.table('students').delete().neq('student_id', 'DO_NOT_DELETE').execute()
                                log_action(st.session_state.get("admin_user"), "DANGER_ZONE_DELETE", {'table': 'students'})
                                st.toast("All student records deleted.", icon="🚨"); load_roster.clear(); st.rerun()
                            except Exception as e: st.error(f"Error: {e}")
                        if st.button("Permanently Delete All Faculty", type="primary", disabled=not is_danger_unlocked()):
                            try:
                                supabase.table('faculty').delete().neq('faculty_id', 'DO_NOT_DELETE').execute()
                                log_action(st.session_state.get("admin_user"), "DANGER_ZONE_DELETE", {'table': 'faculty'})
                                st.toast("All faculty records deleted.", icon="🚨"); st.rerun()
                            except Exception as e: st.error(f"Error: {e}")
                        if st.button("Permanently Delete All Courses", type="primary", disabled=not is_danger_unlocked()):
                            try:
                                supabase.table('courses').delete().neq('course_code', 'DO_NOT_DELETE').execute()
                                log_action(st.session_state.get("admin_user"), "DANGER_ZONE_DELETE", {'table': 'courses'})
                                st.toast("All course records deleted.", icon="🚨"); get_courses.clear(); st.rerun()
                            except Exception as e: st.error(f"Error: {e}")
