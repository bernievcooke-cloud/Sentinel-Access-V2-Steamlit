#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import platform
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

load_dotenv()
WILLY_API_KEY = os.getenv("WILLY_API_KEY", "").strip()

# ============================================================
# DEFAULT CONFIG
# ============================================================
LOCATION_NAME = "Bells Beach"
LAT = -38.371
LON = 144.281
STATE_HINT: str | None = "VIC"

REPORT_TZ = ZoneInfo("Australia/Melbourne")

BEACH_ORIENTATION_DEG = 210
PREFERRED_SWELL_DIR_MIN = 170
PREFERRED_SWELL_DIR_MAX = 235
PREFERRED_SWELL_MIN_M = 0.8
PREFERRED_SWELL_MAX_M = 2.8

# Leave as None to disable tide scoring
PREFERRED_TIDE_MIN_M = None
PREFERRED_TIDE_MAX_M = None

FORECAST_DAYS = 7
REQUEST_TIMEOUT = 20

LOCAL_DIR = (
    r"C:\RuralAI\OUTPUT\SURF"
    if platform.system() == "Windows"
    else os.path.join(os.path.expanduser("~"), "Documents", "Surf Reports")
)
os.makedirs(LOCAL_DIR, exist_ok=True)


# ============================================================
# HELPERS
# ============================================================
def make_safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name.replace(" ", "_"))


def make_filename(location_name: str) -> str:
    return f"{make_safe_name(location_name)}_Surf_Forecast.pdf"


def now_local() -> datetime:
    return datetime.now(REPORT_TZ)


def parse_local_times(series: pd.Series) -> pd.Series:
    """
    Parse forecast timestamps safely across DST transitions.

    Open-Meteo with timezone=Australia/Melbourne typically returns local
    wall-clock times already. Treat naive values as local display times and
    keep them naive, which avoids AmbiguousTimeError on the DST fallback hour.
    If values are timezone-aware, convert to REPORT_TZ and then drop tz info
    so the rest of the worker continues to use consistent local naive times.
    """
    dt = pd.to_datetime(series, errors="coerce")

    if getattr(dt.dt, "tz", None) is None:
        return dt

    return dt.dt.tz_convert(REPORT_TZ).dt.tz_localize(None)


def deg_to_text(deg: float | int | None) -> str:
    if deg is None or pd.isna(deg):
        return ""
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    return dirs[int((float(deg) + 11.25) // 22.5) % 16]


def deg_to_cardinal_4(deg: float | int | None) -> str:
    if deg is None or pd.isna(deg):
        return ""
    deg = float(deg) % 360
    if deg >= 315 or deg < 45:
        return "N"
    if deg < 135:
        return "E"
    if deg < 225:
        return "S"
    return "W"


def angular_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def in_direction_window(value: float, low: float, high: float) -> bool:
    value = value % 360
    low = low % 360
    high = high % 360
    if low <= high:
        return low <= value <= high
    return value >= low or value <= high


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def circular_mean_deg(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None and not pd.isna(v)]
    if not clean:
        return None
    radians = np.deg2rad(clean)
    sin_sum = np.sin(radians).mean()
    cos_sum = np.cos(radians).mean()
    angle = math.degrees(math.atan2(sin_sum, cos_sum)) % 360
    return angle


def safe_float_text(value, fmt: str = ".1f", suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:{fmt}}{suffix}"


# ============================================================
# FETCHERS
# ============================================================
def fetch_json(url: str) -> dict:
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_open_meteo_marine(lat: float, lon: float) -> pd.DataFrame:
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=swell_wave_height,swell_wave_direction,wave_period"
        f"&forecast_days={FORECAST_DAYS}"
        "&timezone=Australia/Melbourne"
    )
    data = fetch_json(url)
    hourly = data.get("hourly", {})
    df = pd.DataFrame(hourly)
    if df.empty or "time" not in df.columns:
        raise ValueError("Marine API returned no hourly data.")
    df["time"] = parse_local_times(df["time"])
    return df


def fetch_open_meteo_weather(lat: float, lon: float) -> pd.DataFrame:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wind_speed_10m,wind_direction_10m"
        f"&forecast_days={FORECAST_DAYS}"
        "&timezone=Australia/Melbourne"
    )
    data = fetch_json(url)
    hourly = data.get("hourly", {})
    df = pd.DataFrame(hourly)
    if df.empty or "time" not in df.columns:
        raise ValueError("Forecast API returned no hourly data.")
    df["time"] = parse_local_times(df["time"])
    return df.rename(
        columns={
            "wind_speed_10m": "wind_speed_10m_main",
            "wind_direction_10m": "wind_direction_10m_main",
        }
    )


