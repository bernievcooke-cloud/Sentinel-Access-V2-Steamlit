#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib
import json
import os
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
USAGE_LOG_PATH = CONFIG / "usage_log.csv"

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

DEFAULT_ADMIN_PASSWORD = "admin123"


# =========================================================
# BASIC HELPERS
# =========================================================
def ensure_output_dir() -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)


def now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def soft_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def get_admin_password() -> str:
    try:
        secret_pw = st.secrets.get("ADMIN_PASSWORD")
        if secret_pw:
            return str(secret_pw)
    except Exception:
        pass
    return os.getenv("APP_STREAM_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)


def default_state() -> dict[str, Any]:
    return {
        "log": f"[{now_ts()}] SYSTEM READY",
        "files": [],
        "geo_results": [],
        "geo_choice": "",
        "show_geo_results": False,
        "confirmed_reports": [],
        "confirmed_signature": "",
        "selection_message": "",
        "location_after_save": "",
        "preview_report": "Not selected",
        "preview_location": "Not selected",
        "pending_reports": [],
        "report_surf": False,
        "report_sky_moon": False,
        "report_weather": False,
        "report_trip": False,
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
        "add_location_open": False,
        "system_progress_open": False,
        "admin_open": False,
        "location_message": "",
        "location_message_type": "info",
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


# =========================================================
# PDF / FILE HELPERS
# =========================================================
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
    run_root = Path(run_dir).resolve() if run_dir else None
    temp_root = Path(tempfile.gettempdir()).resolve()

    for file_path in file_paths:
        try:
            p = Path(file_path).resolve()
            if not p.exists() or not p.is_file():
                continue

            safe_to_delete = False
            if run_root:
                try:
                    p.relative_to(run_root)
                    safe_to_delete = True
                except ValueError:
                    pass

            if not safe_to_delete:
                try:
                    p.relative_to(temp_root)
                    safe_to_delete = True
                except ValueError:
                    pass

            if safe_to_delete:
                p.unlink()
                log(f"Removed temporary file: {p}")
            else:
                log(f"Kept non-temporary file: {p}")

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


# =========================================================
# LOCATION HELPERS
# =========================================================
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
                **(
                    {"surf_profile": payload.get("surf_profile")}
                    if payload.get("surf_profile") is not None
                    else {}
                ),
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
        except Exception as exc:
            log(f"LocationManager sync skipped: {exc}")


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


# =========================================================
# WORKER / EMAIL HELPERS
# =========================================================
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

    if module_name == "core.surf_worker":
        attempts = [
            (location_name, float(lat), float(lon)),
            (location_name, float(lat), float(lon), None),
        ]
    elif module_name == "core.weather_worker":
        attempts = [
            (location_name, float(lat), float(lon), log),
            (location_name, float(lat), float(lon), output_dir),
            (location_name, float(lat), float(lon)),
            (location_name, [float(lat), float(lon)], output_dir, log),
            (location_name, [float(lat), float(lon)], output_dir),
            (location_name, [float(lat), float(lon)]),
        ]
    else:
        attempts = [
            (location_name, [float(lat), float(lon)], output_dir, log),
            (location_name, [float(lat), float(lon)], output_dir),
            (location_name, [float(lat), float(lon)], log),
            (location_name, [float(lat), float(lon)]),
            (location_name, float(lat), float(lon), output_dir, log),
            (location_name, float(lat), float(lon), output_dir),
            (location_name, float(lat), float(lon), log),
            (location_name, float(lat), float(lon)),
        ]

    for args in attempts:
        try:
            before_files = set(scan_dir(run_dir or output_dir))
            result = generate(*args)

            files = extract_pdf_paths(result)
            if not files:
                files = collect_new_pdfs(before_files, run_dir or output_dir)

            valid_files = [f for f in files if valid_pdf(f)]
            if valid_files:
                for file_path in valid_files:
                    log(f"PDF OK: {file_path}")
                return valid_files

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
    except Exception as exc:
        return False, f"Trip error: {exc}", []


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
            return True, "Email sent successfully ✅"
        except TypeError:
            continue
        except Exception as exc:
            return False, f"EMAIL ERROR: {exc}"

    return False, "Email sender found, but no compatible send function matched."


# =========================================================
# USAGE LOG HELPERS
# =========================================================
def append_usage_log(user_name: str, user_email: str, report_type: str, location_info: str) -> None:
    ensure_output_dir()
    exists = os.path.exists(USAGE_LOG_PATH)
    with open(USAGE_LOG_PATH, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if not exists:
            writer.writerow(["timestamp", "user_name", "user_email", "report_type", "location_info"])
        writer.writerow(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_name.strip(),
                user_email.strip(),
                report_type.strip(),
                location_info.strip(),
            ]
        )


def read_usage_log() -> list[dict[str, str]]:
    if not os.path.exists(USAGE_LOG_PATH):
        return []
    try:
        with open(USAGE_LOG_PATH, "r", newline="", encoding="utf-8") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    except Exception:
        return []


def usage_summary(rows: list[dict[str, str]]):
    report_counts: dict[str, int] = {}
    location_counts: dict[str, int] = {}
    for row in rows:
        report = str(row.get("report_type", "")).strip() or "(blank)"
        location = str(row.get("location_info", "")).strip() or "(blank)"
        report_counts[report] = report_counts.get(report, 0) + 1
        location_counts[location] = location_counts.get(location, 0) + 1
    return (
        sorted(report_counts.items(), key=lambda x: (-x[1], x[0].lower())),
        sorted(location_counts.items(), key=lambda x: (-x[1], x[0].lower())),
    )


# =========================================================
# UI HELPERS
# =========================================================
def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #dceaf7 0%, #eaf2fb 100%);
        }

        .block-container {
            max-width: 920px;
            padding-top: 2.0rem;
            padding-bottom: 1.4rem;
        }

        .title-wrap {
            background: #ffffff;
            border: 1px solid #bfd3e6;
            border-radius: 18px;
            padding: 1.05rem 1.1rem;
            margin-top: 0.35rem;
            margin-bottom: 0.85rem;
            box-shadow: 0 4px 16px rgba(23, 50, 77, 0.08);
        }

        .title-main {
            font-size: 2rem;
            font-weight: 800;
            color: #17324D;
            line-height: 1.1;
        }

        .panel-box,
        .button-row {
            background: transparent;
            border: none;
            border-radius: 0;
            padding: 0;
            margin-bottom: 0.75rem;
            box-shadow: none;
        }

        .compact-box {
            background: #f8fbff;
            border: 1px solid #d5e2ef;
            border-radius: 14px;
            padding: 0.6rem 0.8rem;
            margin-bottom: 0.55rem;
        }

        .compact-label {
            font-size: 0.72rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #4b6785;
            margin-bottom: 0.18rem;
        }

        .compact-value {
            font-size: 0.96rem;
            font-weight: 800;
            color: #17324D;
            line-height: 1.25;
        }

        .minor-heading {
            font-size: 0.92rem;
            font-weight: 800;
            color: #284866;
            margin: 0.08rem 0 0.35rem 0;
        }

        .button-note {
            font-size: 0.82rem;
            color: #5a7693;
            margin-top: 0.5rem;
        }

        label, p, div {
            color: #17324D;
        }

        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        div[data-baseweb="select"] > div,
        .stMultiSelect [data-baseweb="select"] > div {
            background-color: #ffffff !important;
            color: #17324D !important;
            border-radius: 12px !important;
        }

        .stTextArea textarea {
            font-family: Consolas, "Courier New", monospace !important;
            font-size: 0.90rem !important;
            line-height: 1.45 !important;
            border: 1px solid #b8cada !important;
            box-shadow: inset 0 1px 2px rgba(23, 50, 77, 0.04) !important;
            color: #0b1f33 !important;
            font-weight: 700 !important;
        }

        .stButton button {
            height: 2.7rem;
            border-radius: 12px !important;
            font-weight: 800 !important;
            border: 1px solid #b8ccdf !important;
            background: linear-gradient(180deg, #f8fbff 0%, #edf4fb 100%) !important;
            color: #17324D !important;
            box-shadow: 0 2px 8px rgba(23, 50, 77, 0.05);
        }

        .stButton button:hover {
            border-color: #9eb8d1 !important;
            background: linear-gradient(180deg, #ffffff 0%, #eef5fc 100%) !important;
            color: #17324D !important;
        }

        .green-ready .stButton button,
        .green-ready button {
            background: linear-gradient(135deg, #1FAA63, #159251) !important;
            color: #ffffff !important;
            border: 1px solid #14874b !important;
            box-shadow: 0 6px 16px rgba(31, 170, 99, 0.22) !important;
        }

        .green-ready .stButton button:hover,
        .green-ready button:hover {
            background: linear-gradient(135deg, #24b56c, #179a56) !important;
            color: #ffffff !important;
            border: 1px solid #14874b !important;
        }

        @media (max-width: 768px) {
            .title-main {
                font-size: 1.65rem;
            }
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


def sync_report_flags_from_pending_reports() -> None:
    reports = set(normalize_reports(st.session_state.get("pending_reports", [])))
    st.session_state["report_surf"] = "Surf Report" in reports
    st.session_state["report_sky_moon"] = "Sky & Moon Report" in reports
    st.session_state["report_weather"] = "Weather Report" in reports
    st.session_state["report_trip"] = "Trip Planner" in reports


def sync_pending_reports_from_flags() -> list[str]:
    selected: list[str] = []
    if st.session_state.get("report_surf", False):
        selected.append("Surf Report")
    if st.session_state.get("report_sky_moon", False):
        selected.append("Sky & Moon Report")
    if st.session_state.get("report_weather", False):
        selected.append("Weather Report")
    if st.session_state.get("report_trip", False):
        selected.append("Trip Planner")
    st.session_state["pending_reports"] = selected
    return selected


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


# =========================================================
# MAIN APP
# =========================================================
def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="centered")
    init_state()
    apply_styles()

    locations = load_locations()
    location_names = list(locations.keys())

    pending_location = st.session_state.get("location_after_save", "")
    if pending_location and pending_location in location_names:
        st.session_state["selected_location"] = pending_location
        st.session_state["location_after_save"] = ""

    pending_reports_preview = sync_pending_reports_from_flags()
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
    form_ready = bool(normal_ready and trip_ready)

    current_signature = json.dumps(
        {
            "reports": normalize_reports(st.session_state.get("pending_reports", [])),
            "selected_location": st.session_state.get("selected_location", "").strip(),
            "trip_start": st.session_state.get("trip_start", "").strip(),
            "trip_dest_1": st.session_state.get("trip_dest_1", "").strip(),
            "trip_dest_2": st.session_state.get("trip_dest_2", "").strip(),
            "trip_dest_3": st.session_state.get("trip_dest_3", "").strip(),
            "trip_fuel_type": st.session_state.get("trip_fuel_type", "Petrol"),
            "trip_fuel_price": str(st.session_state.get("trip_fuel_price", 2.00)),
            "user_name": st.session_state.get("user_name", "").strip(),
            "user_email": st.session_state.get("user_email", "").strip(),
        },
        sort_keys=True,
    )

    can_generate = form_ready

    render_title()

    search_location_clicked = False
    save_location_clicked = False
    refresh_clicked = False
    generate_clicked = False
    clear_log_clicked = False
    unlock_admin_clicked = False
    lock_admin_clicked = False

    with st.container():
        st.markdown('<div class="panel-box">', unsafe_allow_html=True)
        st.text_input("Name (required field)", key="user_name")
        st.text_input("User email (required field)", key="user_email")
        st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="panel-box">', unsafe_allow_html=True)
        st.markdown('<div class="minor-heading">Select reports (required field)</div>', unsafe_allow_html=True)
        report_col1, report_col2 = st.columns(2, gap="small")
        with report_col1:
            st.checkbox("Surf Report", key="report_surf")
            st.checkbox("Sky & Moon Report", key="report_sky_moon")
        with report_col2:
            st.checkbox("Weather Report", key="report_weather")
            st.checkbox("Trip Planner", key="report_trip")

        pending_reports_live = sync_pending_reports_from_flags()
        pending_trip_mode = "Trip Planner" in pending_reports_live
        pending_standard_mode = any(
            r in pending_reports_live for r in ["Surf Report", "Sky & Moon Report", "Weather Report"]
        )
        st.session_state["preview_report"] = ", ".join(pending_reports_live) if pending_reports_live else "Not selected"
        info_box("Selected report", st.session_state.get("preview_report", "Not selected"))
        st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="panel-box">', unsafe_allow_html=True)

        if pending_standard_mode or not pending_trip_mode:
            location_options = location_names if location_names else [""]
            current_loc = st.session_state.get("selected_location", "")
            if current_loc not in location_options and current_loc != "":
                st.session_state["selected_location"] = ""

            st.selectbox(
                "Select location (required field — type to search)",
                location_options,
                key="selected_location",
            )

        selected_normal_location = st.session_state.get("selected_location", "").strip()

        if pending_trip_mode:
            trip_location_options = [""] + location_names if location_names else [""]
            st.markdown('<div class="minor-heading">Trip settings</div>', unsafe_allow_html=True)
            st.selectbox("Start location (required field)", trip_location_options, key="trip_start")
            st.selectbox("Destination 1 (required field)", trip_location_options, key="trip_dest_1")
            st.selectbox("Destination 2 (required field)", trip_location_options, key="trip_dest_2")
            st.selectbox("Destination 3 (required field)", trip_location_options, key="trip_dest_3")
            st.selectbox("Fuel type (required field)", ["Petrol", "Diesel"], key="trip_fuel_type")
            st.selectbox(
                "Fuel price per litre (required field)",
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

        location_label = " | ".join(preview_parts) if preview_parts else "Not selected"
        st.session_state["preview_location"] = location_label
        info_box("Selected location(s)", st.session_state.get("preview_location", "Not selected"))
        st.markdown("</div>", unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="button-row">', unsafe_allow_html=True)
        btn_col1, btn_col2 = st.columns([1, 1], gap="small")

        with btn_col1:
            refresh_clicked = st.button("Refresh Page", use_container_width=True)

        with btn_col2:
            if can_generate:
                st.markdown('<div class="green-ready">', unsafe_allow_html=True)
            generate_clicked = st.button(
                "Generate Reports",
                use_container_width=True,
                disabled=not can_generate,
            )
            if can_generate:
                st.markdown("</div>", unsafe_allow_html=True)

        if not form_ready:
            st.markdown(
                '<div class="button-note">Complete all required fields.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="button-note">Selections are ready. Press <b>Generate Reports</b> to run.</div>',
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Add new location", expanded=st.session_state.get("add_location_open", False)):
        st.markdown('<div class="panel-box">', unsafe_allow_html=True)
        info_box("Add new location", "Search and save new locations for reports")
        if st.session_state.get("location_message"):
            msg = st.session_state.get("location_message", "")
            msg_type = st.session_state.get("location_message_type", "info")
            if msg_type == "success":
                st.success(msg)
            elif msg_type == "warning":
                st.warning(msg)
            elif msg_type == "error":
                st.error(msg)
            else:
                st.info(msg)
        st.text_input("Location name", key="new_location_name")
        st.selectbox(
            "State (required field)",
            list(STATE_MAP.keys()),
            key="new_location_state",
        )

        loc_btn1, loc_btn2 = st.columns(2, gap="small")
        with loc_btn1:
            search_location_clicked = st.button("Search Location", use_container_width=True)
        with loc_btn2:
            save_location_clicked = st.button("Save Selected Location", use_container_width=True)

        if st.session_state.get("show_geo_results", False):
            geo_results = st.session_state.get("geo_results", [])
            if geo_results:
                option_labels = [
                    f"{item['name']} ({item['state']}) — {float(item['lat']):.5f}, {float(item['lon']):.5f}"
                    for item in geo_results
                ]
                current_choice = st.session_state.get("geo_choice", "")
                if option_labels and current_choice not in option_labels:
                    st.session_state["geo_choice"] = option_labels[0]
                st.selectbox(
                    "Select match (required field)",
                    option_labels,
                    key="geo_choice",
                )
            else:
                st.session_state["show_geo_results"] = False
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("System progress", expanded=st.session_state.get("system_progress_open", False)):
        st.markdown('<div class="panel-box">', unsafe_allow_html=True)
        st.markdown('<div class="minor-heading">System progress</div>', unsafe_allow_html=True)
        st.text_area(
            "System Progress",
            value=st.session_state.get("log", ""),
            height=300,
            disabled=True,
            label_visibility="collapsed",
        )
        clear_log_clicked = st.button("Clear progress", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Admin function", expanded=st.session_state.get("admin_open", False)):
        st.markdown('<div class="panel-box">', unsafe_allow_html=True)
        info_box("Admin function", "Usage logs and controls")
        st.text_input("Admin password", type="password", key="admin_password")
        unlock_admin_clicked = st.button("Unlock Admin", use_container_width=True)

        if st.session_state.get("admin_unlocked"):
            st.success("Admin unlocked")
            lock_admin_clicked = st.button("Lock Admin", use_container_width=True)

            rows = read_usage_log()
            if rows:
                report_counts, location_counts = usage_summary(rows)
                st.markdown('<div class="minor-heading">Usage log</div>', unsafe_allow_html=True)
                st.dataframe(rows, use_container_width=True)

                st.markdown('<div class="minor-heading">Report summary</div>', unsafe_allow_html=True)
                for label, count in report_counts:
                    st.write(f"{label}: {count}")

                st.markdown('<div class="minor-heading">Location summary</div>', unsafe_allow_html=True)
                for label, count in location_counts:
                    st.write(f"{label}: {count}")
            else:
                st.info("No usage data yet")
        st.markdown("</div>", unsafe_allow_html=True)

    if search_location_clicked:
        st.session_state["add_location_open"] = True
        st.session_state["location_message"] = ""
        st.session_state["location_message_type"] = "info"
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
            st.session_state["location_message"] = f"{len(geo_results)} match(es) found. Choose one, then save it."
            st.session_state["location_message_type"] = "success"
            log("Location search complete: matches ready for selection")
        else:
            st.session_state["geo_choice"] = ""
            st.session_state["show_geo_results"] = False
            st.session_state["location_message"] = "No matches found. Try a different spelling or state."
            st.session_state["location_message_type"] = "warning"
            log("Location search complete: no matches found")
        st.rerun()

    if save_location_clicked:
        st.session_state["add_location_open"] = True
        geo_results = st.session_state.get("geo_results", [])
        if not geo_results:
            st.session_state["location_message"] = "Search first, then choose a match to save."
            st.session_state["location_message_type"] = "warning"
            log("Save location blocked: no search results available")
        else:
            option_labels = [
                f"{item['name']} ({item['state']}) — {float(item['lat']):.5f}, {float(item['lon']):.5f}"
                for item in geo_results
            ]
            selected_match = st.session_state.get("geo_choice", "")
            if selected_match not in option_labels:
                st.session_state["location_message"] = "Please choose a match to save."
                st.session_state["location_message_type"] = "warning"
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
                st.session_state["location_message"] = f"Location saved: {chosen['name']}"
                st.session_state["location_message_type"] = "success"
                log(f"Location saved: {chosen['name']} ({chosen['state']})")
        st.rerun()

    if st.session_state.get("selection_message"):
        st.info(st.session_state["selection_message"])

    if clear_log_clicked:
        st.session_state["system_progress_open"] = True
        st.session_state["log"] = f"[{now_ts()}] SYSTEM READY"
        st.rerun()

    if unlock_admin_clicked:
        st.session_state["admin_open"] = True
        if st.session_state.get("admin_password", "") == get_admin_password():
            st.session_state["admin_unlocked"] = True
            log("Admin unlocked")
        else:
            st.error("Incorrect admin password")
            log("Admin unlock failed")
        st.rerun()

    if lock_admin_clicked:
        st.session_state["admin_open"] = True
        st.session_state["admin_unlocked"] = False
        st.session_state["admin_password"] = ""
        log("Admin locked")
        st.rerun()

    if refresh_clicked:
        reset_app_state()
        st.rerun()

    if generate_clicked:
        st.session_state["system_progress_open"] = True
        st.session_state["files"] = []
        st.session_state["log"] = ""
        log("RUN START ✅")

        run_dir = make_run_dir()
        log(f"Temporary run folder: {run_dir}")

        selected_reports = normalize_reports(st.session_state.get("pending_reports", []))
        log(f"Selected run set: {', '.join(selected_reports) if selected_reports else 'None'}")

        current_location = st.session_state.get("selected_location", "").strip()
        log(f"Main report location: {current_location or 'None'}")

        route_points = [
            st.session_state.get("trip_start", ""),
            st.session_state.get("trip_dest_1", ""),
            st.session_state.get("trip_dest_2", ""),
            st.session_state.get("trip_dest_3", ""),
        ]
        filtered_route_points = [p for p in route_points if p and str(p).strip()]
        log(f"Trip route at run: {route_label_from_points(filtered_route_points)}")

        all_files: list[str] = []

        try:
            for report in selected_reports:
                if report == "Trip Planner":
                    log("Trip Planner selected for this run")
                    ok, msg, out_files = trip_planner(
                        filtered_route_points,
                        st.session_state.get("trip_fuel_type", "Petrol"),
                        float(st.session_state.get("trip_fuel_price", 2.00)),
                    )
                    log(msg)
                    if ok and out_files:
                        all_files.extend([f for f in out_files if valid_pdf(f)])
                    continue

                if not current_location:
                    log(f"{report} skipped: no location selected")
                    continue

                location_payload = locations.get(current_location, {})
                lat = location_payload.get("lat")
                lon = location_payload.get("lon")

                if lat is None or lon is None:
                    log(f"{report} skipped: invalid coordinates for {current_location}")
                    continue

                log(f"Resolved coords from locations.json: {lat}, {lon}")

                if report == "Surf Report":
                    log(f"Running Surf Report for {current_location}")
                    out_files = run_worker("core.surf_worker", current_location, float(lat), float(lon), run_dir=run_dir)
                    all_files.extend(out_files)

                elif report == "Sky & Moon Report":
                    log(f"Running Sky & Moon Report for {current_location}")
                    out_files = run_sky_moon_report(current_location, float(lat), float(lon), run_dir=run_dir)
                    all_files.extend(out_files)

                elif report == "Weather Report":
                    log(f"Running Weather Report for {current_location}")
                    out_files = run_worker("core.weather_worker", current_location, float(lat), float(lon), run_dir=run_dir)
                    all_files.extend(out_files)

            unique_files: list[str] = []
            for f in all_files:
                if valid_pdf(f) and f not in unique_files:
                    unique_files.append(f)

            st.session_state["files"] = unique_files

            if not unique_files:
                log("No valid PDF attachments were generated.")
                st.error("No valid PDF attachments were generated.")
                cleanup_generated_files(unique_files, run_dir)
                st.rerun()

            email = st.session_state.get("user_email", "").strip()
            if not email:
                log("No email provided.")
                st.error("No email provided.")
                cleanup_generated_files(unique_files, run_dir)
                st.rerun()

            ok, msg = send_reports(email, selected_reports, current_location or "Trip Planner", unique_files)
            log(msg)

            if ok:
                user_name = st.session_state.get("user_name", "").strip()
                report_label = ", ".join(selected_reports)
                location_label = st.session_state.get("preview_location", "Not selected")
                append_usage_log(user_name, email, report_label, location_label)
                st.success("Reports generated and emailed successfully.")
            else:
                st.error(msg)

        except Exception as exc:
            log(f"REPORT FAILED ❌ {exc}")
            st.error(f"Report run failed: {exc}")

        finally:
            cleanup_generated_files(st.session_state.get("files", []), run_dir)

        st.rerun()


if __name__ == "__main__":
    main()
