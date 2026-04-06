#!/usr/bin/env python3
from pathlib import Path
import base64
import mimetypes
import streamlit as st

# -------------------------------------------------
# SET THIS TO YOUR LIVE SENTINEL APP URL
# -------------------------------------------------
SENTINEL_APP_URL = "https://sentinel-access-v2-steamlit-3m8hjtrpznzu3skhp3inqh.streamlit.app/"

APP_TITLE = "Surf • Sky • Weather • Trip Planner"
APP_SUBTITLE = "Professional report delivery dashboard"

ROOT = Path(__file__).resolve().parent


# -------------------------------------------------
# IMAGE HELPERS
# Accept jpg / jpeg / png / webp automatically
# -------------------------------------------------
def find_image(stem: str) -> Path | None:
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        candidate = ROOT / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def img_to_data_uri(path: Path | None) -> str:
    if not path or not path.exists():
        return ""

    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "image/jpeg"

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


SURF_IMAGE = find_image("surf_report")
SKY_IMAGE = find_image("sky_moon_report")
WEATHER_IMAGE = find_image("weather_report")
TRIP_IMAGE = find_image("trip_planner")


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
            max-width: 1420px;
            padding-top: 1.8rem;
            padding-bottom: 1.4rem;
        }

        .hero-wrap {
            background: linear-gradient(180deg, rgba(46, 77, 112, 0.97) 0%, rgba(39, 68, 100, 0.98) 100%);
            border: 1px solid rgba(190, 215, 240, 0.28);
            border-radius: 22px;
            padding: 1.3rem 1.25rem 1.15rem 1.25rem;
            margin-bottom: 0.8rem;
            box-shadow:
                0 10px 26px rgba(0, 0, 0, 0.16),
                0 0 0 1px rgba(255, 255, 255, 0.02) inset;
        }

        .hero-title {
            font-size: 2.05rem;
            font-weight: 800;
            color: #f4f8ff;
            line-height: 1.05;
            letter-spacing: -0.02em;
            margin-bottom: 0.2rem;
        }

        .hero-subtitle {
            font-size: 0.98rem;
            font-weight: 600;
            color: #d4e4f4;
            margin-bottom: 0.7rem;
        }

        .hero-text {
            font-size: 0.96rem;
            color: #edf4fb;
            line-height: 1.58;
        }

        .cta-top-wrap {
            margin-bottom: 0.9rem;
        }

        .stLinkButton > a {
            background: linear-gradient(135deg, #1faa63, #159251) !important;
            color: #ffffff !important;
            border: 1px solid #14874b !important;
            border-radius: 14px !important;
            font-weight: 800 !important;
            width: 100% !important;
            text-align: center !important;
            padding: 0.88rem 1rem !important;
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

        .reports-row {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.8rem;
            margin-bottom: 0.6rem;
        }

        .report-card {
            background: linear-gradient(180deg, rgba(41, 70, 104, 0.96) 0%, rgba(35, 61, 91, 0.98) 100%);
            border: 1px solid rgba(190, 215, 240, 0.22);
            border-radius: 18px;
            padding: 0.9rem;
            box-shadow:
                0 8px 22px rgba(0, 0, 0, 0.14),
                0 0 0 1px rgba(255, 255, 255, 0.02) inset;
            min-height: 245px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }

        .report-inner {
            display: flex;
            flex-direction: column;
            gap: 0.8rem;
            height: 100%;
        }

        .report-text {
            text-align: left;
        }

        .report-title {
            font-size: 0.98rem;
            font-weight: 800;
            color: #f4f8ff;
            margin-bottom: 0.36rem;
            text-align: left;
        }

        .report-body {
            font-size: 0.85rem;
            color: #eef5fc;
            line-height: 1.48;
            text-align: left;
        }

        .report-image {
            width: 100%;
            height: 112px;
            object-fit: cover;
            border-radius: 14px;
            border: 1px solid rgba(220, 235, 250, 0.22);
            display: block;
            box-shadow: 0 8px 18px rgba(0, 0, 0, 0.14);
        }

        .report-image-fallback {
            width: 100%;
            height: 112px;
            border-radius: 14px;
            border: 1px solid rgba(220, 235, 250, 0.22);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #d4e4f4;
            background: rgba(255, 255, 255, 0.08);
            font-size: 0.82rem;
            font-weight: 700;
        }

        .footer-note {
            text-align: center;
            font-size: 0.86rem;
            color: #c8dbee;
            padding-top: 0.7rem;
        }

        @media (max-width: 1200px) {
            .reports-row {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 720px) {
            .reports-row {
                grid-template-columns: 1fr;
            }

            .hero-title {
                font-size: 1.72rem;
            }

            .hero-subtitle {
                font-size: 0.94rem;
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


def top_button() -> None:
    st.markdown('<div class="cta-top-wrap">', unsafe_allow_html=True)
    st.link_button("Run Report", SENTINEL_APP_URL, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def report_card_html(title: str, text: str, image_path: Path | None) -> str:
    data_uri = img_to_data_uri(image_path)

    if data_uri:
        image_html = f'<img class="report-image" src="{data_uri}" alt="{title}">'
    else:
        image_html = '<div class="report-image-fallback">Image not found</div>'

    return f"""
    <div class="report-card">
        <div class="report-inner">
            <div class="report-text">
                <div class="report-title">{title}</div>
                <div class="report-body">{text}</div>
            </div>
            {image_html}
        </div>
    </div>
    """


def reports_section() -> None:
    html = f"""
    <div class="reports-row">
        {report_card_html(
            "Surf Report",
            "Daily surf conditions, next best day guidance, and weekly outlooks covering swell, wind, and tide intelligence.",
            SURF_IMAGE,
        )}
        {report_card_html(
            "Sky & Moon Report",
            "Built for photographers and night-sky viewing, including day and night clarity, best viewing windows, moon phase tracking, and lunar events.",
            SKY_IMAGE,
        )}
        {report_card_html(
            "Weather Report",
            "Daily and weekly forecast views with temperature, conditions, and weather alert summaries for your selected location.",
            WEATHER_IMAGE,
        )}
        {report_card_html(
            "Trip Planner",
            "Route planning with a start point, multiple destinations, fuel usage estimates, and trip cost guidance.",
            TRIP_IMAGE,
        )}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


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
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    apply_styles()
    hero_section()
    top_button()
    reports_section()
    footer()


if __name__ == "__main__":
    main()
