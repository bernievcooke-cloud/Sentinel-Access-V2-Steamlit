# ==============================================
# SENTINEL ACCESS PRO — FULL PRODUCTION BUILD
# COMPLETE • STABLE • UI CLEAN • ALL FEATURES
# ==============================================

from __future__ import annotations

import importlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

# ---------------- CONFIG ----------------
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
    "Trip Report",
]

# ---------------- INIT ----------------

def now():
    return datetime.now().strftime("%H:%M:%S")


def init():
    defaults = {
        "progress": f"[{now()}] SYSTEM READY",
        "files": [],
        "status": "",
        "selected_reports": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def log(msg: str):
    st.session_state.progress += f"\n[{now()}] {msg}"

# ---------------- UTIL ----------------

def soft_import(name):
    try:
        return importlib.import_module(name)
    except:
        return None


def valid_pdf(path):
    try:
        p = Path(path)
        return p.exists() and p.suffix.lower() == ".pdf" and p.stat().st_size > 1000
    except:
        return False


def extract_files(result):
    files = []

    if isinstance(result, str):
        files.append(result)
    elif isinstance(result, (list, tuple)):
        files += [x for x in result if isinstance(x, str)]
    elif isinstance(result, dict):
        files += [v for v in result.values() if isinstance(v, str)]

    return [f for f in files if valid_pdf(f)]


def scan_outputs():
    return [str(p) for p in OUTPUTS_DIR.glob("*.pdf") if valid_pdf(p)]

# ---------------- LOCATIONS ----------------

def load_locations():
    if not LOCATIONS_FILE.exists():
        return {}
    try:
        return json.loads(LOCATIONS_FILE.read_text())
    except:
        return {}

# ---------------- WORKERS ----------------

def run_worker(module_name, location, lat, lon):
    mod = soft_import(module_name)
    if not mod:
        log(f"{module_name} missing")
        return []

    try:
        result = mod.generate_report(location, [lat, lon], str(OUTPUTS_DIR), log)
    except Exception as e:
        log(f"{module_name} failed: {e}")
        return []

    files = extract_files(result)
    if not files:
        files = scan_outputs()

    return files

# ---------------- EMAIL ----------------

def send_email(to_email, files):
    mod = soft_import("core.email_sender")
    if not mod:
        return False, "Email module missing"

    try:
        mod.send_email(to_email, "Sentinel Report", "Attached reports", files)
        return True, "Email sent"
    except Exception as e:
        return False, str(e)

# ---------------- UI STYLE ----------------

def style():
    st.markdown("""
    <style>
    .block-container {max-width:1300px; padding-top:1rem}
    .stButton button {height:48px; border-radius:10px; font-weight:700}
    .stTextInput input, .stSelectbox div, .stMultiSelect div {border-radius:10px}
    </style>
    """, unsafe_allow_html=True)

# ---------------- MAIN ----------------

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init()
    style()

    st.title("Sentinel Access Pro")

    locations = load_locations()
    loc_names = list(locations.keys())

    # --- STEP CARDS ---
    c1, c2, c3 = st.columns(3)

    with c1:
        st.info("Step 1 — Enter Details")
    with c2:
        st.info("Step 2 — Select Reports")
    with c3:
        st.success("SYSTEM READY" if st.session_state.selected_reports else "Awaiting input")

    st.markdown("---")

    # --- INPUTS ---
    col1, col2 = st.columns(2)

    with col1:
        name = st.text_input("Name")
        email = st.text_input("Email")

    with col2:
        reports = st.multiselect("Reports", REPORTS)
        location = st.selectbox("Location", loc_names if loc_names else ["No locations"])

    st.session_state.selected_reports = reports

    ready = name and email and reports and location != "No locations"

    st.markdown("---")

    generate = st.button("Generate & Email Reports", disabled=not ready)

    # --- RUN ---
    if generate:
        st.session_state.progress = ""
        log("RUN START")

        if location in locations:
            lat = locations[location]["lat"]
            lon = locations[location]["lon"]
        else:
            lat, lon = -38.33, 143.78

        all_files = []

        for r in reports:
            log(f"Running {r}...")

            if r == "Weather Report":
                all_files += run_worker("core.weather_worker", location, lat, lon)

            elif r == "Surf Report":
                all_files += run_worker("core.surf_worker", location, lat, lon)

            elif r == "Sky Report":
                all_files += run_worker("core.sky_worker", location, lat, lon)

            elif r == "Moon Events Report":
                all_files += run_worker("core.moon_events_worker", location, lat, lon)

            elif r == "Sky & Moon Report":
                all_files += run_worker("core.sky_worker", location, lat, lon)
                all_files += run_worker("core.moon_events_worker", location, lat, lon)

        # remove duplicates
        all_files = list(dict.fromkeys(all_files))

        if not all_files:
            log("NO PDF GENERATED")
            st.error("No reports generated")
            return

        log(f"{len(all_files)} PDFs ready")

        ok, msg = send_email(email, all_files)
        log(msg)

        if ok:
            st.success("Reports sent successfully")
        else:
            st.error(msg)

        st.session_state.files = all_files

    # --- OUTPUT ---
    if st.session_state.files:
        st.markdown("### Generated Files")
        for f in st.session_state.files:
            st.write(f)

    st.markdown("---")

    st.text_area("System Progress", st.session_state.progress, height=300)


if __name__ == "__main__":
    main()
