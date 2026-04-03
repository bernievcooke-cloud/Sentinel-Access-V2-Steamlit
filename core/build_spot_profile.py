#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import requests

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SEARCH_NAME = "Bells Beach, Victoria, Australia"
OUTPUT_JSON = BASE_DIR / "config" / "spot_profile.json"
REQUEST_TIMEOUT = 25
USER_AGENT = "RuralAI-SurfProfileBuilder/1.0"

# Search / geometry tuning
SEARCH_RADIUS_METRES = 2500
COASTLINE_POINT_LIMIT = 400
DEFAULT_SWELL_MIN_M = 0.8
DEFAULT_SWELL_MAX_M = 2.8

# Generic derived swell window width around facing direction
SWELL_WINDOW_HALF_WIDTH_DEG = 40


# ============================================================
# HELPERS
# ============================================================
def clamp_angle(deg: float) -> float:
    return deg % 360.0


def deg_to_text(deg: float | None) -> str:
    if deg is None:
        return ""
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    return dirs[int((deg + 11.25) // 22.5) % 16]


def bearing_from_point_a_to_b(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlon_r = math.radians(lon2 - lon1)

    y = math.sin(dlon_r) * math.cos(lat2_r)
    x = (
        math.cos(lat1_r) * math.sin(lat2_r)
        - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon_r)
    )
    brng = math.degrees(math.atan2(y, x))
    return clamp_angle(brng)


def circular_mean_deg(angles: list[float]) -> float | None:
    if not angles:
        return None
    sin_sum = sum(math.sin(math.radians(a)) for a in angles)
    cos_sum = sum(math.cos(math.radians(a)) for a in angles)
    if abs(sin_sum) < 1e-9 and abs(cos_sum) < 1e-9:
        return None
    return clamp_angle(math.degrees(math.atan2(sin_sum, cos_sum)))


def fetch_json(url: str, params: dict | None = None, method: str = "GET") -> dict:
    headers = {"User-Agent": USER_AGENT}
    if method.upper() == "GET":
        r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    else:
        r = requests.post(url, data=params, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


# ============================================================
# STEP 1 — GEOCODE PLACE NAME
# ============================================================
def geocode_place(search_name: str) -> dict:
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": search_name,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }
    data = fetch_json(url, params=params)
    if not data:
        raise ValueError(f"No geocoding result found for: {search_name}")

    best = data[0]
    return {
        "location_name": best.get("display_name", search_name),
        "lat": float(best["lat"]),
        "lon": float(best["lon"]),
    }


# ============================================================
# STEP 2 — FIND NEARBY COASTLINE / WATER EDGE FEATURES
# ============================================================
def fetch_nearby_water_geometry(lat: float, lon: float, radius_m: int = SEARCH_RADIUS_METRES) -> list[tuple[float, float]]:
    overpass_url = "https://overpass-api.de/api/interpreter"

    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius_m},{lat},{lon})["natural"="coastline"];
      way(around:{radius_m},{lat},{lon})["natural"="beach"];
      way(around:{radius_m},{lat},{lon})["landuse"="beach"];
    );
    out geom;
    """

    data = fetch_json(overpass_url, {"data": query}, method="POST")
    elements = data.get("elements", [])

    points: list[tuple[float, float]] = []
    for el in elements:
        geom = el.get("geometry", [])
        for p in geom:
            plat = p.get("lat")
            plon = p.get("lon")
            if plat is not None and plon is not None:
                points.append((float(plat), float(plon)))

    seen = set()
    unique_points: list[tuple[float, float]] = []
    for p in points:
        key = (round(p[0], 6), round(p[1], 6))
        if key not in seen:
            seen.add(key)
            unique_points.append(p)

    return unique_points[:COASTLINE_POINT_LIMIT]


# ============================================================
# STEP 3 — ESTIMATE BEACH FACING DIRECTION
# ============================================================
def estimate_beach_orientation(lat: float, lon: float, nearby_points: list[tuple[float, float]]) -> float | None:
    if not nearby_points:
        return None

    bearings_to_points = [
        bearing_from_point_a_to_b(lat, lon, p_lat, p_lon)
        for p_lat, p_lon in nearby_points
    ]
    mean_bearing_to_land_edge = circular_mean_deg(bearings_to_points)
    if mean_bearing_to_land_edge is None:
        return None

    facing_deg = clamp_angle(mean_bearing_to_land_edge + 180.0)
    return facing_deg


def fallback_orientation_from_search_name(search_name: str) -> float:
    s = (search_name or "").lower()

    if any(
        x in s
        for x in [
            "noosa", "sunshine", "gold coast", "snapper", "kirra",
            "burleigh", "bondi", "manly", "byron",
        ]
    ):
        return 90.0

    if any(
        x in s
        for x in [
            "bells", "torquay", "jan juc", "point leo",
            "phillip island", "wilsons prom",
        ]
    ):
        return 180.0

    if any(
        x in s
        for x in [
            "margaret river", "yallingup", "trigg", "cottesloe", "gnaraloo",
        ]
    ):
        return 270.0

    if any(x in s for x in ["middleton", "waitpinga", "pondalowie"]):
        return 180.0

    return 180.0


# ============================================================
# STEP 4 — AUTO DERIVE SURF WINDOW
# ============================================================
def derive_swell_window(beach_orientation_deg: float | None) -> tuple[int | None, int | None]:
    if beach_orientation_deg is None:
        return None, None
    low = int(round(clamp_angle(beach_orientation_deg - SWELL_WINDOW_HALF_WIDTH_DEG)))
    high = int(round(clamp_angle(beach_orientation_deg + SWELL_WINDOW_HALF_WIDTH_DEG)))
    return low, high


# ============================================================
# STEP 5 — BUILD PROFILE FROM GEOCODED SEARCH
# ============================================================
def build_profile(search_name: str) -> dict:
    geo = geocode_place(search_name)
    lat = geo["lat"]
    lon = geo["lon"]
    location_name = geo["location_name"]

    print(f"Geocoded: {location_name}")
    print(f"Lat/Lon : {lat:.5f}, {lon:.5f}")

    time.sleep(1.0)
    profile_method = "auto-derived"

    try:
        nearby_points = fetch_nearby_water_geometry(lat, lon)
        print(f"Nearby geometry points found: {len(nearby_points)}")
        beach_orientation_deg = estimate_beach_orientation(lat, lon, nearby_points)
    except Exception as e:
        print(f"WARNING: Coastline lookup failed: {e}")
        beach_orientation_deg = None

    if beach_orientation_deg is None:
        beach_orientation_deg = fallback_orientation_from_search_name(search_name)
        profile_method = "fallback-derived"
        print(f"Using fallback beach orientation: {beach_orientation_deg:.1f}° {deg_to_text(beach_orientation_deg)}")

    swell_min_dir, swell_max_dir = derive_swell_window(beach_orientation_deg)

    return {
        "location_name": location_name,
        "lat": lat,
        "lon": lon,
        "beach_orientation_deg": round(beach_orientation_deg, 1),
        "beach_orientation_text": deg_to_text(beach_orientation_deg),
        "preferred_swell_dir_min": swell_min_dir,
        "preferred_swell_dir_max": swell_max_dir,
        "preferred_swell_min_m": DEFAULT_SWELL_MIN_M,
        "preferred_swell_max_m": DEFAULT_SWELL_MAX_M,
        "preferred_tide_min_m": None,
        "preferred_tide_max_m": None,
        "profile_method": profile_method,
        "search_name": search_name,
    }


# ============================================================
# STEP 6 — BUILD PROFILE FROM KNOWN LAT/LON
# ============================================================
def build_profile_from_known_location(
    search_name: str,
    lat: float,
    lon: float,
    location_name: str | None = None,
) -> dict:
    lat = float(lat)
    lon = float(lon)
    location_name = (location_name or search_name or "").strip() or f"{lat:.5f}, {lon:.5f}"

    print(f"Using provided location: {location_name}")
    print(f"Lat/Lon : {lat:.5f}, {lon:.5f}")

    time.sleep(0.2)
    profile_method = "auto-derived"

    try:
        nearby_points = fetch_nearby_water_geometry(lat, lon)
        print(f"Nearby geometry points found: {len(nearby_points)}")
        beach_orientation_deg = estimate_beach_orientation(lat, lon, nearby_points)
    except Exception as e:
        print(f"WARNING: Coastline lookup failed: {e}")
        beach_orientation_deg = None

    if beach_orientation_deg is None:
        beach_orientation_deg = fallback_orientation_from_search_name(search_name or location_name)
        profile_method = "fallback-derived"
        print(f"Using fallback beach orientation: {beach_orientation_deg:.1f}° {deg_to_text(beach_orientation_deg)}")

    swell_min_dir, swell_max_dir = derive_swell_window(beach_orientation_deg)

    return {
        "location_name": location_name,
        "lat": lat,
        "lon": lon,
        "beach_orientation_deg": round(beach_orientation_deg, 1),
        "beach_orientation_text": deg_to_text(beach_orientation_deg),
        "preferred_swell_dir_min": swell_min_dir,
        "preferred_swell_dir_max": swell_max_dir,
        "preferred_swell_min_m": DEFAULT_SWELL_MIN_M,
        "preferred_swell_max_m": DEFAULT_SWELL_MAX_M,
        "preferred_tide_min_m": None,
        "preferred_tide_max_m": None,
        "profile_method": profile_method,
        "search_name": search_name,
    }


# ============================================================
# SAVE
# ============================================================
def save_profile(profile: dict, output_json: str | Path = OUTPUT_JSON) -> Path:
    out_path = Path(output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return out_path


# ============================================================
# MAIN
# ============================================================
def main() -> None:
    try:
        profile = build_profile(DEFAULT_SEARCH_NAME)
        out_path = save_profile(profile, OUTPUT_JSON)

        print("\nSUCCESS")
        print(f"Profile saved to: {out_path.resolve()}")
        print(json.dumps(profile, indent=2))
    except requests.HTTPError as e:
        print(f"HTTP ERROR: {e}")
    except requests.RequestException as e:
        print(f"NETWORK ERROR: {e}")
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    main()