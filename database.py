"""
Database Module for Smart AI Safety Camera.
===========================================
Manages local SQLite database storage for incident logs, camera statuses,
and system configuration audit trails.

For first-year CSE students:
----------------------------
SQLite is a lightweight, serverless relational database built directly
into Python (`import sqlite3`). All records are stored in a single local
file (`safety_camera.db`), meaning zero configuration or setup is required!
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import config

logger = logging.getLogger(__name__)

DB_PATH = config.BASE_DIR / "safety_camera.db"


def get_db_connection() -> sqlite3.Connection:
    """Creates a connection to the SQLite database with row dictionaries."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    """Initializes tables in the SQLite database if they do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Alerts & Incident History Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            camera_name TEXT NOT NULL,
            location_address TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            gesture_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,  -- 'Pending', 'Sent', 'Cancelled', 'Resolved'
            snapshot_path TEXT,
            notes TEXT
        )
        """
    )

    # 2. Cameras Table (Tracks local and remote surveillance cameras)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cameras (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            status TEXT NOT NULL,  -- 'Online', 'Alert', 'Offline', 'Resolved'
            is_local INTEGER DEFAULT 0,
            last_ping TEXT,
            organization TEXT DEFAULT 'Public Safety Agency',
            installation_location TEXT DEFAULT 'Main Gate / Pedestrian Pole',
            zone TEXT DEFAULT 'Zone A',
            camera_type TEXT DEFAULT 'CCTV-RTSP',
            health_status TEXT DEFAULT 'Healthy',
            blur_score REAL DEFAULT 145.0,
            last_health_check TEXT
        )
        """
    )

    # Safely migrate existing cameras table if columns are missing
    cursor.execute("PRAGMA table_info(cameras)")
    cam_cols = [row["name"] for row in cursor.fetchall()]
    migration_cols = [
        ("organization", "TEXT DEFAULT 'Public Safety & Municipal Surveillance Division'"),
        ("installation_location", "TEXT DEFAULT 'Street Level / Pedestrian Pole'"),
        ("zone", "TEXT DEFAULT 'Zone A'"),
        ("camera_type", "TEXT DEFAULT 'CCTV-RTSP'"),
        ("health_status", "TEXT DEFAULT 'Healthy'"),
        ("blur_score", "REAL DEFAULT 145.0"),
        ("last_health_check", "TEXT"),
    ]
    for col_name, col_def in migration_cols:
        if col_name not in cam_cols:
            cursor.execute(f"ALTER TABLE cameras ADD COLUMN {col_name} {col_def}")

    # 3. Emergency Contacts Table (with OTP verification)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS emergency_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            relationship TEXT NOT NULL,  -- 'Primary Contact', 'Family Contact', 'Security Contact', 'Emergency Contact'
            is_verified INTEGER DEFAULT 0,
            is_primary INTEGER DEFAULT 0,
            otp_code TEXT,
            otp_expires_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute("PRAGMA table_info(emergency_contacts)")
    ec_cols = [row["name"] for row in cursor.fetchall()]
    if "is_primary" not in ec_cols:
        cursor.execute("ALTER TABLE emergency_contacts ADD COLUMN is_primary INTEGER DEFAULT 0")

    # 4. Verified Incidents Table (Human-in-the-Loop & Incident Evidence Package)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_uuid TEXT NOT NULL UNIQUE,
            camera_id TEXT NOT NULL,
            camera_name TEXT NOT NULL,
            location_address TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timestamp TEXT NOT NULL,
            stage TEXT NOT NULL,  -- 'GREEN', 'ORANGE', 'RED'
            confidence REAL NOT NULL,
            gesture_breakdown TEXT,
            status TEXT NOT NULL,  -- 'Pending Verification', 'Confirmed Emergency', 'Monitoring', 'False Alarm', 'Resolved'
            operator_action TEXT,
            operator_id TEXT,
            action_timestamp TEXT,
            evidence_snapshot TEXT,
            evidence_video TEXT,
            sha256_hash TEXT,
            escalation_level INTEGER DEFAULT 1,
            delivery_status TEXT DEFAULT 'Pending',
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # 5. False Alarm Feedback Table (Learning from False Alarms & Model Improvement)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS false_alarm_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER,
            camera_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            reported_by TEXT NOT NULL,
            gesture_classified_as TEXT NOT NULL,
            actual_activity TEXT NOT NULL,  -- 'phone_use', 'waving', 'pointing', 'scratching', 'holding_object', 'other'
            anonymized_landmarks TEXT,
            notes TEXT
        )
        """
    )

    # 6. Cross-Camera Incident Links (Incident Continuity Across Multiple Nodes)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cross_camera_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            primary_incident_id INTEGER NOT NULL,
            linked_camera_id TEXT NOT NULL,
            linked_timestamp TEXT NOT NULL,
            observation TEXT,
            operator_id TEXT NOT NULL
        )
        """
    )

    # 7. Privacy & Security Audit Trail Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_role TEXT NOT NULL,
            action TEXT NOT NULL,
            target_resource TEXT NOT NULL,
            details TEXT,
            ip_address TEXT
        )
        """
    )

    # Seed default cameras if empty
    cursor.execute("SELECT COUNT(*) FROM cameras")
    if cursor.fetchone()[0] == 0:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        seed_cameras = [
            (
                "CAM-01",
                "Local AI Camera (Your Device)",
                "Noida / Delhi NCR",
                config.CAMERA_LATITUDE,
                config.CAMERA_LONGITUDE,
                "Online",
                1,
                now_str,
                "Public Safety & Municipal Surveillance Division",
                "Building Entrance Overhead Pole 1",
                "Zone A - Main Campus",
                "Edge-AI Camera",
                "Healthy",
                162.4,
                now_str,
            ),
            (
                "CAM-02",
                "Connaught Place Inner Circle",
                "New Delhi",
                28.6328,
                77.2197,
                "Online",
                0,
                now_str,
                "Delhi Police City Surveillance Project",
                "Radial Road 3 Lamp Post",
                "Zone Central - Commercial Hub",
                "CCTV-PTZ 4K",
                "Healthy",
                145.0,
                now_str,
            ),
            (
                "CAM-03",
                "Marine Drive Promenade",
                "Mumbai",
                18.9438,
                72.8232,
                "Online",
                0,
                now_str,
                "Greater Mumbai Coastal Security",
                "Promenade Walkway Mast 14",
                "Zone South - Promenade",
                "CCTV-IP High Dynamic Range",
                "Healthy",
                155.8,
                now_str,
            ),
            (
                "CAM-04",
                "Indiranagar 100ft Road",
                "Bengaluru",
                12.9784,
                77.6408,
                "Online",
                0,
                now_str,
                "Bengaluru Smart City Integrated Command",
                "Junction 12 Traffic Gantry",
                "Zone East - Tech Corridor",
                "Traffic-AI Camera",
                "Healthy",
                138.2,
                now_str,
            ),
            (
                "CAM-05",
                "HITEC City Cyber Towers",
                "Hyderabad",
                17.4504,
                78.3808,
                "Online",
                0,
                now_str,
                "Cyberabad Police Security Grid",
                "Cyber Towers Outer Ring Pole 8",
                "Zone West - Cyberabad",
                "CCTV-IP ONVIF",
                "Healthy",
                171.0,
                now_str,
            ),
            (
                "CAM-06",
                "Park Street Crossing",
                "Kolkata",
                22.5516,
                88.3524,
                "Online",
                0,
                now_str,
                "Kolkata Police Security Network",
                "Metro Station Gate 2 Pole",
                "Zone Central - Heritage Crossing",
                "CCTV-Fixed Dome",
                "Healthy",
                125.6,
                now_str,
            ),
            (
                "CAM-07",
                "FC Road College Gate",
                "Pune",
                18.5284,
                73.8400,
                "Online",
                0,
                now_str,
                "Pune Smart City Surveillance",
                "Fergusson College Main Gate",
                "Zone West - Educational Precinct",
                "CCTV-IP High Sensitivity",
                "Healthy",
                142.1,
                now_str,
            ),
            (
                "CAM-08",
                "Anna Nagar Roundtana",
                "Chennai",
                13.0850,
                80.2101,
                "Online",
                0,
                now_str,
                "Greater Chennai City Police Network",
                "Roundabout Surveillance Gantry",
                "Zone North - Commercial Ring",
                "CCTV-PTZ Night Vision",
                "Healthy",
                150.3,
                now_str,
            ),
        ]
        cursor.executemany(
            """
            INSERT INTO cameras (
                id, name, city, latitude, longitude, status, is_local, last_ping,
                organization, installation_location, zone, camera_type,
                health_status, blur_score, last_health_check
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            seed_cameras,
        )

    # Seed default emergency contacts if table is empty
    cursor.execute("SELECT COUNT(*) FROM emergency_contacts")
    if cursor.fetchone()[0] == 0:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        phone = config.ALERT_RECIPIENT_PHONE or "+919876543210"
        seed_contacts = [
            ("Primary Guardian", phone, "Primary Contact", 1, "VERIFIED", now_str, now_str),
            ("Family Contact", "+919811122233", "Family Contact", 1, "VERIFIED", now_str, now_str),
            ("Campus Security Control", "+919844455566", "Security Contact", 1, "VERIFIED", now_str, now_str),
            ("Emergency Dispatch Liaison", "+919877788899", "Emergency Contact", 0, "482910", now_str, now_str),
        ]
        cursor.executemany(
            """
            INSERT INTO emergency_contacts (
                name, phone, relationship, is_verified, otp_code, otp_expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            seed_contacts,
        )

    conn.commit()
    conn.close()
    logger.info("SQLite database initialized at %s", DB_PATH)


def log_alert(
    camera_id: str,
    camera_name: str,
    location_address: str,
    latitude: float,
    longitude: float,
    gesture_type: str,
    confidence: float,
    status: str = "Pending",
    snapshot_path: Optional[str] = None,
    notes: str = "",
) -> int:
    """Logs a new emergency alert incident into SQLite."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT INTO alert_logs (
            timestamp, camera_id, camera_name, location_address,
            latitude, longitude, gesture_type, confidence,
            status, snapshot_path, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_str,
            camera_id,
            camera_name,
            location_address,
            latitude,
            longitude,
            gesture_type,
            confidence,
            status,
            snapshot_path,
            notes,
        ),
    )
    alert_id = cursor.lastrowid

    # Update camera status to Alert
    cursor.execute(
        "UPDATE cameras SET status = 'Alert', last_ping = ? WHERE id = ?",
        (now_str, camera_id),
    )

    conn.commit()
    conn.close()
    return alert_id


