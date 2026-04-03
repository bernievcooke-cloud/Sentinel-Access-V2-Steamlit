#!/usr/bin/env python3
import json
import re
import shutil
from pathlib import Path

# ---------------------------------------------
# PATH TO YOUR LOCATIONS FILE
# ---------------------------------------------
LOC_FILE = Path(r"C:\OneDrive\Sentinel-Access-V2\Sentinel-Access-V2\config\locations.json")

# Legacy keys we want to ACCEPT (read) but NOT keep
LEGACY_LAT_KEYS = ["lat", "LAT", "Latitude", "y", "Y"]
LEGACY_LON_KEYS = ["lon", "LON", "lng", "LNG", "Longitude", "x", "X"]

# Canonical keys we want to KEEP
CANON_LAT_KEY = "latitude"
CANON_LON_KEY = "longitude"

STATE_NAME_MAP = {
    "NEW SOUTH WALES": "NSW",
    "VICTORIA": "VIC",
    "QUEENSLAND": "QLD",
    "SOUTH AUSTRALIA": "SA",
    "WESTERN AUSTRALIA": "WA",
    "TASMANIA": "TAS",
    "NORTHERN TERRITORY": "NT",
    "AUSTRALIAN CAPITAL TERRITORY": "ACT",
    "NSW": "NSW",
    "VIC": "VIC",
    "QLD": "QLD",
    "SA": "SA",
    "WA": "WA",
    "TAS": "TAS",
    "NT": "NT",
    "ACT": "ACT",
}


def find_number(payload, keys):
    for k in keys:
        if k in payload:
            try:
                return float(payload[k])
            except Exception:
                pass
    return None


def normalize_state(value):
    s = str(value or "").strip().upper()
    return STATE_NAME_MAP.get(s, s)


def clean_display_name(name, state):
    base = re.sub(r"\s+", " ", str(name or "").strip())
    st = normalize_state(state)
    if st and not re.search(rf",\s*{re.escape(st)}$", base, flags=re.IGNORECASE):
        return f"{base}, {st}"
    return base


def normalize():
    if not LOC_FILE.exists():
        print(f"ERROR: locations.json not found at: {LOC_FILE}")
        return

    backup = LOC_FILE.with_suffix(".backup2.json")
    shutil.copy2(LOC_FILE, backup)
    print(f"Backup created: {backup}")

    data = json.loads(LOC_FILE.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        print("ERROR: locations.json must be a dict of {name: payload}")
        return

    cleaned = {}
    skipped = []
    collisions = []

    for name, payload in data.items():
        if not isinstance(payload, dict):
            skipped.append(name)
            continue

        lat = find_number(payload, [CANON_LAT_KEY]) or find_number(payload, LEGACY_LAT_KEYS)
        lon = find_number(payload, [CANON_LON_KEY]) or find_number(payload, LEGACY_LON_KEYS)

        new_payload = dict(payload)

        if lat is None or lon is None:
            skipped.append(name)
            display_name = str(new_payload.get("display_name", name)).strip()
            cleaned[display_name] = new_payload
            continue

        state = normalize_state(new_payload.get("state", ""))
        display_name = clean_display_name(new_payload.get("display_name", name), state)

        new_payload["display_name"] = display_name
        new_payload["state"] = state
        new_payload[CANON_LAT_KEY] = lat
        new_payload[CANON_LON_KEY] = lon

        for k in LEGACY_LAT_KEYS + LEGACY_LON_KEYS:
            new_payload.pop(k, None)

        if display_name in cleaned:
            collisions.append(display_name)

        cleaned[display_name] = new_payload

    sorted_cleaned = dict(sorted(cleaned.items(), key=lambda kv: kv[0].casefold()))
    LOC_FILE.write_text(
        json.dumps(sorted_cleaned, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"locations.json normalized OK. Locations: {len(sorted_cleaned)}")

    if skipped:
        print(f"WARNING: {len(skipped)} location(s) missing coords and left unchanged:")
        print(", ".join(skipped))

    if collisions:
        print(f"WARNING: {len(collisions)} duplicate canonical name collision(s) occurred:")
        print(", ".join(sorted(set(collisions), key=str.casefold)))


if __name__ == "__main__":
    normalize()