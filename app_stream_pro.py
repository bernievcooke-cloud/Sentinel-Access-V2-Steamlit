# ==============================================
# SENTINEL ACCESS PRO — FINAL POLISHED UI BUILD
# ==============================================

from __future__ import annotations

import importlib
import json
from datetime import datetime
from pathlib import Path
import requests
import streamlit as st

APP_TITLE = "Surf Sky Weather Trip Planning"
ADMIN_PASSWORD = "admin123"

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
LOC_FILE = CONFIG / "locations.json"
OUTPUTS = ROOT / "outputs"

REPORTS = [
    "Surf Report",
    "Sky Report",
    "Moon Events Report",
    "Sky & Moon Report",
    "Weather Report",
]

STATE_MAP = {
    "VIC": "Victoria",
    "NSW": "New South Wales",
    "QLD": "Queensland",
    "SA": "South Australia",
    "WA": "Western Australia",
    "TAS": "Tasmania",
    "NT": "Northern Territory",
    "ACT": "Australian Capital Territory",
}

# ---------- INIT ----------

def now(): return datetime.now().strftime("%H:%M:%S")

def init():
    for k, v in {
        "log": f"[{now()}] SYSTEM READY",
        "files": [],
        "geo_results": [],
        "admin_open": False,
    }.items():
        st.session_state.setdefault(k, v)


def log(msg):
    st.session_state.log += f"\n[{now()}] {msg}"

# ---------- UTIL ----------

def soft_import(name):
    try: return importlib.import_module(name)
    except: return None


def valid_pdf(p):
    try:
        p = Path(p)
        return p.exists() and p.stat().st_size > 1000
    except: return False


def extract(result):
    out = []
    if isinstance(result, str): out.append(result)
    elif isinstance(result, (list, tuple)):
        out += [x for x in result if isinstance(x, str)]
    elif isinstance(result, dict):
        out += [v for v in result.values() if isinstance(v, str)]
    return [f for f in out if valid_pdf(f)]


def scan():
    return [str(p) for p in OUTPUTS.glob("*.pdf") if valid_pdf(p)]

# ---------- LOCATIONS ----------

def load_locations():
    if not LOC_FILE.exists(): return {}
    return json.loads(LOC_FILE.read_text())


def save_location(name, lat, lon, state):
    CONFIG.mkdir(exist_ok=True)
    data = load_locations()
    data[name] = {"lat": lat, "lon": lon, "state": state}
    LOC_FILE.write_text(json.dumps(data, indent=2))

# ---------- GEOCODE ----------

def geocode(name, state):
    try:
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
            params={"name": name, "count": 10, "countryCode": "AU"}, timeout=10)
        data = r.json().get("results", [])
    except Exception as e:
        log(f"Geocode failed: {e}")
        return []

    target = STATE_MAP.get(state, "").lower()
    results = []

    for item in data:
        if target and target not in str(item.get("admin1", "")).lower():
            continue
        results.append({
            "name": item.get("name"),
            "lat": item.get("latitude"),
            "lon": item.get("longitude"),
            "state": state
        })

    return results

# ---------- WORKER ----------

def run(module, loc, lat, lon):
    mod = soft_import(module)
    if not mod:
        log(f"{module} missing")
        return []

    # FIX: correct surf worker bad argument issue
    if module == "core.surf_worker":
        # HARD FIX: surf_worker REQUIRES lat, lon (NOT list)
        attempts = [
            (loc, lat, lon, str(OUTPUTS), log),
            (loc, lat, lon, str(OUTPUTS)),
            (loc, lat, lon, log),
            (loc, lat, lon),
        ]
    else:
        attempts = [
        (loc, [lat, lon], str(OUTPUTS), log),
        (loc, [lat, lon], str(OUTPUTS)),
        (loc, lat, lon, str(OUTPUTS), log),
        (loc, lat, lon, str(OUTPUTS)),
        (loc, [lat, lon], log),
        (loc, lat, lon, log),
        (loc, [lat, lon]),
        (loc, lat, lon),
    ]

    for args in attempts:
        try:
            res = mod.generate_report(*args)
            files = extract(res)
            if not files: files = scan()

            if files:
                for f in files: log(f"PDF OK: {f}")
                return files

        except TypeError:
            continue
        except Exception as e:
            log(f"{module} failed: {e}")
            return []

    log(f"{module} failed: signature mismatch")
    return []

