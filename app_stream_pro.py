#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import streamlit as st

APP_TITLE = "Sentinel Access"
CONFIG = Path("config")
LOC_FILE = CONFIG / "locations.json"
USAGE_LOG = CONFIG / "usage_log.csv"
DEFAULT_ADMIN_PASSWORD = "admin123"

REPORTS = [
    "Surf Report",
    "Sky & Moon Report",
    "Weather Report",
    "Trip Planner",
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

# =========================
# STATE
# =========================
def init_state():
    defaults = {
        "log": "",
        "pending_reports": [],
        "confirmed_reports": [],
        "selected_location": "",
        "user_name": "",
        "user_email": "",
        "geo_results": [],
        "admin_unlocked": False,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    current = st.session_state.get("log", "")
    st.session_state["log"] = f"{current}\n[{ts}] {msg}" if current else f"[{ts}] {msg}"

# =========================
# LOCATIONS
# =========================
def load_locations():
    if not LOC_FILE.exists():
        return {}
    try:
        data = json.loads(LOC_FILE.read_text())
        return dict(sorted(data.items(), key=lambda x: x[0].lower()))
    except:
        return {}

def save_location(name, lat, lon, state):
    CONFIG.mkdir(exist_ok=True)
    data = load_locations()
    data[name] = {"lat": lat, "lon": lon, "state": state}
    ordered = dict(sorted(data.items(), key=lambda x: x[0].lower()))
    LOC_FILE.write_text(json.dumps(ordered, indent=2))

# =========================
# GEOCODE
# =========================
def geocode(name, state):
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": name, "countryCode": "AU"},
            timeout=10,
        )
        res = r.json().get("results", [])
        return [
            {
                "name": x["name"],
                "lat": x["latitude"],
                "lon": x["longitude"],
                "state": state,
            }
            for x in res
        ]
    except Exception as e:
        log(f"Geocode failed: {e}")
        return []

# =========================
# WORKERS
# =========================
def run_worker(module, loc, lat, lon):
    try:
        mod = importlib.import_module(module)
        return mod.generate_report(loc, lat, lon)
    except Exception as e:
        log(f"{module} failed: {e}")
        return []

# =========================
# USAGE LOG
# =========================
def append_usage(user, email, report, location):
    CONFIG.mkdir(exist_ok=True)
    exists = os.path.exists(USAGE_LOG)
    with open(USAGE_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp", "user", "email", "report", "location"])
        writer.writerow([datetime.now(), user, email, report, location])

def read_usage():
    if not os.path.exists(USAGE_LOG):
        return []
    with open(USAGE_LOG, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

# =========================
# MAIN
# =========================
def main():
    st.set_page_config(page_title=APP_TITLE, layout="centered")
    init_state()

    # -------------------
    # HEADER (TOP)
    # -------------------
    st.title(APP_TITLE)

    # -------------------
    # USER DETAILS
    # -------------------
    st.subheader("User Details")
    st.text_input("Name", key="user_name")
    st.text_input("Email", key="user_email")

    # -------------------
    # REPORTS
    # -------------------
    st.subheader("Select Report")
    st.multiselect("Reports", REPORTS, key="pending_reports")

    # -------------------
    # LOCATION
    # -------------------
    locations = load_locations()
    st.subheader("Select Location")
    st.selectbox("Location", list(locations.keys()), key="selected_location")

    # -------------------
    # ACTIONS
    # -------------------
    st.subheader("Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Refresh"):
            st.session_state.clear()
            st.rerun()

    with col2:
        if st.button("Confirm"):
            st.session_state["confirmed_reports"] = st.session_state["pending_reports"]
            log("Selection confirmed")

    with col3:
        ready = all([
            st.session_state["user_name"],
            st.session_state["user_email"],
            st.session_state["confirmed_reports"],
            st.session_state["selected_location"]
        ])

        if ready:
            st.markdown("<style>button{background-color:green;color:white;}</style>", unsafe_allow_html=True)

        if st.button("Generate", disabled=not ready):
            log("RUN START ✅")

            loc = st.session_state["selected_location"]
            lat = locations[loc]["lat"]
            lon = locations[loc]["lon"]

            for r in st.session_state["confirmed_reports"]:
                log(f"Running {r}")
                append_usage(st.session_state["user_name"], st.session_state["user_email"], r, loc)

                if r == "Surf Report":
                    run_worker("core.surf_worker", loc, lat, lon)
                elif r == "Weather Report":
                    run_worker("core.weather_worker", loc, lat, lon)
                elif r == "Sky & Moon Report":
                    run_worker("core.sky_2_worker_2", loc, lat, lon)

            log("Run complete")

    # -------------------
    # ADD LOCATION
    # -------------------
    st.subheader("Add New Location")

    name = st.text_input("Location name")
    state = st.selectbox("State", list(STATE_MAP.keys()))

    if st.button("Search"):
        st.session_state["geo_results"] = geocode(name, state)

    if st.session_state.get("geo_results"):
        options = [f"{x['name']} ({x['lat']},{x['lon']})" for x in st.session_state["geo_results"]]
        st.selectbox("Matches", options)

        if st.button("Save Location"):
            chosen = st.session_state["geo_results"][0]
            save_location(chosen["name"], chosen["lat"], chosen["lon"], chosen["state"])
            log(f"Saved {chosen['name']}")
            st.rerun()

    # -------------------
    # SYSTEM PROGRESS (NOW FIXED + VISIBLE)
    # -------------------
    st.subheader("System Progress")

    st.text_area(
        "",
        value=st.session_state.get("log", ""),
        height=250,
    )

    if st.button("Clear Progress"):
        st.session_state["log"] = ""
        st.rerun()

    # -------------------
    # ADMIN (FORCED LAST)
    # -------------------
    st.subheader("Admin")

    pw = st.text_input("Password", type="password")

    if st.button("Unlock Admin"):
        if pw == DEFAULT_ADMIN_PASSWORD:
            st.session_state["admin_unlocked"] = True
        else:
            st.error("Wrong password")

    if st.session_state.get("admin_unlocked"):
        st.success("Admin unlocked")

        data = read_usage()
        if data:
            st.dataframe(data)
        else:
            st.info("No usage yet")

# =========================
if __name__ == "__main__":
    main()