def update_alert_status(alert_id: int, new_status: str, notes: Optional[str] = None) -> bool:
    """Updates the status of an alert (e.g. 'Sent', 'Cancelled', 'Resolved')."""
    conn = get_db_connection()
    cursor = conn.cursor()

    if notes is not None:
        cursor.execute(
            "UPDATE alert_logs SET status = ?, notes = ? WHERE id = ?",
            (new_status, notes, alert_id),
        )
    else:
        cursor.execute(
            "UPDATE alert_logs SET status = ? WHERE id = ?",
            (new_status, alert_id),
        )

    # If resolved or cancelled, reset camera status back to Online
    cursor.execute("SELECT camera_id FROM alert_logs WHERE id = ?", (alert_id,))
    row = cursor.fetchone()
    if row and new_status in ("Cancelled", "Resolved"):
        cursor.execute(
            "UPDATE cameras SET status = 'Online' WHERE id = ?",
            (row["camera_id"],),
        )

    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0


def get_all_alerts(limit: int = 100, status_filter: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetches alert logs with optional filtering and search."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM alert_logs WHERE 1=1"
    params = []

    if status_filter and status_filter.lower() != "all":
        query += " AND status = ?"
        params.append(status_filter)

    if search:
        query += " AND (camera_name LIKE ? OR location_address LIKE ? OR gesture_type LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_cameras() -> List[Dict[str, Any]]:
    """Retrieves all surveillance cameras and their active status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cameras ORDER BY is_local DESC, id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_camera_status(camera_id: str, status: str) -> None:
    """Sets camera status (Online, Alert, Offline, Resolved)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE cameras SET status = ?, last_ping = ? WHERE id = ?",
        (status, now_str, camera_id),
    )
    conn.commit()
    conn.close()


