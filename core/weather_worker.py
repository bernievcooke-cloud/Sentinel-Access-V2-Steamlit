#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
from io import BytesIO
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Callable

import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib import colors


DEFAULT_TZ = "Australia/Melbourne"

LOCAL_DIR = (
    r"C:\RuralAI\OUTPUT\WEATHER"
    if platform.system() == "Windows"
    else os.path.join(os.path.expanduser("~"), "Documents", "Weather Reports")
)
os.makedirs(LOCAL_DIR, exist_ok=True)


def make_safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name.replace(" ", "_"))


def deg_to_compass(deg):
    if deg is None or (isinstance(deg, float) and np.isnan(deg)):
        return "N/A"
    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]
    idx = int((deg + 11.25) / 22.5) % 16
    return dirs[idx]


def _safe_get_json(url: str, timeout: int = 12):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _parse_local_times(series: pd.Series, tz_name: str) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)

    if getattr(dt.dt, "tz", None) is None:
        return dt.dt.tz_localize(tz).dt.tz_localize(None)
    return dt.dt.tz_convert(tz).dt.tz_localize(None)


def fetch_weather_data(lat, lon, logger: Callable[[str], None] = print):
    try:
        h_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code"
            "&timezone=Australia/Melbourne"
            "&forecast_days=3"
        )

        d_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,precipitation_sum,weather_code"
            "&timezone=Australia/Melbourne"
            "&forecast_days=7"
        )

        h_resp = _safe_get_json(h_url)
        d_resp = _safe_get_json(d_url)

        tz_name = h_resp.get("timezone") or d_resp.get("timezone") or DEFAULT_TZ

        if "hourly" not in h_resp or "time" not in h_resp["hourly"]:
            logger("Open-Meteo hourly response missing expected fields.")
            return None, None, tz_name

        if "daily" not in d_resp or "time" not in d_resp["daily"]:
            logger("Open-Meteo daily response missing expected fields.")
            return None, None, tz_name

        h_df = pd.DataFrame(h_resp["hourly"])
        d_df = pd.DataFrame(d_resp["daily"])

        h_df["time"] = _parse_local_times(h_df["time"], tz_name)
        d_df["time"] = _parse_local_times(d_df["time"], tz_name)

        h_cols = [
            "temperature_2m",
            "precipitation",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
            "weather_code",
        ]
        d_cols = [
            "temperature_2m_max",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
            "wind_direction_10m_dominant",
            "precipitation_sum",
            "weather_code",
        ]

        for col in h_cols:
            if col not in h_df.columns:
                h_df[col] = np.nan
            h_df[col] = pd.to_numeric(h_df[col], errors="coerce")

        for col in d_cols:
            if col not in d_df.columns:
                d_df[col] = np.nan
            d_df[col] = pd.to_numeric(d_df[col], errors="coerce")

        h_df["precipitation"] = h_df["precipitation"].fillna(0.0)
        d_df["precipitation_sum"] = d_df["precipitation_sum"].fillna(0.0)

        h_df = h_df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
        d_df = d_df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

        return h_df, d_df, tz_name

    except Exception as e:
        logger(f"fetch_weather_data failed: {e}")
        return None, None, DEFAULT_TZ


def _format_hour_axis(ax):
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 3, 6, 9, 12, 15, 18, 21]))

    def fmt(x, pos=None):
        dt = mdates.num2date(x)
        label = dt.strftime("%I%p")
        return label.replace("AM", "A").replace("PM", "P").lstrip("0")

    ax.xaxis.set_major_formatter(fmt)
    ax.tick_params(axis="x", rotation=0)


