#!/usr/bin/env python3
from __future__ import annotations

import calendar
import json
import math
import platform
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
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
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer

# ============================================================
# OPTIONAL ASTRAL IMPORTS (PRIMARY MOON SOURCE)
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
SYNODIC_MONTH = 29.53058867
KNOWN_NEW_MOON_JD = 2451550.1
FIG_DPI = 180
PAGE_IMAGE_WIDTH_CM = 18.6
PAGE1_IMAGE_HEIGHT_CM = 16.6
PAGE2_IMAGE_HEIGHT_CM = 18.0

COLOR_LINE = "#1e88e5"
COLOR_BAR = "#1e88e5"
COLOR_EVENT = "#2e7d32"
COLOR_GRID = "#b0bec5"
COLOR_RUNTIME = "#424242"
COLOR_ALT = "#f9a825"


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


def _fmt_hour() -> str:
    return "%#I%p" if platform.system().lower().startswith("win") else "%-I%p"


def _ensure_tz(ts: datetime | pd.Timestamp, tz_name: str) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize(tz_name, ambiguous="NaT", nonexistent="shift_forward")
    return ts.tz_convert(tz_name)


def _tonight_start_for_date(d: date, tz_name: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(d, dtime(18, 0))).tz_localize(tz_name)


def _night_anchor_date(run_ts: pd.Timestamp) -> date:
    ts = pd.Timestamp(run_ts)
    if ts.hour < 6:
        return (ts - pd.Timedelta(days=1)).date()
    return ts.date()


def _next_month_start(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _month_end(d: date) -> date:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)


# ============================================================
# LOCATION RESOLUTION
# ============================================================
def _safe_float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None
        return float(value)
    except Exception:
        return None


def _extract_lat_lon_tz_from_value(value: Any) -> tuple[Optional[float], Optional[float], str]:
    if isinstance(value, list) and len(value) >= 2:
        lat = _safe_float_or_none(value[0])
        lon = _safe_float_or_none(value[1])
        if lat is not None and lon is not None:
            return lat, lon, TZ_FALLBACK

    if isinstance(value, dict):
        lat = _safe_float_or_none(value.get("lat", value.get("latitude")))
        lon = _safe_float_or_none(value.get("lon", value.get("lng", value.get("longitude"))))
        tz_name = str(value.get("timezone") or TZ_FALLBACK)
        if lat is not None and lon is not None:
            return lat, lon, tz_name

        coords = value.get("coords")
        if isinstance(coords, list) and len(coords) >= 2:
            lat = _safe_float_or_none(coords[0])
            lon = _safe_float_or_none(coords[1])
            if lat is not None and lon is not None:
                return lat, lon, tz_name

        for nested_key in ("location", "position", "point", "geo"):
            nested = value.get(nested_key)
            if isinstance(nested, dict):
                lat = _safe_float_or_none(nested.get("lat", nested.get("latitude")))
                lon = _safe_float_or_none(nested.get("lon", nested.get("lng", nested.get("longitude"))))
                nested_tz = str(nested.get("timezone") or value.get("timezone") or TZ_FALLBACK)
                if lat is not None and lon is not None:
                    return lat, lon, nested_tz
            elif isinstance(nested, list) and len(nested) >= 2:
                lat = _safe_float_or_none(nested[0])
                lon = _safe_float_or_none(nested[1])
                if lat is not None and lon is not None:
                    return lat, lon, tz_name

    return None, None, TZ_FALLBACK


def _load_coords_from_locations_json(location_name: str) -> tuple[float, float, str]:
    possible_paths = [
        APP_DIR / "config" / "locations.json",
        APP_DIR.parent / "config" / "locations.json",
        Path.cwd() / "config" / "locations.json",
        Path("/mount/src/sentinel-access-v2/config/locations.json"),
    ]
    location_key = "".join((location_name or "").strip().lower().split())

    for path in possible_paths:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                for name, value in data.items():
                    if "".join(str(name).strip().lower().split()) == location_key:
                        lat, lon, tz_name = _extract_lat_lon_tz_from_value(value)
                        if lat is not None and lon is not None:
                            return lat, lon, tz_name

                for name, value in data.items():
                    norm_name = "".join(str(name).strip().lower().split())
                    if location_key in norm_name or norm_name in location_key:
                        lat, lon, tz_name = _extract_lat_lon_tz_from_value(value)
                        if lat is not None and lon is not None:
                            return lat, lon, tz_name

            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name", item.get("location", ""))
                    norm_name = "".join(str(name).strip().lower().split())
                    if norm_name == location_key or location_key in norm_name or norm_name in location_key:
                        lat, lon, tz_name = _extract_lat_lon_tz_from_value(item)
                        if lat is not None and lon is not None:
                            return lat, lon, tz_name
        except Exception:
            continue

    raise ValueError(f"Could not resolve coordinates for location: {location_name}")