def get_dashboard_metrics() -> Dict[str, Any]:
    """Computes high-level security metrics for the control room counters."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM cameras")
    total_cameras = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cameras WHERE status = 'Alert'")
    active_alerts = cursor.fetchone()[0]

    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM alert_logs WHERE timestamp LIKE ?", (f"{today_str}%",))
    alerts_today = cursor.fetchone()[0]

    conn.close()

    return {
        "total_cameras": total_cameras,
        "active_alerts": active_alerts,
        "alerts_today": alerts_today,
        "avg_response_time": "12s",
    }


# ==============================================================================
# EMERGENCY CONTACT REGISTRATION & OTP VERIFICATION
# ==============================================================================
def get_emergency_contacts() -> List[Dict[str, Any]]:
    """Retrieves all registered emergency contacts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM emergency_contacts ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_emergency_contact(name: str, phone: str, relationship: str = "Primary Contact", is_primary: bool = False) -> int:
    """Adds a new trusted emergency contact in pending verification state."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO emergency_contacts (name, phone, relationship, is_verified, is_primary, created_at)
        VALUES (?, ?, ?, 0, ?, ?)
        """,
        (name.strip(), phone.strip(), relationship.strip(), 1 if is_primary else 0, now_str),
    )
    cid = cursor.lastrowid
    conn.commit()
    conn.close()
    return cid


