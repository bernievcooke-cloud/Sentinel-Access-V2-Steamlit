#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import platform
from datetime import datetime
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
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

# ============================================================
# 1. USER CONFIG — EDIT THESE FOR ANY AUSTRALIAN SURF SITE
# ============================================================
LOCATION_NAME = "Bells Beach"
LAT = -38.371
LON = 144.281

# Beach / break tuning
# Direction the beach faces toward the ocean, in degrees:
# N=0, E=90, S=180, W=270
BEACH_ORIENTATION_DEG = 210

# Preferred swell direction window (degrees)
PREFERRED_SWELL_DIR_MIN = 170
PREFERRED_SWELL_DIR_MAX = 235

# Preferred swell size window (metres)
PREFERRED_SWELL_MIN_M = 0.8
PREFERRED_SWELL_MAX_M = 2.8

# Preferred tide window (optional). Leave as None to disable tide scoring.
PREFERRED_TIDE_MIN_M = None
PREFERRED_TIDE_MAX_M = None

# Optional synthetic tide fallback.
USE_ESTIMATED_TIDE_IF_MISSING = False

FORECAST_DAYS = 7
REQUEST_TIMEOUT = 20

SAFE_NAME = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in LOCATION_NAME.replace(" ", "_"))
FILENAME = f"{SAFE_NAME}_Surf_Forecast.pdf"

LOCAL_DIR = (
    r"C:\RuralAI\OUTPUT\SURF"
    if platform.system() == "Windows"
    else os.path.join(os.path.expanduser("~"), "Documents", "Surf Reports")
)
os.makedirs(LOCAL_DIR, exist_ok=True)


# ============================================================
# 2. SMALL HELPERS
# ============================================================
def deg_to_text(deg: float | int | None) -> str:
    if deg is None or pd.isna(deg):
        return ""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((float(deg) + 11.25) // 22.5) % 16]


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
# 3. FETCHERS
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
        "&timezone=auto"
    )
    data = fetch_json(url)
    hourly = data.get("hourly", {})
    df = pd.DataFrame(hourly)
    if df.empty or "time" not in df.columns:
        raise ValueError("Marine API returned no hourly data.")
    df["time"] = pd.to_datetime(df["time"])
    return df


def fetch_open_meteo_weather(lat: float, lon: float) -> pd.DataFrame:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wind_speed_10m,wind_direction_10m"
        f"&forecast_days={FORECAST_DAYS}"
        "&timezone=auto"
    )
    data = fetch_json(url)
    hourly = data.get("hourly", {})
    df = pd.DataFrame(hourly)
    if df.empty or "time" not in df.columns:
        raise ValueError("Forecast API returned no hourly data.")
    df["time"] = pd.to_datetime(df["time"])
    return df.rename(columns={
        "wind_speed_10m": "wind_speed_10m_main",
        "wind_direction_10m": "wind_direction_10m_main",
    })


def fetch_bom_access_g_weather(lat: float, lon: float) -> pd.DataFrame | None:
    try:
        url = (
            "https://api.open-meteo.com/v1/bom"
            f"?latitude={lat}&longitude={lon}"
            "&hourly=wind_speed_10m,wind_direction_10m"
            f"&forecast_days={FORECAST_DAYS}"
            "&timezone=auto"
        )
        data = fetch_json(url)
        hourly = data.get("hourly", {})
        df = pd.DataFrame(hourly)
        if df.empty or "time" not in df.columns:
            return None
        df["time"] = pd.to_datetime(df["time"])
        return df.rename(columns={
            "wind_speed_10m": "wind_speed_10m_bom",
            "wind_direction_10m": "wind_direction_10m_bom",
        })
    except Exception:
        return None


