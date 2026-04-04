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
