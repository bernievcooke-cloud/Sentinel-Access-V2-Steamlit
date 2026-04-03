
#!/usr/bin/env python3
from __future__ import annotations

import importlib
import inspect
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
import requests
import streamlit as st

APP_TITLE = "Sentinel Access Pro"
APP_SUBTITLE = "Premium report delivery dashboard"

REPORT_OPTIONS = [
    "Surf Report",
    "Sky Report",
    "Moon Events Report",
    "Sky & Moon Report",
    "Weather Report",
    "Trip Report",
]

STATE_OPTIONS = ["VIC", "NSW", "QLD", "SA", "WA", "TAS", "NT", "ACT"]
STATE_TO_ADMIN1 = {
    "VIC": "Victoria",
    "NSW": "New South Wales",
    "QLD": "Queensland",
    "SA": "South Australia",
    "WA": "Western Australia",
    "TAS": "Tasmania",
    "NT": "Northern Territory",
    "ACT": "Australian Capital Territory",
}

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = ROOT_DIR / "config"
LOCATIONS_FILE = CONFIG_DIR / "locations.json"
OUTPUTS_DIR = ROOT_DIR / "outputs"
DEFAULT_TZ = "Australia/Melbourne"


def now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log_progress(message: str) -> None:
    line = f"[{now_ts()}] {message}"
    current = st.session_state.get("progress_log", "")
    st.session_state["progress_log"] = f"{current}\n{line}".strip()
    st.session_state["last_status"] = message


def soft_import(module_name: str):
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_name(value: str) -> str:
    return " ".join((value or "").replace("_", " ").replace("-", " ").split()).casefold()


def load_locations() -> dict[str, dict[str, float]]:
    ensure_dirs()
    if not LOCATIONS_FILE.exists():
        return {}
    try:
        data = json.loads(LOCATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    locations: dict[str, dict[str, float]] = {}
    if isinstance(data, dict):
        for name, payload in data.items():
            if isinstance(payload, dict):
                lat = payload.get("lat") if payload.get("lat") is not None else payload.get("latitude")
                lon = payload.get("lon") if payload.get("lon") is not None else payload.get("longitude")
                state = payload.get("state", "")
                surf_profile = payload.get("surf_profile")
                if lat is not None and lon is not None:
                    locations[str(name)] = {
                        "lat": float(lat),
                        "lon": float(lon),
                        "state": str(state or ""),
                        **({"surf_profile": surf_profile} if surf_profile is not None else {}),
                    }
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("location") or "").strip()
            lat = item.get("lat") if item.get("lat") is not None else item.get("latitude")
            lon = item.get("lon") if item.get("lon") is not None else item.get("longitude")
            state = item.get("state", "")
            surf_profile = item.get("surf_profile")
            if name and lat is not None and lon is not None:
                locations[name] = {
                    "lat": float(lat),
                    "lon": float(lon),
                    "state": str(state or ""),
                    **({"surf_profile": surf_profile} if surf_profile is not None else {}),
                }
    return dict(sorted(locations.items(), key=lambda kv: kv[0].casefold()))


def save_locations(locations: dict[str, dict[str, float]]) -> None:
    ensure_dirs()
    ordered = dict(sorted(locations.items(), key=lambda kv: kv[0].casefold()))
    LOCATIONS_FILE.write_text(json.dumps(ordered, indent=2), encoding="utf-8")


def resolve_location(name: str, locations: dict[str, dict[str, float]]) -> tuple[float | None, float | None, dict[str, Any] | None]:
    target = _normalize_name(name)
    for loc_name, payload in locations.items():
        if _normalize_name(loc_name) == target:
            return payload.get("lat"), payload.get("lon"), payload
    return None, None, None


def save_location_entry(name: str, lat: float, lon: float, state: str, surf_profile: str | None = None) -> tuple[bool, str]:
    locations = load_locations()
    clean_name = " ".join((name or "").split())
    if not clean_name:
        return False, "Location name is empty."
    for existing_name in locations:
        if _normalize_name(existing_name) == _normalize_name(clean_name):
            return False, f"Location already exists as '{existing_name}'."

    locations[clean_name] = {
        "lat": float(lat),
        "lon": float(lon),
        "state": state,
        **({"surf_profile": surf_profile} if surf_profile else {}),
    }
    save_locations(locations)

    lm_mod = soft_import("core.location_manager")
    if lm_mod and hasattr(lm_mod, "LocationManager"):
        try:
            manager = lm_mod.LocationManager(str(LOCATIONS_FILE))
            if hasattr(manager, "add_location"):
                try:
                    manager.add_location(clean_name, float(lat), float(lon), state=state, surf_profile=surf_profile)
                except TypeError:
                    manager.add_location(clean_name, float(lat), float(lon))
        except Exception:
            pass

    return True, f"Saved {clean_name} ({state}) to locations.json"