def build_weather_status_table(
    h_df: pd.DataFrame,
    tz_name: str,
    styles,
    logger: Callable[[str], None] = print
):
    try:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo(DEFAULT_TZ)

        now_dt = datetime.now(tz).replace(tzinfo=None)
        check_df = h_df[
            (h_df["time"] >= now_dt) &
            (h_df["time"] <= now_dt + timedelta(hours=24))
        ].copy()

        if check_df.empty:
            status = "NORMAL CONDITIONS"
            bg = colors.honeydew
        else:
            fire = any(
                (check_df["temperature_2m"] > 28) &
                (
                    (check_df["wind_direction_10m"] >= 315) |
                    (check_df["wind_direction_10m"] <= 45)
                )
            )
            storm = any(check_df["weather_code"].isin([95, 96, 99]))
            wind = any(check_df["wind_gusts_10m"] > 45)
            rain = any(check_df["precipitation"] >= 1)

            status = "NORMAL CONDITIONS"
            bg = colors.honeydew

            if fire:
                status = "FIRE ALERT: HEAT & NORTH WIND"
                bg = colors.orange
            elif storm:
                status = "STORM ALERT"
                bg = colors.lightsalmon
            elif wind:
                status = "WIND ALERT"
                bg = colors.lightsalmon
            elif rain:
                status = "RAIN ALERT"
                bg = colors.lightsalmon

        stat_t = Table(
            [["WEATHER STATUS", status]],
            colWidths=[4.5 * cm, 13.5 * cm]
        )
        stat_t.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), colors.black),
                ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
                ("BACKGROUND", (1, 0), (1, 0), bg),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        return stat_t

    except Exception as e:
        logger(f"Failed to build weather status table: {e}")
        fallback = Table(
            [["WEATHER STATUS", "NORMAL CONDITIONS"]],
            colWidths=[4.5 * cm, 13.5 * cm]
        )
        fallback.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), colors.black),
                ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
                ("BACKGROUND", (1, 0), (1, 0), colors.honeydew),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ])
        )
        return fallback