def fetch_bom_access_g_weather(lat: float, lon: float) -> pd.DataFrame | None:
    try:
        url = (
            "https://api.open-meteo.com/v1/bom"
            f"?latitude={lat}&longitude={lon}"
            "&hourly=wind_speed_10m,wind_direction_10m"
            f"&forecast_days={FORECAST_DAYS}"
            "&timezone=Australia/Melbourne"
        )
        data = fetch_json(url)
        hourly = data.get("hourly", {})
        df = pd.DataFrame(hourly)
        if df.empty or "time" not in df.columns:
            return None
        df["time"] = parse_local_times(df["time"])
        return df.rename(
            columns={
                "wind_speed_10m": "wind_speed_10m_bom",
                "wind_direction_10m": "wind_direction_10m_bom",
            }
        )
    except Exception:
        return None


# ============================================================
# WILLYWEATHER
# ============================================================
def willy_headers(payload: dict) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-payload": json.dumps(payload),
    }


def get_willyweather_location(lat: float, lon: float) -> tuple[int, str]:
    if not WILLY_API_KEY:
        raise ValueError("Missing WILLY_API_KEY")

    url = f"https://api.willyweather.com.au/v2/{WILLY_API_KEY}/search.json"
    payload = {
        "lat": float(lat),
        "lng": float(lon),
        "range": 10,
        "units": {"distance": "km"},
    }

    r = requests.get(url, headers=willy_headers(payload), timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()

    location = data.get("location")
    if not location:
        raise ValueError("No WillyWeather location found for coordinates")

    location_id = location.get("id")
    location_name = location.get("name", "Unknown")

    if location_id is None:
        raise ValueError("WillyWeather location response missing id")

    return int(location_id), str(location_name)


def fetch_willyweather_tide_events(lat: float, lon: float) -> tuple[pd.DataFrame, dict]:
    if not WILLY_API_KEY:
        raise ValueError("Missing WILLY_API_KEY")

    location_id, location_name = get_willyweather_location(lat, lon)

    url = f"https://api.willyweather.com.au/v2/{WILLY_API_KEY}/locations/{location_id}/weather.json"
    payload = {
        "forecasts": ["tides"],
        "days": FORECAST_DAYS,
        "startDate": now_local().strftime("%Y-%m-%d"),
    }

    r = requests.get(url, headers=willy_headers(payload), timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()

    tides_block = data.get("forecasts", {}).get("tides", {})
    days = tides_block.get("days", [])

    rows: list[dict] = []
    for day in days:
        for entry in day.get("entries", []):
            dt = pd.to_datetime(entry.get("dateTime"), errors="coerce")
            if pd.isna(dt):
                continue

            if getattr(dt, "tzinfo", None) is None:
                dt = dt.tz_localize(
                    REPORT_TZ,
                    ambiguous=False,
                    nonexistent="shift_forward",
                ).tz_localize(None)
            else:
                dt = dt.tz_convert(REPORT_TZ).tz_localize(None)

            rows.append(
                {
                    "time": dt,
                    "tide_height": pd.to_numeric(entry.get("height", np.nan), errors="coerce"),
                    "type": str(entry.get("type", "")).lower(),
                }
            )

    if not rows:
        raise ValueError(f"No tide entries returned for WillyWeather location {location_name}")

    tide_df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    tide_df["tide_is_high"] = tide_df["type"] == "high"
    tide_df["tide_is_low"] = tide_df["type"] == "low"

    diagnostics = {
        "tide_source": "WillyWeather API",
        "tide_station": f"{location_name} (id {location_id})",
        "tide_station_distance_km": "nearest WillyWeather location",
        "tide_notes": "Live tide data via WillyWeather API",
    }
    return tide_df, diagnostics


def add_real_tide(df: pd.DataFrame, lat: float, lon: float, state_hint=None):
    diagnostics = {
        "tide_source": "Unavailable",
        "tide_station": f"{lat:.3f}, {lon:.3f}",
        "tide_station_distance_km": "",
        "tide_notes": "Tide not requested yet",
    }

    try:
        tide_events, tide_diag = fetch_willyweather_tide_events(lat, lon)
        diagnostics.update(tide_diag)

        base = df.sort_values("time").copy()
        base["tide_height"] = np.nan
        base["tide_is_high"] = False
        base["tide_is_low"] = False

        tide_numeric = tide_events.dropna(subset=["tide_height"]).copy()
        if len(tide_numeric) >= 2:
            src_x = tide_numeric["time"].astype("int64").to_numpy()
            src_y = tide_numeric["tide_height"].astype(float).to_numpy()
            dst_x = base["time"].astype("int64").to_numpy()

            interp = np.interp(dst_x, src_x, src_y, left=np.nan, right=np.nan)

            min_x = src_x.min()
            max_x = src_x.max()
            interp[(dst_x < min_x) | (dst_x > max_x)] = np.nan
            base["tide_height"] = interp
        elif len(tide_numeric) == 1:
            only_time = tide_numeric["time"].iloc[0]
            only_height = float(tide_numeric["tide_height"].iloc[0])
            nearest_idx = (base["time"] - only_time).abs().idxmin()
            if abs((base.loc[nearest_idx, "time"] - only_time).total_seconds()) <= 3600:
                base.loc[nearest_idx, "tide_height"] = only_height

        for _, event in tide_events.iterrows():
            if not bool(event.get("tide_is_high", False)) and not bool(event.get("tide_is_low", False)):
                continue

            deltas = (base["time"] - event["time"]).abs()
            nearest_idx = deltas.idxmin()
            if pd.isna(nearest_idx):
                continue

            if deltas.loc[nearest_idx] <= pd.Timedelta(minutes=45):
                if bool(event.get("tide_is_high", False)):
                    base.loc[nearest_idx, "tide_is_high"] = True
                if bool(event.get("tide_is_low", False)):
                    base.loc[nearest_idx, "tide_is_low"] = True

        if base["tide_height"].isna().all():
            raise ValueError("Tide interpolation produced no usable tide heights")

        return base, diagnostics

    except Exception as e:
        print(f"TIDE ERROR: {type(e).__name__}: {e}")

        df = df.copy()
        df["tide_height"] = np.nan
        df["tide_is_high"] = False
        df["tide_is_low"] = False

        diagnostics["tide_source"] = "Unavailable"
        diagnostics["tide_notes"] = f"WillyWeather fetch failed: {type(e).__name__}: {e}"

        return df, diagnostics


# ============================================================
# DATA PREP / CONSENSUS
# ============================================================
def build_dataset(
    lat: float,
    lon: float,
    state_hint: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    marine = fetch_open_meteo_marine(lat, lon)
    wx_main = fetch_open_meteo_weather(lat, lon)
    wx_bom = fetch_bom_access_g_weather(lat, lon)

    df = marine.merge(wx_main, on="time", how="inner")

    diagnostics = {
        "marine_source": "Open-Meteo Marine",
        "wind_source_main": "Open-Meteo Forecast",
        "wind_source_secondary": "Open-Meteo BOM ACCESS-G" if wx_bom is not None else "Unavailable",
        "tide_source": "",
        "tide_station": "",
        "tide_station_distance_km": "",
        "tide_notes": "",
        "timezone": "Australia/Melbourne",
    }

    if wx_bom is not None:
        df = df.merge(wx_bom, on="time", how="left")
    else:
        df["wind_speed_10m_bom"] = np.nan
        df["wind_direction_10m_bom"] = np.nan

    df["wind_speed_10m"] = df[["wind_speed_10m_main", "wind_speed_10m_bom"]].mean(axis=1, skipna=True)

    wind_dirs = []
    for _, row in df.iterrows():
        wind_dirs.append(
            circular_mean_deg(
                [
                    row.get("wind_direction_10m_main"),
                    row.get("wind_direction_10m_bom"),
                ]
            )
        )
    df["wind_direction_10m"] = wind_dirs

    def wind_agreement(row: pd.Series) -> float:
        a = row.get("wind_direction_10m_main")
        b = row.get("wind_direction_10m_bom")
        if pd.isna(a) or pd.isna(b):
            return 0.65
        diff = angular_diff(float(a), float(b))
        if diff <= 20:
            return 1.0
        if diff <= 45:
            return 0.8
        if diff <= 70:
            return 0.55
        return 0.3

    df["wind_agreement"] = df.apply(wind_agreement, axis=1)

    df, tide_diag = add_real_tide(df, lat, lon, state_hint=state_hint)
    diagnostics.update(tide_diag)

    df = df.sort_values("time").reset_index(drop=True)
    return df, diagnostics


# ============================================================
# SURF SCORING
# ============================================================
def score_row(row: pd.Series) -> pd.Series:
    reasons: list[str] = []

    swell_h = row.get("swell_wave_height", np.nan)
    swell_dir = row.get("swell_wave_direction", np.nan)
    wave_period = row.get("wave_period", np.nan)
    wind_kmh = row.get("wind_speed_10m", np.nan)
    wind_dir = row.get("wind_direction_10m", np.nan)
    tide_h = row.get("tide_height", np.nan)

    score = 0.0

    swell_score = 0.0
    if not pd.isna(swell_h):
        if PREFERRED_SWELL_MIN_M <= swell_h <= PREFERRED_SWELL_MAX_M:
            swell_score = 30.0
            reasons.append(f"swell size in range ({swell_h:.1f}m)")
        elif swell_h < PREFERRED_SWELL_MIN_M:
            gap = PREFERRED_SWELL_MIN_M - swell_h
            swell_score = max(0.0, 30.0 - gap * 20.0)
            reasons.append(f"swell a bit small ({swell_h:.1f}m)")
        else:
            gap = swell_h - PREFERRED_SWELL_MAX_M
            swell_score = max(0.0, 30.0 - gap * 10.0)
            reasons.append(f"swell a bit oversized ({swell_h:.1f}m)")
    score += swell_score

    swell_dir_score = 0.0
    if not pd.isna(swell_dir):
        if in_direction_window(float(swell_dir), PREFERRED_SWELL_DIR_MIN, PREFERRED_SWELL_DIR_MAX):
            swell_dir_score = 20.0
            reasons.append(f"swell suits break ({deg_to_text(swell_dir)})")
        else:
            diffs = [
                angular_diff(float(swell_dir), PREFERRED_SWELL_DIR_MIN),
                angular_diff(float(swell_dir), PREFERRED_SWELL_DIR_MAX),
            ]
            swell_dir_score = max(0.0, 20.0 - min(diffs) * 0.35)
            reasons.append(f"swell less ideal ({deg_to_text(swell_dir)})")
    score += swell_dir_score

    period_score = 0.0
    if not pd.isna(wave_period):
        if wave_period >= 14:
            period_score = 10.0
            reasons.append(f"long period ({wave_period:.0f}s)")
        elif wave_period >= 10:
            period_score = 7.5
            reasons.append(f"decent period ({wave_period:.0f}s)")
        elif wave_period >= 8:
            period_score = 5.0
        else:
            period_score = 2.0
    score += period_score

    offshore_from_deg = (BEACH_ORIENTATION_DEG + 180) % 360
    wind_score = 0.0
    if not pd.isna(wind_kmh) and not pd.isna(wind_dir):
        alignment = angular_diff(float(wind_dir), offshore_from_deg)

        if alignment <= 30:
            dir_component = 20.0
            reasons.append(f"offshore wind ({deg_to_text(wind_dir)})")
        elif alignment <= 60:
            dir_component = 14.0
            reasons.append(f"cross-offshore wind ({deg_to_text(wind_dir)})")
        elif alignment <= 100:
            dir_component = 7.0
            reasons.append(f"cross-shore wind ({deg_to_text(wind_dir)})")
        else:
            dir_component = 0.0
            reasons.append(f"onshore wind ({deg_to_text(wind_dir)})")

        if wind_kmh <= 12:
            speed_component = 10.0
            reasons.append(f"light wind ({wind_kmh:.0f} km/h)")
        elif wind_kmh <= 20:
            speed_component = 7.0
        elif wind_kmh <= 28:
            speed_component = 4.0
        else:
            speed_component = 1.0
            reasons.append(f"windy ({wind_kmh:.0f} km/h)")

        wind_score = dir_component + speed_component

    score += wind_score

    tide_score = 0.0
    if (
        PREFERRED_TIDE_MIN_M is not None
        and PREFERRED_TIDE_MAX_M is not None
        and not pd.isna(tide_h)
    ):
        if PREFERRED_TIDE_MIN_M <= tide_h <= PREFERRED_TIDE_MAX_M:
            tide_score = 10.0
            reasons.append(f"tide in range ({tide_h:.1f}m)")
        else:
            if tide_h < PREFERRED_TIDE_MIN_M:
                tide_score = max(0.0, 10.0 - (PREFERRED_TIDE_MIN_M - tide_h) * 6.0)
            else:
                tide_score = max(0.0, 10.0 - (tide_h - PREFERRED_TIDE_MAX_M) * 4.0)
            reasons.append(f"tide less ideal ({tide_h:.1f}m)")
    elif (
        PREFERRED_TIDE_MIN_M is not None
        and PREFERRED_TIDE_MAX_M is not None
        and pd.isna(tide_h)
    ):
        reasons.append("tide unavailable")
    score += tide_score

    hour = row["time"].hour
    morning_bonus = 5.0 if 5 <= hour <= 9 else (2.0 if 10 <= hour <= 12 else 0.0)
    if morning_bonus > 0:
        reasons.append("better time-of-day bias")
    score += morning_bonus

    confidence = 0.85
    if pd.isna(swell_h) or pd.isna(swell_dir) or pd.isna(wind_kmh) or pd.isna(wind_dir):
        confidence -= 0.25
    confidence *= float(row.get("wind_agreement", 0.65))
    if pd.isna(tide_h) and PREFERRED_TIDE_MIN_M is not None and PREFERRED_TIDE_MAX_M is not None:
        confidence -= 0.12
    confidence = clamp(confidence, 0.15, 0.98)

    if score >= 75:
        rating = "Good"
    elif score >= 55:
        rating = "Fair"
    elif score >= 38:
        rating = "Marginal"
    else:
        rating = "Poor"

    return pd.Series(
        {
            "surf_score": round(score, 1),
            "surf_rating": rating,
            "confidence": round(confidence, 2),
            "summary_reasons": ", ".join(reasons[:5]),
        }
    )


def find_best_windows(df: pd.DataFrame) -> pd.DataFrame:
    scored = df.copy()
    scored[["surf_score", "surf_rating", "confidence", "summary_reasons"]] = scored.apply(score_row, axis=1)
    return scored


# ============================================================
# DAY SELECTION
# ============================================================
def get_midnight_to_midnight_df(df: pd.DataFrame, target_date) -> pd.DataFrame:
    start = pd.Timestamp(target_date)
    end = start + pd.Timedelta(days=1)
    out = df[(df["time"] >= start) & (df["time"] < end)].copy()
    return out.sort_values("time").reset_index(drop=True)


def get_today_df(df: pd.DataFrame) -> pd.DataFrame:
    today = now_local().date()
    today_df = get_midnight_to_midnight_df(df, today)

    if today_df.empty:
        first_date = df["time"].dt.date.min()
        today_df = get_midnight_to_midnight_df(df, first_date)

    return today_df


def get_next_best_day_df(df: pd.DataFrame) -> pd.DataFrame:
    today = now_local().date()

    daily_best = (
        df.groupby(df["time"].dt.date)["surf_score"]
        .max()
        .reset_index()
    )
    daily_best.columns = ["date", "day_best_score"]

    future_days = daily_best[daily_best["date"] != today].copy()

    if future_days.empty:
        dates = sorted(df["time"].dt.date.unique())
        fallback_date = dates[1] if len(dates) > 1 else dates[0]
        return get_midnight_to_midnight_df(df, fallback_date)

    next_best_date = future_days.sort_values(
        ["day_best_score", "date"],
        ascending=[False, True]
    ).iloc[0]["date"]

    return get_midnight_to_midnight_df(df, next_best_date)


# ============================================================
# CHART HELPERS
# ============================================================
def annotate_direction_points(ax, day_df: pd.DataFrame, y_max: float, include_current_line: bool = False) -> None:
    if day_df.empty:
        return

    label_rows = day_df.iloc[::4].copy()
    if len(label_rows) == 0:
        label_rows = day_df.copy()

    for _, row in label_rows.iterrows():
        swell_txt = deg_to_text(row.get("swell_wave_direction"))
        wind_txt = deg_to_text(row.get("wind_direction_10m"))

        tide_flag = ""
        if bool(row.get("tide_is_high", False)):
            tide_flag = " HT"
        elif bool(row.get("tide_is_low", False)):
            tide_flag = " LT"

        label = f"S:{swell_txt} W:{wind_txt}{tide_flag}"
        y_base = row.get("swell_wave_height", np.nan)
        if pd.isna(y_base):
            continue

        y = y_base + max(0.08, y_max * 0.03)
        ax.text(
            row["time"],
            y,
            label,
            ha="center",
            va="bottom",
            fontsize=6.2,
            color="black",
            bbox=dict(facecolor="white", alpha=0.70, edgecolor="none", pad=0.15),
            zorder=9,
        )

    if include_current_line:
        ax.axvline(now_local().replace(tzinfo=None), color="red", lw=1.7, label="Current Time")


def annotate_wind_markers(
    ax,
    times: pd.Series,
    wind_speed: pd.Series,
    wind_dir: pd.Series,
    step: int = 4,
) -> None:
    if len(times) == 0:
        return

    idxs = list(range(0, len(times), step))
    if idxs and idxs[-1] != len(times) - 1:
        idxs.append(len(times) - 1)

    for i in idxs:
        ws = wind_speed.iloc[i]
        wd = wind_dir.iloc[i]

        if pd.isna(ws) or pd.isna(wd):
            continue

        label = deg_to_cardinal_4(wd)
        if not label:
            continue

        ax.annotate(
            label,
            (times.iloc[i], ws),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=6.6,
            fontweight="bold",
            color="black",
            bbox=dict(
                facecolor="white",
                alpha=0.70,
                edgecolor="none",
                pad=0.15,
            ),
            zorder=10,
        )


def base_day_chart(day_df: pd.DataFrame, title: str, include_current_line: bool) -> BytesIO:
    fig, ax1 = plt.subplots(figsize=(10.8, 2.95))
    ax2 = ax1.twinx()

    ax1.plot(day_df["time"], day_df["swell_wave_height"], lw=2.2, color="#1f77b4", label="Swell (m)")
    ax2.plot(day_df["time"], day_df["wind_speed_10m"], lw=1.2, ls="--", color="#2ca02c", alpha=0.75, label="Wind (km/h)")

    if "tide_height" in day_df.columns and not day_df["tide_height"].isna().all():
        ax1.plot(day_df["time"], day_df["tide_height"], lw=1.0, ls=":", color="#9467bd", alpha=0.9, label="Tide (m)")

    y_max = max(
        1.0,
        float(day_df["swell_wave_height"].max()) * 1.35 if not day_df["swell_wave_height"].isna().all() else 1.0,
    )
    if "tide_height" in day_df.columns and not day_df["tide_height"].isna().all():
        y_max = max(y_max, float(day_df["tide_height"].max()) * 1.15)

    ax1.set_ylim(0, y_max)

    best = day_df.loc[day_df["surf_score"].idxmax()]
    ax1.scatter(
        best["time"],
        best["swell_wave_height"],
        marker="x",
        s=85,
        linewidths=2.0,
        zorder=11,
        color="darkred",
    )

    tide_txt = ""
    if not pd.isna(best.get("tide_height", np.nan)):
        tide_txt = f" Tide {best['tide_height']:.1f}m"

    ax1.annotate(
        f"{best['time'].strftime('%H:%M')}  {best['surf_rating']}  {best['surf_score']:.0f}/100{tide_txt}",
        (best["time"], best["swell_wave_height"]),
        xytext=(0, 11),
        textcoords="offset points",
        ha="center",
        fontsize=6.8,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.18", facecolor="white", alpha=0.88),
        zorder=12,
    )

    annotate_direction_points(ax1, day_df, y_max, include_current_line=include_current_line)
    annotate_wind_markers(
        ax2,
        day_df["time"],
        day_df["wind_speed_10m"],
        day_df["wind_direction_10m"],
        step=4,
    )

    start = pd.Timestamp(day_df["time"].dt.date.iloc[0])
    end = start + pd.Timedelta(days=1)
    ax1.set_xlim(start, end)

    tick_times = pd.date_range(start=start, end=end, freq="3h")
    ax1.set_xticks(tick_times)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    ax1.set_title(title, fontweight="bold", fontsize=10.4, pad=6)
    ax1.set_ylabel("Swell / Tide", fontsize=7)
    ax2.set_ylabel("Wind", fontsize=7)
    ax1.tick_params(axis="both", labelsize=7)
    ax2.tick_params(axis="y", labelsize=7)

    lines = ax1.get_lines() + ax2.get_lines()
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left", fontsize=6.5, framealpha=0.9)

    plt.tight_layout(pad=0.8)
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=145, bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return buf


def generate_daily_chart(df: pd.DataFrame, location_name: str) -> BytesIO:
    day_df = get_today_df(df)
    return base_day_chart(day_df, f"{location_name} — Today", include_current_line=True)


def generate_next_best_day_chart(df: pd.DataFrame, location_name: str) -> BytesIO:
    day_df = get_next_best_day_df(df)
    day_title = day_df["time"].iloc[0].strftime("%a %d %b")
    return base_day_chart(day_df, f"{location_name} — Next Best Day ({day_title})", include_current_line=False)


def generate_weekly_chart(df: pd.DataFrame, location_name: str) -> BytesIO:
    fig, ax1 = plt.subplots(figsize=(10.8, 2.75))
    ax2 = ax1.twinx()

    ax1.plot(df["time"], df["swell_wave_height"], lw=2.0, color="#1f77b4", label="Swell (m)")
    ax2.plot(df["time"], df["wind_speed_10m"], lw=1.1, ls="--", color="#2ca02c", alpha=0.7, label="Wind (km/h)")

    if "tide_height" in df.columns and not df["tide_height"].isna().all():
        ax1.plot(df["time"], df["tide_height"], lw=0.9, ls=":", color="#9467bd", alpha=0.85, label="Tide (m)")

    y_max = max(
        1.0,
        float(df["swell_wave_height"].max()) * 1.30 if not df["swell_wave_height"].isna().all() else 1.0,
    )
    if "tide_height" in df.columns and not df["tide_height"].isna().all():
        y_max = max(y_max, float(df["tide_height"].max()) * 1.12)

    ax1.set_ylim(0, y_max)

    for _, group in df.groupby(df["time"].dt.date):
        best = group.loc[group["surf_score"].idxmax()]
        tide_txt = ""
        if not pd.isna(best.get("tide_height", np.nan)):
            tide_txt = f"\nT:{best['tide_height']:.1f}m"
        ax1.scatter(best["time"], best["swell_wave_height"], marker="x", s=42, zorder=8, color="darkred")
        ax1.annotate(
            f"{best['time'].strftime('%a %H:%M')}\n{best['surf_rating']} {best['surf_score']:.0f}{tide_txt}\nS:{deg_to_text(best['swell_wave_direction'])} W:{deg_to_text(best['wind_direction_10m'])}",
            (best["time"], best["swell_wave_height"]),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=6.2,
            bbox=dict(boxstyle="round,pad=0.16", facecolor="white", alpha=0.82),
        )

    annotate_wind_markers(
        ax2,
        df["time"],
        df["wind_speed_10m"],
        df["wind_direction_10m"],
        step=8,
    )

    ax1.set_title(f"{location_name} — Weekly Outlook", fontweight="bold", fontsize=10.5, pad=6)
    ax1.set_ylabel("Swell / Tide", fontsize=7)
    ax2.set_ylabel("Wind", fontsize=7)
    ax1.tick_params(axis="both", labelsize=7)
    ax2.tick_params(axis="y", labelsize=7)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))

    lines = ax1.get_lines() + ax2.get_lines()
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left", fontsize=6.5, framealpha=0.9)

    plt.tight_layout(pad=0.8)
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=145, bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return buf


# ============================================================
# PDF
# ============================================================
def build_pdf(df: pd.DataFrame, diagnostics: dict, location_name: str) -> str:
    filename = make_filename(location_name)
    ppath = os.path.join(LOCAL_DIR, filename)

    doc = SimpleDocTemplate(
        ppath,
        pagesize=A4,
        leftMargin=0.65 * cm,
        rightMargin=0.65 * cm,
        topMargin=0.55 * cm,
        bottomMargin=0.50 * cm,
    )

    styles = getSampleStyleSheet()
    now = now_local()

    compact = ParagraphStyle(
        "compact",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=6.9,
        leading=7.8,
        spaceAfter=0,
        textColor=colors.black,
    )
    compact_bold = ParagraphStyle(
        "compact_bold",
        parent=compact,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    today_df = get_today_df(df)
    best_today = today_df.loc[today_df["surf_score"].idxmax()] if not today_df.empty else df.loc[df["surf_score"].idxmax()]

    tide_notes_pdf = diagnostics.get("tide_notes", "n/a")
    why_para = Paragraph(best_today.get("summary_reasons", "n/a"), compact)

    daily_rows = [
        [Paragraph("Best Today", compact_bold),
         Paragraph(
             f"{best_today['time'].strftime('%a %d %b %H:%M')} | "
             f"{best_today['surf_rating']} | {best_today['surf_score']:.0f}/100",
             compact,
         )],
        [Paragraph("Swell", compact_bold),
         Paragraph(
             f"{safe_float_text(best_today.get('swell_wave_height'), '.1f', 'm')} | "
             f"{deg_to_text(best_today.get('swell_wave_direction'))} | "
             f"{safe_float_text(best_today.get('wave_period'), '.0f', 's')}",
             compact,
         )],
        [Paragraph("Wind", compact_bold),
         Paragraph(
             f"{safe_float_text(best_today.get('wind_speed_10m'), '.0f', ' km/h')} | "
             f"{deg_to_text(best_today.get('wind_direction_10m'))}",
             compact,
         )],
        [Paragraph("Tide", compact_bold),
         Paragraph(
             safe_float_text(best_today.get("tide_height"), ".1f", "m"),
             compact,
         )],
        [Paragraph("Source", compact_bold),
         Paragraph(
             f"{diagnostics.get('marine_source', 'n/a')} | "
             f"{diagnostics.get('wind_source_main', 'n/a')} | "
             f"{diagnostics.get('wind_source_secondary', 'n/a')}",
             compact,
         )],
        [Paragraph("Tide Feed", compact_bold),
         Paragraph(tide_notes_pdf, compact)],
        [Paragraph("Confidence", compact_bold),
         Paragraph(f"{int(best_today['confidence'] * 100)}%", compact)],
        [Paragraph("Why", compact_bold), why_para],
    ]

    t1 = Table(daily_rows, colWidths=[4.15 * cm, 14.45 * cm])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#1f3b5c")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("BACKGROUND", (1, 0), (1, -1), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.40, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.20, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    footer_bits = [
        f"Generated {now.strftime('%Y-%m-%d %H:%M %Z')}",
        "Daily charts run midnight to midnight at 3-hour intervals",
        "Today chart keeps the live time marker",
        "Direction labels: S = swell direction, W = wind direction, HT/LT = high/low tide marker",
        f"Timezone: {diagnostics.get('timezone', 'Australia/Melbourne')}",
    ]

    story = [
        Paragraph(f"<b>{location_name.upper()} SURF REPORT</b>", styles["Title"]),
        Paragraph(f"<font size=6.8>{' | '.join(footer_bits)}</font>", styles["Normal"]),
        Spacer(1, 0.08 * cm),
        t1,
        Spacer(1, 0.10 * cm),
        Image(generate_daily_chart(df, location_name), 18.6 * cm, 4.45 * cm),
        Spacer(1, 0.05 * cm),
        Image(generate_next_best_day_chart(df, location_name), 18.6 * cm, 4.45 * cm),
        Spacer(1, 0.05 * cm),
        Image(generate_weekly_chart(df, location_name), 18.6 * cm, 4.25 * cm),
        Spacer(1, 0.03 * cm),
        Paragraph(
            "<font size=6.6><b>Guide:</b> Good ≥ 75 | Fair 55–74 | Marginal 38–54 | Poor &lt; 38</font>",
            styles["Normal"],
        ),
    ]

    doc.build(story)
    return ppath


# ============================================================
# PUBLIC WORKER FUNCTION
# ============================================================
def generate_report(
    location_name: str = LOCATION_NAME,
    lat: float = LAT,
    lon: float = LON,
    state_hint: str | None = STATE_HINT,
) -> str:
    df, diagnostics = build_dataset(lat, lon, state_hint=state_hint)
    df = find_best_windows(df)
    output_path = build_pdf(df, diagnostics, location_name)
    return output_path


if __name__ == "__main__":
    output = generate_report()
    print(f"SUCCESS: Surf PDF created at {output}")