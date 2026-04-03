#!/usr/bin/env python3
from future import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import streamlit as st

# ==============================

# CONFIG

# ==============================

APP_TITLE = "Sentinel Access Pro"

ROOT_DIR = Path(**file**).resolve().parent
CONFIG_DIR = ROOT_DIR / "config"
LOCATIONS_FILE = CONFIG_DIR / "locations.json"
OUTPUTS_DIR = ROOT_DIR / "outputs"

REPORT_OPTIONS = [
"Surf Report",
"Sky Report",
"Moon Events Report",
"Sky & Moon Report",
"Weather Report",
"Trip Report",
]

# ==============================

# INIT

# ==============================

st.set_page_config(page_title=APP_TITLE, layout="wide")

if "progress_log" not in st.session_state:
st.session_state["progress_log"] = ""

# ==============================

# UTILS

# ==============================

def now():
return datetime.now().strftime("%H:%M:%S")

def log(msg):
st.session_state["progress_log"] += f"[{now()}] {msg}\n"

def ensure_dirs():
CONFIG_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# ==============================

# LOCATIONS

# ==============================

def load_locations():
if not LOCATIONS_FILE.exists():
return {}
return json.loads(LOCATIONS_FILE.read_text())

def save_location(name, lat, lon):
data = load_locations()
data[name] = {"lat": lat, "lon": lon}
LOCATIONS_FILE.write_text(json.dumps(data, indent=2))

# ==============================

# EMAIL

# ==============================

def send_email(email, files):
try:
from core.email_sender import send_report_email
send_report_email(email, "Sentinel Report", "Attached", files)
return True, "EMAIL OK"
except Exception as e:
return False, f"EMAIL ERROR: {e}"

# ==============================

# PREMIUM CSS (FIXED)

# ==============================

st.markdown("""

<style>
.stApp {
    background: linear-gradient(180deg, #f1f6fb, #e3edf7);
}

.card {
    background: white;
    padding: 10px;
    border-radius: 12px;
    border: 1px solid rgba(0,0,0,0.08);
    margin-bottom: 10px;
}

/* Smaller step cards */
.step {
    font-size: 13px;
    font-weight: 600;
}

/* IMPORTANT: no select override (fix dropdown bug) */

textarea {
    font-size: 12px !important;
}
</style>

""", unsafe_allow_html=True)

# ==============================

# HEADER

# ==============================

st.title(APP_TITLE)

# ==============================

# STEP CARDS

# ==============================

c1, c2, c3 = st.columns(3)

c1.markdown('<div class="card step">STEP 1<br>User Details</div>', unsafe_allow_html=True)
c2.markdown('<div class="card step">STEP 2<br>Select Reports</div>', unsafe_allow_html=True)
c3.markdown('<div class="card step">SYSTEM<br>Ready</div>', unsafe_allow_html=True)

# ==============================

# MAIN LAYOUT

# ==============================

left, mid, right = st.columns(3)

locations = load_locations()
location_names = list(locations.keys())

# ==============================

# LEFT PANEL

# ==============================

with left:
st.subheader("User Details")
name = st.text_input("Name")
email = st.text_input("Email")

```
st.markdown("---")

st.subheader("Admin")

pw = st.text_input("Password", type="password")

if pw == "sentinel":
    st.success("Unlocked")

    new_name = st.text_input("Location Name")
    lat = st.text_input("Lat")
    lon = st.text_input("Lon")

    if st.button("Save Location"):
        try:
            save_location(new_name, float(lat), float(lon))
            st.success("Saved")
            log(f"Location saved: {new_name}")
        except:
            st.error("Invalid input")
```

# ==============================

# MID PANEL

# ==============================

with mid:
st.subheader("Reports")

```
reports = st.multiselect("Select Reports", REPORT_OPTIONS, key="reports")

location = st.selectbox("Location", location_names)

run = st.button("Generate & Email")

if st.button("Clear Progress"):
    st.session_state["progress_log"] = ""
```

# ==============================

# RIGHT PANEL

# ==============================

with right:
st.subheader("System Progress")

```
st.text_area(
    "",
    st.session_state["progress_log"],
    height=350
)
```

# ==============================

# RUN LOGIC

# ==============================

if run:

```
st.session_state["progress_log"] = ""
log("RUN START")

if not name or not email:
    log("Missing user details")
    st.stop()

lat = locations[location]["lat"]
lon = locations[location]["lon"]

outputs = []

# WEATHER
if "Weather Report" in reports:
    try:
        from core.weather_worker import generate_report
        log("Weather running...")
        out = generate_report(location, [lat, lon])
        outputs.append(out)
        log("Weather OK")
    except Exception as e:
        log(f"Weather ERROR: {e}")

# MOON
if "Moon Events Report" in reports:
    try:
        from core.moon_events_worker import generate_report
        log("Moon running...")
        out = generate_report(location, [lat, lon])
        outputs.append(out)
        log("Moon OK")
    except Exception as e:
        log(f"Moon ERROR: {e}")

# EMAIL
if outputs:
    log("Sending email...")
    ok, msg = send_email(email, outputs)
    log(msg)

    if ok:
        st.success(msg)
    else:
        st.error(msg)
else:
    log("No reports generated")

log("RUN COMPLETE")
```