def add_optional_tide(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    tide_source = "No tide source configured"
    if USE_ESTIMATED_TIDE_IF_MISSING:
        hours = np.arange(len(df))
        df["tide_height"] = 1.35 + 0.85 * np.sin(hours * (2 * np.pi / 12.4))
        tide_source = "Estimated tide model (low confidence)"
    else:
        df["tide_height"] = np.nan
    return df, tide_source


# ============================================================
# 4. DATA PREP / CONSENSUS
# ============================================================
def build_dataset(lat: float, lon: float) -> tuple[pd.DataFrame, dict]:
    marine = fetch_open_meteo_marine(lat, lon)
    wx_main = fetch_open_meteo_weather(lat, lon)
    wx_bom = fetch_bom_access_g_weather(lat, lon)

    df = marine.merge(wx_main, on="time", how="inner")

    diagnostics = {
        "marine_source": "Open-Meteo Marine",
        "wind_source_main": "Open-Meteo Forecast",
        "wind_source_secondary": "Open-Meteo BOM ACCESS-G" if wx_bom is not None else "Unavailable",
        "tide_source": "",
    }

    if wx_bom is not None:
        df = df.merge(wx_bom, on="time", how="left")
    else:
        df["wind_speed_10m_bom"] = np.nan
        df["wind_direction_10m_bom"] = np.nan

    df["wind_speed_10m"] = df[["wind_speed_10m_main", "wind_speed_10m_bom"]].mean(axis=1, skipna=True)

    wind_dirs = []
    for _, row in df.iterrows():
        wind_dirs.append(circular_mean_deg([
            row.get("wind_direction_10m_main"),
            row.get("wind_direction_10m_bom"),
        ]))
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

    df, tide_source = add_optional_tide(df)
    diagnostics["tide_source"] = tide_source

    return df, diagnostics


# ============================================================
# 5. GENERIC SURF SCORING FOR A SINGLE POINT
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

    # Swell size score (0..30)
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

    # Swell direction score (0..20)
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

    # Wave period score (0..10)
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

    # Wind score (0..30)
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

    # Tide score (0..10)
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
    score += tide_score

    # Morning bias (0..5)
    hour = row["time"].hour
    morning_bonus = 5.0 if 5 <= hour <= 9 else (2.0 if 10 <= hour <= 12 else 0.0)
    if morning_bonus > 0:
        reasons.append("better time-of-day bias")
    score += morning_bonus

    confidence = 0.85
    if pd.isna(swell_h) or pd.isna(swell_dir) or pd.isna(wind_kmh) or pd.isna(wind_dir):
        confidence -= 0.25
    confidence *= float(row.get("wind_agreement", 0.65))
    if USE_ESTIMATED_TIDE_IF_MISSING and not pd.isna(tide_h):
        confidence -= 0.10
    confidence = clamp(confidence, 0.15, 0.98)

    if score >= 75:
        rating = "Good"
    elif score >= 55:
        rating = "Fair"
    elif score >= 38:
        rating = "Marginal"
    else:
        rating = "Poor"

    return pd.Series({
        "surf_score": round(score, 1),
        "surf_rating": rating,
        "confidence": round(confidence, 2),
        "summary_reasons": ", ".join(reasons[:5]),
    })


def find_best_windows(df: pd.DataFrame) -> pd.DataFrame:
    scored = df.copy()
    scored[["surf_score", "surf_rating", "confidence", "summary_reasons"]] = scored.apply(score_row, axis=1)
    return scored


# ============================================================
# 6. DAY SELECTION
# ============================================================
def get_today_df(df: pd.DataFrame) -> pd.DataFrame:
    now = datetime.now()
    today_df = df[df["time"].dt.date == now.date()].copy()
    if today_df.empty:
        today_df = df.head(24).copy()
    return today_df


def get_next_best_day_df(df: pd.DataFrame) -> pd.DataFrame:
    today = datetime.now().date()
    daily_best = (
        df.groupby(df["time"].dt.date)
        .apply(lambda g: g["surf_score"].max())
        .reset_index(name="day_best_score")
        .rename(columns={"time": "date"})
    )
    future_days = daily_best[daily_best["time"] != today].copy() if "time" in daily_best.columns else daily_best[daily_best["date"] != today].copy()
    if future_days.empty:
        # fallback to best non-empty later slice
        dates = sorted(df["time"].dt.date.unique())
        fallback_date = dates[1] if len(dates) > 1 else dates[0]
        return df[df["time"].dt.date == fallback_date].copy()

    date_col = "date" if "date" in future_days.columns else "time"
    next_best_date = future_days.sort_values("day_best_score", ascending=False).iloc[0][date_col]
    return df[df["time"].dt.date == next_best_date].copy()


# ============================================================
# 7. CHART HELPERS
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
        label = f"S:{swell_txt}  W:{wind_txt}"
        y = row["swell_wave_height"] + max(0.08, y_max * 0.03)
        ax.text(
            row["time"],
            y,
            label,
            ha="center",
            va="bottom",
            fontsize=6.5,
            color="black",
            bbox=dict(facecolor="white", alpha=0.65, edgecolor="none", pad=0.15),
            zorder=9,
        )

    if include_current_line:
        now = datetime.now()
        ax.axvline(now, color="red", lw=1.7, label="Current Time")


def base_day_chart(day_df: pd.DataFrame, title: str, include_current_line: bool) -> BytesIO:
    fig, ax1 = plt.subplots(figsize=(10.8, 2.5))
    ax2 = ax1.twinx()

    ax1.plot(day_df["time"], day_df["swell_wave_height"], lw=2.2, color="#1f77b4", label="Swell (m)")
    ax2.plot(day_df["time"], day_df["wind_speed_10m"], lw=1.2, ls="--", color="#2ca02c", alpha=0.75, label="Wind (km/h)")

    y_max = max(1.0, float(day_df["swell_wave_height"].max()) * 1.35 if not day_df["swell_wave_height"].isna().all() else 1.0)
    ax1.set_ylim(0, y_max)

    top = day_df.nlargest(min(3, len(day_df)), "surf_score").sort_values("time")
    for _, row in top.iterrows():
        ax1.scatter(row["time"], row["swell_wave_height"], marker="o", s=34, zorder=10, color="darkblue")
        ax1.annotate(
            f"{row['time'].strftime('%H:%M')}  {row['surf_rating']} {row['surf_score']:.0f}",
            (row["time"], row["swell_wave_height"]),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=6.7,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.18", facecolor="white", alpha=0.85),
        )

    annotate_direction_points(ax1, day_df, y_max, include_current_line=include_current_line)

    ax1.set_title(title, fontweight="bold", fontsize=10.5, pad=6)
    ax1.set_ylabel("Swell", fontsize=7)
    ax2.set_ylabel("Wind", fontsize=7)
    ax1.tick_params(axis="both", labelsize=7)
    ax2.tick_params(axis="y", labelsize=7)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    lines = ax1.get_lines() + ax2.get_lines()
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left", fontsize=6.7, framealpha=0.9)

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
    fig, ax1 = plt.subplots(figsize=(10.8, 2.7))
    ax2 = ax1.twinx()

    ax1.plot(df["time"], df["swell_wave_height"], lw=2.0, color="#1f77b4", label="Swell (m)")
    ax2.plot(df["time"], df["wind_speed_10m"], lw=1.1, ls="--", color="#2ca02c", alpha=0.7, label="Wind (km/h)")

    y_max = max(1.0, float(df["swell_wave_height"].max()) * 1.30 if not df["swell_wave_height"].isna().all() else 1.0)
    ax1.set_ylim(0, y_max)

    for day, group in df.groupby(df["time"].dt.date):
        best = group.loc[group["surf_score"].idxmax()]
        ax1.scatter(best["time"], best["swell_wave_height"], marker="x", s=42, zorder=8, color="darkred")
        ax1.annotate(
            f"{best['time'].strftime('%a %H:%M')}\n{best['surf_rating']} {best['surf_score']:.0f}\nS:{deg_to_text(best['swell_wave_direction'])} W:{deg_to_text(best['wind_direction_10m'])}",
            (best["time"], best["swell_wave_height"]),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=6.4,
            bbox=dict(boxstyle="round,pad=0.16", facecolor="white", alpha=0.82),
        )

    ax1.set_title(f"{location_name} — Weekly Outlook", fontweight="bold", fontsize=10.5, pad=6)
    ax1.set_ylabel("Swell", fontsize=7)
    ax2.set_ylabel("Wind", fontsize=7)
    ax1.tick_params(axis="both", labelsize=7)
    ax2.tick_params(axis="y", labelsize=7)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))

    lines = ax1.get_lines() + ax2.get_lines()
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left", fontsize=6.7, framealpha=0.9)

    plt.tight_layout(pad=0.8)
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=145, bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return buf