def generate_daily(h_df, location_name, tz_name=DEFAULT_TZ):
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)

    now_dt = datetime.now(tz).replace(tzinfo=None)
    day_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    day_df = h_df[(h_df["time"] >= day_start) & (h_df["time"] < day_end)].copy()
    if day_df.empty or len(day_df) < 8:
        day_df = h_df.head(24).copy()

    actual = day_df[day_df["time"] <= now_dt].copy()
    forecast = day_df[day_df["time"] > now_dt].copy()

    fig, ax_temp = plt.subplots(figsize=(11, 5.7))
    ax_wind = ax_temp.twinx()
    ax_rain = ax_temp.twinx()
    ax_rain.spines["right"].set_position(("axes", 1.12))

    l1a, = ax_temp.plot(
        actual["time"],
        actual["temperature_2m"],
        "-",
        lw=2.6,
        color="red",
        label="Actual Temp"
    )
    l1f, = ax_temp.plot(
        forecast["time"],
        forecast["temperature_2m"],
        "--",
        lw=2.6,
        color="red",
        label="Forecast Temp"
    )

    l2a, = ax_wind.plot(actual["time"], actual["wind_speed_10m"], "-", lw=1.6, label="Actual Wind")
    l2f, = ax_wind.plot(forecast["time"], forecast["wind_speed_10m"], "--", lw=1.6, label="Forecast Wind")
    l2g, = ax_wind.plot(day_df["time"], day_df["wind_gusts_10m"], ":", lw=1.2, label="Wind Gusts")

    l3 = ax_rain.bar(day_df["time"], day_df["precipitation"], alpha=0.25, width=0.03, label="Rain")

    for _, row in day_df.iloc[::3].iterrows():
        compass = deg_to_compass(row["wind_direction_10m"])
        if pd.notna(row["wind_speed_10m"]):
            ax_wind.annotate(
                compass,
                (row["time"], row["wind_speed_10m"]),
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                fontweight="bold",
            )

        if pd.notna(row["temperature_2m"]) and pd.notna(row["wind_direction_10m"]):
            if row["temperature_2m"] > 28 and (row["wind_direction_10m"] >= 315 or row["wind_direction_10m"] <= 45):
                ax_temp.scatter(row["time"], row["temperature_2m"], color="red", marker="x", s=120, zorder=5)

        if pd.notna(row["wind_gusts_10m"]) and pd.notna(row["wind_speed_10m"]):
            if row["wind_gusts_10m"] > 45:
                ax_wind.scatter(row["time"], row["wind_speed_10m"], color="red", marker="x", s=120, zorder=5)

        if pd.notna(row["precipitation"]):
            if row["precipitation"] >= 1:
                ax_rain.scatter(row["time"], row["precipitation"], color="red", marker="x", s=120, zorder=5)

    ax_temp.axvline(now_dt, linestyle=":", lw=2, color="black")

    ax_temp.set_title(f"{location_name.upper()} — TODAY (Hourly)", fontweight="bold", fontsize=14)
    ax_temp.set_ylabel("Temp (°C)", fontweight="bold", color="red")
    ax_wind.set_ylabel("Wind (km/h)", fontweight="bold")
    ax_rain.set_ylabel("Rain (mm)", fontweight="bold")

    _format_hour_axis(ax_temp)
    ax_temp.grid(True, alpha=0.18)

    ax_temp.legend(
        [l1a, l1f, l2a, l2f, l2g, l3],
        ["Actual Temp", "Forecast Temp", "Actual Wind", "Forecast Wind", "Wind Gusts", "Rain"],
        loc="upper left",
        fontsize=8,
    )

    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_weekly(d_df, location_name):
    fig, ax_temp = plt.subplots(figsize=(11, 5.7))

    if d_df is None or d_df.empty or "time" not in d_df.columns:
        ax_temp.text(
            0.5, 0.5,
            "No weekly data returned from API.",
            ha="center", va="center",
            transform=ax_temp.transAxes
        )
        ax_temp.set_title(f"7-DAY OUTLOOK: {location_name}", fontweight="bold", fontsize=14)
        ax_temp.axis("off")
        buf = BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        buf.seek(0)
        return buf

    ax_wind = ax_temp.twinx()
    ax_rain = ax_temp.twinx()
    ax_rain.spines["right"].set_position(("axes", 1.12))

    l1, = ax_temp.plot(
        d_df["time"],
        d_df["temperature_2m_max"],
        lw=2.6,
        color="red",
        label="Max Temp"
    )
    l2, = ax_wind.plot(d_df["time"], d_df["wind_speed_10m_max"], lw=1.8, label="Max Wind")
    l2g, = ax_wind.plot(d_df["time"], d_df["wind_gusts_10m_max"], linestyle=":", lw=1.3, label="Max Gusts")
    l3 = ax_rain.bar(d_df["time"], d_df["precipitation_sum"], alpha=0.25, width=0.55, label="Rain")

    for _, row in d_df.iterrows():
        compass = deg_to_compass(row["wind_direction_10m_dominant"])
        if pd.notna(row["wind_speed_10m_max"]):
            ax_wind.annotate(
                compass,
                (row["time"], row["wind_speed_10m_max"]),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                fontweight="bold",
            )

        if pd.notna(row["temperature_2m_max"]) and pd.notna(row["wind_direction_10m_dominant"]):
            if row["temperature_2m_max"] > 28 and (row["wind_direction_10m_dominant"] >= 315 or row["wind_direction_10m_dominant"] <= 45):
                ax_temp.scatter(row["time"], row["temperature_2m_max"], color="red", marker="x", s=120, zorder=5)

        if pd.notna(row["wind_gusts_10m_max"]) and pd.notna(row["wind_speed_10m_max"]):
            if row["wind_gusts_10m_max"] > 45:
                ax_wind.scatter(row["time"], row["wind_speed_10m_max"], color="red", marker="x", s=120, zorder=5)

        if pd.notna(row["precipitation_sum"]):
            if row["precipitation_sum"] >= 5:
                ax_rain.scatter(row["time"], row["precipitation_sum"], color="red", marker="x", s=120, zorder=5)

    ax_temp.set_title(f"7-DAY OUTLOOK: {location_name}", fontweight="bold", fontsize=14)
    ax_temp.set_ylabel("Max Temp (°C)", fontweight="bold", color="red")
    ax_wind.set_ylabel("Wind (km/h)", fontweight="bold")
    ax_rain.set_ylabel("Rain (mm)", fontweight="bold")

    ax_temp.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    ax_temp.grid(True, alpha=0.18)

    ax_temp.legend(
        [l1, l2, l2g, l3],
        ["Max Temp", "Max Wind", "Max Gusts", "Rain"],
        loc="upper left",
        fontsize=8,
    )

    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def _generate_report_legacy(target: str, data: Any, output_dir: str, logger: Callable[[str], None] = print):
    try:
        if isinstance(data, dict):
            lat = float(data.get("latitude", data.get("lat", 0)))
            lon = float(data.get("longitude", data.get("lon", 0)))
        elif isinstance(data, (list, tuple)) and len(data) >= 2:
            lat, lon = float(data[0]), float(data[1])
        else:
            logger(f"Error: Unexpected data format in weather_worker for {target}")
            return None

        final_folder = os.path.join(output_dir, target)
        os.makedirs(final_folder, exist_ok=True)

        return _build_weather_pdf(
            location_name=target,
            lat=lat,
            lon=lon,
            output_dir=final_folder,
            logger=logger,
        )

    except Exception as e:
        logger(f"Critical failure in weather_worker for {target}: {e}")
        return None