# ============================================================
# FALLBACK MOON MATH
# ============================================================
def _julian_day(dt_utc: datetime) -> float:
    year = dt_utc.year
    month = dt_utc.month
    day = dt_utc.day + (dt_utc.hour + (dt_utc.minute + dt_utc.second / 60.0) / 60.0) / 24.0
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
    e = 0.0549
    m = math.radians((115.3654 + 13.0649929509 * d) % 360)

    e_anom = m + e * math.sin(m) * (1 + e * math.cos(m))
    xv = a * (math.cos(e_anom) - e)
    yv = a * (math.sqrt(1 - e * e) * math.sin(e_anom))

    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)

    xh = r * (math.cos(n) * math.cos(v + w) - math.sin(n) * math.sin(v + w) * math.cos(i))
    yh = r * (math.sin(n) * math.cos(v + w) + math.cos(n) * math.sin(v + w) * math.cos(i))
    zh = r * math.sin(v + w) * math.sin(i)

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
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t - (t ** 3) / 38710000.0
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
    alt = math.degrees(math.asin(sin_alt))

    cos_az = (math.sin(dec_r) - math.sin(math.radians(alt)) * math.sin(lat_r)) / max(1e-9, math.cos(math.radians(alt)) * math.cos(lat_r))
    cos_az = min(1.0, max(-1.0, cos_az))
    az = math.degrees(math.acos(cos_az))
    if math.sin(ha_r) > 0:
        az = 360 - az
    return alt, az


def moon_phase_fraction_fallback(dt_local: datetime) -> float:
    dt_utc = dt_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    jd = _julian_day(dt_utc)
    age = (jd - KNOWN_NEW_MOON_JD) % SYNODIC_MONTH
    return age / SYNODIC_MONTH


# ============================================================
# MOON HELPERS
# ============================================================
def moon_phase_fraction(dt_local: datetime) -> float:
    if ASTRAL_AVAILABLE:
        try:
            phase_days = float(astral_moon.phase(dt_local.date()))
            return (phase_days % SYNODIC_MONTH) / SYNODIC_MONTH
        except Exception:
            pass
    return moon_phase_fraction_fallback(dt_local)


def moon_phase_name(dt_local: datetime) -> str:
    p = moon_phase_fraction(dt_local)
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


def moon_illumination_factor(dt_local: datetime) -> float:
    return 0.5 * (1 - math.cos(2 * math.pi * moon_phase_fraction(dt_local)))


def moon_altitude_azimuth(dt_local: datetime, lat: float, lon: float) -> tuple[float, float, str]:
    if ASTRAL_AVAILABLE:
        try:
            observer = Observer(latitude=lat, longitude=lon)
            alt = float(astral_moon.elevation(observer, dt_local))
            az = float(astral_moon.azimuth(observer, dt_local))
            return alt, az, "Astral"
        except Exception as e:
            _ = e
    alt, az = moon_altitude_azimuth_fallback(dt_local, lat, lon)
    return alt, az, "Fallback"


def moonrise_moonset_for_date(d: date, lat: float, lon: float, tz_name: str) -> tuple[str, str]:
    if ASTRAL_AVAILABLE:
        observer = Observer(latitude=lat, longitude=lon)
        try:
            mr = astral_moon.moonrise(observer, d, tzinfo=_tz(tz_name))
            ms = astral_moon.moonset(observer, d, tzinfo=_tz(tz_name))
            mr_txt = pd.Timestamp(mr).strftime("%I:%M %p").lstrip("0") if mr else "—"
            ms_txt = pd.Timestamp(ms).strftime("%I:%M %p").lstrip("0") if ms else "—"
            return mr_txt, ms_txt
        except Exception:
            pass
    return "—", "—"


# ============================================================
# SKY CLARITY MODEL
# ============================================================
def calculate_sky_clarity(altitude_deg: float, illumination_pct: float) -> float:
    """
    Realistic moonlight impact proxy for night-sky clarity.

    100% = darkest / clearest viewing conditions
    Lower values = brighter moonlight impact

    This is intentionally based on:
    - moon below horizon -> near 100%
    - moon near horizon -> small impact
    - moon high and bright -> larger impact
    """
    illum = max(0.0, min(100.0, float(illumination_pct)))

    if altitude_deg <= -6:
        return 100.0
    if altitude_deg <= 0:
        return max(96.0, 100.0 - illum * 0.04)
    if altitude_deg <= 10:
        impact = illum * 0.15
    elif altitude_deg <= 25:
        impact = illum * 0.35
    elif altitude_deg <= 45:
        impact = illum * 0.55
    else:
        impact = illum * 0.72

    clarity = 100.0 - impact
    return max(0.0, min(100.0, clarity))