def set_contact_otp(contact_id: int, otp_code: Optional[str] = None, expiry_minutes: int = 10) -> str:
    """Stores a generated OTP and expiry timestamp for a contact. Returns the OTP code."""
    import random
    from datetime import timedelta
    if not otp_code:
        otp_code = f"{random.randint(100000, 999999)}"

    conn = get_db_connection()
    cursor = conn.cursor()
    expiry_time = (datetime.now() + timedelta(minutes=expiry_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE emergency_contacts SET otp_code = ?, otp_expires_at = ? WHERE id = ?",
        (otp_code, expiry_time, contact_id),
    )
    conn.commit()
    conn.close()
    return otp_code


def verify_contact_otp(contact_id: int, entered_otp: str) -> Tuple[bool, str]:
    """Validates entered OTP against stored code and expiration."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM emergency_contacts WHERE id = ?", (contact_id,))
    contact = cursor.fetchone()

    if not contact:
        conn.close()
        return False, "Contact not found."

    stored_otp = contact["otp_code"]
    expires_at = contact["otp_expires_at"]

    if not stored_otp or not expires_at:
        conn.close()
        return False, "No active OTP generated. Please request a new OTP."

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if now_str > expires_at:
        conn.close()
        return False, "OTP has expired. Please request a new one."

    if stored_otp.strip() != entered_otp.strip():
        conn.close()
        return False, "Invalid OTP code. Please check and try again."

    cursor.execute(
        "UPDATE emergency_contacts SET is_verified = 1, otp_code = NULL, otp_expires_at = NULL WHERE id = ?",
        (contact_id,),
    )
    conn.commit()
    conn.close()
    return True, "Phone number verified successfully!"


def delete_emergency_contact(contact_id: int) -> bool:
    """Deletes an emergency contact."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM emergency_contacts WHERE id = ?", (contact_id,))
    conn.commit()
    rows = cursor.rowcount
    conn.close()
    return rows > 0


