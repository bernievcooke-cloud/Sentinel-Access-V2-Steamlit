import streamlit as st
from datetime import datetime
import os
import json

# ==============================
# PAGE CONFIG
# ==============================
st.set_page_config(page_title="Sentinel Access Pro", layout="wide")

# ==============================
# SESSION STATE
# ==============================
if "progress_log" not in st.session_state:
    st.session_state.progress_log = []

# ==============================
# LOGGING FUNCTION
# ==============================
def log_progress(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.progress_log.append(f"[{timestamp}] {msg}")

# ==============================
# SAFE EMAIL WRAPPER
# ==============================
def send_email_safe(subject, body, attachments, recipient):
    try:
        from core.email_sender import send_report_email
        send_report_email(subject, body, attachments, recipient)
        log_progress("EMAIL SENT SUCCESSFULLY")
    except Exception as e:
        log_progress(f"EMAIL ERROR: {str(e)}")

# ==============================
# LOAD LOCATIONS
# ==============================
def load_locations():
    path = "config/locations.json"
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)

locations = load_locations()
location_names = sorted(locations.keys())

# ==============================
# UI STYLES (SAFE)
# ==============================
st.markdown("""
<style>
.block-container {padding-top: 1.5rem;}

.card {
    padding:10px;
    border-radius:10px;
    border:1px solid #e5e7eb;
    background:#ffffff;
    margin-bottom:10px;
}

.step-title {
    font-size:11px;
    color:#6b7280;
    font-weight:600;
}

.step-body {
    font-size:14px;
    font-weight:600;
    color:#111827;
}
</style>
""", unsafe_allow_html=True)

# ==============================
# HEADER
# ==============================
st.title("Sentinel Access Pro")
st.caption("Premium report generation and email delivery")

# ==============================
# STEP CARDS
# ==============================
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown('<div class="card"><div class="step-title">STEP 1</div><div class="step-body">Enter user details</div></div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="card"><div class="step-title">STEP 2</div><div class="step-body">Choose report set</div></div>', unsafe_allow_html=True)

with col3:
    st.markdown('<div class="card"><div class="step-title">SYSTEM</div><div class="step-body">System ready</div></div>', unsafe_allow_html=True)

# ==============================
# MAIN LAYOUT
# ==============================
left, mid, right = st.columns(3)

# ==============================
# LEFT PANEL
# ==============================
with left:
    st.subheader("User Details")

    name = st.text_input("Name", key="name_input")
    email = st.text_input("Email", key="email_input")

    st.caption("Press Enter after typing name or email.")

# ==============================
# MIDDLE PANEL
# ==============================
with mid:
    st.subheader("Select Reports & Locations")

    reports = st.multiselect(
        "Reports",
        ["Surf Report", "Sky Report", "Weather Report", "Trip Report"],
        key="report_select"
    )

    selected_location = st.selectbox(
        "Location",
        location_names if location_names else ["No locations found"],
        key="location_select"
    )

    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        generate = st.button("Generate & Email Reports")

    with col_btn2:
        if st.button("Clear progress"):
            st.session_state.progress_log = []

# ==============================
# RIGHT PANEL
# ==============================
with right:
    st.subheader("Live System Progress")

    st.text_area(
        "System progress",
        "\n".join(st.session_state.progress_log),
        height=300
    )

# ==============================
# RUN LOGIC
# ==============================
if generate:

    if not name or not email:
        log_progress("ERROR: Name and Email required")
        st.stop()

    if not reports:
        log_progress("ERROR: No report selected")
        st.stop()

    log_progress("RUN START")

    output_files = []

    # ==========================
    # WEATHER REPORT
    # ==========================
    if "Weather Report" in reports:
        try:
            log_progress(f"Running Weather for {selected_location}")

            from core.weather_worker import generate_report

            lat = locations[selected_location]["lat"]
            lon = locations[selected_location]["lon"]

            result = generate_report(selected_location, [lat, lon])

            if result:
                output_files.append(result)
                log_progress("Weather report generated")

        except Exception as e:
            log_progress(f"Weather ERROR: {str(e)}")

    # ==========================
    # SEND EMAIL
    # ==========================
    if output_files:
        log_progress("Preparing email...")
        send_email_safe(
            subject="Sentinel Report",
            body="Your report is attached.",
            attachments=output_files,
            recipient=email
        )
    else:
        log_progress("No reports generated - email skipped")

    log_progress("RUN COMPLETE")