def build_today_track(day_date: date, lat: float, lon: float, tz_name: str) -> pd.DataFrame:
    start = _tonight_start_for_date(day_date, tz_name)
    times = pd.date_range(start=start, periods=13, freq="1h", tz=tz_name)
    rows: list[dict[str, Any]] = []

    for t in times:
        dt = t.to_pydatetime()
        alt, az, source = moon_altitude_azimuth(dt, lat, lon)
        illumination = moon_illumination_factor(dt) * 100.0
        sky_clarity = calculate_sky_clarity(alt, illumination)
        rows.append(
            {
                "time": t,
                "moon_altitude": alt,
                "moon_azimuth": az,
                "illumination": illumination,
                "sky_clarity": sky_clarity,
                "phase_name": moon_phase_name(dt),
                "phase_fraction": moon_phase_fraction(dt),
                "source": source,
            }
        )
    return pd.DataFrame(rows)


def build_current_moon_sample(run_ts: pd.Timestamp, lat: float, lon: float, tz_name: str) -> dict[str, Any]:
    run_local = _ensure_tz(run_ts, tz_name)
    dt = run_local.to_pydatetime()
    alt, az, source = moon_altitude_azimuth(dt, lat, lon)
    illumination = moon_illumination_factor(dt) * 100.0
    sky_clarity = calculate_sky_clarity(alt, illumination)
    return {
        "time": run_local,
        "moon_altitude": alt,
        "moon_azimuth": az,
        "illumination": illumination,
        "sky_clarity": sky_clarity,
        "phase_name": moon_phase_name(dt),
        "phase_fraction": moon_phase_fraction(dt),
        "source": source,
    }


