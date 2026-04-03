#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    import streamlit as st
except Exception:
    st = None  # type: ignore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# ENV LOADING
# ============================================================
FIXED_ENV_FILE_PATH = Path(r"C:\OneDrive\Sentinel-Access-V2\Sentinel-Access-V2\config\.env")
PROJECT_ENV_FILE_PATH = Path(__file__).resolve().parents[1] / "config" / ".env"

if FIXED_ENV_FILE_PATH.exists():
    load_dotenv(dotenv_path=FIXED_ENV_FILE_PATH)
    logger.info(f"Loaded .env from {FIXED_ENV_FILE_PATH}")
elif PROJECT_ENV_FILE_PATH.exists():
    load_dotenv(dotenv_path=PROJECT_ENV_FILE_PATH)
    logger.info(f"Loaded .env from {PROJECT_ENV_FILE_PATH}")
else:
    load_dotenv()
    logger.warning("No explicit .env file found; loaded default environment if available.")


def _get_secret(name: str, default: str = "") -> str:
    # 1) environment / .env
    value = os.getenv(name, "").strip()
    if value:
        return value

    # 2) Streamlit secrets
    try:
        if st is not None and hasattr(st, "secrets") and name in st.secrets:
            value = str(st.secrets[name]).strip()
            if value:
                return value
    except Exception:
        pass

    return default


EMAIL_FROM = _get_secret("EMAIL_FROM", "")
EMAIL_PASSWORD = _get_secret("EMAIL_PASSWORD", "")
SMTP_SERVER = _get_secret("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(_get_secret("SMTP_PORT", "587"))


# ============================================================
# PATH NORMALIZATION
# ============================================================
def _extract_single_path(item: Any) -> str | None:
    if item is None:
        return None

    if isinstance(item, dict):
        # support dict-wrapped result payloads
        item = item.get("result", item.get("path", item.get("file_path")))

    if isinstance(item, (tuple, list)):
        for sub in item:
            found = _extract_single_path(sub)
            if found:
                return found
        return None

    if isinstance(item, Path):
        item = str(item)

    if isinstance(item, os.PathLike):
        item = os.fspath(item)

    if isinstance(item, str):
        item = item.strip()
        return item or None

    return None


def _normalize_paths(paths: list[Any] | None) -> list[str]:
    out: list[str] = []
    for p in (paths or []):
        extracted = _extract_single_path(p)
        if extracted:
            out.append(extracted)
    return out


def _valid_pdf_paths(paths: list[str]) -> list[str]:
    good: list[str] = []
    seen: set[str] = set()

    for p in paths:
        try:
            if not p:
                continue

            p = str(Path(p))

            if p in seen:
                continue
            if not os.path.isfile(p):
                continue
            if not p.lower().endswith(".pdf"):
                continue
            if os.path.getsize(p) <= 1000:
                continue

            good.append(p)
            seen.add(p)
        except Exception:
            continue

    return good


# ============================================================
# CORE EMAIL SEND
# ============================================================
def send_report_email(
    to_email: str,
    username: str,
    pdf_paths: list[Any] | None,
    subject: str | None = None,
    body: str | None = None,
) -> tuple[bool, str | None]:
    to_email = (to_email or "").strip()
    username = (username or "there").strip() or "there"
    subject = (subject or "Your Reports").strip()

    if not EMAIL_FROM:
        return False, "Missing EMAIL_FROM in environment or Streamlit secrets."
    if not EMAIL_PASSWORD:
        return False, "Missing EMAIL_PASSWORD in environment or Streamlit secrets."
    if not to_email:
        return False, "Recipient email is required."

    normalized_paths = _normalize_paths(pdf_paths)
    valid_paths = _valid_pdf_paths(normalized_paths)

    if not valid_paths:
        return False, "No valid PDF attachments found."

    if body is None:
        body = (
            f"Hi {username},\n\n"
            f"Please find your requested report(s) attached.\n\n"
            f"Regards,\n"
            f"Reports\n"
        )

    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        for pdf_path in valid_paths:
            with open(pdf_path, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())

            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{os.path.basename(pdf_path)}"',
            )
            msg.attach(part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)

        logger.info(f"Email successfully sent to {to_email} with {len(valid_paths)} attachment(s).")
        return True, None

    except smtplib.SMTPAuthenticationError:
        logger.exception("Email authentication error")
        return False, "Login failed. Verify EMAIL_FROM and EMAIL_PASSWORD / Gmail App Password."
    except Exception as e:
        logger.exception("Email error")
        return False, str(e)


# ============================================================
# APP-FRIENDLY WRAPPER
# ============================================================
def send_email(
    to_email: str,
    subject: str,
    body: str,
    attachments: list[Any] | None = None,
    attachment_path: str | None = None,
    pdf_path: str | None = None,
    file_path: str | None = None,
    username: str = "there",
) -> bool:
    """
    Supports multiple calling styles from app.py:
      send_email(..., attachments=[...])
      send_email(..., attachment_path="file.pdf")
      send_email(..., pdf_path="file.pdf")
      send_email(..., file_path="file.pdf")
    """
    collected: list[Any] = []

    if attachments:
        collected.extend(attachments)

    for single in [attachment_path, pdf_path, file_path]:
        if single:
            collected.append(single)

    ok, err = send_report_email(
        to_email=to_email,
        username=username,
        pdf_paths=collected,
        subject=subject or "Your Reports",
        body=body,
    )

    if not ok:
        raise RuntimeError(err or "Email failed")

    return True