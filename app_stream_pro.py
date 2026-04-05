#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import streamlit as st

APP_TITLE = "Surf Sky Weather Trip Planning"

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
LOC_FILE = CONFIG / "locations.json"

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

ADMIN_PASSWORD = " "


def now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def default_state() -> dict[str, Any]:
    return {
        "log": f"[{now_ts()}] SYSTEM READY",
        "files": [],
        "geo_results": [],
        "geo_choice": "",
        "show_geo_results": False,
        "confirmed_reports": [],
        "selection_message": "",
        "location_after_save": "",
        "preview_report": "Not selected",
        "preview_location": "Not selected",
        "pending_reports": [],
        "selected_location": "",
        "user_name": "",
        "user_email": "",
        "trip_start": "",
        "trip_dest_1": "",
        "trip_dest_2": "",
        "trip_dest_3": "",
        "trip_fuel_type": "Petrol",
        "trip_fuel_price": 2.00,
        "new_location_name": "",
        "new_location_state": "VIC",
        "admin_password": "",
        "admin_unlocked": False,
    }


def init_state() -> None:
    for key, value in default_state().items():
        st.session_state.setdefault(key, value)


def reset_app_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_state()


def log(message: str) -> None:
    message = str(message).strip()
    if not message:
        return
    current = st.session_state.get("log", "")
    if current:
        st.session_state["log"] = f"{current}\n[{now_ts()}] {message}"
    else:
        st.session_state["log"] = f"[{now_ts()}] {message}"


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
                found.append(str(Path(item).resolve()))
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
            results.append(str(p.resolve()))
    results.sort()
    return results


def make_run_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "sentinel_runs"
    base.mkdir(parents=True, exist_ok=True)
    run_dir = base / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def collect_new_pdfs(before_run: set[str], run_dir: str | Path) -> list[str]:
    after = set(scan_dir(run_dir))
    return [f for f in sorted(after - before_run) if valid_pdf(f)]


