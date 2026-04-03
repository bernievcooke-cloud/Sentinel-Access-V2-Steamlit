#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import platform
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.patches import Circle, Ellipse
import numpy as np
import pandas as pd
import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer

# ============================================================
# OPTIONAL ASTRAL IMPORT (preferred for live moon tracking)
# ============================================================
ASTRAL_AVAILABLE = False
ASTRAL_IMPORT_ERROR = ""
try:
    from astral import Observer
    from astral import moon as astral_moon
    ASTRAL_AVAILABLE = True
except Exception as e:  # pragma: no cover
    ASTRAL_AVAILABLE = False
    ASTRAL_IMPORT_ERROR = f"{type(e).__name__}: {e}"


# ============================================================
# CONFIG
# ============================================================
APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR.parent / "outputs" if (APP_DIR.parent / "outputs").exists() else APP_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TZ_FALLBACK = "Australia/Melbourne"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = 25
FORECAST_DAYS = 8
RETRY_DELAYS = [1.5, 3.0, 6.0]

FIG_DPI = 180
PAGE_IMAGE_WIDTH_CM = 19.0
PAGE1_IMAGE_HEIGHT_CM = 22.3
PAGE2_IMAGE_HEIGHT_CM = 22.8

COLOR_SCORE = "#c62828"
COLOR_CLOUD = "#1e88e5"
COLOR_VIS = "#2e7d32"
COLOR_HAZE = "#8e24aa"
COLOR_MOON = "#f9a825"
COLOR_RUNTIME = "#424242"
COLOR_WEEK_BAR = "#90caf9"
COLOR_WEEK_BAR_HIGHLIGHT = "#66bb6a"


# ============================================================
# LOGGING
# ============================================================
def _log(logger: Optional[Callable[[str], None]], msg: str) -> None:
    if logger:
        try:
            logger(msg)
            return
        except Exception:
            pass
    print(msg)


# ============================================================
# TIME HELPERS
# ============================================================
def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or TZ_FALLBACK)
    except Exception:
        return ZoneInfo(TZ_FALLBACK)


def _coerce_to_series_dt(values: list[str] | pd.Series | pd.Index, tz_name: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if isinstance(parsed, pd.DatetimeIndex):
        s = pd.Series(parsed)
    elif isinstance(parsed, pd.Series):
        s = parsed.copy()
    else:
        s = pd.Series(parsed)

    if getattr(s.dt, "tz", None) is not None:
        return s.dt.tz_convert(tz_name)
    return s.dt.tz_localize(tz_name, ambiguous="NaT", nonexistent="shift_forward")


def _ensure_tz(ts: pd.Timestamp, tz_name: str) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize(tz_name, ambiguous="NaT", nonexistent="shift_forward")
    return ts.tz_convert(tz_name)


def _local_wall_time(day_ts: pd.Timestamp, hour: int, tz_name: str) -> pd.Timestamp:
    ts = _ensure_tz(day_ts, tz_name)
    day = ts.date()
    naive = pd.Timestamp(f"{day} {hour:02d}:00:00")
    return naive.tz_localize(tz_name, ambiguous="NaT", nonexistent="shift_forward")


def _day_window_start(day_ts: pd.Timestamp, tz_name: str) -> pd.Timestamp:
    return _local_wall_time(day_ts, 6, tz_name)


def _day_window_end(day_ts: pd.Timestamp, tz_name: str) -> pd.Timestamp:
    return _local_wall_time(day_ts, 18, tz_name)


def _night_window_start(day_ts: pd.Timestamp, tz_name: str) -> pd.Timestamp:
    return _local_wall_time(day_ts, 18, tz_name)


def _night_window_end(day_ts: pd.Timestamp, tz_name: str) -> pd.Timestamp:
    ts = _ensure_tz(day_ts, tz_name) + pd.Timedelta(days=1)
    return _local_wall_time(ts, 6, tz_name)


def _window_ticks(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    ticks: list[pd.Timestamp] = []
    current = pd.Timestamp(start)
    while current <= end:
        ticks.append(current)
        current = current + pd.Timedelta(hours=3)
    return ticks


def _fmt_hour() -> str:
    return "%#I%p" if platform.system().lower().startswith("win") else "%-I%p"


# ============================================================
# WEATHER FETCH
# ============================================================
def fetch_weather_data(lat: float, lon: float, tz_name: str, logger=None) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "cloud_cover",
            "visibility",
            "relative_humidity_2m",
            "precipitation_probability",
            "temperature_2m",
        ]),
        "forecast_days": FORECAST_DAYS,
        "timezone": tz_name,
    }

    last_error: Exception | None = None

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            r = requests.get(OPEN_METEO_URL, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                raise requests.HTTPError("429 rate limit", response=r)
            r.raise_for_status()
            data = r.json()
            hourly = data.get("hourly", {})

            time_series = _coerce_to_series_dt(hourly.get("time", []), tz_name)
            df = pd.DataFrame({
                "time": time_series,
                "cloud_cover": pd.to_numeric(hourly.get("cloud_cover", []), errors="coerce"),
                "visibility_m": pd.to_numeric(hourly.get("visibility", []), errors="coerce"),
                "humidity": pd.to_numeric(hourly.get("relative_humidity_2m", []), errors="coerce"),
                "precip_prob": pd.to_numeric(hourly.get("precipitation_probability", []), errors="coerce"),
                "temp_c": pd.to_numeric(hourly.get("temperature_2m", []), errors="coerce"),
            })

            df = df.dropna(subset=["time"]).copy()
            if df.empty:
                raise ValueError("No hourly weather data returned")

            df["visibility_km"] = df["visibility_m"] / 1000.0
            haze_raw = (
                (20 - np.clip(df["visibility_km"].fillna(0), 0, 20)) * 3.0
                + np.clip(df["humidity"].fillna(100) - 45, 0, 55) * 0.85
                + df["cloud_cover"].fillna(100) * 0.12
            )
            df["haze_proxy"] = np.clip(haze_raw, 0, 100)
            return df

        except Exception as e:
            last_error = e
            if attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                if isinstance(e, requests.HTTPError) and getattr(e, "response", None) is not None and e.response is not None and e.response.status_code == 429:
                    _log(logger, f"Open-Meteo rate limit hit (429) on attempt {attempt + 1}.")
                else:
                    _log(logger, f"Open-Meteo fetch failed on attempt {attempt + 1}: {e}")
                _log(logger, f"Open-Meteo retry {attempt + 1}/{len(RETRY_DELAYS)} after {delay:.1f}s")
                time.sleep(delay)
            else:
                break

    raise ValueError(f"fetch_weather_data failed: {last_error}")


# ============================================================
# FALLBACK MOON MATH
# ============================================================
def _julian_day(dt_utc: datetime) -> float:
    year = dt_utc.year
    month = dt_utc.month
    day = dt_utc.day + (dt_utc.hour + (dt_utc.minute + dt_utc.second / 60) / 60) / 24
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5


def _moon_ra_dec_approx(dt_utc: datetime) -> tuple[float, float, float]:
    jd = _julian_day(dt_utc)
    d = jd - 2451543.5

    n = math.radians((125.1228 - 0.0529538083 * d) % 360)
    i = math.radians(5.1454)
    w = math.radians((318.0634 + 0.1643573223 * d) % 360)
    a = 60.2666
    e = 0.054900
    m = math.radians((115.3654 + 13.0649929509 * d) % 360)

    e_anom = m + e * math.sin(m) * (1.0 + e * math.cos(m))
    xv = a * (math.cos(e_anom) - e)
    yv = a * (math.sqrt(1.0 - e * e) * math.sin(e_anom))

    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)

    xh = r * (math.cos(n) * math.cos(v + w) - math.sin(n) * math.sin(v + w) * math.cos(i))
    yh = r * (math.sin(n) * math.cos(v + w) + math.cos(n) * math.sin(v + w) * math.cos(i))
    zh = r * (math.sin(v + w) * math.sin(i))

    lonecl = math.atan2(yh, xh)
    latecl = math.atan2(zh, math.sqrt(xh * xh + yh * yh))

    ms = math.radians((356.0470 + 0.9856002585 * d) % 360)
    ls = math.radians((280.460 + 0.9856474 * d) % 360)
    lm = math.radians((218.316 + 13.176396 * d) % 360)
    dm = lm - ls
    fm = lm - n

    lonecl = lonecl + math.radians(-1.274) * math.sin(m - 2 * dm) + math.radians(0.658) * math.sin(2 * dm) - math.radians(0.186) * math.sin(ms)
    latecl = latecl + math.radians(-0.173) * math.sin(fm - 2 * dm) - math.radians(0.055) * math.sin(m - fm - 2 * dm) - math.radians(0.046) * math.sin(m + fm - 2 * dm) + math.radians(0.033) * math.sin(fm + 2 * dm)

    eps = math.radians(23.4393 - 3.563e-7 * d)
    xe = math.cos(lonecl) * math.cos(latecl)
    ye = math.sin(lonecl) * math.cos(latecl) * math.cos(eps) - math.sin(latecl) * math.sin(eps)
    ze = math.sin(lonecl) * math.cos(latecl) * math.sin(eps) + math.sin(latecl) * math.cos(eps)

    ra = math.degrees(math.atan2(ye, xe)) % 360
    dec = math.degrees(math.atan2(ze, math.sqrt(xe * xe + ye * ye)))
    return ra, dec, jd


