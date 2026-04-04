# ==============================================
# SENTINEL ACCESS PRO — FULL PRODUCTION (FIXED)
# ==============================================

from __future__ import annotations

import importlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

APP_TITLE = "Sentinel Access Pro"
ROOT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = ROOT_DIR / "config"
LOCATIONS_FILE = CONFIG_DIR / "locations.json"
OUTPUTS_DIR = ROOT_DIR / "outputs"

REPORTS = [
    "Surf Report",
    "Sky Report",
    "Moon Events Report",
    "Sky & Moon Report",
    "Weather Report",
]

# ---------------- INIT ----------------

def now(): return datetime.now().strftime("%H:%M:%S")

def init():
    for k, v in {
        "progress": f"[{now()}] SYSTEM READY",
        "files": [],
        "selected_reports": [],
    }.items():
        st.session_state.setdefault(k, v)


def log(msg):
    st.session_state.progress += f"\n[{now()}] {msg}"

# ---------------- UTIL ----------------

def soft_import(name):
    try: return importlib.import_module(name)
    except: return None


def valid_pdf(path):
    try:
        p = Path(path)
        return p.exists() and p.stat().st_size > 1000
    except: return False


def extract_files(result):
    files = []
    if isinstance(result, str): files.append(result)
    elif isinstance(result, (list, tuple)):
        files += [x for x in result if isinstance(x, str)]
    elif isinstance(result, dict):
        files += [v for v in result.values() if isinstance(v, str)]
    return [f for f in files if valid_pdf(f)]


def scan_outputs():
    return [str(p) for p in OUTPUTS_DIR.glob("*.pdf") if valid_pdf(p)]

# ---------------- LOCATIONS ----------------

def load_locations():
    if not LOCATIONS_FILE.exists(): return {}
    try: return json.loads(LOCATIONS_FILE.read_text())
    except: return {}


def save_location(name, lat, lon):
    data = load_locations()
    data[name] = {"lat": lat, "lon": lon}
    CONFIG_DIR.mkdir(exist_ok=True)
    LOCATIONS_FILE.write_text(json.dumps(data, indent=2))

# ---------------- WORKERS ----------------

def run_worker(module, location, lat, lon):
    mod = soft_import(module)
    if not mod:
        log(f"{module} missing")
        return []

    try:
        result = mod.generate_report(location, [lat, lon], str(OUTPUTS_DIR), log)
    except Exception as e:
        log(f"{module} failed: {e}")
        return []

    files = extract_files(result)
    if not files:
        files = scan_outputs()
    return files

# ---------------- EMAIL ----------------

def send_email(email, files):
    mod = soft_import("core.email_sender")
    if not mod:
        return False, "Email module missing"
    try:
        mod.send_email(email, "Sentinel Reports", "Attached", files)
        return True, "EMAIL OK"
    except Exception as e:
        return False, str(e)

# ---------------- UI ----------------

def main():
    st.set_page_config(layout="wide")
    init()

    st.title(APP_TITLE)

    locations = load_locations()

    # ---- STEP CARDS ----
    c1, c2, c3 = st.columns(3)
    c1.success("Step 1: Enter Details")
    c2.success("Step 2: Select Reports")
    c3.success("SYSTEM READY" if st.session_state.selected_reports else "Waiting")

    st.markdown("---")

    # ---- INPUTS ----
    col1, col2 = st.columns(2)

    with col1:
        name = st.text_input("Name")
        email = st.text_input("Email")

    with col2:
        reports = st.multiselect("Select Reports", REPORTS, key="report_select")
        location = st.selectbox("Location", list(locations.keys()) or ["None"])

    st.session_state.selected_reports = reports

    # ---- ADMIN PANEL ----
    with st.expander("Admin — Add Location"):
        new_name = st.text_input("New Location Name")
        lat = st.number_input("Latitude")
        lon = st.number_input("Longitude")
        if st.button("Save Location"):
            save_location(new_name, lat, lon)
            st.success("Saved — refresh app")

    st.markdown("---")

    ready = name and email and reports and location != "None"

    if st.button("Generate & Email", disabled=not ready):
        st.session_state.progress = ""
        log("RUN START")

        lat = locations.get(location, {}).get("lat", -38.33)
        lon = locations.get(location, {}).get("lon", 143.78)

        files = []

        for r in reports:
            log(f"Running {r}")

            if r == "Weather Report":
                files += run_worker("core.weather_worker", location, lat, lon)
            elif r == "Surf Report":
                files += run_worker("core.surf_worker", location, lat, lon)
            elif r == "Sky Report":
                files += run_worker("core.sky_worker", location, lat, lon)
            elif r == "Moon Events Report":
                files += run_worker("core.moon_events_worker", location, lat, lon)
            elif r == "Sky & Moon Report":
                files += run_worker("core.sky_worker", location, lat, lon)
                files += run_worker("core.moon_events_worker", location, lat, lon)

        files = list(dict.fromkeys(files))

        if not files:
            log("NO PDF GENERATED")
            st.error("No reports generated")
            return

        log(f"{len(files)} PDFs ready")

        ok, msg = send_email(email, files)
        log(msg)

        if ok: st.success("Email sent")
        else: st.error(msg)

        st.session_state.files = files

    # ---- OUTPUT ----
    if st.session_state.files:
        st.subheader("Generated Files")
        for f in st.session_state.files:
            st.write(f)

    st.markdown("---")

    st.text_area("System Progress", st.session_state.progress, height=300)


if __name__ == "__main__":
    main()
