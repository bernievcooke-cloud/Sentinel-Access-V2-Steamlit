import os
from dotenv import load_dotenv

load_dotenv()

# File Paths
BASE_PATH = os.getenv("BASE_PATH", r"C:\OneDrive\Sentinel-Access-V2")
BASE_OUTPUT = os.getenv("BASE_OUTPUT", r"C:\OneDrive\Sentinel-Access-V2\storage\reports")
BASE_OUTPUT_PATH = os.getenv("BASE_OUTPUT_PATH", r"C:\OneDrive\Sentinel-Access-V2\storage\reports")

# GitHub Configuration
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "bernievcooke-cloud")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Sentinel-Access")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Report Types
REPORT_TYPES = os.getenv("REPORT_TYPES", "Surf, Sky, Weather, Trip Planner").split(",")

# Email Configuration
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# Debug mode
DEBUG = os.getenv("DEBUG", "True") == "True"