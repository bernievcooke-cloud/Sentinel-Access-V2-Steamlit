#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import platform
from datetime import datetime
from io import BytesIO
from typing import Any, Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from core.location_manager import LocationManager


LOCAL_DIR = (
    r"C:\RuralAI\OUTPUT\TRIP"
    if platform.system() == "Windows"
    else os.path.join(os.path.expanduser("~"), "Documents", "Trip Reports")
)
os.makedirs(LOCAL_DIR, exist_ok=True)

OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"
ROUTING_TIMEOUT = 20


def _get_logger(
    logger: Callable[[str], None] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> Callable[[str], None]:
    return progress_callback or logger or print


def make_safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name.replace(" ", "_"))


def _fresh_location_manager() -> LocationManager:
    lm = LocationManager()
    if hasattr(lm, "reload"):
        try:
            lm.reload()
        except Exception:
            pass
    return lm


def _get_lat_lon_from_location(name: str) -> tuple[float, float]:
    original_name = str(name).strip()
    lm = _fresh_location_manager()

    candidates = [original_name]

    if "," in original_name:
        stripped = original_name.split(",", 1)[0].strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)

    for candidate in candidates:
        payload = lm.get(candidate)

        if isinstance(payload, dict):
            lat = payload.get("latitude", payload.get("lat"))
            lon = payload.get("longitude", payload.get("lon"))
            if lat is not None and lon is not None:
                return float(lat), float(lon)

        if isinstance(payload, (tuple, list)) and len(payload) >= 2:
            return float(payload[0]), float(payload[1])

    all_locations = []
    if hasattr(lm, "_locations") and isinstance(getattr(lm, "_locations"), dict):
        for key, value in lm._locations.items():
            if isinstance(value, dict):
                all_locations.append((str(key), value))

    for candidate in candidates:
        candidate_cf = candidate.casefold()
        for key, value in all_locations:
            if key.casefold() == candidate_cf:
                lat = value.get("latitude", value.get("lat"))
                lon = value.get("longitude", value.get("lon"))
                if lat is not None and lon is not None:
                    return float(lat), float(lon)

    raise ValueError(f"Unknown location: {original_name}")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180.0
    a = (
        0.5
        - math.cos((lat2 - lat1) * p) / 2.0
        + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2.0
    )
    return 12742.0 * math.asin(math.sqrt(a))


def _get_road_route(lat1: float, lon1: float, lat2: float, lon2: float) -> dict[str, float | str]:
    """
    Returns road route info from OSRM.
    Falls back via exception handling in caller if needed.
    """
    url = (
        f"{OSRM_ROUTE_URL}/"
        f"{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
        "?overview=false&steps=false&alternatives=false"
    )

    r = requests.get(url, timeout=ROUTING_TIMEOUT)
    r.raise_for_status()
    data = r.json()

    routes = data.get("routes") or []
    if not routes:
        raise ValueError("No road route returned")

    route0 = routes[0]
    distance_m = float(route0.get("distance", 0.0))
    duration_s = float(route0.get("duration", 0.0))

    if distance_m <= 0:
        raise ValueError("Road distance returned as zero")

    return {
        "distance_km": distance_m / 1000.0,
        "duration_hr": duration_s / 3600.0,
        "source": "road",
    }


def _get_leg_distance_and_time(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    logger: Callable[[str], None],
) -> dict[str, float | str]:
    """
    Prefer road distance. Fall back to haversine if routing fails.
    """
    try:
        return _get_road_route(lat1, lon1, lat2, lon2)
    except Exception as e:
        fallback_km = _haversine_km(lat1, lon1, lat2, lon2)
        logger(f"Road routing unavailable, using straight-line fallback: {e}")
        return {
            "distance_km": fallback_km,
            "duration_hr": 0.0,
            "source": "straight-line fallback",
        }


def _litres(distance_km: float, fuel_l_per_100km: float) -> float:
    return max(0.0, float(distance_km)) * (float(fuel_l_per_100km) / 100.0)


def _money(v: float) -> str:
    return f"${v:,.2f}"


def _make_leg_short_name(start: str, end: str, idx: int) -> str:
    s = str(start).strip()
    e = str(end).strip()

    s_short = s.split(",")[0].strip()
    e_short = e.split(",")[0].strip()

    if len(s_short) > 12:
        s_short = s_short[:12] + "…"
    if len(e_short) > 12:
        e_short = e_short[:12] + "…"

    return f"L{idx}\n{s_short}→{e_short}"