def build_daily_summary(
    start_date: date,
    end_date: date,
    lat: float,
    lon: float,
    tz_name: str,
    hour: int = 21,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    d = start_date
    while d <= end_date:
        dt_local = datetime.combine(d, dtime(hour, 0)).replace(tzinfo=_tz(tz_name))
        alt, az, source = moon_altitude_azimuth(dt_local, lat, lon)
        illumination = moon_illumination_factor(dt_local) * 100.0
        sky_clarity = calculate_sky_clarity(alt, illumination)
        mr, ms = moonrise_moonset_for_date(d, lat, lon, tz_name)

        rows.append(
            {
                "date": pd.Timestamp(d),
                "illumination": illumination,
                "sky_clarity": sky_clarity,
                "phase_name": moon_phase_name(dt_local),
                "phase_fraction": moon_phase_fraction(dt_local),
                "moon_altitude": alt,
                "moon_azimuth": az,
                "moonrise": mr,
                "moonset": ms,
                "source": source,
            }
        )
        d += timedelta(days=1)
    return pd.DataFrame(rows)


# ============================================================
# PHASE EVENT DETECTION
# ============================================================
@dataclass
class MoonEvent:
    when: pd.Timestamp
    phase_name: str
    description: str


def _phase_distance(a: float, b: float) -> float:
    diff = abs(a - b)
    return min(diff, 1.0 - diff)


def detect_phase_events(start_dt: datetime, end_dt: datetime, tz_name: str) -> list[MoonEvent]:
    start_ts = _ensure_tz(start_dt, tz_name)
    end_ts = _ensure_tz(end_dt, tz_name)
    hourly = pd.date_range(start_ts, end_ts, freq="1h", tz=tz_name)
    if len(hourly) < 3:
        return []

    phases = pd.Series([moon_phase_fraction(ts.to_pydatetime()) for ts in hourly], index=hourly)
    targets = [
        (0.00, "New Moon", "Dark-sky window strongest around this phase."),
        (0.25, "First Quarter", "Half-lit moon; evening viewing usually improves."),
        (0.50, "Full Moon", "Bright moonlight can reduce dark-sky viewing quality."),
        (0.75, "Last Quarter", "Late-night / dawn moon; darker evenings return."),
    ]

    events: list[MoonEvent] = []
    used_hours: set[pd.Timestamp] = set()

    for target_fraction, target_name, desc in targets:
        distances = phases.apply(lambda x: _phase_distance(float(x), target_fraction))
        min_dist = float(distances.min())
        if min_dist <= 0.045:
            candidates = distances[distances == min_dist].index
            if len(candidates) > 0:
                winner = pd.Timestamp(candidates[0]).tz_convert(tz_name)
                rounded_key = winner.floor("6h")
                if rounded_key not in used_hours:
                    used_hours.add(rounded_key)
                    events.append(MoonEvent(when=winner, phase_name=target_name, description=desc))

    events.sort(key=lambda e: e.when)
    return events


def detect_blue_moon(month_df: pd.DataFrame) -> Optional[str]:
    if month_df.empty:
        return None
    full_moons = month_df[month_df["phase_name"] == "Full Moon"].copy()
    if len(full_moons) >= 2:
        first_date = pd.Timestamp(full_moons.iloc[0]["date"]).strftime("%d %b")
        second_date = pd.Timestamp(full_moons.iloc[1]["date"]).strftime("%d %b")
        return f"Blue Moon month: two full moons detected ({first_date} and {second_date})."
    return None


# ============================================================
# DRAWN MOON ICON
# ============================================================
def add_moon_icon(ax, x, y, phase_fraction: float, size: int = 12) -> None:
    """
    Professional vector moon icon for PDF output.
    Uses shape drawing only — no emoji fonts.
    """
    phase_fraction = float(phase_fraction) % 1.0

    # palette
    MOON_OUTLINE = "#4b5563"   # soft slate outline
    MOON_DARK = "#23313a"      # shadow side
    MOON_LIGHT = "#f4f1e8"     # warm ivory
    MOON_FULL = "#fbf8ef"      # slightly brighter full moon

    da = DrawingArea(size, size, 0, 0)
    r = size / 2.0 - 1.0
    cx = cy = size / 2.0

    # dark base disc
    base = Circle(
        (cx, cy),
        r,
        facecolor=MOON_DARK,
        edgecolor=MOON_OUTLINE,
        linewidth=0.75,
    )
    da.add_artist(base)

    p = phase_fraction

    # new moon
    if p < 0.02 or p > 0.98:
        pass

    # full moon
    elif abs(p - 0.5) < 0.02:
        bright = Circle(
            (cx, cy),
            r - 0.05,
            facecolor=MOON_FULL,
            edgecolor="none",
        )
        da.add_artist(bright)

    else:
        # illuminated fraction: 0=new, 1=full
        illum = 0.5 * (1 - math.cos(2 * math.pi * p))
        waxing = p < 0.5

        # bright disc
        bright = Circle(
            (cx, cy),
            r - 0.05,
            facecolor=MOON_LIGHT,
            edgecolor="none",
        )
        da.add_artist(bright)

        # shadow ellipse width
        shadow_w = max(0.7, (1.0 - illum) * 2.0 * r)

        if waxing:
            shadow_cx = cx - (r - shadow_w / 2.0)
        else:
            shadow_cx = cx + (r - shadow_w / 2.0)

        shadow = Ellipse(
            (shadow_cx, cy),
            shadow_w,
            2.0 * r,
            facecolor=MOON_DARK,
            edgecolor="none",
        )
        da.add_artist(shadow)

        # subtle terminator sharpening for quarter moons
        if abs(p - 0.25) < 0.04 or abs(p - 0.75) < 0.04:
            terminator = Ellipse(
                (cx, cy),
                0.55,
                2.0 * r,
                facecolor=MOON_OUTLINE,
                edgecolor="none",
                alpha=0.16,
            )
            da.add_artist(terminator)

    # final outline
    border = Circle(
        (cx, cy),
        r,
        facecolor="none",
        edgecolor=MOON_OUTLINE,
        linewidth=0.75,
    )
    da.add_artist(border)

    ab = AnnotationBbox(
        da,
        (x, y),
        xycoords="data",
        frameon=False,
        box_alignment=(0.5, 0.5),
        pad=0.0,
        annotation_clip=False,
        zorder=8,
    )
    ax.add_artist(ab)


# ============================================================
# CHARTS
# ============================================================
def _apply_day_axis(ax, start: pd.Timestamp, end: pd.Timestamp) -> None:
    ax.set_xlim(start.to_pydatetime(), end.to_pydatetime())
    ticks = pd.date_range(start, end, freq="3h", tz=start.tz)
    ax.set_xticks([t.to_pydatetime() for t in ticks])
    ax.xaxis.set_major_formatter(mdates.DateFormatter(_fmt_hour(), tz=start.tzinfo))
    ax.tick_params(axis="x", rotation=0, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(True, alpha=0.25, color=COLOR_GRID)


def plot_today(
    ax,
    df_today: pd.DataFrame,
    run_ts: pd.Timestamp,
    location_name: str,
    current_sample: Optional[dict[str, Any]] = None,
) -> None:
    start = pd.Timestamp(df_today["time"].min())
    end = pd.Timestamp(df_today["time"].max())
    run_ts = pd.Timestamp(run_ts)

    # Visual sky-path version.
    # Keep the real time axis, but flip altitude vertically to present a sky-arc style path.
    visual_moon_path = -df_today["moon_altitude"].astype(float)

    ax2 = ax.twinx()

    # Split the moon path so the already-observed part is solid and the upcoming part is dashed.
    past_mask = df_today["time"] <= run_ts
    future_mask = df_today["time"] >= run_ts

    if past_mask.any():
        ax.plot(
            df_today.loc[past_mask, "time"],
            visual_moon_path.loc[past_mask],
            color=COLOR_ALT,
            linewidth=2.8,
            linestyle="-",
            label="Moon path (past)",
            zorder=3,
        )

    if future_mask.any():
        ax.plot(
            df_today.loc[future_mask, "time"],
            visual_moon_path.loc[future_mask],
            color=COLOR_ALT,
            linewidth=2.2,
            linestyle="--",
            alpha=0.78,
            label="Moon path (ahead)",
            zorder=2,
        )

    ax2.plot(
        df_today["time"],
        df_today["sky_clarity"],
        color=COLOR_LINE,
        linewidth=2.2,
        linestyle=":",
        label="Sky clarity %",
    )
    ax2.set_ylim(0, 100)
    ax2.tick_params(axis="y", labelsize=8)
    ax2.set_ylabel("Sky clarity %", fontsize=8)

    # Horizon reference
    ax.axhline(0, color="#757575", linewidth=0.8, alpha=0.6)

    # Runtime marker
    if start <= run_ts <= end:
        ax.axvline(run_ts.to_pydatetime(), color=COLOR_RUNTIME, linestyle=":", linewidth=1.9, zorder=4)

    # Place moon icons only at 3-hour chart intervals that have already happened.
    tick_times = pd.date_range(start=start, end=end, freq="3h", tz=start.tz)
    past_ticks = [t for t in tick_times if t <= run_ts]

    for tick in past_ticks:
        nearest_idx = (df_today["time"] - tick).abs().idxmin()
        row = df_today.loc[nearest_idx]
        moon_y = -float(row["moon_altitude"])

        add_moon_icon(
            ax,
            row["time"],
            moon_y,
            float(row["phase_fraction"]),
            size=10,
        )

        hour_fmt = "%#I%p" if platform.system().lower().startswith("win") else "%-I%p"
        label_txt = pd.Timestamp(tick).strftime(hour_fmt).lower()

        ax.annotate(
            label_txt,
            (row["time"], moon_y),
            xytext=(0, -12),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=6.6,
            color="#37474f",
        )

    # Show the moon at the exact report runtime.
    if current_sample is not None and start <= run_ts <= end:
        current_x = pd.Timestamp(current_sample["time"])
        current_y = -float(current_sample["moon_altitude"])

        add_moon_icon(
            ax,
            current_x,
            current_y,
            float(current_sample["phase_fraction"]),
            size=14,
        )
        ax.scatter(
            [current_x],
            [current_y],
            s=150,
            facecolors="none",
            edgecolors="#263238",
            linewidths=1.8,
            zorder=9,
        )
        ax.annotate(
            "Now",
            (current_x, current_y),
            xytext=(0, 12),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.2,
            fontweight="bold",
            color="#263238",
        )

    # Highlight best clarity so far within the displayed period.
    visible_so_far = df_today[df_today["time"] <= run_ts].copy()
    if visible_so_far.empty:
        visible_so_far = df_today.copy()

    best_idx = visible_so_far["sky_clarity"].idxmax()
    best_row = visible_so_far.loc[best_idx]
    best_y = -float(best_row["moon_altitude"])

    ax.scatter(
        [best_row["time"]],
        [best_y],
        marker="x",
        s=80,
        linewidths=2.0,
        color="black",
        zorder=6,
    )
    ax.annotate(
        f"Best clarity {best_row['sky_clarity']:.0f}%",
        (best_row["time"], best_y),
        xytext=(0, 8),
        textcoords="offset points",
        ha="center",
        fontsize=7.2,
        fontweight="bold",
    )

    ax.set_ylabel("Visual moon path", fontsize=8)
    ax.set_title(f"Tonight — Visual Moon Path & Sky Clarity ({location_name})", fontsize=10.5, pad=8)

    _apply_day_axis(ax, start, end)

    # Orientation cues.
    ax.text(
        0.01,
        0.96,
        "W",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        fontweight="bold",
        color="#455a64",
    )
    ax.text(
        0.99,
        0.96,
        "E",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        fontweight="bold",
        color="#455a64",
    )

    # Visual range tuned for sky-arc presentation.
    y_min = min(-95, float(visual_moon_path.min()) - 5)
    y_max = max(20, float(visual_moon_path.max()) + 5)
    ax.set_ylim(y_min, y_max)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=3,
        fontsize=7,
        frameon=False,
    )


def _plot_period_bars(
    ax,
    df: pd.DataFrame,
    title: str,
    highlight_date: Optional[pd.Timestamp] = None,
    value_col: str = "sky_clarity",
) -> str:
    if df.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontsize=10.5, pad=8)
        return "N/A"

    heights = df[value_col].to_numpy()
    x = df["date"]
    colors = [COLOR_BAR] * len(df)

    best_idx = int(np.argmax(df[value_col].to_numpy()))
    if highlight_date is None:
        highlight_date = pd.Timestamp(df.iloc[best_idx]["date"])

    for i, dt in enumerate(x):
        if pd.Timestamp(dt).date() == pd.Timestamp(highlight_date).date():
            colors[i] = COLOR_EVENT

    ax.bar(x, heights, width=0.8, color=colors, edgecolor="#0d47a1", linewidth=0.6)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Sky clarity %", fontsize=8)
    ax.set_title(title, fontsize=10.5, pad=8)
    ax.grid(True, axis="y", alpha=0.24, color=COLOR_GRID)
    ax.tick_params(axis="x", labelsize=8)
    ax.tick_params(axis="y", labelsize=8)

    best_row = df.iloc[best_idx]
    ax.scatter([best_row["date"]], [min(98, float(best_row[value_col]) + 4)], marker="x", s=80, linewidths=2.0, color="black", zorder=6)
    ax.annotate(
        f"X {best_row['phase_name']}",
        (best_row["date"], min(98, float(best_row[value_col]) + 4)),
        xytext=(0, 8),
        textcoords="offset points",
        ha="center",
        fontsize=7.0,
        fontweight="bold",
    )

    for _, row in df.iterrows():
        y = min(97.5, float(row[value_col]) + 8)
        add_moon_icon(ax, row["date"], y, float(row["phase_fraction"]), size=10)

    if len(df) <= 10:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a\n%d"))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    return pd.Timestamp(best_row["date"]).strftime("%a %d %b")