def _gmst_deg(jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t - t * t * t / 38710000.0
    return gmst % 360


def moon_altitude_azimuth_fallback(dt_local: datetime, lat: float, lon: float) -> tuple[float, float]:
    dt_utc = dt_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    ra, dec, jd = _moon_ra_dec_approx(dt_utc)
    lst = (_gmst_deg(jd) + lon) % 360
    ha = (lst - ra + 540) % 360 - 180

    lat_r = math.radians(lat)
    dec_r = math.radians(dec)
    ha_r = math.radians(ha)

    sin_alt = math.sin(dec_r) * math.sin(lat_r) + math.cos(dec_r) * math.cos(lat_r) * math.cos(ha_r)
    sin_alt = min(1.0, max(-1.0, sin_alt))
    alt = math.asin(sin_alt)

    cos_az = (math.sin(dec_r) - math.sin(alt) * math.sin(lat_r)) / max(1e-9, (math.cos(alt) * math.cos(lat_r)))
    cos_az = min(1.0, max(-1.0, cos_az))
    az = math.degrees(math.acos(cos_az))
    if math.sin(ha_r) > 0:
        az = 360 - az
    return math.degrees(alt), az


def moon_phase_fraction_fallback(dt_local: datetime) -> float:
    dt_utc = dt_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    jd = _julian_day(dt_utc)
    synodic = 29.53058867
    known_new_moon = 2451550.1
    age = (jd - known_new_moon) % synodic
    return age / synodic


# ============================================================
# MOON API - ASTRAL PREFERRED
# ============================================================
def moon_phase_fraction(dt_local: datetime) -> tuple[float, str]:
    if ASTRAL_AVAILABLE:
        try:
            p = float(astral_moon.phase(dt_local.date()))
            return (p % 29.53058867) / 29.53058867, "astral"
        except Exception:
            pass
    return moon_phase_fraction_fallback(dt_local), "fallback"


def moon_phase_name(dt_local: datetime) -> str:
    p, _ = moon_phase_fraction(dt_local)
    phases = [
        (0.0625, "New Moon"),
        (0.1875, "Waxing Crescent"),
        (0.3125, "First Quarter"),
        (0.4375, "Waxing Gibbous"),
        (0.5625, "Full Moon"),
        (0.6875, "Waning Gibbous"),
        (0.8125, "Last Quarter"),
        (0.9375, "Waning Crescent"),
        (1.0001, "New Moon"),
    ]
    for limit, name in phases:
        if p < limit:
            return name
    return "Moon"


def moon_phase_emoji(dt_local: datetime) -> str:
    p, _ = moon_phase_fraction(dt_local)
    emojis = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
    idx = int((p * 8) + 0.5) % 8
    return emojis[idx]


def moon_illumination_factor(dt_local: datetime) -> float:
    p, _ = moon_phase_fraction(dt_local)
    return 0.5 * (1 - math.cos(2 * math.pi * p))


def moon_altitude_azimuth(dt_local: datetime, lat: float, lon: float) -> tuple[float, float, str, str]:
    if ASTRAL_AVAILABLE:
        try:
            observer = Observer(latitude=lat, longitude=lon)
            alt = float(astral_moon.elevation(observer, dt_local))
            az = float(astral_moon.azimuth(observer, dt_local))
            return alt, az, "astral", ""
        except Exception as e:
            alt, az = moon_altitude_azimuth_fallback(dt_local, lat, lon)
            return alt, az, "fallback", f"{type(e).__name__}: {e}"
    alt, az = moon_altitude_azimuth_fallback(dt_local, lat, lon)
    reason = ASTRAL_IMPORT_ERROR or "Astral not installed"
    return alt, az, "fallback", reason


def build_moon_track(
    times: pd.Series | pd.DatetimeIndex,
    lat: float,
    lon: float,
    location_name: str,
    tz_name: str,
    logger: Optional[Callable[[str], None]] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    iterable = list(times) if not isinstance(times, pd.Series) else times.tolist()
    counts = {"astral": 0, "fallback": 0}
    first_fallback_reason = ""

    for t in iterable:
        if pd.isna(t):
            continue
        dt = pd.Timestamp(t).to_pydatetime()
        alt, az, source, err = moon_altitude_azimuth(dt, lat, lon)
        counts[source] = counts.get(source, 0) + 1
        if source != "astral" and not first_fallback_reason:
            first_fallback_reason = err
        illum = moon_illumination_factor(dt)
        phase_name = moon_phase_name(dt)
        phase_emoji = moon_phase_emoji(dt)
        rows.append({
            "time": pd.Timestamp(t),
            "moon_altitude": alt,
            "moon_azimuth": az,
            "moon_illumination": illum,
            "moon_phase_name": phase_name,
            "moon_phase_emoji": phase_emoji,
            "moon_source": source,
        })

    moon_df = pd.DataFrame(rows)
    meta = {
        "astral_points": int(counts.get("astral", 0)),
        "fallback_points": int(counts.get("fallback", 0)),
        "first_fallback_reason": first_fallback_reason,
        "location_name": location_name,
        "tz_name": tz_name,
    }

    if logger:
        if meta["astral_points"] > 0 and meta["fallback_points"] == 0:
            _log(logger, f"Moon track: Astral live tracking active ({meta['astral_points']} points)")
        elif meta["astral_points"] > 0 and meta["fallback_points"] > 0:
            _log(logger, f"Moon track: Astral active with fallback on some points ({meta['astral_points']} Astral / {meta['fallback_points']} fallback)")
            if first_fallback_reason:
                _log(logger, f"Moon track fallback reason: {first_fallback_reason}")
        else:
            _log(logger, f"Moon track: live computed altitude active (Astral unavailable: {first_fallback_reason or ASTRAL_IMPORT_ERROR or 'not installed'})")

    return moon_df, meta


# ============================================================
# SCORING
# ============================================================
def day_night_label(ts: pd.Timestamp) -> str:
    ts = pd.Timestamp(ts)
    return "day" if 6 <= ts.hour < 18 else "night"


def period_anchor_date(ts: pd.Timestamp) -> datetime.date:
    ts = pd.Timestamp(ts)
    if 6 <= ts.hour < 18:
        return ts.date()
    if ts.hour < 6:
        return (ts - pd.Timedelta(days=1)).date()
    return ts.date()


def compute_sky_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["period"] = out["time"].apply(day_night_label)

    cloud = out["cloud_cover"].fillna(100)
    haze = out["haze_proxy"].fillna(100)
    humidity = out["humidity"].fillna(100)
    precip = out["precip_prob"].fillna(100)
    vis = np.clip(out["visibility_km"].fillna(0), 0, 20)
    temp = out["temp_c"].fillna(12)
    moon_alt = out["moon_altitude"].fillna(-12)
    moon_illum = np.clip(out["moon_illumination"].fillna(0.5), 0, 1)

    is_day = out["period"].eq("day")

    day_score = (
        100 - cloud * 0.42 - haze * 0.24 - np.clip(humidity - 65, 0, 35) * 0.40 - precip * 0.22 + vis * 1.35 - np.clip(np.abs(temp - 17), 0, 18) * 0.30
    )
    bright_moon_penalty = np.where(moon_alt > 0, moon_illum * 8.0, 0.0)
    night_score = (
        100 - cloud * 0.48 - haze * 0.26 - np.clip(humidity - 68, 0, 32) * 0.34 - precip * 0.24 + vis * 1.20 + np.clip(moon_alt + 8, 0, 55) * 0.34 - bright_moon_penalty
    )

    out["score"] = np.where(is_day, day_score, night_score)
    out["score"] = np.clip(out["score"], 0, 100)
    out["score10"] = out["score"] / 10.0
    return out


# ============================================================
# HELPERS
# ============================================================
def slice_window(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    return df[(df["time"] >= start) & (df["time"] <= end)].copy()


def best_hour_row(df: pd.DataFrame) -> Optional[pd.Series]:
    if df.empty:
        return None
    return df.sort_values(["score", "moon_altitude"], ascending=[False, False]).iloc[0]


def _load_coords_from_locations_json(location_name: str) -> tuple[float, float, str]:
    possible_paths = [
        APP_DIR / "config" / "locations.json",
        APP_DIR.parent / "config" / "locations.json",
        Path.cwd() / "config" / "locations.json",
    ]
    location_key = (location_name or "").strip().lower()

    for path in possible_paths:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                for name, value in data.items():
                    if str(name).strip().lower() == location_key and isinstance(value, dict):
                        lat = value.get("lat", value.get("latitude"))
                        lon = value.get("lon", value.get("lng", value.get("longitude")))
                        tz_name = value.get("timezone", TZ_FALLBACK)
                        if lat is not None and lon is not None:
                            return float(lat), float(lon), str(tz_name)

            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name", item.get("location", ""))
                    if str(name).strip().lower() == location_key:
                        lat = item.get("lat", item.get("latitude"))
                        lon = item.get("lon", item.get("lng", item.get("longitude")))
                        tz_name = item.get("timezone", TZ_FALLBACK)
                        if lat is not None and lon is not None:
                            return float(lat), float(lon), str(tz_name)
        except Exception:
            continue

    raise ValueError(f"Could not resolve coordinates for location: {location_name}")


# ============================================================
# PLOTTING HELPERS
# ============================================================
def _apply_window_axis(ax, start: pd.Timestamp, end: pd.Timestamp) -> None:
    tzinfo = start.tzinfo
    ticks = _window_ticks(start, end)
    ax.set_xlim(start.to_pydatetime(), end.to_pydatetime())
    ax.set_xticks([t.to_pydatetime() for t in ticks])
    ax.xaxis.set_major_formatter(mdates.DateFormatter(_fmt_hour(), tz=tzinfo))
    ax.tick_params(axis="x", rotation=0, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_ylim(0, 10.4)
    ax.grid(True, alpha=0.22)


def _score_band_label(score10: float) -> str:
    if score10 >= 7.5:
        return "Excellent"
    if score10 >= 6.0:
        return "Good"
    if score10 >= 4.5:
        return "Fair"
    return "Poor"


def _moon_y(altitude: float) -> float:
    return float(np.clip((altitude + 10.0) / 10.0, 0.0, 10.0))


def _moon_phase_fraction_from_row(row: pd.Series) -> float:
    illum = float(np.clip(row.get("moon_illumination", 0.5), 0.0, 1.0))
    phase_name = str(row.get("moon_phase_name", "")).lower()
    base = (1.0 - math.sqrt(max(0.0, 1.0 - illum))) / 2.0
    if "waxing crescent" in phase_name:
        return 0.125 - base * 0.5
    if "first quarter" in phase_name:
        return 0.25
    if "waxing gibbous" in phase_name:
        return 0.25 + base * 0.5
    if "full moon" in phase_name:
        return 0.5
    if "waning gibbous" in phase_name:
        return 0.5 + base * 0.5
    if "last quarter" in phase_name:
        return 0.75
    if "waning crescent" in phase_name:
        return 0.875 + base * 0.5
    return 0.0


def _draw_moon_phase_icon(ax, x, y, phase_fraction: float, size: int = 11) -> None:
    phase_fraction = float(phase_fraction) % 1.0

    MOON_OUTLINE = "#4b5563"
    MOON_DARK = "#23313a"
    MOON_LIGHT = "#f4f1e8"
    MOON_FULL = "#fbf8ef"

    da = DrawingArea(size, size, 0, 0)
    r = size / 2.0 - 1.0
    cx = cy = size / 2.0

    base = Circle((cx, cy), r, facecolor=MOON_DARK, edgecolor=MOON_OUTLINE, linewidth=0.75)
    da.add_artist(base)

    p = phase_fraction
    if p < 0.02 or p > 0.98:
        pass
    elif abs(p - 0.5) < 0.02:
        bright = Circle((cx, cy), r - 0.05, facecolor=MOON_FULL, edgecolor="none")
        da.add_artist(bright)
    else:
        illum = 0.5 * (1 - math.cos(2 * math.pi * p))
        waxing = p < 0.5
        bright = Circle((cx, cy), r - 0.05, facecolor=MOON_LIGHT, edgecolor="none")
        da.add_artist(bright)
        shadow_w = max(0.7, (1.0 - illum) * 2.0 * r)
        shadow_cx = cx - (r - shadow_w / 2.0) if waxing else cx + (r - shadow_w / 2.0)
        shadow = Ellipse((shadow_cx, cy), shadow_w, 2.0 * r, facecolor=MOON_DARK, edgecolor="none")
        da.add_artist(shadow)
        if abs(p - 0.25) < 0.04 or abs(p - 0.75) < 0.04:
            terminator = Ellipse((cx, cy), 0.55, 2.0 * r, facecolor=MOON_OUTLINE, edgecolor="none", alpha=0.16)
            da.add_artist(terminator)

    border = Circle((cx, cy), r, facecolor="none", edgecolor=MOON_OUTLINE, linewidth=0.75)
    da.add_artist(border)

    ab = AnnotationBbox(da, (x, y), frameon=False, box_alignment=(0.5, 0.5), pad=0.0, zorder=9, annotation_clip=False)
    ax.add_artist(ab)


def _nearest_row(df: pd.DataFrame, target_time: pd.Timestamp) -> Optional[pd.Series]:
    if df.empty:
        return None
    work = df.copy()
    deltas = (work["time"] - target_time).abs()
    idx = deltas.idxmin()
    return work.loc[idx]


def _interpolated_row(df: pd.DataFrame, target_time: pd.Timestamp) -> Optional[pd.Series]:
    if df.empty:
        return None

    work = df.sort_values("time").reset_index(drop=True).copy()
    target_time = pd.Timestamp(target_time)

    if target_time <= pd.Timestamp(work.iloc[0]["time"]):
        row = work.iloc[0].copy()
        row["time"] = target_time
        return row
    if target_time >= pd.Timestamp(work.iloc[-1]["time"]):
        row = work.iloc[-1].copy()
        row["time"] = target_time
        return row

    earlier = work[work["time"] <= target_time].tail(1)
    later = work[work["time"] >= target_time].head(1)
    if earlier.empty or later.empty:
        return _nearest_row(work, target_time)

    left = earlier.iloc[0].copy()
    right = later.iloc[0].copy()
    t0 = pd.Timestamp(left["time"])
    t1 = pd.Timestamp(right["time"])

    if t0 == t1:
        left["time"] = target_time
        return left

    frac = (target_time.value - t0.value) / (t1.value - t0.value)
    frac = float(np.clip(frac, 0.0, 1.0))

    row = left.copy()
    row["time"] = target_time
    for col in ["moon_altitude", "moon_azimuth", "moon_illumination", "score", "score10", "cloud_cover", "visibility_km", "haze_proxy"]:
        if col in work.columns:
            try:
                lv = float(left[col])
                rv = float(right[col])
                row[col] = lv + (rv - lv) * frac
            except Exception:
                pass

    if frac >= 0.5:
        for col in ["moon_phase_name", "moon_phase_emoji", "moon_source", "period"]:
            if col in work.columns:
                row[col] = right.get(col, left.get(col))
    return row


def _representative_moon_row(df: pd.DataFrame) -> Optional[pd.Series]:
    if df.empty:
        return None
    visible = df[df["moon_altitude"] > 0].copy()
    if not visible.empty:
        return visible.sort_values(["moon_altitude", "score"], ascending=[False, False]).iloc[0]
    mid_time = df["time"].min() + (df["time"].max() - df["time"].min()) / 2
    return _nearest_row(df, pd.Timestamp(mid_time))


def _is_night_window(title: str) -> bool:
    lowered = str(title).lower()
    return ("night" in lowered) or ("tonight" in lowered) or ("6pm–6am" in lowered) or ("6pm-6am" in lowered)


def _add_orientation_labels(ax, title: str) -> None:
    if not _is_night_window(title):
        return
    ax.text(0.01, 0.96, "W", transform=ax.transAxes, ha="left", va="top", fontsize=8, fontweight="bold", color="#455a64")
    ax.text(0.99, 0.96, "E", transform=ax.transAxes, ha="right", va="top", fontsize=8, fontweight="bold", color="#455a64")


def _add_three_hour_moon_markers(
    ax,
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    now_local: pd.Timestamp,
    size: int = 9,
    elapsed_only: bool = False,
) -> None:
    if df.empty:
        return

    tick_times = _window_ticks(start, end)
    if elapsed_only:
        tick_times = [t for t in tick_times if t <= now_local]

    for tick in tick_times:
        row = _interpolated_row(df, pd.Timestamp(tick))
        if row is None:
            continue
        _draw_moon_phase_icon(
            ax,
            pd.Timestamp(row["time"]),
            _moon_y(float(row.get("moon_altitude", -10))),
            _moon_phase_fraction_from_row(row),
            size=size,
        )


def _add_now_moon_marker(ax, df: pd.DataFrame, now_local: pd.Timestamp) -> None:
    row = _interpolated_row(df, now_local)
    if row is None:
        return

    x = pd.Timestamp(row["time"])
    y = _moon_y(float(row.get("moon_altitude", -10)))
    phase_fraction = _moon_phase_fraction_from_row(row)

    _draw_moon_phase_icon(ax, x, y, phase_fraction, size=14)
    ax.scatter([x], [y], s=145, facecolors="none", edgecolors="#263238", linewidths=1.8, zorder=11)
    ax.annotate(
        "Now",
        (x, y),
        xytext=(0, 12),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=7.2,
        fontweight="bold",
        color="#263238",
        zorder=12,
    )


def _add_moon_marker_with_label(ax, row: pd.Series) -> None:
    if row is None:
        return
    x = row["time"]
    y = _moon_y(float(row.get("moon_altitude", -10)))
    phase_fraction = _moon_phase_fraction_from_row(row)
    phase_name = str(row.get("moon_phase_name", "Moon"))
    _draw_moon_phase_icon(ax, x, y, phase_fraction, size=11)
    ax.annotate(
        phase_name,
        (x, y),
        xytext=(0, 10),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=6.8,
        fontweight="bold",
        color="#37474f",
        zorder=10,
    )


def _plot_single_window(
    ax,
    df: pd.DataFrame,
    title: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    now_local: pd.Timestamp,
    show_now_line: bool = True,
    show_runtime_moon: bool = False,
) -> None:
    if df.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes, fontsize=11)
        ax.set_title(title, fontsize=9.8, pad=8)
        _apply_window_axis(ax, start, end)
        return

    df = df.sort_values("time").copy()
    x = df["time"]
    moon_line = np.clip((df["moon_altitude"] + 10) / 10.0, 0, 10)
    now_in_window = bool(start <= now_local <= end)
    night_window = _is_night_window(title)

    ax.plot(x, df["score10"], color=COLOR_SCORE, linewidth=2.7, linestyle="-", label="Score /10", zorder=3)
    ax.plot(x, df["cloud_cover"] / 10.0, color=COLOR_CLOUD, linewidth=1.9, linestyle="--", label="Cloud /10", zorder=2)
    ax.plot(x, np.clip(df["visibility_km"], 0, 10), color=COLOR_VIS, linewidth=1.8, linestyle="-.", label="Visibility", zorder=2)
    ax.plot(x, np.clip(df["haze_proxy"] / 10.0, 0, 10), color=COLOR_HAZE, linewidth=1.8, linestyle=":", label="Haze /10", zorder=2)

    if now_in_window:
        past_mask = df["time"] <= now_local
        future_mask = df["time"] >= now_local
        if past_mask.any():
            ax.plot(
                x.loc[past_mask],
                moon_line.loc[past_mask],
                color=COLOR_MOON,
                linewidth=2.25,
                linestyle="-",
                label="Moon path (past)",
                zorder=2,
            )
        if future_mask.any():
            ax.plot(
                x.loc[future_mask],
                moon_line.loc[future_mask],
                color=COLOR_MOON,
                linewidth=1.95,
                linestyle="--",
                alpha=0.8,
                label="Moon path (ahead)",
                zorder=2,
            )
    else:
        ax.plot(x, moon_line, color=COLOR_MOON, linewidth=2.1, linestyle="-", label="Moon path", zorder=2)

    if show_now_line and now_in_window:
        ax.axvline(now_local.to_pydatetime(), color=COLOR_RUNTIME, linestyle=":", linewidth=1.7, zorder=5)

    _add_three_hour_moon_markers(
        ax,
        df,
        start,
        end,
        now_local,
        size=9 if night_window else 8,
        elapsed_only=bool(now_in_window and night_window),
    )

    if show_runtime_moon and now_in_window:
        _add_now_moon_marker(ax, df, now_local)
    else:
        marker_row = _representative_moon_row(df)
        if marker_row is not None:
            _add_moon_marker_with_label(ax, marker_row)

    # Draw best-time X last so it always sits above moon markers and labels.
    best = best_hour_row(df)
    if best is not None:
        bx = best["time"]
        by = float(best["score10"])
        ax.scatter([bx], [by], marker="x", s=95, linewidths=2.3, color="black", zorder=20)
        ax.annotate(
            f"X {best['score10']:.1f}/10",
            (bx, by),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.8,
            fontweight="bold",
            color="black",
            zorder=20,
        )

    avg_score = float(df["score10"].mean())
    best_score = float(df["score10"].max())
    subtitle = f"Avg {avg_score:.1f}/10  |  Best {best_score:.1f}/10  |  {_score_band_label(best_score)}"
    ax.set_title(f"{title}\n{subtitle}", fontsize=9.6, pad=8)

    _apply_window_axis(ax, start, end)
    _add_orientation_labels(ax, title)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=6, fontsize=6.2, frameon=False, handlelength=2.25, columnspacing=0.8)

def _weekly_reference_times(df: pd.DataFrame, period: str, tz_name: str) -> pd.DataFrame:
    work = df.copy()
    work["period"] = work["time"].apply(day_night_label)
    work["date_local"] = work["time"].apply(period_anchor_date)
    work = work[work["period"] == period].copy()
    if work.empty:
        return pd.DataFrame(columns=["date_local", "moon_phase_name", "moon_phase_fraction"])

    rows: list[dict[str, Any]] = []
    for date_local, grp in work.groupby("date_local"):
        ref_row = _representative_moon_row(grp)
        if ref_row is None:
            continue
        rows.append({
            "date_local": pd.Timestamp(date_local),
            "moon_phase_name": str(ref_row.get("moon_phase_name", "Moon")),
            "moon_phase_fraction": float(_moon_phase_fraction_from_row(ref_row)),
        })
    return pd.DataFrame(rows)


def _best_window_from_weekly(df: pd.DataFrame, period: str) -> tuple[pd.DataFrame, str]:
    """
    Return the exact hourly window and display label for the strongest weekly day/night period.
    This avoids label round-tripping so the "Next Best Night" chart cannot come back empty.
    """
    work = df.copy()
    work["period"] = work["time"].apply(day_night_label)
    work["anchor_date"] = work["time"].apply(period_anchor_date)
    work = work[work["period"] == period].copy()

    if work.empty:
        return work.iloc[0:0].copy(), "N/A"

    g = work.groupby("anchor_date").agg(
        avg_score=("score10", "mean"),
        max_score=("score10", "max"),
    ).reset_index()

    if g.empty:
        return work.iloc[0:0].copy(), "N/A"

    best = g.sort_values(["avg_score", "max_score", "anchor_date"], ascending=[False, False, True]).iloc[0]
    chosen_anchor = best["anchor_date"]
    out_df = work[work["anchor_date"] == chosen_anchor].sort_values("time").copy()
    label = pd.Timestamp(chosen_anchor).strftime("%a %d %b")
    return out_df, label


def _weekly_best_label(df: pd.DataFrame, period: str) -> str:
    _, label = _best_window_from_weekly(df, period)
    return label


def _window_df_from_label(df: pd.DataFrame, period: str, label: str) -> pd.DataFrame:
    if not label or label == "N/A":
        return df.iloc[0:0].copy()

    work = df.copy()
    work["period"] = work["time"].apply(day_night_label)
    work["anchor_date"] = work["time"].apply(period_anchor_date)
    label_series = pd.to_datetime(work["anchor_date"]).dt.strftime("%a %d %b")
    return work[(work["period"] == period) & (label_series == label)].sort_values("time").copy()



def _weekly_bar_plot(ax, df: pd.DataFrame, period: str, title: str, tz_name: str, highlight_label: str = "") -> str:
    work = df.copy()
    work["period"] = work["time"].apply(day_night_label)
    work["date_local"] = work["time"].apply(period_anchor_date)
    work = work[work["period"] == period].copy()

    if work.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontsize=10.2, pad=8)
        return "N/A"

    g = work.groupby("date_local").agg(
        avg_score=("score10", "mean"),
        best_score=("score10", "max"),
    ).reset_index()
    g["date_local"] = pd.to_datetime(g["date_local"])

    moon_refs = _weekly_reference_times(df, period, tz_name)
    if not moon_refs.empty:
        g = g.merge(moon_refs, on="date_local", how="left")
    else:
        g["moon_phase_name"] = "Moon"
        g["moon_phase_fraction"] = 0.0

    g = g.sort_values("date_local").reset_index(drop=True)
    x = np.arange(len(g))
    highlight_ts = pd.to_datetime(highlight_label, format="%a %d %b", errors="coerce") if highlight_label else pd.NaT
    bar_colors = []
    for _, row in g.iterrows():
        row_day = pd.Timestamp(row["date_local"])
        if pd.notna(highlight_ts) and row_day.month == highlight_ts.month and row_day.day == highlight_ts.day:
            bar_colors.append(COLOR_WEEK_BAR_HIGHLIGHT)
        else:
            bar_colors.append(COLOR_WEEK_BAR)

    ax.bar(x, g["avg_score"], width=0.62, color=bar_colors, edgecolor="#455a64", linewidth=1.0)

    x_best = int(np.argmax(g["avg_score"].to_numpy()))
    best_row = g.iloc[x_best]

    for i, (_, row) in enumerate(g.iterrows()):
        value = float(row["avg_score"])
        ax.annotate(
            f"{value:.1f}/10",
            (i, value),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.6,
            fontweight="bold",
        )
        _draw_moon_phase_icon(
            ax,
            i,
            min(value + 0.7, 10.05),
            float(row.get("moon_phase_fraction", 0.0)),
            size=10,
        )

    ax.scatter([x_best], [float(best_row["avg_score"])], marker="x", s=95, linewidths=2.2, color="black", zorder=6)
    ax.annotate(
        f"X {float(best_row['avg_score']):.1f}/10",
        (x_best, float(best_row["avg_score"])),
        xytext=(0, 12),
        textcoords="offset points",
        ha="center",
        fontsize=7.8,
        fontweight="bold",
    )

    ax.set_ylim(0, 10.4)
    ax.set_title(title, fontsize=10.0, pad=8)
    ax.grid(True, axis="y", alpha=0.22)
    ax.set_xticks(x)
    ax.set_xticklabels([pd.Timestamp(d).strftime("%a\n%d") for d in g["date_local"]], fontsize=8)
    ax.tick_params(axis="y", labelsize=8)   

# ============================================================
# COMET WATCH
# ============================================================
def _comet_watch_items(report_run_time: pd.Timestamp) -> list[dict[str, str]]:
    now = pd.Timestamp(report_run_time)

    items: list[dict[str, str]] = []

    # C/2026 A1 (MAPS) — conditional visibility after perihelion
    maps_start = pd.Timestamp("2026-04-07", tz=now.tz)
    maps_end = pd.Timestamp("2026-04-20", tz=now.tz)
    if maps_start <= now <= maps_end:
        items.append({
            "name": "C/2026 A1 (MAPS)",
            "window": "7–20 Apr",
            "direction": "Low west after sunset",
            "confidence": "Uncertain",
            "note": "May become visible if it survives perihelion; binoculars may help. Do not observe near the Sun.",
        })

    # C/2025 R3 (PanSTARRS) — late-April candidate
    r3_start = pd.Timestamp("2026-04-13", tz=now.tz)
    r3_end = pd.Timestamp("2026-04-30", tz=now.tz)
    if r3_start <= now <= r3_end:
        items.append({
            "name": "C/2025 R3 (PanSTARRS)",
            "window": "13–30 Apr",
            "direction": "Best chance low after sunset / evening twilight",
            "confidence": "Possible",
            "note": "Late-April comet candidate; brightness remains uncertain.",
        })

    return items


def _comet_watch_summary(report_run_time: pd.Timestamp) -> str:
    items = _comet_watch_items(report_run_time)
    if not items:
        return "Comet watch: No notable comet alert in the current report window."

    parts: list[str] = []
    for item in items:
        parts.append(
            f"{item['name']} ({item['window']}): {item['direction']} — {item['confidence']}. {item['note']}"
        )
    return "Comet watch: " + " | ".join(parts)

# ============================================================
# CHART BUILD
# ============================================================
def build_charts(
    df: pd.DataFrame,
    location_name: str,
    tz_name: str,
    moon_meta: dict[str, Any],
    report_run_time: pd.Timestamp,
    logger=None,
) -> tuple[BytesIO, BytesIO, dict[str, str]]:
    now_local = _ensure_tz(report_run_time, tz_name)

    today_start = _day_window_start(now_local, tz_name)
    today_end = _day_window_end(now_local, tz_name)
    tonight_start = _night_window_start(now_local, tz_name)
    tonight_end = _night_window_end(now_local, tz_name)

    today_df = slice_window(df, today_start, today_end)
    tonight_df = slice_window(df, tonight_start, tonight_end)

    next_best_day_df, next_best_day_label = _best_window_from_weekly(df, "day")
    next_best_night_df, next_best_night_label = _best_window_from_weekly(df, "night")

    next_best_day_start = _day_window_start(next_best_day_df["time"].min(), tz_name) if not next_best_day_df.empty else today_start + pd.Timedelta(days=1)
    next_best_day_end = _day_window_end(next_best_day_df["time"].min(), tz_name) if not next_best_day_df.empty else today_end + pd.Timedelta(days=1)
    next_best_night_start = _night_window_start(next_best_night_df["time"].min(), tz_name) if not next_best_night_df.empty else tonight_start + pd.Timedelta(days=1)
    next_best_night_end = _night_window_end(next_best_night_df["time"].min(), tz_name) if not next_best_night_df.empty else tonight_end + pd.Timedelta(days=1)

    if moon_meta.get("astral_points", 0) > 0 and moon_meta.get("fallback_points", 0) == 0:
        track_status = "Moon track: Astral live tracking active"
    elif moon_meta.get("astral_points", 0) > 0:
        track_status = (
            f"Moon track: Astral active with fallback on some points "
            f"({moon_meta.get('astral_points', 0)} Astral / {moon_meta.get('fallback_points', 0)} fallback)"
        )
    else:
        track_status = f"Moon track: live computed altitude active (Astral unavailable: {moon_meta.get('first_fallback_reason') or ASTRAL_IMPORT_ERROR or 'not installed'})"

    header_meta = {
        "track_status": track_status,
        "phase": f"Moon phase now: {moon_phase_name(now_local.to_pydatetime())}",
        "next_best_day": next_best_day_label,
        "next_best_night": next_best_night_label,
        "report_run": now_local.strftime("%a %d %b %Y %I:%M:%S %p %Z"),
    }

    fig1, axes1 = plt.subplots(4, 1, figsize=(11.4, 13.2))
    fig1.suptitle(f"Sky Report — {location_name}", fontsize=13.2, fontweight="bold", y=0.988)
    _plot_single_window(axes1[0], today_df, "Today (Day) 6AM–6PM", today_start, today_end, now_local, True, True)
    _plot_single_window(axes1[1], tonight_df, "Tonight 6PM–6AM", tonight_start, tonight_end, now_local, True, True)
    _plot_single_window(axes1[2], next_best_day_df, f"Next Best Day — {next_best_day_label}", next_best_day_start, next_best_day_end, now_local, False, False)
    _plot_single_window(axes1[3], next_best_night_df, f"Next Best Night — {next_best_night_label}", next_best_night_start, next_best_night_end, now_local, False, False)
    fig1.subplots_adjust(left=0.065, right=0.985, top=0.95, bottom=0.055, hspace=0.78)
    page1 = BytesIO()
    fig1.savefig(page1, format="png", dpi=FIG_DPI)
    plt.close(fig1)
    page1.seek(0)

    fig2, axes2 = plt.subplots(2, 1, figsize=(11.4, 10.6))
    fig2.suptitle(f"Weekly Sky Trends — {location_name}", fontsize=13.2, fontweight="bold", y=0.985)
    weekly_best_day = _weekly_bar_plot(axes2[0], df, "day", "Weekly Day Trend (6AM–6PM)", tz_name, next_best_day_label)
    weekly_best_night = _weekly_bar_plot(axes2[1], df, "night", "Weekly Night Trend (6PM–6AM)", tz_name, next_best_night_label)
    header_meta["weekly_best_day"] = weekly_best_day
    header_meta["weekly_best_night"] = weekly_best_night
    header_meta["next_best_day"] = weekly_best_day
    header_meta["next_best_night"] = weekly_best_night
    fig2.subplots_adjust(left=0.065, right=0.985, top=0.93, bottom=0.07, hspace=0.42)
    page2 = BytesIO()
    fig2.savefig(page2, format="png", dpi=FIG_DPI)
    plt.close(fig2)
    page2.seek(0)

    _log(logger, header_meta["track_status"])
    _log(logger, header_meta["phase"])
    _log(logger, f"Next best day: {header_meta['next_best_day']}")
    _log(logger, f"Next best night: {header_meta['next_best_night']}")
    return page1, page2, header_meta


# ============================================================
# PDF
# ============================================================
# ============================================================
# PDF
# ============================================================
def build_pdf(
    location_name: str,
    tz_name: str,
    page1: BytesIO,
    page2: BytesIO,
    header_meta: dict[str, str],
    output_path: Path,
) -> str:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=15, leading=17, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=8.2, leading=9.3, spaceAfter=2)
    small2 = ParagraphStyle("small2", parent=styles["BodyText"], fontSize=7.8, leading=8.8, spaceAfter=1.5)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=0.9 * cm,
        rightMargin=0.9 * cm,
        topMargin=0.8 * cm,
        bottomMargin=0.8 * cm,
    )

    story = []
    story.append(Paragraph(f"Sky Report — {location_name}", title_style))
    story.append(Paragraph(f"Time zone: {tz_name}", small))
    story.append(Paragraph(header_meta.get("track_status", "Moon track status unavailable"), small))
    story.append(Paragraph(header_meta.get("phase", "Moon phase now: N/A"), small))
    story.append(
        Paragraph(
            f"Next best day: {header_meta.get('next_best_day', 'N/A')} &nbsp;&nbsp;&nbsp; "
            f"Next best night: {header_meta.get('next_best_night', 'N/A')}",
            small,
        )
    )
    story.append(Paragraph(header_meta.get("comet_watch", "Comet watch: No notable comet alert in the current report window."), small2))
    story.append(Paragraph(f"Report run: {header_meta.get('report_run', 'N/A')}", small2))
    story.append(Spacer(1, 0.08 * cm))
    story.append(Image(page1, width=PAGE_IMAGE_WIDTH_CM * cm, height=PAGE1_IMAGE_HEIGHT_CM * cm))

    story.append(PageBreak())
    story.append(Paragraph(f"Weekly Sky Trends — {location_name}", title_style))
    story.append(
        Paragraph(
            "The weekly charts summarise average score out of 10 for each day and night window. "
            "The X marks the strongest overall period, and the moon icon above each bar shows the representative moon phase for that window.",
            small2,
        )
    )
    story.append(Spacer(1, 0.05 * cm))
    story.append(Image(page2, width=PAGE_IMAGE_WIDTH_CM * cm, height=PAGE2_IMAGE_HEIGHT_CM * cm))

    doc.build(story)
    return str(output_path)