def _add_top_totals_band(fig, total_km: float, total_l: float, total_cost: float, fuel_type: str, price_per_l: float):
    band = fig.add_axes([0.06, 0.89, 0.88, 0.085])
    band.set_facecolor("#e8f5e9")
    for spine in band.spines.values():
        spine.set_color("#2e7d32")
        spine.set_linewidth(1.2)
    band.set_xticks([])
    band.set_yticks([])
    band.set_xlim(0, 1)
    band.set_ylim(0, 1)

    band.text(
        0.02, 0.67,
        "TRIP TOTALS",
        fontsize=12,
        fontweight="bold",
        color="#1b5e20",
        va="center",
        ha="left",
    )
    band.text(
        0.02, 0.25,
        f"{fuel_type} @ ${price_per_l:.2f}/L",
        fontsize=9,
        color="#2f3b2f",
        va="center",
        ha="left",
    )

    band.text(
        0.42, 0.58,
        f"Total kms\n{total_km:.1f} km",
        fontsize=11,
        fontweight="bold",
        color="#1b5e20",
        va="center",
        ha="center",
    )
    band.text(
        0.66, 0.58,
        f"Total fuel\n{total_l:.1f} L",
        fontsize=11,
        fontweight="bold",
        color="#1b5e20",
        va="center",
        ha="center",
    )
    band.text(
        0.88, 0.58,
        f"Total fuel cost\n{_money(total_cost)}",
        fontsize=11,
        fontweight="bold",
        color="#1b5e20",
        va="center",
        ha="center",
    )