def geocode_au_location(place_name: str, state_code: str) -> tuple[bool, str, list[dict[str, Any]]]:
    clean_place = " ".join((place_name or "").split())
    if not clean_place:
        return False, "Enter a location name first.", []

    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": clean_place,
        "count": 10,
        "language": "en",
        "format": "json",
        "countryCode": "AU",
    }
    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return False, f"Geocoding failed: {exc}", []

    results = payload.get("results") or []
    admin1_target = STATE_TO_ADMIN1.get(state_code, "").casefold()
    filtered: list[dict[str, Any]] = []
    for item in results:
        admin1 = str(item.get("admin1") or "").casefold()
        country = str(item.get("country_code") or "").upper()
        if country != "AU":
            continue
        if admin1_target and admin1_target != admin1:
            continue
        filtered.append({
            "name": item.get("name"),
            "admin1": item.get("admin1"),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
        })

    if not filtered:
        return False, f"No AU geocoding matches found for {clean_place} in {state_code}.", []

    return True, f"Found {len(filtered)} match(es) for {clean_place}.", filtered


def import_worker(module_name: str):
    mod = soft_import(module_name)
    if mod is None:
        log_progress(f"{module_name} not available.")
    return mod


def file_list_from_result(result: Any) -> list[str]:
    files: list[str] = []

    def _walk(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, (str, os.PathLike)):
            files.append(str(value))
            return
        if isinstance(value, dict):
            for v in value.values():
                _walk(v)
            return
        if isinstance(value, (list, tuple, set)):
            for v in value:
                _walk(v)

    _walk(result)
    seen = []
    for f in files:
        path = str(f)
        if path not in seen:
            seen.append(path)
    return seen


def valid_output_files(items: Iterable[str]) -> list[str]:
    valid: list[str] = []
    for item in items:
        try:
            path = Path(item)
            if not path.exists():
                log_progress(f"Attachment path not found: {path}")
                continue
            if not path.is_file():
                log_progress(f"Attachment path is not a file: {path}")
                continue
            if path.suffix.lower() != ".pdf":
                log_progress(f"Attachment ignored (not PDF): {path}")
                continue
            if path.stat().st_size <= 1000:
                log_progress(f"Attachment too small: {path} ({path.stat().st_size} bytes)")
                continue
            valid.append(str(path))
        except Exception as exc:
            log_progress(f"Attachment validation error: {exc}")
            continue
    return valid


def call_generate_report(mod, call_variants: list[tuple], report_name: str) -> list[str]:
    if not mod or not hasattr(mod, "generate_report"):
        log_progress(f"{report_name} worker not available.")
        return []

    generate = getattr(mod, "generate_report")
    last_error: Exception | None = None

    def newest_pdfs(limit_seconds: int = 180) -> list[str]:
        try:
            now = datetime.now().timestamp()
            candidates = []
            for p in OUTPUTS_DIR.glob("*.pdf"):
                try:
                    if p.is_file() and p.stat().st_size > 1000:
                        age = now - p.stat().st_mtime
                        if age <= limit_seconds:
                            candidates.append((p.stat().st_mtime, str(p)))
                except Exception:
                    continue
            candidates.sort(reverse=True)
            return [path for _, path in candidates]
        except Exception:
            return []

    for args in call_variants:
        try:
            result = generate(*args)

            # 1) Normal path extraction from returned value
            files = valid_output_files(file_list_from_result(result))
            if files:
                for f in files:
                    log_progress(f"{report_name} PDF OK: {f}")
                return files

            # 2) Fallback: worker may have written file to outputs/ without returning it cleanly
            fallback_files = newest_pdfs()
            if fallback_files:
                for f in fallback_files:
                    log_progress(f"{report_name} PDF OK (fallback): {f}")
                return fallback_files

            maybe = file_list_from_result(result)
            if maybe:
                log_progress(f"{report_name} returned non-valid file paths: {maybe}")

        except TypeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            log_progress(f"{report_name} failed: {exc}")
            break

    if last_error:
        log_progress(f"{report_name} failed: {last_error}")
    return []