def _build_weather_pdf(
    location_name: str,
    lat: float,
    lon: float,
    output_dir: str,
    logger: Callable[[str], None] = print,
):
    h_df, d_df, tz_name = fetch_weather_data(lat, lon, logger=logger)
    if h_df is None or h_df.empty:
        logger(f"API failure in weather_worker for {location_name}")
        return None

    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now(ZoneInfo(DEFAULT_TZ)).strftime("%Y-%m-%d_%H%M%S")
    safe_name = make_safe_name(location_name)
    ppath = os.path.join(output_dir, f"{safe_name}_Weather_Report_{timestamp}.pdf")

    daily_img = generate_daily(h_df, location_name, tz_name=tz_name)
    weekly_img = generate_weekly(d_df, location_name)

    doc = SimpleDocTemplate(
        ppath,
        pagesize=A4,
        topMargin=0.6 * cm,
        bottomMargin=0.6 * cm
    )
    styles = getSampleStyleSheet()

    status_table = build_weather_status_table(h_df, tz_name, styles, logger=logger)

    story = [
        Paragraph(f"<b>WEATHER REPORT: {location_name}</b>", styles["Title"]),
        Spacer(1, 8),
        status_table,
        Spacer(1, 10),
        Image(daily_img, 19 * cm, 9.2 * cm),
        Spacer(1, 10),
        Image(weekly_img, 19 * cm, 9.2 * cm),
        Spacer(1, 6),
        Paragraph(
            f"<font size=8>Generated | {datetime.now(ZoneInfo(DEFAULT_TZ)).strftime('%Y-%m-%d %H:%M')}</font>",
            styles["Normal"]
        ),
    ]

    doc.build(story)

    if os.path.exists(ppath) and os.path.getsize(ppath) > 1000:
        logger(f"SUCCESS: Weather PDF created at {ppath}")
        return ppath

    logger("Weather PDF was not written or is too small.")
    return None


def generate_report(
    location_name: str,
    lat: float,
    lon: float,
    logger: Callable[[str], None] = print,
):
    """
    App-friendly worker signature.
    Matches app.py:
        generate_report(location_name=..., lat=..., lon=...)
    """
    return _build_weather_pdf(
        location_name=location_name,
        lat=float(lat),
        lon=float(lon),
        output_dir=LOCAL_DIR,
        logger=logger,
    )