#!/usr/bin/env python3
from pathlib import Path
import base64
import streamlit as st

# -------------------------------------------------
# SET THIS TO YOUR LIVE SENTINEL APP URL
# -------------------------------------------------
SENTINEL_APP_URL = "https://sentinel-access-v2-steamlit-3m8hjtrpznzu3skhp3inqh.streamlit.app/"

APP_TITLE = "Surf • Sky • Weather • Trip Planner"
APP_SUBTITLE = "Professional report delivery dashboard"

# -------------------------------------------------
# IMAGE FILES
# Put these in the SAME folder as this script
# -------------------------------------------------
ROOT = Path(__file__).resolve().parent
SURF_IMAGE = ROOT / "surf_report.jpg"
SKY_IMAGE = ROOT / "sky_moon_report.jpg"
WEATHER_IMAGE = ROOT / "weather_report.jpg"
TRIP_IMAGE = ROOT / "trip_planner.jpg"


def img_to_base64(path: Path) -> str:
    if not path.exists():
        return ""
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(90, 140, 195, 0.12) 0%, rgba(90, 140, 195, 0.00) 28%),
                radial-gradient(circle at top right, rgba(39, 174, 96, 0.06) 0%, rgba(39, 174, 96, 0.00) 24%),
                linear-gradient(180deg, #183454 0%, #22486f 52%, #1b3c5d 100%);
        }

        .block-container {
            max-width: 1080px;
            padding-top: 2.2rem;
            padding-bottom: 2rem;
        }

        .hero-wrap {
            background: linear-gradient(180deg, rgba(46, 77, 112, 0.97) 0%, rgba(39, 68, 100, 0.98) 100%);
            border: 1px solid rgba(190, 215, 240, 0.28);
            border-radius: 24px;
            padding: 1.55rem 1.45rem 1.35rem 1.45rem;
            margin-bottom: 1.05rem;
            box-shadow:
                0 10px 26px rgba(0, 0, 0, 0.16),
                0 0 0 1px rgba(255, 255, 255, 0.02) inset;
        }

        .hero-title {
            font-size: 2.25rem;
            font-weight: 800;
            color: #f4f8ff;
            line-height: 1.05;
            letter-spacing: -0.02em;
            margin-bottom: 0.28rem;
        }

        .hero-subtitle {
            font-size: 1.02rem;
            font-weight: 600;
            color: #d4e4f4;
            margin-bottom: 0.85rem;
        }

        .hero-text {
            font-size: 1rem;
            color: #edf4fb;
            line-height: 1.68;
        }

        .report-grid-gap {
            height: 0.9rem;
        }

        .report-card {
            background: linear-gradient(180deg, rgba(41, 70, 104, 0.96) 0%, rgba(35, 61, 91, 0.98) 100%);
            border: 1px solid rgba(190, 215, 240, 0.22);
            border-radius: 20px;
            padding: 1rem;
            margin-bottom: 0.95rem;
            box-shadow:
                0 8px 22px rgba(0, 0, 0, 0.14),
                0 0 0 1px rgba(255, 255, 255, 0.02) inset;
        }

        .report-inner {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }

        .report-text {
            flex: 1 1 auto;
            min-width: 0;
            text-align: left;
        }

        .report-title {
            font-size: 1.02rem;
            font-weight: 800;
            color: #f4f8ff;
            margin-bottom: 0.42rem;
            text-align: left;
        }

        .report-body {
            font-size: 0.95rem;
            color: #eef5fc;
            line-height: 1.58;
            text-align: left;
        }

        .report-image-wrap {
            flex: 0 0 220px;
            width: 220px;
        }

        .report-image {
            width: 220px;
            height: 130px;
            object-fit: cover;
            border-radius: 16px;
            border: 1px solid rgba(220, 235, 250, 0.22);
            display: block;
            box-shadow: 0 8px 18px rgba(0, 0, 0, 0.14);
        }

        .cta-card {
            background: linear-gradient(180deg, rgba(41, 70, 104, 0.96) 0%, rgba(35, 61, 91, 0.98) 100%);
            border: 1px solid rgba(190, 215, 240, 0.22);
            border-radius: 20px;
            padding: 0.95rem 1rem 0.95rem 1rem;
            margin-top: 0.6rem;
            box-shadow:
                0 8px 22px rgba(0, 0, 0, 0.14),
                0 0 0 1px rgba(255, 255, 255, 0.02) inset;
        }

        .cta-heading {
            font-size: 1.06rem;
            font-weight: 800;
            color: #f4f8ff;
            margin-bottom: 0.35rem;
        }

        .cta-note {
            font-size: 0.92rem;
            color: #d4e4f4;
            margin-top: 0.55rem;
        }

        .footer-note {
            text-align: center;
            font-size: 0.88rem;
            color: #c8dbee;
            padding-top: 0.75rem;
        }

        .stLinkButton > a {
            background: linear-gradient(135deg, #1faa63, #159251) !important;
            color: #ffffff !important;
            border: 1px solid #14874b !important;
            border-radius: 15px !important;
            font-weight: 800 !important;
            width: 100% !important;
            text-align: center !important;
            padding: 0.92rem 1rem !important;
            text-decoration: none !important;
            box-shadow:
                0 6px 16px rgba(21, 146, 81, 0.26),
                0 0 18px rgba(31, 170, 99, 0.10);
            transition: all 0.18s ease !important;
        }

        .stLinkButton > a:hover {
            transform: translateY(-1px);
            box-shadow:
                0 10px 22px rgba(21, 146, 81, 0.30),
                0 0 22px rgba(31, 170, 99, 0.14);
            border-color: #19a65a !important;
        }

        @media (max-width: 860px) {
            .report-inner {
                flex-direction: column;
                align-items: stretch;
            }

            .report-image-wrap {
                flex: none;
                width: 100%;
            }

            .report-image {
                width: 100%;
                height: 190px;
            }

            .hero-title {
                font-size: 1.78rem;
            }

            .hero-subtitle {
                font-size: 0.96rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero_section() -> None:
    st.markdown(
        f"""
        <div class="hero-wrap">
            <div class="hero-title">{APP_TITLE}</div>
            <div class="hero-subtitle">{APP_SUBTITLE}</div>
            <div class="hero-text">
                Sentinel Access is a mobile-friendly reporting platform designed to generate
                location-based PDF reports and deliver them directly by email.
                Choose your report type, select your location, and launch the Sentinel system
                for surf, sky, weather, moon, and trip planning insights.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def report_card(title: str, text: str, image_path: Path) -> None:
    img_b64 = img_to_base64(image_path)

    if img_b64:
        image_html = f'<img class="report-image" src="data:image/jpeg;base64,{img_b64}" alt="{title}">'
    else:
        image_html = (
            '<div class="report-image" '
            'style="display:flex;align-items:center;justify-content:center;'
            'color:#d4e4f4;background:rgba(255,255,255,0.08);font-weight:700;">'
            'Image not found</div>'
        )

    st.markdown(
        f"""
        <div class="report-card">
            <div class="report-inner">
                <div class="report-text">
                    <div class="report-title">{title}</div>
                    <div class="report-body">{text}</div>
                </div>
                <div class="report-image-wrap">
                    {image_html}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def reports_section() -> None:
    report_card(
        "Surf Report",
        "Daily surf conditions, next best day guidance, and weekly outlooks covering swell, wind, and tide intelligence.",
        SURF_IMAGE,
    )

    report_card(
        "Sky & Moon Report",
        "Built for photographers and night-sky viewing, including day and night clarity, best viewing windows, moon phase tracking, and lunar events.",
        SKY_IMAGE,
    )

    report_card(
        "Weather Report",
        "Daily and weekly forecast views with temperature, conditions, and weather alert summaries for your selected location.",
        WEATHER_IMAGE,
    )

    report_card(
        "Trip Planner",
        "Route planning with a start point, multiple destinations, fuel usage estimates, and trip cost guidance.",
        TRIP_IMAGE,
    )


def cta_section() -> None:
    st.markdown(
        """
        <div class="cta-card">
            <div class="cta-heading">Start Sentinel</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.link_button("Run Report", SENTINEL_APP_URL, use_container_width=True)

    st.markdown(
        """
        <div class="cta-note">
            Open the Sentinel report system to generate and email your selected reports.
        </div>
        """,
        unsafe_allow_html=True,
    )


def footer() -> None:
    st.markdown(
        """
        <div class="footer-note">
            Sentinel Access • Surf • Sky • Weather • Moon • Trip Planning
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    apply_styles()
    hero_section()
    reports_section()
    st.markdown("<div style='height:0.45rem;'></div>", unsafe_allow_html=True)
    cta_section()
    footer()


if __name__ == "__main__":
    main()