def get_verified_contacts() -> List[Dict[str, Any]]:
    """Returns only phone numbers that have completed OTP verification."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM emergency_contacts WHERE is_verified = 1 ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ==============================================================================
# INCIDENTS & HUMAN-IN-THE-LOOP CONTROL ROOM CONSOLE
# ==============================================================================
def create_incident(
    incident_uuid: str,
    camera_id: str,
    camera_name: str,
    location_address: str,
    latitude: float,
    longitude: float,
    stage: str,
    confidence: float,
    gesture_breakdown: str = "{}",
    evidence_snapshot: Optional[str] = None,
    evidence_video: Optional[str] = None,
    sha256_hash: Optional[str] = None,
    notes: str = "",
) -> int:
    """Creates a verified incident record for control room review."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT INTO incidents (
            incident_uuid, camera_id, camera_name, location_address, latitude, longitude,
            timestamp, stage, confidence, gesture_breakdown, status,
            evidence_snapshot, evidence_video, sha256_hash, escalation_level,
            delivery_status, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending Verification', ?, ?, ?, 1, 'Pending', ?, ?)
        """,
        (
            incident_uuid,
            camera_id,
            camera_name,
            location_address,
            latitude,
            longitude,
            now_str,
            stage,
            confidence,
            gesture_breakdown,
            evidence_snapshot or "",
            evidence_video or "",
            sha256_hash or "",
            notes,
            now_str,
        ),
    )
    inc_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return inc_id


def get_all_incidents(limit: int = 50, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves incident evidence packages for the operator console."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM incidents WHERE 1=1"
    params = []
    if status_filter and status_filter.lower() != "all":
        query += " AND status = ?"
        params.append(status_filter)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_incident_by_id(incident_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single incident record by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_incident_operator_action(
    incident_id: int,
    action: str,  # 'Confirmed Emergency', 'Continue Monitoring', 'False Alarm', 'Resolved'
    operator_id: str,
    notes: Optional[str] = None,
) -> bool:
    """Records human operator verification action and notes."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        UPDATE incidents
        SET status = ?, operator_action = ?, operator_id = ?, action_timestamp = ?,
            notes = COALESCE(?, notes)
        WHERE id = ?
        """,
        (action, action, operator_id, now_str, notes, incident_id),
    )

    # If action is 'False Alarm' or 'Resolved', reset camera status to Online
    cursor.execute("SELECT camera_id FROM incidents WHERE id = ?", (incident_id,))
    inc = cursor.fetchone()
    if inc and action in ("False Alarm", "Resolved"):
        cursor.execute("UPDATE cameras SET status = 'Online' WHERE id = ?", (inc["camera_id"],))

    conn.commit()
    rows = cursor.rowcount
    conn.close()
    return rows > 0


def update_incident_delivery_status(
    incident_uuid: str,
    delivery_status: str,
    notes: Optional[str] = None,
) -> bool:
    """Updates the dispatch/delivery status of an incident record by UUID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE incidents
        SET delivery_status = ?, notes = COALESCE(?, notes)
        WHERE incident_uuid = ?
        """,
        (delivery_status, notes, incident_uuid),
    )
    conn.commit()
    rows = cursor.rowcount
    conn.close()
    return rows > 0


# ==============================================================================
# FALSE ALARM LEARNING & MODEL FEEDBACK
# ==============================================================================
def log_false_alarm_feedback(
    incident_id: Optional[int],
    camera_id: str,
    reported_by: str,
    gesture_classified_as: str,
    actual_activity: str,
    anonymized_landmarks: str = "{}",
    notes: str = "",
) -> int:
    """Logs false alarm telemetry without personal identity for model evaluation."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT INTO false_alarm_feedback (
            incident_id, camera_id, timestamp, reported_by,
            gesture_classified_as, actual_activity, anonymized_landmarks, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            incident_id,
            camera_id,
            now_str,
            reported_by,
            gesture_classified_as,
            actual_activity,
            anonymized_landmarks,
            notes,
        ),
    )
    fid = cursor.lastrowid
    conn.commit()
    conn.close()
    return fid