# ============================================================
# PUBLIC ENTRYPOINT
# ============================================================
def generate_report(location_name: str, coords: list[float] | tuple[float, float] | dict[str, Any] | None = None, output_dir: str | Path | None = None, logger: Optional[Callable[[str], None]] = None) -> str:
    tz_name = TZ_FALLBACK

    if coords is not None:
        if isinstance(coords, dict):
            lat = float(coords.get("latitude", coords.get("lat")))
            lon = float(coords.get("longitude", coords.get("lon", coords.get("lng"))))
            tz_name = str(coords.get("timezone") or TZ_FALLBACK)
        else:
            lat = float(coords[0])
            lon = float(coords[1])
    else:
        lat, lon, tz_name = _load_coords_from_locations_json(location_name)
        _log(logger, f"Resolved coords from locations.json: {lat}, {lon}")

    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in (" ", "-", "_", ",") else "_" for ch in location_name).strip().replace("  ", " ")
    pdf_path = out_dir / f"Sky Report - {safe_name}.pdf"

    report_run_time = pd.Timestamp.now(tz=ZoneInfo(tz_name)).floor("min")

    _log(logger, f"Running Sky for {location_name}.")
    _log(logger, f"Using timezone: {tz_name}")

    df = fetch_weather_data(lat, lon, tz_name, logger=logger)
    if df.empty:
        raise ValueError("SKY worker fetch returned no data")

    moon_df, moon_meta = build_moon_track(df["time"], lat, lon, location_name, tz_name, logger=logger)
    if moon_df.empty or len(moon_df) < 12:
        raise ValueError("Moon track generation returned too few valid points")

    merged = df.merge(moon_df, on="time", how="left")
    merged = compute_sky_scores(merged)

    page1, page2, header_meta = build_charts(merged, location_name=location_name, tz_name=tz_name, moon_meta=moon_meta, report_run_time=report_run_time, logger=logger)
    result = build_pdf(location_name=location_name, tz_name=tz_name, page1=page1, page2=page2, header_meta=header_meta, output_path=pdf_path)

    if not Path(result).exists() or Path(result).stat().st_size < 1000:
        raise ValueError("Generated Sky PDF is missing or too small")

    _log(logger, f"SKY PDF OK: {result}")
    return result


if __name__ == "__main__":
    def log(msg: str) -> None:
        print(msg)

    sample = generate_report("Bells Beach, VIC", [-38.3706, 144.2833], output_dir=OUTPUT_DIR, logger=log)
    print(sample)