def run_surf_report(location_name: str, lat: float, lon: float, loc_payload: dict[str, Any] | None) -> list[str]:
    mod = import_worker("core.surf_worker")
    surf_profile = None if not loc_payload else loc_payload.get("surf_profile")
    variants = [
        (location_name, [lat, lon, surf_profile], str(OUTPUTS_DIR), log_progress),
        (location_name, [lat, lon, surf_profile], str(OUTPUTS_DIR)),
        (location_name, [lat, lon], str(OUTPUTS_DIR), log_progress),
        (location_name, [lat, lon], str(OUTPUTS_DIR)),
        (location_name, lat, lon, str(OUTPUTS_DIR), log_progress),
        (location_name, lat, lon, str(OUTPUTS_DIR)),
    ]
    return call_generate_report(mod, variants, "Surf Report")


def run_sky_report(location_name: str, lat: float, lon: float) -> list[str]:
    mod = import_worker("core.sky_worker")
    variants = [
        (location_name, [lat, lon], str(OUTPUTS_DIR), log_progress),
        (location_name, [lat, lon], str(OUTPUTS_DIR)),
        (location_name, lat, lon, str(OUTPUTS_DIR), log_progress),
        (location_name, lat, lon, str(OUTPUTS_DIR)),
    ]
    return call_generate_report(mod, variants, "Sky Report")


def run_moon_report(location_name: str, lat: float, lon: float) -> list[str]:
    mod = import_worker("core.moon_events_worker")
    variants = [
        (location_name, [lat, lon], str(OUTPUTS_DIR), log_progress),
        (location_name, [lat, lon], str(OUTPUTS_DIR)),
        (location_name, lat, lon, str(OUTPUTS_DIR), log_progress),
        (location_name, lat, lon, str(OUTPUTS_DIR)),
    ]
    return call_generate_report(mod, variants, "Moon Events Report")


def run_weather_report(location_name: str, lat: float, lon: float) -> list[str]:
    mod = import_worker("core.weather_worker")
    variants = [
        (location_name, [lat, lon], str(OUTPUTS_DIR), log_progress),
        (location_name, [lat, lon], str(OUTPUTS_DIR)),
        (location_name, lat, lon, str(OUTPUTS_DIR), log_progress),
        (location_name, lat, lon, str(OUTPUTS_DIR)),
    ]
    return call_generate_report(mod, variants, "Weather Report")


def run_trip_report(trip_payload: dict[str, Any]) -> list[str]:
    mod = import_worker("core.trip_worker")
    variants = [
        (trip_payload, str(OUTPUTS_DIR), log_progress),
        (trip_payload, str(OUTPUTS_DIR)),
        (trip_payload,),
    ]
    return call_generate_report(mod, variants, "Trip Report")