def build_chart_pages(
    today_df: pd.DataFrame,
    week_df: pd.DataFrame,
    next_week_df: pd.DataFrame,
    month_df: pd.DataFrame,
    next_month_df: pd.DataFrame,
    run_ts: pd.Timestamp,
    location_name: str,
    current_sample: Optional[dict[str, Any]] = None,
) -> tuple[BytesIO, BytesIO, dict[str, str]]:
    fig1, axes1 = plt.subplots(3, 1, figsize=(8.27, 10.8))
    fig1.suptitle(f"Moon Events Report — {location_name}", fontsize=13.5, fontweight="bold", y=0.992)
    plot_today(axes1[0], today_df, run_ts, location_name, current_sample=current_sample)
    week_best = _plot_period_bars(axes1[1], week_df, "This Week — Daily Sky Clarity & Phase")
    next_week_best = _plot_period_bars(axes1[2], next_week_df, "Next Week — Daily Sky Clarity & Phase")
    fig1.tight_layout(rect=[0.03, 0.04, 0.98, 0.982], h_pad=1.8)
    page1 = BytesIO()
    fig1.savefig(page1, format="png", dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig1)
    page1.seek(0)

    fig2, axes2 = plt.subplots(2, 1, figsize=(8.27, 8.8))
    fig2.suptitle(f"Monthly Moon Clarity — {location_name}", fontsize=13.0, fontweight="bold", y=0.988)

    month_title = (
        f"{pd.Timestamp(month_df['date'].iloc[0]).strftime('%B')} — Daily Sky Clarity & Phase"
        if not month_df.empty
        else "This Month — Daily Sky Clarity & Phase"
    )
    next_month_title = (
        f"{pd.Timestamp(next_month_df['date'].iloc[0]).strftime('%B')} — Daily Sky Clarity & Phase"
        if not next_month_df.empty
        else "Next Month — Daily Sky Clarity & Phase"
    )

    month_best = _plot_period_bars(axes2[0], month_df, month_title)
    next_month_best = _plot_period_bars(axes2[1], next_month_df, next_month_title)
    fig2.tight_layout(rect=[0.03, 0.05, 0.98, 0.975], h_pad=1.9)
    page2 = BytesIO()
    fig2.savefig(page2, format="png", dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig2)
    page2.seek(0)

    meta = {
        "week_best": week_best,
        "next_week_best": next_week_best,
        "month_best": month_best,
        "next_month_best": next_month_best,
    }
    return page1, page2, meta

