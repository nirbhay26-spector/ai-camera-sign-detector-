"""
Configuration Module for Smart AI Safety Camera.
=================================================
This file loads environment variables from a `.env` file using `python-dotenv`
and provides strongly typed, documented settings for the entire application.

For beginners:
- We keep all sensitive credentials (like Twilio tokens) and camera configs
  in a `.env` file so they are never hardcoded into Python source code.
- This module parses those settings and provides sensible defaults if .env
  is missing or incomplete.
"""

import os
from pathlib import Path
# pyrefly: ignore[missing-import]
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent

# Load .env file from the project root
load_dotenv(dotenv_path=BASE_DIR / ".env")


def _get_bool(key: str, default: bool) -> bool:
    """Helper to convert environment variable string to boolean."""
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "t", "yes", "y")


def _get_int(key: str, default: int) -> int:
    """Helper to convert environment variable string to integer."""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    """Helper to convert environment variable string to float."""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return float(val.strip())
    except ValueError:
        return default


# ==============================================================================
# 1. CAMERA CONFIGURATION
# ==============================================================================
# Camera source can be:
# - An integer index (e.g., 0 for built-in Mac/PC webcam, 1 for external USB camera)
# - A string path to a test video file (e.g., "samples/test_gesture.mp4")
# - An RTSP / HTTP URL for an IP camera (e.g., "rtsp://admin:12345@192.168.1.50:554/stream1")
_raw_camera_source = os.getenv("CAMERA_SOURCE", "0").strip()
if _raw_camera_source.isdigit():
    CAMERA_SOURCE = int(_raw_camera_source)
else:
    CAMERA_SOURCE = _raw_camera_source

FRAME_WIDTH: int = _get_int("FRAME_WIDTH", 1280)
FRAME_HEIGHT: int = _get_int("FRAME_HEIGHT", 720)
TARGET_FPS: int = _get_int("TARGET_FPS", 15)  # Target processing rate (10-15 FPS to conserve CPU)


# ==============================================================================
# 2. FALSE ALARM REDUCTION & DECISION TIMING
# ==============================================================================
# Time in seconds that the distress gesture must be detected CONTINUOUSLY before
# triggering an emergency alert. (e.g., 2.5 seconds).
CONFIRMATION_SECONDS: float = _get_float("CONFIRMATION_SECONDS", 2.5)

# Cooldown time in seconds after an alert triggers. During this window, no new
# SMS alerts will be sent, even if the gesture is still visible.
COOLDOWN_SECONDS: float = _get_float("COOLDOWN_SECONDS", 60.0)

# State machine timeout: how long (in seconds) the system waits for the user
# to transition between gesture steps (open palm -> thumb tucked -> closed fingers).
STATE_EXPIRY_SECONDS: float = _get_float("STATE_EXPIRY_SECONDS", 3.0)


# ==============================================================================
# 3. SAFETY, TESTING & EMERGENCY POLICY
# ==============================================================================
# DRY_RUN: When True, alerts and snapshots are logged on screen and to disk,
# but NO actual Twilio SMS is sent. Great for testing without spending money!
DRY_RUN: bool = _get_bool("DRY_RUN", True)

# TEST_MODE: When True, alerts are strictly constrained to the developer's
# phone number (ALERT_RECIPIENT_PHONE). Automated emergency calls (112 / 911)
# are strictly prohibited.
TEST_MODE: bool = _get_bool("TEST_MODE", True)


# ==============================================================================
# 4. TWILIO CREDENTIALS (ALERTING)
# ==============================================================================
# Get these free from your Twilio Console (https://console.twilio.com)
TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")
ALERT_RECIPIENT_PHONE: str = os.getenv("ALERT_RECIPIENT_PHONE", "")