# ============================================================
# 8. PDF
# ============================================================
def build_pdf(df: pd.DataFrame, diagnostics: dict) -> str:
    ppath = os.path.join(LOCAL_DIR, FILENAME)
    doc = SimpleDocTemplate(
        ppath,
        pagesize=A4,
        leftMargin=0.65 * cm,
        rightMargin=0.65 * cm,
        topMargin=0.45 * cm,
        bottomMargin=0.45 * cm,
    )

    styles = getSampleStyleSheet()
    compact = ParagraphStyle(
        "compact",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.4,
        leading=8.4,
        spaceAfter=0,
    )
    compact_bold = ParagraphStyle(
        "compact_bold",
        parent=compact,
        fontName="Helvetica-Bold",
    )

    now = datetime.now()
    today_df = get_today_df(df)
    next_best_df = get_next_best_day_df(df)

    best_today = today_df.loc[today_df["surf_score"].idxmax()]
    today_sorted = today_df.sort_values("surf_score", ascending=False).reset_index(drop=True)
    backup_today = today_sorted.iloc[1] if len(today_sorted) > 1 else best_today

    next_best = next_best_df.loc[next_best_df["surf_score"].idxmax()]

    why_para = Paragraph(best_today["summary_reasons"], compact)

    daily_rows = [
        [Paragraph("Location", compact_bold), Paragraph(LOCATION_NAME, compact)],
        [Paragraph("Best window today", compact_bold),
         Paragraph(f"{best_today['time'].strftime('%H:%M')} — {best_today['surf_rating']} ({best_today['surf_score']:.0f}/100)", compact)],
        [Paragraph("Backup window", compact_bold),
         Paragraph(f"{backup_today['time'].strftime('%H:%M')} — {backup_today['surf_rating']} ({backup_today['surf_score']:.0f}/100)", compact)],
        [Paragraph("Next best day", compact_bold),
         Paragraph(f"{next_best['time'].strftime('%a %d %b %H:%M')} — {next_best['surf_rating']} ({next_best['surf_score']:.0f}/100)", compact)],
        [Paragraph("Wind", compact_bold),
         Paragraph(f"{safe_float_text(best_today['wind_speed_10m'], '.0f', ' km/h')} {deg_to_text(best_today['wind_direction_10m'])}", compact)],
        [Paragraph("Swell", compact_bold),
         Paragraph(f"{safe_float_text(best_today['swell_wave_height'], '.1f', ' m')} {deg_to_text(best_today['swell_wave_direction'])}", compact)],
        [Paragraph("Wave period", compact_bold),
         Paragraph(f"{safe_float_text(best_today['wave_period'], '.0f', ' s')}", compact)],
        [Paragraph("Confidence", compact_bold),
         Paragraph(f"{int(best_today['confidence'] * 100)}%", compact)],
        [Paragraph("Why", compact_bold), why_para],
    ]

    t1 = Table(daily_rows, colWidths=[3.9 * cm, 14.7 * cm])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.black),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("BACKGROUND", (1, 0), (1, -1), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.45, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.22, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    story = [
        Paragraph(f"<b>{LOCATION_NAME.upper()} SURF REPORT</b>", styles["Title"]),
        Paragraph(
            f"<font size=7.2>Generated {now.strftime('%Y-%m-%d %H:%M')} | "
            f"Today chart keeps the live time marker. "
            f"Direction labels: S = swell direction, W = wind direction.</font>",
            styles["Normal"],
        ),
        Spacer(1, 0.10 * cm),
        t1,
        Spacer(1, 0.12 * cm),
        Image(generate_daily_chart(df, LOCATION_NAME), 18.6 * cm, 4.15 * cm),
        Spacer(1, 0.06 * cm),
        Image(generate_next_best_day_chart(df, LOCATION_NAME), 18.6 * cm, 4.15 * cm),
        Spacer(1, 0.06 * cm),
        Image(generate_weekly_chart(df, LOCATION_NAME), 18.6 * cm, 4.35 * cm),
        Spacer(1, 0.04 * cm),
        Paragraph(
            "<font size=6.8><b>Guide:</b> Good ≥ 75 | Fair 55–74 | Marginal 38–54 | Poor &lt; 38</font>",
            styles["Normal"],
        ),
    ]

    doc.build(story)
    return ppath


# ============================================================
# 9. MAIN
# ============================================================
def main() -> None:
    try:
        df, diagnostics = build_dataset(LAT, LON)
        df = find_best_windows(df)
        output_path = build_pdf(df, diagnostics)

        best = df.loc[df["surf_score"].idxmax()]
        print("SUCCESS")
        print(f"Location: {LOCATION_NAME}")
        print(f"Best forecast window: {best['time'].strftime('%Y-%m-%d %H:%M')}")
        print(f"Rating: {best['surf_rating']} ({best['surf_score']:.0f}/100)")
        print(f"Confidence: {int(best['confidence'] * 100)}%")
        print(f"PDF saved to: {output_path}")

    except requests.HTTPError as e:
        print(f"HTTP ERROR: {e}")
    except requests.RequestException as e:
        print(f"NETWORK ERROR: {e}")
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    main()