# ============================================================
# COMET WATCH
# ============================================================
def _comet_watch_items(report_run_time: pd.Timestamp) -> list[dict[str, str]]:
    now = pd.Timestamp(report_run_time)
    items: list[dict[str, str]] = []

    april_start = pd.Timestamp("2026-04-01", tz=now.tz)
    april_end = pd.Timestamp("2026-04-30", tz=now.tz)

    if april_start <= now <= april_end:
        if now < pd.Timestamp("2026-04-07", tz=now.tz):
            items.append({
                "name": "C/2026 A1 (MAPS)",
                "window": "Expected from 7 Apr",
                "direction": "Low west after sunset",
                "confidence": "Watch",
                "note": "Possible Australian visibility may begin soon if the comet survives perihelion.",
            })
        elif now <= pd.Timestamp("2026-04-20", tz=now.tz):
            items.append({
                "name": "C/2026 A1 (MAPS)",
                "window": "7–20 Apr",
                "direction": "Low west after sunset",
                "confidence": "Uncertain",
                "note": "Possible visibility now if the comet survived perihelion; binoculars may help.",
            })

        if now < pd.Timestamp("2026-04-13", tz=now.tz):
            items.append({
                "name": "C/2025 R3 (Pan-STARRS)",
                "window": "Expected later in Apr",
                "direction": "Evening twilight",
                "confidence": "Watch",
                "note": "Late-April comet candidate; brightness remains uncertain.",
            })
        else:
            items.append({
                "name": "C/2025 R3 (Pan-STARRS)",
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
# PDF
# ============================================================
# ============================================================
# PDF
# ============================================================
def build_pdf(
    location_name: str,
    tz_name: str,
    report_run: pd.Timestamp,
    page1_image: BytesIO,
    page2_image: BytesIO,
    events: list[MoonEvent],
    special_note: Optional[str],
    today_df: pd.DataFrame,
    output_path: Path,
) -> str:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=15, leading=17, spaceAfter=5)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=8.5, leading=10, spaceAfter=3)
    small2 = ParagraphStyle("small2", parent=styles["BodyText"], fontSize=8.0, leading=9.0, spaceAfter=2)

    today_phase = str(today_df.iloc[0]["phase_name"]) if not today_df.empty else "N/A"
    today_clarity = float(today_df.iloc[0]["sky_clarity"]) if not today_df.empty else float("nan")
    moon_source = (
        "Astral"
        if (not today_df.empty and (today_df["source"] == "Astral").all())
        else ("Mixed" if not today_df.empty and (today_df["source"] == "Astral").any() else "Fallback")
    )

    comet_watch = _comet_watch_summary(report_run)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.0 * cm,
        rightMargin=1.0 * cm,
        topMargin=0.8 * cm,
        bottomMargin=0.8 * cm,
    )
    story = []
    story.append(Paragraph(f"Moon Events Report — {location_name}", title_style))
    story.append(Paragraph(f"Time zone: {tz_name}", small))
    story.append(
        Paragraph(
            f"Moon source: {moon_source}" + (
                "" if moon_source != "Fallback" else f" (Astral unavailable: {ASTRAL_IMPORT_ERROR or 'not installed'})"
            ),
            small,
        )
    )
    story.append(Paragraph(f"Current moon phase: {today_phase} &nbsp;&nbsp;&nbsp; Sky clarity now: {today_clarity:.0f}%", small))
    story.append(Paragraph(comet_watch, small2))
    story.append(Paragraph(f"Report run: {report_run.strftime('%a %d %b %Y %I:%M:%S %p')}", small2))
    story.append(Spacer(1, 0.06 * cm))

    story.append(
        Paragraph(
            "Upcoming Moon Events",
            ParagraphStyle("events_hdr", parent=styles["Heading2"], fontSize=11.5, leading=13, spaceAfter=3),
        )
    )

    if events:
        for event in events[:4]:
            when_txt = pd.Timestamp(event.when).strftime("%a %d %b %Y %I:%M %p")
            story.append(Paragraph(f"<b>{event.phase_name}</b> — {when_txt}: {event.description}", small2))
    else:
        story.append(Paragraph("No major primary phase event detected inside the scanned report window.", small2))

    if special_note:
        story.append(Paragraph(f"<b>Special note</b> — {special_note}", small2))

    story.append(Spacer(1, 0.08 * cm))
    story.append(Image(page1_image, width=PAGE_IMAGE_WIDTH_CM * cm, height=PAGE1_IMAGE_HEIGHT_CM * cm))
    story.append(PageBreak())
    story.append(Image(page2_image, width=PAGE_IMAGE_WIDTH_CM * cm, height=PAGE2_IMAGE_HEIGHT_CM * cm))
    story.append(Spacer(1, 0.08 * cm))
    story.append(Paragraph("How to read the charts", small))
    story.append(
        Paragraph(
            "Tonight shows moon altitude and live sky clarity from 6PM to 6AM, with the dotted vertical line marking the exact report run time when it falls inside that night window. The moon path is drawn as solid for elapsed hours and dashed for upcoming hours, with a larger Now marker placed at the exact report run time and 3-hour moon markers retained as the night progresses. W and E labels are included as orientation cues. This week and next week show daily sky-clarity bars with a moon-phase icon above each bar. The monthly charts roll automatically to the current month and next month, with the X marking the best viewing day in each period.",
            small2,
        )
    )
    doc.build(story)
    return str(output_path)


