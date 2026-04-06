#!/usr/bin/env python3
import streamlit as st

# -------------------------------------------------
# SET THIS TO YOUR LIVE SENTINEL APP URL
# -------------------------------------------------
SENTINEL_APP_URL = "https://sentinel-access-v2-steamlit-3m8hjtrpznzu3skhp3inqh.streamlit.app/"

APP_TITLE = "Surf • Sky • Weather • Trip Planner"
APP_SUBTITLE = "Professional report delivery dashboard"


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(53, 93, 145, 0.18) 0%, rgba(53, 93, 145, 0.00) 28%),
                radial-gradient(circle at top right, rgba(39, 174, 96, 0.10) 0%, rgba(39, 174, 96, 0.00) 22%),
                linear-gradient(180deg, #0b1e34 0%, #102844 52%, #0e2138 100%);
        }

        .block-container {
            max-width: 1040px;
            padding-top: 2.2rem;
            padding-bottom: 2rem;
        }

        .hero-wrap {
            background: linear-gradient(180deg, rgba(22, 42, 68, 0.96) 0%, rgba(18, 36, 58, 0.98) 100%);
            border: 1px solid rgba(145, 182, 219, 0.22);
            border-radius: 24px;
            padding: 1.55rem 1.45rem 1.35rem 1.45rem;
            margin-bottom: 1.05rem;
            box-shadow:
                0 10px 30px rgba(0, 0, 0, 0.22),
                0 0 0 1px rgba(255, 255, 255, 0.02) inset,
                0 0 26px rgba(98, 164, 255, 0.08);
        }

        .hero-title {
            font-size: 2.25rem;
            font-weight: 800;
            color: #e6f0ff;
            line-height: 1.05;
            letter-spacing: -0.02em;
            margin-bottom: 0.28rem;
        }

        .hero-subtitle {
            font-size: 1.02rem;
            font-weight: 600;
            color: #9bb7d6;
            margin-bottom: 0.85rem;
        }

        .hero-text {
            font-size: 1rem;
            color: #c7d9ee;
            line-height: 1.68;
        }

        .section-card {
            background: linear-gradient(180deg, rgba(20, 38, 61, 0.94) 0%, rgba(17, 33, 53, 0.98) 100%);
            border: 1px solid rgba(145, 182, 219, 0.18);
            border-radius: 20px;
            padding: 0.95rem 1rem 0.9rem 1rem;
            margin-bottom: 0.95rem;
            box-shadow:
                0 8px 24px rgba(0, 0, 0, 0.18),
                0 0 0 1px rgba(255, 255, 255, 0.02) inset;
        }

        .section-heading {
            font-size: 1.06rem;
            font-weight: 800;
            color: #e6f0ff;
            margin-bottom: 0.2rem;
            letter-spacing: 0.01em;
        }

        .feature-card {
            background: linear-gradient(180deg, rgba(27, 49, 78, 0.98) 0%, rgba(22, 42, 68, 0.98) 100%);
            border: 1px solid rgba(155, 183, 214, 0.18);
            border-radius: 18px;
            padding: 1rem 1rem 0.9rem 1rem;
            min-height: 158px;
            box-shadow:
                0 10px 20px rgba(0, 0, 0, 0.16),
                0 0 18px rgba(88, 151, 255, 0.05);
            transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
        }

        .feature-card:hover {
            transform: translateY(-2px);
            border-color: rgba(155, 183, 214, 0.30);
            box-shadow:
                0 14px 26px rgba(0, 0, 0, 0.22),
                0 0 24px rgba(88, 151, 255, 0.08);
        }

        .feature-title {
            font-size: 1rem;
            font-weight: 800;
            color: #e6f0ff;
            margin-bottom: 0.42rem;
        }

        .feature-text {
            font-size: 0.95rem;
            color: #c7d9ee;
            line-height: 1.58;
        }

        .cta-note {
            font-size: 0.92rem;
            color: #9bb7d6;
            margin-top: 0.55rem;
        }

        .footer-note {
            text-align: center;
            font-size: 0.88rem;
            color: #88a8cb;
            padding-top: 0.45rem;
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
                0 6px 16px rgba(21, 146, 81, 0.28),
                0 0 18px rgba(31, 170, 99, 0.12);
            transition: all 0.18s ease !important;
        }

        .stLinkButton > a:hover {
            transform: translateY(-1px);
            box-shadow:
                0 10px 22px rgba(21, 146, 81, 0.34),
                0 0 22px rgba(31, 170, 99, 0.16);
            border-color: #19a65a !important;
        }

        .stLinkButton > a:active {
            transform: translateY(0px);
        }

        div[data-testid="stHorizontalBlock"] > div {
            gap: 0.9rem !important;
        }

        @media (max-width: 768px) {
            .block-container {
                padding-top: 1.4rem;
            }

            .hero-wrap {
                padding: 1.2rem 1rem 1.1rem 1rem;
                border-radius: 20px;
            }

            .hero-title {
                font-size: 1.78rem;
            }

            .hero-subtitle {
                font-size: 0.96rem;
            }

            .feature-card {
                min-height: auto;
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
                    Daily surf conditions, next best day guidance, and weekly outlooks
                    covering swell, wind, and tide intelligence.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:0.85rem;'></div>", unsafe_allow_html=True)

        st.markdown(
            """
            <div class="feature-card">
                <div class="feature-title">Weather Report</div>
                <div class="feature-text">
                    Daily and weekly forecast views with temperature, conditions,
                    and weather alert summaries for your selected location.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            """
            <div class="feature-card">
                <div class="feature-title">Sky & Moon Report</div>
                <div class="feature-text">
                    Built for photographers and night-sky viewing, including day and night
                    clarity, best viewing windows, moon phase tracking, and lunar events.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:0.85rem;'></div>", unsafe_allow_html=True)

        st.markdown(
            """
            <div class="feature-card">
                <div class="feature-title">Trip Planner</div>
                <div class="feature-text">
                    Route planning with a start point, multiple destinations,
                    fuel usage estimates, and trip cost guidance.
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
    description_section()
    st.markdown("<div style='height:0.45rem;'></div>", unsafe_allow_html=True)
    cta_section()
    st.markdown("<div style='height:0.75rem;'></div>", unsafe_allow_html=True)
    footer()


if __name__ == "__main__":
    main()
