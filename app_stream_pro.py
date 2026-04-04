#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

import requests
import streamlit as st

APP_TITLE = "Surf Sky Weather Trip Planning"
ADMIN_PASSWORD = "admin123"  # change manually if needed

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
LOC_FILE = CONFIG / "locations.json"
OUTPUTS = ROOT / "outputs"

REPORTS = [
    "Surf Report",
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


def now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def init_state() -> None:
    defaults = {
        "log": f"[{now_ts()}] SYSTEM READY",
        "files": [],
        "geo_results": [],
        "admin_open": False,
        "confirmed_reports": [],
        "selection_message": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)



def log(message: str) -> None:
    current = st.session_state.get("log", "")
    st.session_state["log"] = f"{current}\n[{now_ts()}] {message}".strip()



def soft_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        return None



def valid_pdf(pathlike: Any) -> bool:
    try:
        p = Path(pathlike)
        return p.exists() and p.is_file() and p.suffix.lower() == ".pdf" and p.stat().st_size > 1000
    except Exception:
        return False



def extract_pdf_paths(value: Any) -> list[str]:
    found: list[str] = []

    def _walk(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, (str, Path)):
            if valid_pdf(item):
                found.append(str(item))
            return
        if isinstance(item, dict):
            for v in item.values():
                _walk(v)
            return
        if isinstance(item, (list, tuple, set)):
            for v in item:
                _walk(v)

    _walk(value)

    unique: list[str] = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique



def scan_dir(target_dir: str | Path | None) -> list[str]:
    if not target_dir:
        return []
    path = Path(target_dir)
    if not path.exists():
        return []
    results: list[str] = []
    for p in path.rglob("*.pdf"):
        if valid_pdf(p):
            results.append(str(p))
    results.sort()
    return results



def make_run_dir() -> Path:
    run_dir = OUTPUTS / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir



def collect_new_pdfs(before_run: set[str], run_dir: str | Path) -> list[str]:
    after = set(scan_dir(run_dir)) | set(scan_dir(OUTPUTS))
    return [f for f in sorted(after - before_run) if valid_pdf(f)]



def load_locations() -> dict[str, dict[str, Any]]:
    if not LOC_FILE.exists():
        return {}
    try:
        raw = json.loads(LOC_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    cleaned: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for name, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            lat = payload.get("lat", payload.get("latitude"))
            lon = payload.get("lon", payload.get("longitude"))
            if lat is None or lon is None:
                continue
            cleaned[str(name)] = {
                "lat": float(lat),
                "lon": float(lon),
                "state": payload.get("state", ""),
                **({"surf_profile": payload.get("surf_profile")} if payload.get("surf_profile") is not None else {}),
            }
    return dict(sorted(cleaned.items(), key=lambda kv: kv[0].casefold()))



def save_location(name: str, lat: float, lon: float, state: str) -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    locations = load_locations()
    locations[name] = {"lat": float(lat), "lon": float(lon), "state": state}
    ordered = dict(sorted(locations.items(), key=lambda kv: kv[0].casefold()))
    LOC_FILE.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

    lm_mod = soft_import("core.location_manager")
    if lm_mod and hasattr(lm_mod, "LocationManager"):
        try:
            manager = lm_mod.LocationManager(str(LOC_FILE))
            if hasattr(manager, "add_location"):
                try:
                    manager.add_location(name, float(lat), float(lon), state=state)
                except TypeError:
                    manager.add_location(name, float(lat), float(lon))
        except Exception:
            pass



def geocode_location(name: str, state_code: str) -> list[dict[str, Any]]:
    clean = " ".join((name or "").split())
    if not clean:
        log("Geocode skipped: no location name entered")
        return []

    try:
        response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": clean, "count": 10, "countryCode": "AU", "language": "en", "format": "json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log(f"Geocode failed: {exc}")
        return []

    target = STATE_MAP.get(state_code, "").casefold()
    results: list[dict[str, Any]] = []
    for item in payload.get("results", []) or []:
        admin1 = str(item.get("admin1") or "").casefold()
        country = str(item.get("country_code") or "AU").upper()
        if country != "AU":
            continue
        if target and target != admin1:
            continue
        results.append(
            {
                "name": str(item.get("name") or clean),
                "lat": item.get("latitude"),
                "lon": item.get("longitude"),
                "state": state_code,
            }
        )
    log(f"Geocode matches found: {len(results)}")
    return results



def run_worker(
    module_name: str,
    location_name: str,
    lat: float,
    lon: float,
    payload: dict[str, Any] | None = None,
    run_dir: str | Path | None = None,
) -> list[str]:
    mod = soft_import(module_name)
    if not mod or not hasattr(mod, "generate_report"):
        log(f"{module_name} missing")
        return []

    generate = getattr(mod, "generate_report")
    output_dir = str(Path(run_dir) if run_dir else OUTPUTS)

    if module_name == "core.surf_worker":
        attempts = [
            (location_name, lat, lon, output_dir, log),
            (location_name, lat, lon, output_dir),
            (location_name, lat, lon),
        ]
    elif module_name == "core.weather_worker":
        attempts = [
            (location_name, lat, lon, log),
            (location_name, lat, lon),
        ]
    else:
        attempts = [
            (location_name, [lat, lon], output_dir, log),
            (location_name, [lat, lon], output_dir),
            (location_name, lat, lon, output_dir, log),
            (location_name, lat, lon, output_dir),
            (location_name, [lat, lon]),
            (location_name, lat, lon),
        ]

    for args in attempts:
        try:
            before_files = set(scan_dir(run_dir)) | set(scan_dir(OUTPUTS))
            result = generate(*args)
            files = extract_pdf_paths(result)
            if not files:
                files = collect_new_pdfs(before_files, run_dir or OUTPUTS)
            if files:
                for file_path in files:
                    log(f"PDF OK: {file_path}")
                return files
        except TypeError:
            continue
        except Exception as exc:
            log(f"{module_name} failed: {exc}")
            return []

    log(f"{module_name} failed: incompatible generate_report signature")
    return []



def run_sky_moon_report(
    location_name: str,
    lat: float,
    lon: float,
    payload: dict[str, Any] | None = None,
    run_dir: str | Path | None = None,
) -> list[str]:
    combined_candidates = [
        "core.sky_moon_worker",
        "core.sky_and_moon_worker",
        "core.skymoon_worker",
        "core.sky_2_worker",
    ]

    for module_name in combined_candidates:
        mod = soft_import(module_name)
        if mod and hasattr(mod, "generate_report"):
            log(f"Using combined sky/moon worker: {module_name}")
            return run_worker(module_name, location_name, lat, lon, payload, run_dir)

    log("No combined sky/moon worker found. Falling back to individual sky and moon workers if available.")
    files: list[str] = []

    sky_mod = soft_import("core.sky_worker")
    if sky_mod and hasattr(sky_mod, "generate_report"):
        files.extend(run_worker("core.sky_worker", location_name, lat, lon, payload, run_dir))
    else:
        log("core.sky_worker missing")

    moon_mod = soft_import("core.moon_events_worker")
    if moon_mod and hasattr(moon_mod, "generate_report"):
        files.extend(run_worker("core.moon_events_worker", location_name, lat, lon, payload, run_dir))
    else:
        log("core.moon_events_worker missing")

    unique_files: list[str] = []
    for file_path in files:
        if file_path not in unique_files:
            unique_files.append(file_path)
    return unique_files



def send_reports(email: str, reports: list[str], location_name: str, file_paths: list[str]) -> tuple[bool, str]:
    mod = soft_import("core.email_sender")
    if not mod:
        return False, "Email module missing"

    subject = f"Sentinel Reports — {', '.join(reports)} — {location_name}"
    body = (
        "Your requested Sentinel reports are attached.\n\n"
        f"Reports: {', '.join(reports)}\n"
        f"Location: {location_name}\n"
    )

    candidates = [
        ("send_email", (email, subject, body, file_paths), {}),
        ("send_email", (), {"to_email": email, "subject": subject, "body": body, "attachments": file_paths}),
        ("send_email", (), {"recipient_email": email, "subject": subject, "body": body, "attachments": file_paths}),
        ("send_report_email", (email, subject, body, file_paths), {}),
        ("send_report_email", (), {"recipient_email": email, "subject": subject, "body": body, "attachments": file_paths}),
    ]

    for func_name, args, kwargs in candidates:
        fn = getattr(mod, func_name, None)
        if not callable(fn):
            continue
        try:
            result = fn(*args, **kwargs)
            if result is False:
                continue
            return True, "EMAIL OK"
        except TypeError:
            continue
        except Exception as exc:
            return False, f"EMAIL ERROR: {exc}"

    return False, "Email sender found, but no compatible send function matched"



def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #dfeaf7 0%, #eaf2fb 100%);
        }
        .block-container {
            max-width: 1240px;
            padding-top: 1.1rem;
            padding-bottom: 1.5rem;
        }
        .title-wrap {
            background: rgba(255,255,255,0.72);
            border: 1px solid #c9dced;
            border-radius: 18px;
            padding: 0.95rem 1.1rem;
            margin-bottom: 0.8rem;
        }
        .title-main {
            font-size: 2rem;
            font-weight: 800;
            color: #17324d;
            line-height: 1.1;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.8rem;
            margin-bottom: 0.9rem;
        }
        .status-card {
            background: rgba(255,255,255,0.88);
            border: 1px solid #c9dced;
            border-radius: 16px;
            padding: 0.8rem 0.95rem;
        }
        .status-label {
            font-size: 0.74rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #4b6785;
            margin-bottom: 0.3rem;
        }
        .status-value {
            font-size: 1rem;
            font-weight: 800;
            color: #17324d;
            margin-bottom: 0.15rem;
        }
        .status-help {
            font-size: 0.82rem;
            color: #58728d;
        }
        .panel-box {
            background: rgba(255,255,255,0.88);
            border: 1px solid #c9dced;
            border-radius: 16px;
            padding: 1rem 1rem 0.85rem 1rem;
            margin-bottom: 0.9rem;
        }
        .panel-title {
            font-size: 1rem;
            font-weight: 800;
            color: #17324d;
            margin-bottom: 0.35rem;
        }
        .panel-note {
            font-size: 0.82rem;
            color: #5e7894;
            margin-bottom: 0.55rem;
        }
        div[data-testid="stTextInput"] label,
        div[data-testid="stSelectbox"] label,
        div[data-testid="stMultiSelect"] label,
        div[data-testid="stTextArea"] label {
            font-size: 1rem !important;
            font-weight: 700 !important;
            color: #284866 !important;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stSelectbox"] > div,
        div[data-testid="stMultiSelect"] > div {
            border-radius: 12px !important;
            border: 1px solid #c9dced !important;
            background: #ffffff !important;
        }
        .green-ready button {
            background: linear-gradient(135deg, #1faa63, #159251) !important;
            color: white !important;
            border: 1px solid #14874b !important;
        }
        .stButton button {
            height: 2.7rem;
            border-radius: 12px !important;
            font-weight: 800 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )



def render_header(ready: bool, confirmed_count: int) -> None:
    st.markdown(
        f"""
        <div class="title-wrap">
            <div class="title-main">{APP_TITLE}</div>
        </div>
        <div class="status-grid">
            <div class="status-card">
                <div class="status-label">Step 1</div>
                <div class="status-value">Enter user details</div>
                <div class="status-help">Name, email, report selection and location</div>
            </div>
            <div class="status-card">
                <div class="status-label">Step 2</div>
                <div class="status-value">Confirm report selection</div>
                <div class="status-help">{confirmed_count} confirmed report{'s' if confirmed_count != 1 else ''}</div>
            </div>
            <div class="status-card">
                <div class="status-label">System</div>
                <div class="status-value">{'SYSTEM READY' if ready else 'Awaiting confirmation'}</div>
                <div class="status-help">Generate turns green once selection is confirmed</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )



def normalize_reports(confirmed_reports: list[str]) -> list[str]:
    deduped: list[str] = []
    for report in confirmed_reports:
        if report not in deduped:
            deduped.append(report)
    return deduped



def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()
    apply_styles()

    locations = load_locations()
    location_names = list(locations.keys())

    confirmed_reports = st.session_state.get("confirmed_reports", [])
    ready = bool(
        st.session_state.get("user_name", "").strip()
        and st.session_state.get("user_email", "").strip()
        and st.session_state.get("selected_location", "") not in ("", "None")
        and confirmed_reports
    )

    render_header(ready, len(confirmed_reports))

    left, right = st.columns(2, gap="large")

    with left:
        st.markdown(
            '<div class="panel-box"><div class="panel-title">User details</div><div class="panel-note">Enter name and email.</div>',
            unsafe_allow_html=True,
        )
        st.text_input("Name", key="user_name")
        st.text_input("Email", key="user_email")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown(
            '<div class="panel-box"><div class="panel-title">Report selection</div><div class="panel-note">Select one or more reports, confirm them, then choose the location.</div>',
            unsafe_allow_html=True,
        )
        pending_reports = st.multiselect(
            "Select reports",
            REPORTS,
            default=st.session_state.get("confirmed_reports", []),
            key="pending_reports",
        )

        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1], gap="small")
        with btn_col1:
            refresh_clicked = st.button("Refresh Page", use_container_width=True)
        with btn_col2:
            confirm_clicked = st.button("Confirm Selection", use_container_width=True)
        with btn_col3:
            if ready:
                st.markdown('<div class="green-ready">', unsafe_allow_html=True)
            generate_clicked = st.button("Generate Reports", use_container_width=True, disabled=not ready)
            if ready:
                st.markdown("</div>", unsafe_allow_html=True)

        st.selectbox("Location", location_names if location_names else ["None"], key="selected_location")

        if st.session_state.get("selection_message"):
            st.info(st.session_state["selection_message"])
        st.markdown("</div>", unsafe_allow_html=True)

    if refresh_clicked:
        st.session_state["selection_message"] = ""
        st.rerun()

    if confirm_clicked:
        st.session_state["confirmed_reports"] = list(pending_reports)
        if pending_reports:
            st.session_state["selection_message"] = f"Confirmed {len(pending_reports)} report{'s' if len(pending_reports) != 1 else ''}."
            log(f"Confirmed reports: {', '.join(pending_reports)}")
        else:
            st.session_state["selection_message"] = "No reports selected."
            log("Confirm selection pressed with no reports selected")
        st.rerun()

    with st.expander("Add New Location"):
        new_location_name = st.text_input("Location name", key="new_location_name")
        new_state = st.selectbox("State", list(STATE_MAP.keys()), key="new_location_state")

        if st.button("Search Location"):
            st.session_state["geo_results"] = geocode_location(new_location_name, new_state)
            st.rerun()

        geo_results = st.session_state.get("geo_results", [])
        if geo_results:
            options = [f"{item['name']} ({item['state']})" for item in geo_results]
            selected_match = st.selectbox("Select match", options, key="geo_choice")
            if st.button("Save Selected Location"):
                idx = options.index(selected_match)
                chosen = geo_results[idx]
                save_location(chosen["name"], chosen["lat"], chosen["lon"], chosen["state"])
                st.session_state["selected_location"] = chosen["name"]
                st.session_state["geo_results"] = []
                st.success(f"Saved {chosen['name']} — location list refreshed")
                log(f"Location saved: {chosen['name']} ({chosen['state']})")
                st.rerun()

    admin_col1, admin_col2 = st.columns([1, 5], gap="small")
    with admin_col1:
        if st.button("Admin Panel", use_container_width=True):
            st.session_state["admin_open"] = True
            st.rerun()
    with admin_col2:
        if st.session_state.get("admin_open"):
            st.markdown('<div class="panel-box"><div class="panel-title">Admin panel</div>', unsafe_allow_html=True)
            pwd = st.text_input("Password", type="password", key="admin_password")
            if pwd == ADMIN_PASSWORD:
                st.success("Admin unlocked")
                st.write("Confirmed reports:", st.session_state.get("confirmed_reports", []))
                st.write("Selected location:", st.session_state.get("selected_location", ""))
                st.write("User email:", st.session_state.get("user_email", ""))
            close_col1, _ = st.columns([1, 4])
            with close_col1:
                if st.button("Close Admin", use_container_width=True):
                    st.session_state["admin_open"] = False
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    if generate_clicked:
        st.session_state["log"] = ""
        st.session_state["files"] = []
        current_reports = normalize_reports(list(st.session_state.get("confirmed_reports", [])))
        current_location = st.session_state.get("selected_location", "")
        payload = locations.get(current_location, {})
        lat = payload.get("lat")
        lon = payload.get("lon")
        run_dir = make_run_dir()

        log("RUN START ✅")
        log(f"Run folder: {run_dir}")

        if lat is None or lon is None:
            log(f"Selected location not found in locations.json: {current_location}")
            st.error("Selected location was not found. Please refresh and try again.")
        else:
            log(f"Confirmed run set: {', '.join(current_reports)}")
            all_files: list[str] = []

            for report in current_reports:
                log(f"Running {report}")
                before_count = len(all_files)

                if report == "Surf Report":
                    files = run_worker("core.surf_worker", current_location, lat, lon, payload, run_dir)
                elif report == "Sky & Moon Report":
                    files = run_sky_moon_report(current_location, lat, lon, payload, run_dir)
                elif report == "Weather Report":
                    files = run_worker("core.weather_worker", current_location, lat, lon, payload, run_dir)
                else:
                    files = []

                all_files.extend(files)
                if len(all_files) == before_count:
                    log(f"No PDF captured for {report}")

            unique_files: list[str] = []
            for file_path in all_files:
                if file_path not in unique_files:
                    unique_files.append(file_path)

            if not unique_files:
                log("❌ NO REPORTS GENERATED — CHECK WORKER")
                st.error("No reports generated — see System Progress below")
            else:
                ok, message = send_reports(
                    st.session_state.get("user_email", ""),
                    current_reports,
                    current_location,
                    unique_files,
                )
                log(message)
                st.session_state["files"] = unique_files
                if ok:
                    st.success(f"Reports sent successfully ({len(unique_files)} PDF attachments)")
                else:
                    st.error(message)

    st.markdown(
        '<div class="panel-box"><div class="panel-title">System progress</div><div class="panel-note">Run status and worker messages.</div>',
        unsafe_allow_html=True,
    )
    st.text_area("System Progress", value=st.session_state.get("log", ""), height=240, disabled=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.get("files"):
        st.markdown('<div class="panel-box"><div class="panel-title">Generated files</div>', unsafe_allow_html=True)
        for item in st.session_state["files"]:
            st.write(item)
        st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