# ============================================================
# PUBLIC ENTRYPOINT
# ============================================================
def generate_report(
    location_name: str,
    coords: list[float] | tuple[float, float] | dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    logger: Optional[Callable[[str], None]] = None,
) -> str:
    tz_name = TZ_FALLBACK
    lat: Optional[float] = None
    lon: Optional[float] = None

    if coords is not None:
        if isinstance(coords, dict):
            lat = _safe_float_or_none(coords.get("latitude", coords.get("lat")))
            lon = _safe_float_or_none(coords.get("longitude", coords.get("lon", coords.get("lng"))))
            tz_name = str(coords.get("timezone") or TZ_FALLBACK)
        else:
            try:
                if len(coords) >= 2:
                    lat = _safe_float_or_none(coords[0])
                    lon = _safe_float_or_none(coords[1])
            except Exception:
                lat = None
                lon = None

    if lat is None or lon is None:
        lat, lon, tz_name = _load_coords_from_locations_json(location_name)
        _log(logger, f"Resolved coords from locations.json: {lat}, {lon}")

    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in (" ", "-", "_", ",") else "_" for ch in location_name).strip().replace("  ", " ")
    pdf_path = out_dir / f"Moon Events Report - {safe_name}.pdf"

    _log(logger, f"Running Moon Events for {location_name}.")
    _log(logger, f"Using timezone: {tz_name}")
    report_run = pd.Timestamp.now(tz=_tz(tz_name))

    today_date = _night_anchor_date(report_run)
    week_start = today_date
    week_end = today_date + timedelta(days=6)
    next_week_start = today_date + timedelta(days=7)
    next_week_end = today_date + timedelta(days=13)
    month_start = date(today_date.year, today_date.month, 1)
    month_end = _month_end(today_date)
    next_month_start = _next_month_start(today_date)
    next_month_end = _month_end(next_month_start)

    today_df = build_today_track(today_date, lat, lon, tz_name)
    current_sample = build_current_moon_sample(report_run, lat, lon, tz_name)
    week_df = build_daily_summary(week_start, week_end, lat, lon, tz_name)
    next_week_df = build_daily_summary(next_week_start, next_week_end, lat, lon, tz_name)
    month_df = build_daily_summary(month_start, month_end, lat, lon, tz_name)
    next_month_df = build_daily_summary(next_month_start, next_month_end, lat, lon, tz_name)

    if today_df.empty or week_df.empty or next_week_df.empty or month_df.empty or next_month_df.empty:
        raise ValueError("Moon Events report data build returned no data")

    page1_image, page2_image, meta = build_chart_pages(
        today_df,
        week_df,
        next_week_df,
        month_df,
        next_month_df,
        report_run,
        location_name,
        current_sample=current_sample,
    )

    events = detect_phase_events(
        report_run.to_pydatetime(),
        (report_run + pd.Timedelta(days=30)).to_pydatetime(),
        tz_name,
    )
    blue_moon_note = detect_blue_moon(month_df)

    if ASTRAL_AVAILABLE:
        astral_points = int((today_df["source"] == "Astral").sum()) if not today_df.empty else 0
        _log(logger, f"Moon source: Astral priority active ({astral_points} points)")
    else:
        _log(logger, f"Moon source: fallback active ({ASTRAL_IMPORT_ERROR or 'Astral not installed'})")

    _log(logger, f"This week highlight: {meta['week_best']}")
    _log(logger, f"Next week highlight: {meta['next_week_best']}")
    _log(logger, f"Month highlight: {meta['month_best']}")
    _log(logger, f"Next month highlight: {meta['next_month_best']}")
    if events:
        _log(logger, f"Upcoming moon events detected: {', '.join(e.phase_name for e in events)}")
    if blue_moon_note:
        _log(logger, blue_moon_note)

    result = build_pdf(
        location_name,
        tz_name,
        report_run,
        page1_image,
        page2_image,
        events,
        blue_moon_note,
        today_df,
        pdf_path,
    )

    if not Path(result).exists() or Path(result).stat().st_size < 1000:
        raise ValueError("Generated Moon Events PDF is missing or too small")

    _log(logger, f"MOON EVENTS PDF OK: {result}")
    return result


if __name__ == "__main__":
    def log(msg: str) -> None:
        print(msg)

    sample = generate_report("Birregurra", [-38.33681, 143.78473], output_dir=OUTPUT_DIR, logger=log)
    print(sample)