def cleanup_generated_files(file_paths: list[str], run_dir: str | Path | None = None) -> None:
    for file_path in file_paths:
        try:
            p = Path(file_path)
            if p.exists() and p.is_file():
                p.unlink()
                log(f"Removed temporary file: {p}")
        except Exception as exc:
            log(f"Cleanup warning for {file_path}: {exc}")

    if run_dir:
        try:
            rp = Path(run_dir)
            if rp.exists():
                shutil.rmtree(rp, ignore_errors=True)
                log(f"Removed temporary run folder: {rp}")
        except Exception as exc:
            log(f"Cleanup warning for run folder: {exc}")


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
    final_name = str(name).strip()
    if not final_name:
        raise ValueError("Location name is blank")

    CONFIG.mkdir(parents=True, exist_ok=True)
    locations = load_locations()
    locations[final_name] = {
        "lat": float(lat),
        "lon": float(lon),
        "state": str(state).strip(),
    }
    ordered = dict(sorted(locations.items(), key=lambda kv: kv[0].casefold()))
    LOC_FILE.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

    lm_mod = soft_import("core.location_manager")
    if lm_mod and hasattr(lm_mod, "LocationManager"):
        try:
            manager = lm_mod.LocationManager(str(LOC_FILE))
            if hasattr(manager, "add_location"):
                try:
                    manager.add_location(final_name, float(lat), float(lon), state=state)
                except TypeError:
                    manager.add_location(final_name, float(lat), float(lon))
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
            params={
                "name": clean,
                "count": 10,
                "countryCode": "AU",
                "language": "en",
                "format": "json",
            },
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
        if target and admin1 != target:
            continue
        lat = item.get("latitude")
        lon = item.get("longitude")
        if lat is None or lon is None:
            continue
        results.append(
            {
                "name": str(item.get("name") or clean).strip(),
                "lat": float(lat),
                "lon": float(lon),
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
    output_dir = str(Path(run_dir)) if run_dir else str(make_run_dir())

    if module_name in {"core.surf_worker", "core.weather_worker"}:
        attempts: list[tuple[Any, ...]] = [
            (location_name, float(lat), float(lon), output_dir, log),
            (location_name, float(lat), float(lon), log),
            (location_name, float(lat), float(lon), output_dir),
            (location_name, float(lat), float(lon)),
            (location_name, [float(lat), float(lon)], output_dir, log),
            (location_name, [float(lat), float(lon)], log),
            (location_name, [float(lat), float(lon)], output_dir),
            (location_name, [float(lat), float(lon)]),
        ]
    else:
        attempts = [
            (location_name, [float(lat), float(lon)], output_dir, log),
            (location_name, float(lat), float(lon), output_dir, log),
            (location_name, [float(lat), float(lon)], log),
            (location_name, float(lat), float(lon), log),
            (location_name, [float(lat), float(lon)], output_dir),
            (location_name, float(lat), float(lon), output_dir),
            (location_name, [float(lat), float(lon)]),
            (location_name, float(lat), float(lon)),
        ]

    for args in attempts:
        try:
            before_files = set(scan_dir(run_dir or output_dir))
            result = generate(*args)
            files = extract_pdf_paths(result)
            if not files:
                files = collect_new_pdfs(before_files, run_dir or output_dir)
            if files:
                for file_path in files:
                    log(f"PDF OK: {file_path}")
                return files
        except TypeError as exc:
            log(f"{module_name} signature mismatch on args {args}: {exc}")
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
        "core.sky_moon_report_worker",
    ]

    for module_name in combined_candidates:
        mod = soft_import(module_name)
        if mod and hasattr(mod, "generate_report"):
            log(f"Using combined sky/moon worker: {module_name}")
            return run_worker(module_name, location_name, lat, lon, payload, run_dir)

    log("No combined sky/moon worker found. Running sky and moon workers separately.")
    files: list[str] = []

    sky_mod_name = "core.sky_2_worker_2"
    moon_mod_name = "core.moon_events_worker_2"

    sky_mod = soft_import(sky_mod_name)
    if sky_mod and hasattr(sky_mod, "generate_report"):
        log("Running Sky worker")
        files.extend(run_worker(sky_mod_name, location_name, lat, lon, payload, run_dir))
    else:
        log(f"{sky_mod_name} missing")

    moon_mod = soft_import(moon_mod_name)
    if moon_mod and hasattr(moon_mod, "generate_report"):
        log("Running Moon Events worker")
        files.extend(run_worker(moon_mod_name, location_name, lat, lon, payload, run_dir))
    else:
        log(f"{moon_mod_name} missing")

    unique_files: list[str] = []
    for file_path in files:
        if file_path not in unique_files:
            unique_files.append(file_path)
    return unique_files


def trip_planner(route_points: list[str], fuel_type: str, fuel_price: float):
    try:
        from core.trip_worker import generate_trip_report_from_route
    except Exception:
        return False, "Trip worker not available.", []

    route = [p for p in route_points if p and str(p).strip()]
    if len(route) < 2:
        return False, "Trip needs at least a start and one destination.", []

    log(f"Running Trip Planner: {' -> '.join(route)}")
    log(f"Fuel type: {fuel_type}")
    log(f"Fuel price: ${float(fuel_price):.2f}/L")

    try:
        import os

        pdf_path = generate_trip_report_from_route(
            route=route,
            fuel_type=fuel_type,
            fuel_price=float(fuel_price),
            logger=log,
        )
        if pdf_path and os.path.exists(pdf_path):
            log(f"PDF OK: {pdf_path}")
            return True, "Trip report generated.", [pdf_path]
        return False, "Trip report failed to generate.", []
    except Exception as e:
        return False, f"Trip error: {e}", []


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
            return True, "Email sent."
        except TypeError:
            continue
        except Exception as exc:
            return False, f"EMAIL ERROR: {exc}"

    return False, "Email sender found, but no compatible send function matched."


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #dceaf7 0%, #eaf2fb 100%);
        }
        .block-container {
            max-width: 1240px;
            padding-top: 2.55rem;
            padding-bottom: 1.2rem;
        }
        .title-wrap {
            background: #ffffff;
            border: 1px solid #bfd3e6;
            border-radius: 18px;
            padding: 1.00rem 1.05rem;
            margin-top: 0.35rem;
            margin-bottom: 0.85rem;
            box-shadow: 0 2px 10px rgba(23, 50, 77, 0.06);
        }
        .title-main {
            font-size: 1.9rem;
            font-weight: 800;
            color: #17324d;
            line-height: 1.1;
        }
        .panel-box {
            background: #ffffff;
            border: 1px solid #bfd3e6;
            border-radius: 16px;
            padding: 0.85rem 0.9rem 0.75rem 0.9rem;
            margin-bottom: 0.8rem;
            box-shadow: 0 2px 10px rgba(23, 50, 77, 0.06);
        }
        .compact-box {
            background: #ffffff;
            border: 1px solid #bfd3e6;
            border-radius: 14px;
            padding: 0.55rem 0.75rem;
            margin-bottom: 0.55rem;
        }
        .compact-label {
            font-size: 0.72rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #4b6785;
            margin-bottom: 0.15rem;
        }
        .compact-value {
            font-size: 0.94rem;
            font-weight: 800;
            color: #17324d;
            line-height: 1.2;
        }
        .minor-heading {
            font-size: 0.9rem;
            font-weight: 800;
            color: #284866;
            margin: 0.05rem 0 0.3rem 0;
        }
        .section-spacer {
            height: 0.12rem;
        }
        div[data-testid="stTextInput"] label,
        div[data-testid="stSelectbox"] label,
        div[data-testid="stMultiSelect"] label,
        div[data-testid="stTextArea"] label {
            font-size: 0.96rem !important;
            font-weight: 700 !important;
            color: #284866 !important;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stSelectbox"] > div,
        div[data-testid="stMultiSelect"] > div {
            border-radius: 12px !important;
            border: 1px solid #bfd3e6 !important;
            background: #ffffff !important;
            color: #17324d !important;
        }
        .green-ready button {
            background: linear-gradient(135deg, #1faa63, #159251) !important;
            color: white !important;
            border: 1px solid #14874b !important;
        }
        .stButton button {
            height: 2.6rem;
            border-radius: 12px !important;
            font-weight: 800 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def route_label_from_points(points: list[str]) -> str:
    filtered = [p for p in points if p and str(p).strip()]
    if not filtered:
        return "Not selected"
    return " → ".join(filtered)


def normalize_reports(reports: list[str]) -> list[str]:
    deduped: list[str] = []
    for report in reports:
        if report not in deduped:
            deduped.append(report)
    return deduped


def info_box(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="compact-box">
            <div class="compact-label">{label}</div>
            <div class="compact-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_title() -> None:
    st.markdown(
        f"""
        <div class="title-wrap">
            <div class="title-main">{APP_TITLE}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_state()
    apply_styles()

    if not st.session_state.get("pending_reports"):
        st.session_state["pending_reports"] = list(st.session_state.get("confirmed_reports", []))

    locations = load_locations()
    location_names = list(locations.keys())

    pending_location = st.session_state.get("location_after_save", "")
    if pending_location and pending_location in location_names:
        st.session_state["selected_location"] = pending_location
        st.session_state["location_after_save"] = ""

    pending_reports_preview = normalize_reports(st.session_state.get("pending_reports", []))

    trip_points_preview = [
        st.session_state.get("trip_start", ""),
        st.session_state.get("trip_dest_1", ""),
        st.session_state.get("trip_dest_2", ""),
        st.session_state.get("trip_dest_3", ""),
    ]
    trip_route_preview = [p for p in trip_points_preview if p and str(p).strip()]

    has_trip_selected = "Trip Planner" in pending_reports_preview
    has_standard_reports_selected = any(
        r in pending_reports_preview for r in ["Surf Report", "Sky & Moon Report", "Weather Report"]
    )

    normal_ready = bool(
        st.session_state.get("user_name", "").strip()
        and st.session_state.get("user_email", "").strip()
        and (not has_standard_reports_selected or st.session_state.get("selected_location", "").strip())
        and pending_reports_preview
    )

    trip_ready = bool(not has_trip_selected or len(trip_route_preview) >= 2)
    ready = bool(normal_ready and trip_ready)

    render_title()

    left, right = st.columns([1, 1], gap="large")

    search_location_clicked = False
    save_location_clicked = False
    refresh_clicked = False
    confirm_clicked = False
    generate_clicked = False
    clear_log_clicked = False
    unlock_admin_clicked = False

    with left:
        st.markdown('<div class="panel-box">', unsafe_allow_html=True)
        st.text_input("Name", key="user_name")
        st.text_input("Email", key="user_email")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="panel-box">', unsafe_allow_html=True)
        info_box("Admin function", "Password")
        st.text_input("Admin password", type="password", key="admin_password")
        unlock_admin_clicked = st.button("Unlock Admin", use_container_width=True)

        st.markdown(
            '<div class="panel-box"><div class="minor-heading">System progress</div>',
            unsafe_allow_html=True,
        )
        st.text_area(
            "System Progress",
            value=st.session_state.get("log", ""),
            height=300,
            disabled=True,
            label_visibility="collapsed",
        )
        clear_log_clicked = st.button("Clear progress", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    
    with right:
        st.markdown('<div class="panel-box">', unsafe_allow_html=True)

        st.multiselect(
            "Select reports",
            REPORTS,
            key="pending_reports",
        )

        pending_reports_live = normalize_reports(st.session_state.get("pending_reports", []))
        pending_trip_mode = "Trip Planner" in pending_reports_live
        pending_standard_mode = any(
            r in pending_reports_live for r in ["Surf Report", "Sky & Moon Report", "Weather Report"]
        )

        location_label = "Not selected"

        if pending_standard_mode or not pending_trip_mode:
            st.selectbox(
                "Location",
                location_names if location_names else [""],
                key="selected_location",
            )

        selected_normal_location = st.session_state.get("selected_location", "").strip()

        if pending_trip_mode:
            trip_location_options = [""] + location_names if location_names else [""]
            st.markdown('<div class="minor-heading">Trip route</div>', unsafe_allow_html=True)
            st.selectbox("Start location", trip_location_options, key="trip_start")
            st.selectbox("Destination 1", trip_location_options, key="trip_dest_1")
            st.selectbox("Destination 2", trip_location_options, key="trip_dest_2")
            st.selectbox("Destination 3", trip_location_options, key="trip_dest_3")

            st.markdown('<div class="minor-heading">Trip settings</div>', unsafe_allow_html=True)
            st.selectbox("Fuel type", ["Petrol", "Diesel"], key="trip_fuel_type")
            st.selectbox(
                "Fuel price per litre",
                [round(x / 100, 2) for x in range(140, 401, 5)],
                key="trip_fuel_price",
            )

        preview_parts: list[str] = []
        if pending_standard_mode:
            preview_parts.append(selected_normal_location or "No main location selected")

        trip_points = [
            st.session_state.get("trip_start", ""),
            st.session_state.get("trip_dest_1", ""),
            st.session_state.get("trip_dest_2", ""),
            st.session_state.get("trip_dest_3", ""),
        ]
        trip_route_label = route_label_from_points(trip_points)
        if pending_trip_mode:
            preview_parts.append(f"Trip: {trip_route_label}")

        if preview_parts:
            location_label = " | ".join(preview_parts)

        st.session_state["preview_report"] = ", ".join(pending_reports_live) if pending_reports_live else "Not selected"
        st.session_state["preview_location"] = location_label if location_label else "Not selected"

        st.markdown('<div class="section-spacer"></div>', unsafe_allow_html=True)
        info_box("Selected report", st.session_state.get("preview_report", "Not selected"))
        info_box("Selected location(s)", st.session_state.get("preview_location", "Not selected"))

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

                st.markdown('<div class="section-spacer"></div>', unsafe_allow_html=True)
        info_box("Add new location", "Search and save new locations for reports")
        st.text_input("Location name", key="new_location_name")
        st.selectbox("State", list(STATE_MAP.keys()), key="new_location_state")

        loc_btn1, loc_btn2 = st.columns(2, gap="small")
        with loc_btn1:
            search_location_clicked = st.button(
                "Search Location",
                use_container_width=True,
            )
        with loc_btn2:
            save_location_clicked = st.button(
                "Save Selected Location",
                use_container_width=True,
            )

        if st.session_state.get("show_geo_results", False):
            geo_results = st.session_state.get("geo_results", [])
            if geo_results:
                option_labels = [
                    f"{item['name']} ({item['state']}) — {float(item['lat']):.5f}, {float(item['lon']):.5f}"
                    for item in geo_results
                ]
                if option_labels:
                    current_choice = st.session_state.get("geo_choice", "")
                    if current_choice not in option_labels:
                        st.session_state["geo_choice"] = option_labels[0]
                    st.selectbox("Select match", option_labels, key="geo_choice")
            else:
                st.session_state["show_geo_results"] = False

        st.markdown("</div>", unsafe_allow_html=True)

    if unlock_admin_clicked:
        entered = st.session_state.get("admin_password", "")
        if entered == ADMIN_PASSWORD:
            st.session_state["admin_unlocked"] = True
            log("Admin unlocked")
            st.success("Admin unlocked.")
        else:
            st.session_state["admin_unlocked"] = False
            log("Admin unlock failed")
            st.error("Incorrect admin password.")
        st.rerun()

    if search_location_clicked:
        log("Location search started")
        st.session_state["geo_results"] = geocode_location(
            st.session_state.get("new_location_name", ""),
            st.session_state.get("new_location_state", "VIC"),
        )
        geo_results = st.session_state.get("geo_results", [])
        if geo_results:
            option_labels = [
                f"{item['name']} ({item['state']}) — {float(item['lat']):.5f}, {float(item['lon']):.5f}"
                for item in geo_results
            ]
            st.session_state["geo_choice"] = option_labels[0] if option_labels else ""
            st.session_state["show_geo_results"] = True
            log("Location search complete: matches ready for selection")
        else:
            st.session_state["geo_choice"] = ""
            st.session_state["show_geo_results"] = False
            st.warning("No matches found.")
            log("Location search complete: no matches found")
        st.rerun()

    if save_location_clicked:
        geo_results = st.session_state.get("geo_results", [])
        if not geo_results:
            st.warning("Search first, then choose a match to save.")
            log("Save location blocked: no search results available")
        else:
            option_labels = [
                f"{item['name']} ({item['state']}) — {float(item['lat']):.5f}, {float(item['lon']):.5f}"
                for item in geo_results
            ]
            selected_match = st.session_state.get("geo_choice", "")
            if selected_match not in option_labels:
                st.warning("Please choose a match to save.")
                log("Save location blocked: no valid match selected")
            else:
                idx = option_labels.index(selected_match)
                chosen = geo_results[idx]
                save_location(
                    chosen["name"],
                    float(chosen["lat"]),
                    float(chosen["lon"]),
                    chosen["state"],
                )
                st.session_state["location_after_save"] = chosen["name"]
                st.session_state["geo_results"] = []
                st.session_state["geo_choice"] = ""
                st.session_state["show_geo_results"] = False
                st.session_state["selection_message"] = f"Location saved: {chosen['name']}"
                log(f"Location saved: {chosen['name']} ({chosen['state']})")
        st.rerun()

    if st.session_state.get("selection_message"):
        st.info(st.session_state["selection_message"])

    if clear_log_clicked:
        st.session_state["log"] = f"[{now_ts()}] SYSTEM READY"
        st.rerun()

    if refresh_clicked:
        reset_app_state()
        st.rerun()

    if confirm_clicked:
        reports_to_confirm = normalize_reports(st.session_state.get("pending_reports", []))
        st.session_state["confirmed_reports"] = list(reports_to_confirm)

        if reports_to_confirm:
            st.session_state["selection_message"] = f"Confirmed: {', '.join(reports_to_confirm)}"
            log(f"Confirmed reports: {', '.join(reports_to_confirm)}")

            if any(r in reports_to_confirm for r in ["Surf Report", "Sky & Moon Report", "Weather Report"]):
                log(f"Confirmed main location: {st.session_state.get('selected_location', '').strip() or 'None'}")

            if "Trip Planner" in reports_to_confirm:
                trip_points_confirm = [
                    st.session_state.get("trip_start", ""),
                    st.session_state.get("trip_dest_1", ""),
                    st.session_state.get("trip_dest_2", ""),
                    st.session_state.get("trip_dest_3", ""),
                ]
                log(f"Confirmed trip route: {route_label_from_points(trip_points_confirm)}")
        else:
            st.session_state["selection_message"] = "No reports selected."
            log("Confirm selection pressed with no reports selected")

        st.rerun()

    if generate_clicked:
        st.session_state["files"] = []
        st.session_state["log"] = ""
        log("RUN START ✅")

        run_dir = make_run_dir()
        log(f"Temporary run folder: {run_dir}")

        selected_reports = normalize_reports(st.session_state.get("confirmed_reports", []))
        log(f"Confirmed run set: {', '.join(selected_reports) if selected_reports else 'None'}")

        current_location = st.session_state.get("selected_location", "").strip()
        log(f"Main report location: {current_location or 'None'}")

        route_points = [
            st.session_state.get("trip_start", ""),
            st.session_state.get("trip_dest_1", ""),
            st.session_state.get("trip_dest_2", ""),
            st.session_state.get("trip_dest_3", ""),
        ]
        filtered_route_points = [p for p in route_points if p and str(p).strip()]
        log(f"Trip route at run: {route_label_from_points(route_points)}")

        all_files: list[str] = []
        email_location_label = current_location or "Unknown location"

        try:
            if "Trip Planner" in selected_reports:
                log("Trip Planner selected for this run")
                ok, msg, trip_files = trip_planner(
                    route_points=filtered_route_points,
                    fuel_type=st.session_state.get("trip_fuel_type", "Petrol"),
                    fuel_price=float(st.session_state.get("trip_fuel_price", 2.00)),
                )
                log(msg)
                if ok and trip_files:
                    all_files.extend(trip_files)
                else:
                    log("Trip Planner produced no valid PDF")

            non_trip_reports = [r for r in selected_reports if r != "Trip Planner"]

            locations = load_locations()

            if non_trip_reports:
                if not current_location:
                    log("No main location selected for non-trip reports")
                    st.error("Please select a main location for Surf / Sky / Weather reports.")
                else:
                    payload = locations.get(current_location, {})
                    if not payload:
                        log(f"Selected location not found in locations.json: {current_location}")
                        st.error("Selected location was not found. Please refresh and try again.")
                    else:
                        lat = float(payload["lat"])
                        lon = float(payload["lon"])
                        email_location_label = current_location
                        log(f"Resolved coords from locations.json: {lat}, {lon}")

                        for report in non_trip_reports:
                            before_count = len(all_files)

                            if report == "Surf Report":
                                log("Starting Surf Report worker")
                                files = run_worker("core.surf_worker", current_location, lat, lon, payload, run_dir)

                            elif report == "Sky & Moon Report":
                                log("Starting Sky & Moon Report worker")
                                files = run_sky_moon_report(current_location, lat, lon, payload, run_dir)

                            elif report == "Weather Report":
                                log("Starting Weather Report worker")
                                files = run_worker("core.weather_worker", current_location, lat, lon, payload, run_dir)

                            else:
                                files = []

                            if files:
                                log(f"{report} completed with {len(files)} PDF file(s)")
                            else:
                                log(f"{report} returned no PDF file(s)")

                            all_files.extend(files)

                            if len(all_files) == before_count:
                                log(f"No PDF captured for {report}")

            unique_files: list[str] = []
            for file_path in all_files:
                if file_path not in unique_files and valid_pdf(file_path):
                    unique_files.append(file_path)

            st.session_state["files"] = unique_files
            log(f"Total valid PDFs captured: {len(unique_files)}")

            if not unique_files:
                log("❌ NO REPORTS GENERATED — CHECK WORKER")
                st.error("No reports generated — see System progress below.")
            else:
                ok, message = send_reports(
                    st.session_state.get("user_email", "").strip(),
                    selected_reports,
                    email_location_label,
                    unique_files,
                )
                log(message)
                if ok:
                    st.success(f"Reports sent successfully ({len(unique_files)} PDF attachments)")
                    cleanup_generated_files(unique_files, run_dir)
                    st.session_state["files"] = []
                else:
                    st.error(message)

        except Exception as exc:
            log(f"RUN FAILED ❌ {exc}")
            st.error(f"Run failed: {exc}")
        finally:
            try:
                if Path(run_dir).exists():
                    shutil.rmtree(run_dir, ignore_errors=True)
            except Exception:
                pass

    if st.session_state.get("files"):
        st.markdown('<div class="panel-box"><div class="minor-heading">Generated files</div>', unsafe_allow_html=True)
        for item in st.session_state["files"]:
            st.write(item)
        st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