def _make_charts(
    legs_rows: list[dict[str, Any]],
    fuel_type: str,
    price_per_l: float,
    fuel_l_per_100km: float,
    total_km: float,
    total_l: float,
    total_cost: float,
) -> BytesIO:
    df = pd.DataFrame(legs_rows)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.4, 8.6))
    fig.subplots_adjust(top=0.84, bottom=0.09, left=0.09, right=0.96, hspace=0.40)

    _add_top_totals_band(
        fig=fig,
        total_km=total_km,
        total_l=total_l,
        total_cost=total_cost,
        fuel_type=fuel_type,
        price_per_l=price_per_l,
    )

    names = df["name"].tolist()
    dists = df["dist_km"].tolist()
    costs = df["cost"].tolist()

    green_main = "#2e7d32"
    green_mid = "#43a047"
    green_soft = "#81c784"
    edge_col = "#1b5e20"

    bars1 = ax1.bar(
        names,
        dists,
        color=green_main,
        edgecolor=edge_col,
        linewidth=0.9,
        width=0.54,
    )
    ax1.set_title("Distance per Leg", fontsize=12, fontweight="bold", pad=10)
    ax1.set_ylabel("Kilometres", fontsize=9, fontweight="bold")
    ax1.grid(True, axis="y", alpha=0.18, linewidth=0.7)
    ax1.set_axisbelow(True)
    ax1.tick_params(axis="x", labelsize=8)
    ax1.tick_params(axis="y", labelsize=8)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.set_facecolor("#fbfdfb")

    ymax1 = max(dists) if dists else 1.0
    ax1.set_ylim(0, ymax1 * 1.22)

    for rect, value in zip(bars1, dists):
        ax1.text(
            rect.get_x() + rect.get_width() / 2.0,
            rect.get_height() + ymax1 * 0.03,
            f"{value:.1f} km",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color="#1b1b1b",
        )

    bars2 = ax2.bar(
        names,
        costs,
        color=green_soft,
        edgecolor=edge_col,
        linewidth=0.9,
        width=0.54,
    )
    ax2.set_title(
        f"Fuel Cost per Leg  •  {fuel_l_per_100km:.1f} L/100km",
        fontsize=12,
        fontweight="bold",
        pad=10,
    )
    ax2.set_ylabel("Cost ($)", fontsize=9, fontweight="bold")
    ax2.grid(True, axis="y", alpha=0.18, linewidth=0.7)
    ax2.set_axisbelow(True)
    ax2.tick_params(axis="x", labelsize=8)
    ax2.tick_params(axis="y", labelsize=8)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.set_facecolor("#fbfdfb")

    ymax2 = max(costs) if costs else 1.0
    ax2.set_ylim(0, ymax2 * 1.24)

    for rect, value in zip(bars2, costs):
        ax2.text(
            rect.get_x() + rect.get_width() / 2.0,
            rect.get_height() + ymax2 * 0.03,
            f"${value:.2f}",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color="#1b1b1b",
        )

    fig.text(
        0.5,
        0.865,
        "Leg-by-leg trip breakdown",
        ha="center",
        va="center",
        fontsize=10,
        color=green_mid,
        fontweight="bold",
    )

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _build_trip_pdf(
    route: list[str],
    fuel_type: str,
    fuel_l_per_100km: float,
    price_per_l: float,
    output_dir: str,
    logger: Callable[[str], None] = print,
):
    if len(route) < 2:
        raise ValueError("Trip route must contain at least 2 locations.")

    logger(f"Trip route received: {' -> '.join(route)}")

    legs_rows: list[dict[str, Any]] = []
    total_km = 0.0
    total_l = 0.0
    total_cost = 0.0
    total_drive_hr = 0.0
    routing_sources: list[str] = []

    for i in range(len(route) - 1):
        s = str(route[i]).strip()
        e = str(route[i + 1]).strip()

        logger(f"Resolving leg {i+1}: {s} -> {e}")

        lat1, lon1 = _get_lat_lon_from_location(s)
        lat2, lon2 = _get_lat_lon_from_location(e)

        leg_route = _get_leg_distance_and_time(lat1, lon1, lat2, lon2, logger)
        dist_km = float(leg_route["distance_km"])
        duration_hr = float(leg_route["duration_hr"])
        route_source = str(leg_route["source"])

        litres = _litres(dist_km, fuel_l_per_100km)
        cost = litres * price_per_l

        total_km += dist_km
        total_l += litres
        total_cost += cost
        total_drive_hr += duration_hr
        routing_sources.append(route_source)

        logger(
            f"Leg {i+1} done: {s} -> {e} | {dist_km:.1f} km | {litres:.1f} L | ${cost:.2f} | {route_source}"
        )

        legs_rows.append(
            {
                "name": _make_leg_short_name(s, e, i + 1),
                "start": s,
                "end": e,
                "dist_km": dist_km,
                "litres": litres,
                "cost": cost,
                "duration_hr": duration_hr,
                "route_source": route_source,
            }
        )

    chart_buf = _make_charts(
        legs_rows=legs_rows,
        fuel_type=fuel_type,
        price_per_l=price_per_l,
        fuel_l_per_100km=fuel_l_per_100km,
        total_km=total_km,
        total_l=total_l,
        total_cost=total_cost,
    )

    os.makedirs(output_dir, exist_ok=True)
    route_title = " -> ".join(str(x) for x in route)
    filename = f"{make_safe_name('_'.join(str(x) for x in route))}_Trip_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    ppath = os.path.join(output_dir, filename)

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="SmallMuted",
            parent=styles["Normal"],
            fontSize=8.2,
            textColor=colors.HexColor("#4b5563"),
            leading=9.6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TripHeader",
            parent=styles["Title"],
            fontSize=17,
            leading=19,
            textColor=colors.HexColor("#1b5e20"),
            spaceAfter=2,
        )
    )

    doc = SimpleDocTemplate(
        ppath,
        pagesize=A4,
        topMargin=0.65 * cm,
        bottomMargin=0.65 * cm,
        leftMargin=0.85 * cm,
        rightMargin=0.85 * cm,
    )

    unique_sources = sorted(set(routing_sources))
    routing_label = ", ".join(unique_sources) if unique_sources else "unknown"

    summary_table = Table(
        [
            ["Fuel type", fuel_type],
            ["Price per litre", f"${price_per_l:.2f}"],
            ["Consumption", f"{fuel_l_per_100km:.1f} L/100km"],
            ["Total distance", f"{total_km:.1f} km"],
            ["Total fuel", f"{total_l:.1f} L"],
            ["Total fuel cost", f"${total_cost:.2f}"],
            ["Estimated drive time", f"{total_drive_hr:.1f} hr" if total_drive_hr > 0 else "Not available"],
            ["Distance source", routing_label],
        ],
        colWidths=[4.9 * cm, 8.2 * cm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8f5e9")),
                ("BACKGROUND", (1, 0), (1, -1), colors.white),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.3),
                ("GRID", (0, 0), (-1, -1), 0.55, colors.HexColor("#b7c7b7")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    generated_text = datetime.now().strftime("%Y-%m-%d %H:%M")

    story = [
        Paragraph("<b>TRIP REPORT</b>", styles["TripHeader"]),
        Paragraph(f"<b>Route:</b> {route_title}", styles["Normal"]),
        Paragraph(f"Generated {generated_text}", styles["SmallMuted"]),
        Spacer(1, 0.14 * cm),
        Paragraph("<b>Trip Summary</b>", styles["Heading2"]),
        Spacer(1, 0.10 * cm),
        summary_table,
        Spacer(1, 0.20 * cm),
        Paragraph("<b>Leg Breakdown</b>", styles["Heading2"]),
        Spacer(1, 0.08 * cm),
    ]

    for idx, leg in enumerate(legs_rows, start=1):
        duration_text = (
            f" | {leg['duration_hr']:.1f} hr"
            if float(leg["duration_hr"]) > 0
            else ""
        )
        source_text = f" | {leg['route_source']}"

        story.append(
            Paragraph(
                f"{idx}. <b>{leg['start']} → {leg['end']}</b>  |  "
                f"{leg['dist_km']:.1f} km  |  "
                f"{leg['litres']:.1f} L  |  "
                f"${leg['cost']:.2f}"
                f"{duration_text}"
                f"{source_text}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.04 * cm))

    story.append(Spacer(1, 0.18 * cm))
    story.append(Image(chart_buf, 18.3 * cm, 15.2 * cm))

    doc.build(story)

    if os.path.exists(ppath) and os.path.getsize(ppath) > 1000:
        logger(f"SUCCESS: Trip PDF created at {ppath}")
        return ppath

    logger("ERROR: Trip PDF not written or too small.")
    return None


def generate_trip_report_from_route(
    route: list[str],
    fuel_type: str = "Petrol",
    fuel_l_per_100km: float = 9.5,
    fuel_price: float = 2.10,
    logger: Callable[[str], None] | None = None,
    progress_callback: Callable[[str], None] | None = None,
):
    active_logger = _get_logger(logger=logger, progress_callback=progress_callback)
    return _build_trip_pdf(
        route=route,
        fuel_type=fuel_type,
        fuel_l_per_100km=float(fuel_l_per_100km),
        price_per_l=float(fuel_price),
        output_dir=LOCAL_DIR,
        logger=active_logger,
    )


def generate_report(
    location_name: str,
    lat: float,
    lon: float,
    logger: Callable[[str], None] | None = None,
    progress_callback: Callable[[str], None] | None = None,
):
    """
    App-friendly fallback signature.
    This does NOT build a real multi-stop trip.
    It creates a simple placeholder trip report so app.py does not crash.
    """
    active_logger = _get_logger(logger=logger, progress_callback=progress_callback)

    try:
        os.makedirs(LOCAL_DIR, exist_ok=True)
        filename = f"{make_safe_name(location_name)}_Trip_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ppath = os.path.join(LOCAL_DIR, filename)

        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            ppath,
            pagesize=A4,
            topMargin=0.7 * cm,
            bottomMargin=0.7 * cm,
        )

        story = [
            Paragraph(f"<b>TRIP REPORT: {location_name}</b>", styles["Title"]),
            Spacer(1, 0.25 * cm),
            Paragraph(
                "This simplified trip report was generated from app.py using a single location.",
                styles["Normal"],
            ),
            Spacer(1, 0.15 * cm),
            Paragraph(
                "For a full trip calculation, provide a route with at least two saved locations.",
                styles["Normal"],
            ),
            Spacer(1, 0.20 * cm),
            Paragraph(f"<b>Location:</b> {location_name}", styles["Normal"]),
            Spacer(1, 0.08 * cm),
            Paragraph(f"<b>Latitude:</b> {float(lat):.6f}", styles["Normal"]),
            Spacer(1, 0.08 * cm),
            Paragraph(f"<b>Longitude:</b> {float(lon):.6f}", styles["Normal"]),
            Spacer(1, 0.20 * cm),
            Paragraph(
                "Use generate_trip_report_from_route(route=[...]) for real leg-by-leg fuel costing.",
                styles["Normal"],
            ),
        ]

        doc.build(story)

        if os.path.exists(ppath) and os.path.getsize(ppath) > 500:
            active_logger(f"SUCCESS: Trip placeholder PDF created at {ppath}")
            return ppath

        active_logger("ERROR: Trip placeholder PDF not written.")
        return None

    except Exception as e:
        active_logger(f"TRIP worker error: {e}")
        return None