# ==============================================================================
# 5. CAMERA LOCATION (FOR GOOGLE MAPS LINK)
# ==============================================================================
# Each camera has a fixed physical location configuration.
# Later in Version 4, this can be dynamically linked with GPS or nearest police station.
CAMERA_LOCATION_NAME: str = os.getenv("CAMERA_LOCATION_NAME", "Main Entrance / Campus Lab")
CAMERA_LOCATION_ADDRESS: str = os.getenv(
    "CAMERA_LOCATION_ADDRESS", "Block 4, University Campus, Sector 62, Noida, Uttar Pradesh, India"
)
CAMERA_LATITUDE: float = _get_float("CAMERA_LATITUDE", 28.6280)
CAMERA_LONGITUDE: float = _get_float("CAMERA_LONGITUDE", 77.3649)


# ==============================================================================
# 6. EVIDENCE RECORDING (SNAPSHOTS & VIDEO CLIPS)
# ==============================================================================
# Directory where JPG snapshots and pre/post-incident MP4 clips will be saved
EVIDENCE_DIR: Path = BASE_DIR / os.getenv("EVIDENCE_DIR", "evidence")

# Seconds of video to keep in memory BEFORE the trigger happens (ring buffer)
PRE_EVENT_BUFFER_SECONDS: float = _get_float("PRE_EVENT_BUFFER_SECONDS", 4.0)

# Seconds of video to record AFTER the trigger happens
POST_EVENT_RECORD_SECONDS: float = _get_float("POST_EVENT_RECORD_SECONDS", 4.0)


# ==============================================================================
# 7. EMERGENCY INTELLIGENCE & MULTI-FRAME TEMPORAL CONFIRMATION
# ==============================================================================
# Number of consecutive frames required for each stage of Signal for Help
MIN_STAGE1_FRAMES: int = _get_int("MIN_STAGE1_FRAMES", 3)   # Open Palm
MIN_STAGE2_FRAMES: int = _get_int("MIN_STAGE2_FRAMES", 3)   # Thumb Tucked into Palm
MIN_STAGE3_FRAMES: int = _get_int("MIN_STAGE3_FRAMES", 4)   # Four Fingers Closed Over Thumb

# Confidence thresholds for 3-Stage Alert System:
# - GREEN (Normal): Below ORANGE threshold
# - ORANGE (Possible Distress): Partial sequence match or confidence between 0.45 and 0.82
# - RED (Emergency Confirmed): Complete temporal sequence validated with confidence >= 0.82
ORANGE_ALERT_THRESHOLD: float = _get_float("ORANGE_ALERT_THRESHOLD", 0.45)
EMERGENCY_CONFIDENCE_THRESHOLD: float = _get_float("EMERGENCY_CONFIDENCE_THRESHOLD", 0.82)

# Minimum hand size (palm scale relative to frame diagonal) to prevent false positives on distant hands
MIN_PALM_SCALE: float = _get_float("MIN_PALM_SCALE", 0.045)


# ==============================================================================
# 8. CAMERA HEALTH & CCTV NIGHT MODE
# ==============================================================================
BLUR_THRESHOLD: float = _get_float("BLUR_THRESHOLD", 80.0)      # Laplacian variance threshold
BRIGHTNESS_MIN: float = _get_float("BRIGHTNESS_MIN", 12.0)      # Below this is considered blacked out/obstructed
BRIGHTNESS_MAX: float = _get_float("BRIGHTNESS_MAX", 245.0)     # Above this is considered blinded/whiteout
CCTV_NIGHT_MODE: bool = _get_bool("CCTV_NIGHT_MODE", False)     # CLAHE contrast enhancement for night CCTV


# ==============================================================================
# 9. EDGE AI & INTEGRATION LAYER
# ==============================================================================
EDGE_AI_ENABLED: bool = _get_bool("EDGE_AI_ENABLED", False)     # Process detection on edge, transmit metadata only
OTP_EXPIRY_MINUTES: int = _get_int("OTP_EXPIRY_MINUTES", 10)    # Expiration window for phone verification OTP
EVIDENCE_RETENTION_DAYS: int = _get_int("EVIDENCE_RETENTION_DAYS", 30)
DEFAULT_OPERATOR_ID: str = os.getenv("DEFAULT_OPERATOR_ID", "OP-1049 (Duty Officer)")
DEFAULT_ORGANIZATION: str = os.getenv("DEFAULT_ORGANIZATION", "Public Safety & Municipal Surveillance Division")