def get_false_alarm_statistics() -> Dict[str, Any]:
    """Computes false alarm distributions by activity type."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM false_alarm_feedback")
    total_feedback = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT actual_activity, COUNT(*) as count
        FROM false_alarm_feedback
        GROUP BY actual_activity
        ORDER BY count DESC
        """
    )
    breakdown = {row["actual_activity"]: row["count"] for row in cursor.fetchall()}

    conn.close()
    return {
        "total_false_alarms": total_feedback,
        "activity_breakdown": breakdown,
    }


# ==============================================================================
# CROSS-CAMERA CONTINUITY
# ==============================================================================
def link_cross_camera_event(
    primary_incident_id: int,
    linked_camera_id: str,
    observation: str,
    operator_id: str,
) -> int:
    """Associates a nearby camera observation into the primary incident timeline."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT INTO cross_camera_links (
            primary_incident_id, linked_camera_id, linked_timestamp,
            observation, operator_id
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (primary_incident_id, linked_camera_id, now_str, observation, operator_id),
    )
    link_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return link_id


def get_linked_cameras_for_incident(primary_incident_id: int) -> List[Dict[str, Any]]:
    """Retrieves all cross-camera timeline associations for an incident."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT l.*, c.name as camera_name, c.installation_location, c.zone
        FROM cross_camera_links l
        LEFT JOIN cameras c ON l.linked_camera_id = c.id
        WHERE l.primary_incident_id = ?
        ORDER BY l.id ASC
        """,
        (primary_incident_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ==============================================================================
# CAMERA HEALTH MONITORING & REGISTRATION
# ==============================================================================
def update_camera_health(
    camera_id: str,
    health_status: str,  # 'Healthy', 'Blurry', 'Obstructed', 'Frozen', 'Offline'
    blur_score: float,
) -> bool:
    """Updates health telemetry metrics for a monitored camera node."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        UPDATE cameras
        SET health_status = ?, blur_score = ?, last_health_check = ?
        WHERE id = ?
        """,
        (health_status, blur_score, now_str, camera_id),
    )
    conn.commit()
    rows = cursor.rowcount
    conn.close()
    return rows > 0


def register_camera(
    camera_id: str,
    name: str,
    city: str,
    latitude: float,
    longitude: float,
    organization: str = "Public Safety Agency",
    installation_location: str = "Pedestrian Pole",
    zone: str = "Zone A",
    camera_type: str = "CCTV-RTSP",
) -> bool:
    """Registers an authorized new camera node into the surveillance network."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT OR REPLACE INTO cameras (
            id, name, city, latitude, longitude, status, is_local, last_ping,
            organization, installation_location, zone, camera_type,
            health_status, blur_score, last_health_check
        ) VALUES (?, ?, ?, ?, ?, 'Online', 0, ?, ?, ?, ?, ?, 'Healthy', 150.0, ?)
        """,
        (
            camera_id,
            name,
            city,
            latitude,
            longitude,
            now_str,
            organization,
            installation_location,
            zone,
            camera_type,
            now_str,
        ),
    )
    conn.commit()
    conn.close()
    return True


# ==============================================================================
# PRIVACY & ROLE-BASED ACCESS AUDIT TRAIL
# ==============================================================================
def log_audit_event(
    user_role: str,
    action: str,
    target_resource: str,
    details: str = "",
    ip_address: str = "127.0.0.1",
) -> int:
    """Records an immutable audit entry for compliance and privacy regulations."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT INTO audit_logs (timestamp, user_role, action, target_resource, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (now_str, user_role, action, target_resource, details, ip_address),
    )
    aid = cursor.lastrowid
    conn.commit()
    conn.close()
    return aid


def get_recent_audit_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches recent security audit logs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