# ---------- EMAIL ----------

def send(email, files):
    mod = soft_import("core.email_sender")
    if not mod:
        return False, "Email module missing"
    try:
        mod.send_email(email, "Sentinel Reports", "Attached", files)
        return True, "EMAIL OK"
    except Exception as e:
        return False, str(e)

# ---------- UI ----------

def main():
    st.set_page_config(layout="wide")
    init()

    st.markdown("""
    <style>
    .stApp {background-color:#e6f0fa;} 
    .block-container {max-width:1200px; padding-top:1.2rem; padding-bottom:1rem}
    .block-container {max-width:1000px; padding-top:0.5rem}
    .input-box {background:#ffffff; padding:10px; border-radius:10px; border:1px solid #d0e2f2}
    label {font-size:15px !important; font-weight:600 !important;}
    </style>
    """, unsafe_allow_html=True)

    st.title(APP_TITLE)

    locations = load_locations()

    # ---- INPUT ----
    c1, c2 = st.columns([1,1], gap="large")

    with c1:
        st.markdown("<div class='input-box'>", unsafe_allow_html=True)
        name = st.text_input("Name")
        email = st.text_input("Email")
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown("<div class='input-box'>", unsafe_allow_html=True)
        reports = st.multiselect("Reports", REPORTS)
        location = st.selectbox("Location", list(locations.keys()) or ["None"])
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("---")

    # ---- REFRESH ----
    if st.button("Refresh Page"):
        st.rerun()

    # ---- LOCATION ADD ----
    with st.expander("Add New Location"):
        loc_name = st.text_input("Location name")
        state = st.selectbox("State", list(STATE_MAP.keys()))

        if st.button("Search"):
            st.session_state.geo_results = geocode(loc_name, state)

        if st.session_state.geo_results:
            opts = [f"{r['name']} ({state})" for r in st.session_state.geo_results]
            choice = st.selectbox("Select", opts)

            if st.button("Save"):
                r = st.session_state.geo_results[opts.index(choice)]
                save_location(r["name"], r["lat"], r["lon"], r["state"])
                st.success("Saved — refresh")

    # ---- ADMIN ----
    if st.button("Admin Panel"):
        st.session_state.admin_open = True

    if st.session_state.admin_open:
        st.markdown("### Admin Panel")
        pwd = st.text_input("Password", type="password")

        if pwd == ADMIN_PASSWORD:
            st.success("Unlocked")
            st.write("Reports:", reports)
            st.write("Location:", location)

            if st.button("Close Admin"):
                st.session_state.admin_open = False
                st.rerun()

    st.markdown("---")

    # ---- RUN ----
    if st.button("Generate & Email", disabled=not (name and email and reports and location != "None")):
        st.session_state.log = ""
        log("RUN START ✅")

        lat = locations.get(location, {}).get("lat")
        lon = locations.get(location, {}).get("lon")

        files = []

        for r in reports:
            log(f"Running {r}")

            if r == "Weather Report": files += run("core.weather_worker", location, lat, lon)
            if r == "Surf Report": files += run("core.surf_worker", location, lat, lon)
            if r == "Sky Report": files += run("core.sky_worker", location, lat, lon)
            if r == "Moon Events Report": files += run("core.moon_events_worker", location, lat, lon)
            if r == "Sky & Moon Report":
                files += run("core.sky_worker", location, lat, lon)
                files += run("core.moon_events_worker", location, lat, lon)

        files = list(dict.fromkeys(files))

        if not files:
            log("❌ NO REPORTS GENERATED — CHECK WORKER")
            st.error("No reports generated — see log")
            return

        ok, msg = send(email, files)
        log(msg)

        if ok: st.success("Reports sent")
        else: st.error(msg)

        st.session_state.files = files

    # ---- LOG (always visible) ----
    st.markdown("### System Progress")
    st.text_area("", st.session_state.log, height=200)

    st.markdown("---")

    # ---- OUTPUT ----
    if st.session_state.files:
        st.subheader("Generated Files")
        for f in st.session_state.files:
            st.write(f)

    st.markdown("---")
    st.text_area("System Progress", st.session_state.log, height=220)


if __name__ == "__main__":
    main()