def send_reports_by_email(
    recipient_name: str,
    recipient_email: str,
    report_labels: list[str],
    location_summary: str,
    file_paths: list[str],
) -> tuple[bool, str]:
    email_mod = soft_import("core.email_sender")
    if not email_mod:
        return False, "Email sender not available."

    subject = f"Sentinel Access — {', '.join(report_labels)} — {location_summary}"
    body = (
        f"Hello {recipient_name},\n\n"
        f"Your Sentinel Access report request is complete.\n\n"
        f"Reports: {', '.join(report_labels)}\n"
        f"Location: {location_summary}\n\n"
        f"Regards,\nSentinel Access"
    )

    # Try the most likely signatures first
    candidates: list[tuple[str, tuple, dict]] = [
        # Common wrapper styles
        ("send_email", (), {
            "recipient_name": recipient_name,
            "recipient_email": recipient_email,
            "subject": subject,
            "body": body,
            "attachments": file_paths,
        }),
        ("send_email", (), {
            "user_name": recipient_name,
            "user_email": recipient_email,
            "subject": subject,
            "body": body,
            "attachments": file_paths,
        }),
        ("send_email", (), {
            "to_email": recipient_email,
            "subject": subject,
            "body": body,
            "attachments": file_paths,
        }),
        ("send_email", (), {
            "recipient_email": recipient_email,
            "subject": subject,
            "body": body,
            "attachments": file_paths,
        }),

        # Report-specific wrappers
        ("send_report_email", (), {
            "recipient_name": recipient_name,
            "recipient_email": recipient_email,
            "subject": subject,
            "body": body,
            "attachments": file_paths,
        }),
        ("send_report_email", (), {
            "user_name": recipient_name,
            "user_email": recipient_email,
            "subject": subject,
            "body": body,
            "attachments": file_paths,
        }),
        ("send_report_email", (), {
            "to_email": recipient_email,
            "subject": subject,
            "body": body,
            "attachments": file_paths,
        }),
        ("send_report_email", (), {
            "recipient_email": recipient_email,
            "subject": subject,
            "body": body,
            "attachments": file_paths,
        }),

        # Positional fallbacks
        ("send_email", (recipient_name, recipient_email, subject, body, file_paths), {}),
        ("send_report_email", (recipient_name, recipient_email, subject, body, file_paths), {}),
        ("send_email", (recipient_email, subject, body, file_paths), {}),
        ("send_report_email", (recipient_email, subject, body, file_paths), {}),
    ]

    errors: list[str] = []

    for func_name, args, kwargs in candidates:
        fn = getattr(email_mod, func_name, None)
        if not callable(fn):
            continue
        try:
            result = fn(*args, **kwargs)
            if result is False:
                errors.append(f"{func_name} returned False")
                continue
            return True, f"Email OK: sent to {recipient_email}"
        except TypeError as exc:
            errors.append(f"{func_name} TypeError: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{func_name} ERROR: {exc}")
            continue

    if errors:
        return False, "Email ERROR: " + " | ".join(errors[:3])

    return False, "Email sender found, but no compatible send function matched."

    for func_name, args, kwargs in candidates:
        fn = getattr(email_mod, func_name, None)
        if not callable(fn):
            continue
        try:
            result = fn(*args, **kwargs)
            if result is False:
                continue
            return True, f"Email OK: sent to {recipient_email}"
        except TypeError:
            continue
        except Exception as exc:
            return False, f"Email ERROR: {exc}"

    for func_name in ("send_report_email", "send_email"):
        fn = getattr(email_mod, func_name, None)
        if not callable(fn):
            continue
        try:
            sig = inspect.signature(fn)
            params = list(sig.parameters)
            dynamic_kwargs: dict[str, Any] = {}
            for name in params:
                lname = name.lower()
                if lname in {"recipient_email", "to_email", "email", "to"}:
                    dynamic_kwargs[name] = recipient_email
                elif lname == "subject":
                    dynamic_kwargs[name] = subject
                elif lname in {"body", "message", "content"}:
                    dynamic_kwargs[name] = body
                elif lname in {"attachments", "files", "file_paths"}:
                    dynamic_kwargs[name] = file_paths
                elif lname in {"recipient_name", "name", "user_name"}:
                    dynamic_kwargs[name] = recipient_name
            if dynamic_kwargs:
                result = fn(**dynamic_kwargs)
                if result is False:
                    continue
                return True, f"Email OK: sent to {recipient_email}"
        except Exception as exc:
            return False, f"Email ERROR: {exc}"

    return False, "Email sender found, but no compatible send function matched."


