#!/usr/bin/env python3
import streamlit as st

# -------------------------------------------------
# SET THIS TO YOUR LIVE SENTINEL APP URL
# -------------------------------------------------
SENTINEL_APP_URL = "https://sentinel-access-v2-steamlit-3m8hjtrpznzu3skhp3inqh.streamlit.app/"

APP_TITLE = "Surf - Sky - Weather - Trp Planner"
APP_SUBTITLE = "Professional report delivery dashboard"


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #dceaf7 0%, #eaf2fb 100%);
        }

        .block-container {
            max-width: 980px;
            padding-top: 2.2rem;
            padding-bottom: 2rem;
        }

        .hero-wrap {
            background: #ffffff;
            border: 1px solid #bfd3e6;
            border-radius: 22px;
            padding: 1.4rem 1.3rem 1.25rem 1.3rem;
            margin-bottom: 1rem;
            box-shadow: 0 4px 16px rgba(23, 50, 77, 0.08);
        }

        .hero-title {
            font-size: 2.1rem;
            font-weight: 800;
            color: #17324d;
            line-height: 1.05;
            margin-bottom: 0.25rem;
        }

        .hero-subtitle {
            font-size: 1.02rem;
            font-weight: 600;
            color: #4b6785;
            margin-bottom: 0.8rem;
        }

        .hero-text {
            font-size: 1rem;
            color: #284866;
            line-height: 1.6;
        }

        .section-card {
            background: #ffffff;
            border: 1px solid #bfd3e6;
            border-radius: 18px;
            padding: 1rem 1rem 0.9rem 1rem;
            margin-bottom: 0.9rem;
            box-shadow: 0 2px 10px rgba(23, 50, 77, 0.06);
        }

        .section-heading {
            font-size: 1.05rem;
            font-weight: 800;
            color: #17324d;
            margin-bottom: 0.65rem;
        }

        .feature-card {
            background: #f8fbff;
            border: 1px solid #d5e2ef;
            border-radius: 16px;
            padding: 0.9rem 0.9rem 0.8rem 0.9rem;
            min-height: 150px;
        }

        .feature-title {
            font-size: 0.98rem;
            font-weight: 800;
            color: #17324d;
            margin-bottom: 0.4rem;
        }

        .feature-text {
            font-size: 0.94rem;
            color: #284866;
            line-height: 1.5;
        }

        .cta-note {
            font-size: 0.92rem;
            color: #4b6785;
            margin-top: 0.45rem;
        }

        .footer-note {
            text-align: center;
            font-size: 0.88rem;
            color: #5d7690;
            padding-top: 0.4rem;
        }

        .stLinkButton > a {
            background: linear-gradient(135deg, #1faa63, #159251) !important;
            color: white !important;
            border: 1px solid #14874b !important;
            border-radius: 14px !important;
            font-weight: 800 !important;
            width: 100% !important;
            text-align: center !important;
            padding: 0.8rem 1rem !important;
            text-decoration: none !important;
            box-shadow: 0 3px 10px rgba(21, 146, 81, 0.18);
        }

        @media (max-width: 640px) {
            .hero-title {
                font-size: 1.7rem;
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
                "Surf - Sky - Weather - Trip Planner" is a mobile-friendly reporting platform designed to generate
                location-based reports and deliver them va your email as a PDF.
                Select your report type, choose your location, and run the report system
                to generate your Sentinel outputs.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def description_section() -> None:
    st.markdown(
        """
        <div class="section-card">
            <div class="section-heading">Available Reports</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2, gap="medium")

    with col1:
        st.markdown(
            """
            <div class="feature-card">
                <div class="feature-title">Surf Report</div>
                <div class="feature-text">
                    Provides a daily chart, a next best day chart and a weekly chart,
                    including wind, swell and tides.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:0.8rem;'></div>", unsafe_allow_html=True)

        st.markdown(
            """
            <div class="feature-card">
                <div class="feature-title">Weather Report</div>
                <div class="feature-text">
                    Provides a daily and weekly forecast chart together with weather warnings.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            """
            <div class="feature-card">
                <div class="feature-title">Sky Report & Moon Events</div>
                <div class="feature-text">
                    Designed for photographers, providing daily and nightly sky conditions,
                    next best viewing day, weekly outlook, moon phase and azimuth,
                    moon events, and cloud or haze cover.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:0.8rem;'></div>", unsafe_allow_html=True)

        st.markdown(
            """
            <div class="feature-card">
                <div class="feature-title">Trip Planner</div>
                <div class="feature-text">
                    Provides a chart with the start location and next three destinations,
                    together with a fuel and cost calculator.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def cta_section() -> None:
    st.markdown(
        """
        <div class="section-card">
            <div class="section-heading">Start Sentinel</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.link_button("Run Report", SENTINEL_APP_URL, use_container_width=True)
    st.markdown(
        """
        <div class="cta-note">
            Tap the button above to open the Sentinel report system.
        </div>
        """,
        unsafe_allow_html=True,
    )


def footer() -> None:
    st.markdown(
        """
        <div class="footer-note">
            Surf - Sky - Weather - Trip Planner • Report generation for surf, weather, sky, moon and trip planning
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="centered")
    apply_styles()
    hero_section()
    description_section()
    st.markdown("<div style='height:0.4rem;'></div>", unsafe_allow_html=True)
    cta_section()
    st.markdown("<div style='height:0.7rem;'></div>", unsafe_allow_html=True)
    footer()


if __name__ == "__main__":
    main()