def init_state() -> None:
    defaults = {
        "progress_log": f"[{now_ts()}] SYSTEM READY",
        "last_status": "System ready",
        "generated_files": [],
        "email_status": "",
        "geo_matches": [],
        "geo_message": "",
        "saved_location_notice": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def premium_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --sentinel-bg-1: #dde8f3;
            --sentinel-bg-2: #edf4fb;
            --sentinel-card: rgba(255,255,255,0.90);
            --sentinel-card-strong: rgba(255,255,255,0.98);
            --sentinel-border: rgba(21,67,122,0.12);
            --sentinel-text: #16324f;
            --sentinel-muted: #5f7690;
            --sentinel-green: #26c281;
            --sentinel-cyan: #42c5ff;
            --sentinel-gold: #ffd166;
            --sentinel-shadow: 0 12px 28px rgba(26,57,88,0.08);
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(66,197,255,0.10), transparent 24%),
                radial-gradient(circle at top right, rgba(38,194,129,0.08), transparent 21%),
                linear-gradient(180deg, var(--sentinel-bg-2) 0%, var(--sentinel-bg-1) 100%);
        }

        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }

        h1, h2, h3, h4, h5, h6, p, label, div, span {
            letter-spacing: 0.01em;
        }

        .hero {
            background: linear-gradient(135deg, rgba(255,255,255,0.11), rgba(255,255,255,0.05));
            border: 1px solid var(--sentinel-border);
            box-shadow: var(--sentinel-shadow);
            border-radius: 22px;
            padding: 1.15rem 1.25rem 1rem 1.25rem;
            margin-bottom: 0.9rem;
            backdrop-filter: blur(10px);
        }

        .hero-title {
            font-size: 1.8rem;
            font-weight: 800;
            color: var(--sentinel-text);
            margin: 0;
        }

        .hero-sub {
            color: var(--sentinel-muted);
            font-size: 0.97rem;
            margin-top: 0.22rem;
        }

        .badge-row {
            display: flex;
            gap: 0.55rem;
            flex-wrap: wrap;
            margin-top: 0.7rem;
        }

        .badge {
            padding: 0.38rem 0.72rem;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.16);
            background: rgba(255,255,255,0.08);
            color: #f6fbff;
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .status-card {
            background: linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.06));
            border: 1px solid var(--sentinel-border);
            box-shadow: var(--sentinel-shadow);
            border-radius: 20px;
            padding: 0.58rem 0.72rem 0.62rem 0.72rem;
            min-height: 68px;
            backdrop-filter: blur(8px);
            position: relative;
            overflow: hidden;
        }

        .status-card::before {
            content: "";
            position: absolute;
            inset: 0 auto auto 0;
            width: 100%;
            height: 4px;
            background: linear-gradient(90deg, var(--sentinel-cyan), var(--sentinel-green));
            opacity: 0.95;
        }

        .status-label {
            color: #c2d0e6;
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.38rem;
        }

        .status-value {
            color: #16324f;
            font-size: 0.88rem;
            font-weight: 800;
            line-height: 1.15;
            margin-bottom: 0.18rem;
        }

        .status-help {
            color: var(--sentinel-muted);
            font-size: 0.74rem;
            line-height: 1.25;
        }

        .section-shell {
            background: linear-gradient(180deg, rgba(255,255,255,0.09), rgba(255,255,255,0.045));
            border: 1px solid var(--sentinel-border);
            box-shadow: var(--sentinel-shadow);
            border-radius: 22px;
            padding: 0.8rem 0.85rem 0.55rem 0.85rem;
            margin-bottom: 0.95rem;
            backdrop-filter: blur(8px);
        }

        .section-title {
            color: #16324f;
            font-size: 0.92rem;
            font-weight: 800;
            margin-bottom: 0.1rem;
        }

        .section-note {
            color: var(--sentinel-muted);
            font-size: 0.78rem;
            margin-bottom: 0.65rem;
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextArea"] textarea {
            border-radius: 12px !important;
            border: 1px solid rgba(21,67,122,0.16) !important;
            background: #ffffff !important;
            color: #16324f !important;
        }

        div[data-testid="stSelectbox"] > div,
        div[data-testid="stMultiSelect"] > div {
            border-radius: 12px !important;
            background: #ffffff !important;
            border: 1px solid rgba(21,67,122,0.16) !important;
            color: #16324f !important;
        }

        .stSelectbox label, .stMultiSelect label, .stTextInput label, .stNumberInput label, .stTextArea label {
            color: #36516b !important;
            font-weight: 700 !important;
        }

        .stButton button {
            width: 100%;
            border-radius: 14px !important;
            font-weight: 800 !important;
            letter-spacing: 0.02em;
            min-height: 46px;
            border: 1px solid rgba(38,194,129,0.36) !important;
            background: linear-gradient(135deg, rgba(38,194,129,0.95), rgba(20,152,101,0.95)) !important;
            box-shadow: 0 10px 26px rgba(38,194,129,0.26) !important;
            color: white !important;
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }

        .stButton button:hover {
            transform: translateY(-1px);
            box-shadow: 0 14px 28px rgba(38,194,129,0.32) !important;
        }

        .muted-button button {
            background: linear-gradient(135deg, rgba(255,255,255,0.10), rgba(255,255,255,0.07)) !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            box-shadow: none !important;
        }

        .progress-shell {
            border-radius: 18px;
            overflow: hidden;
        }

        .progress-caption {
            color: #36516b;
            font-weight: 700;
            font-size: 0.82rem;
            margin-bottom: 0.35rem;
        }

        .file-chip {
            background: rgba(22,50,79,0.08);
            color: #16324f;
            padding: 0.45rem 0.7rem;
            border-radius: 999px;
            border: 1px solid rgba(21,67,122,0.14);
            display: inline-block;
            margin: 0.18rem 0.2rem 0.18rem 0;
            font-size: 0.78rem;
        }

        .success-box, .info-box {
            border-radius: 16px;
            padding: 0.8rem 0.9rem;
            margin-bottom: 0.7rem;
            border: 1px solid rgba(255,255,255,0.12);
        }

        .success-box {
            background: rgba(38,194,129,0.14);
            color: #f2fff8;
        }

        .info-box {
            background: rgba(66,197,255,0.10);
            color: #eef8ff;
        }


        .section-shell, .hero, .status-card {
            color: #16324f;
        }

        .stMarkdown, .stMarkdown p, .stMarkdown div, .stMarkdown span {
            color: #16324f;
        }

        .small-help {
            color: #b3c4dc;
            font-size: 0.76rem;
            margin-top: -0.2rem;
            margin-bottom: 0.5rem;
        }

        hr {
            border-color: rgba(255,255,255,0.1);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def section_open(title: str, note: str = "") -> None:
    st.markdown('<div class="section-shell">', unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if note:
        st.markdown(f'<div class="section-note">{note}</div>', unsafe_allow_html=True)


def section_close() -> None:
    st.markdown('', unsafe_allow_html=True)


def hero_header() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-title">Sentinel Access Pro</div>
            <div class="hero-sub">Premium report generation and email delivery for surf, sky, weather, moon events, and trip planning.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_status_cards(report_count: int, ready: bool) -> None:
    step1, step2, prog = st.columns(3, gap="small")
    with step1:
        st.markdown(
            f"""
            <div class="status-card">
                <div class="status-label">Step 1</div>
                <div class="status-value">Enter user details</div>
                <div class="status-help">{'Ready' if st.session_state.get('recipient_name') and st.session_state.get('recipient_email') else 'Name and email required'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with step2:
        st.markdown(
            f"""
            <div class="status-card">
                <div class="status-label">Step 2</div>
                <div class="status-value">Choose report set</div>
                <div class="status-help">{report_count} report{'s' if report_count != 1 else ''} selected</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with prog:
        state_text = "SYSTEM READY" if ready else "Awaiting selections"
        st.markdown(
            f"""
            <div class="status-card">
                <div class="status-label">System Progress</div>
                <div class="status-value">{state_text}</div>
                <div class="status-help">{st.session_state.get('last_status', 'System ready')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def run_generation(recipient_name: str, recipient_email: str, selected_reports: list[str], selected_locations: dict[str, str], trip_payload: dict[str, Any]) -> None:
    st.session_state["generated_files"] = []
    st.session_state["email_status"] = ""
    log_progress("RUN START ✅")
    log_progress("Starting report generation.")

    all_files: list[str] = []
    used_locations: list[str] = []
    locations = load_locations()

    for report in selected_reports:
        if report == "Trip Report":
            log_progress("Running Trip Report...")
            trip_files = run_trip_report(trip_payload)
            all_files.extend(trip_files)
            used_locations.append(trip_payload.get("start_location") or "Trip route")
            continue

        location_name = selected_locations.get(report)
        if not location_name:
            log_progress(f"{report}: no location selected.")
            continue

        lat, lon, payload = resolve_location(location_name, locations)
        if lat is None or lon is None:
            log_progress(f"{report}: location '{location_name}' not found in locations.json")
            continue

        used_locations.append(location_name)
        log_progress(f"Resolved coords from locations.json: {lat}, {lon}")

        if report == "Surf Report":
            log_progress(f"Running Surf for {location_name}...")
            all_files.extend(run_surf_report(location_name, lat, lon, payload))
        elif report == "Sky Report":
            log_progress(f"Running Sky for {location_name}...")
            all_files.extend(run_sky_report(location_name, lat, lon))
        elif report == "Moon Events Report":
            log_progress(f"Running Moon Events for {location_name}...")
            all_files.extend(run_moon_report(location_name, lat, lon))
        elif report == "Sky & Moon Report":
            log_progress(f"Running Sky & Moon Report for {location_name}...")
            sky_files = run_sky_report(location_name, lat, lon)
            moon_files = run_moon_report(location_name, lat, lon)
            combined = sky_files + moon_files
            if not combined and sky_files:
                combined = sky_files
            all_files.extend(combined)
        elif report == "Weather Report":
            log_progress(f"Running Weather for {location_name}...")
            all_files.extend(run_weather_report(location_name, lat, lon))

    unique_files = []
    for f in all_files:
        if f not in unique_files:
            unique_files.append(f)
    st.session_state["generated_files"] = unique_files

    if not unique_files:
        log_progress("No valid PDF attachments were generated.")
        st.session_state["email_status"] = "No valid PDF attachments were generated."
        return

    location_summary = ", ".join(dict.fromkeys(used_locations)) if used_locations else "Selected locations"
    ok, msg = send_reports_by_email(recipient_name, recipient_email, selected_reports, location_summary, unique_files)
    log_progress(msg)
    st.session_state["email_status"] = msg


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🌊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    ensure_dirs()
    init_state()
    premium_css()
    hero_header()

    locations = load_locations()
    location_names = list(locations.keys())

    recipient_name = st.session_state.get("recipient_name", "")
    recipient_email = st.session_state.get("recipient_email", "")
    selected_reports = st.session_state.get("selected_reports", [])
    ready = bool(recipient_name.strip() and recipient_email.strip() and selected_reports)

    render_status_cards(len(selected_reports), ready)

    left, middle, right = st.columns(3, gap="medium")

    with left:
        section_open("User Details", "Enter your details. Press Enter after typing name or email.")
        recipient_name = st.text_input("Name", key="recipient_name", placeholder="Your name")
        recipient_email = st.text_input("Email", key="recipient_email", placeholder="your@email.com")
        st.markdown('<div class="small-help">Your report PDFs will be emailed to this address.</div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("**Admin**")
        back_url = "https://www.surfskiesweatherreports.com/"
        st.link_button("Back to website", back_url, use_container_width=True)
        section_close()

        section_open("Add New Location", "Search an Australian place, then save the match to locations.json.")
        new_location_name = st.text_input("Location name", key="new_location_name", placeholder="e.g. Anglesea")
        new_location_state = st.selectbox("State", options=STATE_OPTIONS, key="new_location_state")
        find_col, save_col = st.columns(2, gap="small")

        with find_col:
            if st.button("Find match", key="find_match_btn"):
                ok, msg, matches = geocode_au_location(new_location_name, new_location_state)
                st.session_state["geo_message"] = msg
                st.session_state["geo_matches"] = matches
                log_progress(msg)

        matches = st.session_state.get("geo_matches", [])
        match_labels = [
            f"{m.get('name')} — {m.get('admin1')} ({m.get('latitude'):.5f}, {m.get('longitude'):.5f})"
            for m in matches
            if m.get("latitude") is not None and m.get("longitude") is not None
        ]
        chosen_match_label = None
        if match_labels:
            chosen_match_label = st.selectbox(
                "Geocoding matches",
                options=match_labels,
                index=None,
                placeholder="Choose a match to save",
                key="chosen_match_label",
            )

        with save_col:
            if st.button("Save location", key="save_location_btn"):
                if not matches or not chosen_match_label:
                    notice = "Choose a geocoding match before saving."
                    st.session_state["saved_location_notice"] = notice
                    log_progress(notice)
                else:
                    selected_idx = match_labels.index(chosen_match_label)
                    match = matches[selected_idx]
                    ok, msg = save_location_entry(
                        name=f"{match.get('name')}, {new_location_state}",
                        lat=float(match["latitude"]),
                        lon=float(match["longitude"]),
                        state=new_location_state,
                    )
                    st.session_state["saved_location_notice"] = msg
                    log_progress(msg)
                    if ok:
                        st.session_state["geo_matches"] = []
                        st.rerun()

        if st.session_state.get("geo_message"):
            st.markdown(f'<div class="info-box">{st.session_state["geo_message"]}</div>', unsafe_allow_html=True)
        if st.session_state.get("saved_location_notice"):
            box_cls = "success-box" if "Saved " in st.session_state["saved_location_notice"] else "info-box"
            st.markdown(f'<div class="{box_cls}">{st.session_state["saved_location_notice"]}</div>', unsafe_allow_html=True)
        section_close()

    with middle:
        section_open("Select Reports & Locations", "Choose one or more reports. Each selected report can use its own location.")
        selected_reports = st.multiselect(
            "Reports",
            options=REPORT_OPTIONS,
            key="selected_reports",
            placeholder="Choose report types",
        )

        selected_locations: dict[str, str] = {}
        for report in selected_reports:
            if report == "Trip Report":
                continue
            selected_locations[report] = st.selectbox(
                f"{report} location",
                options=location_names,
                index=None,
                placeholder="Choose location",
                key=f"loc_{report}",
            )

        trip_payload: dict[str, Any] = {}
        if "Trip Report" in selected_reports:
            st.markdown("---")
            st.markdown("**Trip Planner**")
            trip_payload["start_location"] = st.selectbox(
                "Start location",
                options=location_names,
                index=None,
                placeholder="Choose start location",
                key="trip_start_location",
            )
            trip_payload["destination_1"] = st.selectbox(
                "Destination 1",
                options=location_names,
                index=None,
                placeholder="Choose first destination",
                key="trip_destination_1",
            )
            trip_payload["destination_2"] = st.selectbox(
                "Destination 2",
                options=location_names,
                index=None,
                placeholder="Choose second destination",
                key="trip_destination_2",
            )
            trip_payload["destination_3"] = st.selectbox(
                "Destination 3",
                options=location_names,
                index=None,
                placeholder="Choose third destination",
                key="trip_destination_3",
            )
            fuel_left, fuel_right = st.columns(2, gap="small")
            with fuel_left:
                trip_payload["fuel_type"] = st.selectbox("Fuel type", ["Petrol", "Diesel"], key="trip_fuel_type")
            with fuel_right:
                fuel_prices = [f"${x/100:.2f}" for x in range(140, 401, 5)]
                trip_payload["fuel_price_per_litre"] = st.selectbox(
                    "Fuel price / litre",
                    fuel_prices,
                    index=fuel_prices.index("$1.90") if "$1.90" in fuel_prices else 0,
                    key="trip_fuel_price",
                )

        generate_ready = bool(recipient_name.strip() and recipient_email.strip() and selected_reports)
        if any(r != "Trip Report" for r in selected_reports):
            non_trip_ok = all(selected_locations.get(r) for r in selected_reports if r != "Trip Report")
            generate_ready = generate_ready and non_trip_ok
        if "Trip Report" in selected_reports:
            generate_ready = generate_ready and bool(trip_payload.get("start_location"))

        gen_col, clear_col = st.columns(2, gap="small")
        with gen_col:
            if st.button("Generate & Email Reports", key="generate_reports_btn", disabled=not generate_ready):
                run_generation(recipient_name, recipient_email, selected_reports, selected_locations, trip_payload)
        with clear_col:
            if st.button("Clear progress", key="clear_progress_btn"):
                st.session_state["progress_log"] = f"[{now_ts()}] Progress cleared"
                st.session_state["generated_files"] = []
                st.session_state["email_status"] = ""
                st.session_state["last_status"] = "Progress cleared"

        section_close()

    with right:
        section_open("Live System Progress", "The full run log remains visible while the app is running.")
        st.markdown('<div class="progress-caption">System progress</div>', unsafe_allow_html=True)
        st.text_area(
            "System progress",
            value=st.session_state.get("progress_log", ""),
            height=360,
            key="progress_view",
            label_visibility="collapsed",
        )

        if st.session_state.get("email_status"):
            box_cls = "success-box" if "Email OK" in st.session_state["email_status"] else "info-box"
            st.markdown(f'<div class="{box_cls}">{st.session_state["email_status"]}</div>', unsafe_allow_html=True)

        files = st.session_state.get("generated_files", [])
        if files:
            st.markdown("**Generated files**")
            for file_path in files:
                st.markdown(f'<div class="file-chip">{Path(file_path).name}</div>', unsafe_allow_html=True)
        section_close()


if __name__ == "__main__":
    main()
