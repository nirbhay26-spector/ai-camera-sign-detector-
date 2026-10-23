"""
Flask Web Application: Smart AI Safety Camera Control Center.
=============================================================
Provides a real-time web dashboard for distress detection, control room monitoring,
interactive emergency countdowns, live maps, emergency contact OTP verification,
human-in-the-loop incident verification, camera health, and alert audit logs.
"""

import os
import csv
import io
import time
import json
import uuid
import random
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

import cv2
import numpy as np
from flask import (
    Flask,
    render_template,
    Response,
    jsonify,
    request,
    send_from_directory,
    make_response,
)

import config
import database
from camera import Camera
from detectors.hand_signal import HandSignalDetector, STAGE_GREEN, STAGE_ORANGE, STAGE_RED
from decision import DecisionEngine
from alerts.sms import SMSAlertSender
from alerts.location import get_camera_location, get_camera_location_by_id
from evidence import EvidenceRecorder
from geospatial import GeospatialIntelligenceLayer
from edge import EdgeAIManager
from benchmarks.evaluator import BenchmarkEvaluator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SafetyWebApp")

app = Flask(__name__)
database.init_database()

# ==============================================================================
# GLOBAL THREAD-SAFE VIDEO STREAMER & STATE
# ==============================================================================
class CameraStreamService:
    """Manages background camera capture, detection pipeline, edge telemetry, and health."""

    def __init__(self):
        self.lock = threading.Lock()
        self.camera: Optional[Camera] = None
        self.detector = HandSignalDetector(mode="both", sensitivity=1.0)
        self.decision_engine = DecisionEngine()
        self.alert_sender = SMSAlertSender()
        self.evidence_recorder = EvidenceRecorder()
        self.edge_manager = EdgeAIManager()
        self.geospatial = GeospatialIntelligenceLayer()
        self.benchmark_evaluator = BenchmarkEvaluator()

        # Telemetry State for UI
        self.current_frame_jpeg: Optional[bytes] = None
        self.active_incident_uuid: Optional[str] = None
        self.telemetry: Dict[str, Any] = {
            "hand_detected": False,
            "fingers_up": 0,
            "posture": "Initializing...",
            "current_state": "IDLE",
            "is_confirmed": False,
            "should_alert": False,
            "confidence": 0.0,
            "confirmation_progress": 0.0,
            "seconds_detected": 0.0,
            "is_in_cooldown": False,
            "cooldown_remaining": 0.0,
            "mode": "both",
            "sensitivity": 1.0,
            "fps": 0.0,
            "last_snapshot": "",
            "active_alert_id": None,
            "active_incident_uuid": None,
            "countdown_active": False,
            "countdown_seconds_left": 10.0,
            "source_status": "Starting",
            "alert_stage": STAGE_GREEN,
            "handedness": "Unknown",
            "clarity_score": 100.0,
            "night_mode": config.CCTV_NIGHT_MODE,
            "edge_mode": self.edge_manager.edge_mode_enabled,
            "stage1_frames": 0,
            "stage2_frames": 0,
            "stage3_frames": 0,
            "camera_health": {"health_status": "Healthy", "blur_score": 150.0},
            "bandwidth_saved_percent": 0.0,
            "verified_contacts_count": 0,
        }

        # Active countdown & simulation state
        self.countdown_duration = 10.0
        self.countdown_start_time = 0.0
        self.active_alert_id: Optional[int] = None
        self.last_snapshot_filename = ""
        self.siren_enabled = True

        # Running control
        self.is_running = True
        self.worker_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.worker_thread.start()

    def _init_camera(self) -> bool:
        """Attempts to open camera or gracefully falls back to synthetic video."""
        try:
            self.camera = Camera(source=config.CAMERA_SOURCE, target_fps=config.TARGET_FPS, mirror=True)
            if self.camera.is_opened:
                self.telemetry["source_status"] = "Live Webcam / Video Active"
                return True
        except Exception as e:
            logger.warning("Camera init failed: %s. Trying fallback sample...", e)

        # Fallback to demo video file
        sample_file = config.BASE_DIR / "samples" / "demo_feed.mp4"
        if sample_file.exists():
            try:
                self.camera = Camera(source=str(sample_file), target_fps=config.TARGET_FPS, mirror=False)
                if self.camera.is_opened:
                    self.telemetry["source_status"] = "Fallback Sample Video Active"
                    return True
            except Exception as e:
                logger.error("Sample video open failed: %s", e)

        self.telemetry["source_status"] = "No Camera / Permission Needed"
        return False

    def switch_camera_source(self, new_source: Any) -> bool:
        """Dynamically switches camera source to a new camera index, RTSP URL, or file."""
        with self.lock:
            if self.camera:
                self.camera.release()
            config.CAMERA_SOURCE = new_source
            return self._init_camera()

    def _stream_loop(self) -> None:
        """Continuous pipeline loop running in a dedicated background thread."""
        logger.info("Starting background camera pipeline thread...")
        self._init_camera()
        frame_counter = 0

        while self.is_running:
            if not self.camera or not self.camera.is_opened:
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    blank,
                    "CAMERA ACCESS PAUSED OR PERMISSION NEEDED",
                    (40, 220),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 165, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    blank,
                    "Allow camera in System Settings or select another feed",
                    (60, 260),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (200, 200, 200),
                    1,
                    cv2.LINE_AA,
                )
                _, jpeg = cv2.imencode(".jpg", blank, [cv2.IMWRITE_JPEG_QUALITY, 75])
                with self.lock:
                    self.current_frame_jpeg = jpeg.tobytes()
                time.sleep(0.5)
                self._init_camera()
                continue

            success, frame = self.camera.read_frame()
            if not success or frame is None:
                time.sleep(0.05)
                continue

            frame_counter += 1

            # 1. Camera Health Diagnostics (Every 30 frames ~ 2s)
            if frame_counter % 30 == 0:
                health_status = self.camera.check_health(frame)
                database.update_camera_health("CAM-01", health_status, self.camera.blur_score)

            # 2. Evidence buffer
            self.evidence_recorder.add_frame_to_buffer(frame)

            # 3. Gesture Detection (with 3-Stage Alert progression)
            detection = self.detector.detect(frame)

            # 4. Decision Engine (Debounce & Multi-Frame confirmation)
            decision = self.decision_engine.update(
                detection.is_detected,
                alert_stage=self.detector.alert_stage,
                confidence=detection.confidence,
            )

            # 5. Edge Bandwidth Tracking
            self.edge_manager.process_frame_telemetry(decision.is_confirmed)

            # 6. Check if Emergency Triggered
            if decision.should_trigger_alert:
                logger.warning("Emergency distress gesture confirmed! Arming countdown...")
                snap_path = self.evidence_recorder.save_snapshot(frame, event_label="distress_signal")
                self.last_snapshot_filename = snap_path.name
                self.evidence_recorder.start_incident_video_recording()

                incident_uuid = f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
                self.active_incident_uuid = incident_uuid
                loc = get_camera_location()

                # Generate tamper-evident evidence package with SHA256 hashes
                pkg = self.evidence_recorder.generate_evidence_package(
                    incident_uuid=incident_uuid,
                    camera_id="CAM-01",
                    camera_name="Local AI Camera (Your Device)",
                    location_address=loc.address,
                    confidence=detection.confidence,
                    gesture_stage_breakdown=getattr(self.detector, "gesture_stage_breakdown", {}),
                    snapshot_filename=snap_path.name,
                )

                # Create Incident for Human-in-the-Loop console
                database.create_incident(
                    incident_uuid=incident_uuid,
                    camera_id="CAM-01",
                    camera_name="Local AI Camera (Your Device)",
                    location_address=loc.address,
                    latitude=loc.latitude,
                    longitude=loc.longitude,
                    stage=self.detector.alert_stage,
                    confidence=detection.confidence,
                    gesture_breakdown=json.dumps(getattr(self.detector, "gesture_stage_breakdown", {})),
                    evidence_snapshot=snap_path.name,
                    sha256_hash=pkg.get("evidence_files", {}).get("snapshot_sha256", ""),
                    notes="Automated multi-frame verified Signal-for-Help SOS candidate",
                )

                # Also log in legacy alert_logs table for backward compatibility
                alert_id = database.log_alert(
                    camera_id="CAM-01",
                    camera_name="Local AI Camera (Your Device)",
                    location_address=loc.address,
                    latitude=loc.latitude,
                    longitude=loc.longitude,
                    gesture_type=detection.label,
                    confidence=detection.confidence,
                    status="Pending",
                    snapshot_path=snap_path.name,
                    notes=f"Incident {incident_uuid} awaiting operator verification",
                )
                self.active_alert_id = alert_id
                self.countdown_start_time = time.time()
                database.log_audit_event("System-AI", "INCIDENT_CANDIDATE_CREATED", f"Incident {incident_uuid}")

            # Manage active countdown
            countdown_active = False
            countdown_left = 0.0
            if self.active_alert_id is not None:
                elapsed = time.time() - self.countdown_start_time
                countdown_left = max(0.0, self.countdown_duration - elapsed)
                if countdown_left > 0:
                    countdown_active = True
                else:
                    logger.warning("Countdown expired without cancellation! Dispatching alert...")
                    self.auto_dispatch_alert(self.active_alert_id)
                    self.active_alert_id = None

            # 7. Render Visual Annotations on Stream Frame
            annotated = self.detector.draw_annotations(frame, detection)

            # 8. Encode Frame to JPEG for MJPEG browser streaming
            ret, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret:
                with self.lock:
                    self.current_frame_jpeg = jpeg.tobytes()

            # 9. Update Telemetry
            bw_stats = self.edge_manager.get_bandwidth_metrics()
            verified_contacts = database.get_verified_contacts()

            with self.lock:
                self.telemetry = {
                    "hand_detected": self.detector.hand_detected,
                    "fingers_up": self.detector.fingers_up_count,
                    "posture": self.detector.hand_posture_label,
                    "current_state": detection.state_name,
                    "is_confirmed": decision.is_confirmed,
                    "should_alert": decision.should_trigger_alert,
                    "confidence": round(detection.confidence, 2),
                    "confirmation_progress": round(decision.confirmation_progress, 2),
                    "seconds_detected": round(decision.seconds_detected, 1),
                    "is_in_cooldown": decision.is_in_cooldown,
                    "cooldown_remaining": int(decision.cooldown_remaining),
                    "mode": self.detector.mode,
                    "sensitivity": round(self.detector.sensitivity, 2),
                    "fps": round(self.camera.actual_fps, 1),
                    "last_snapshot": self.last_snapshot_filename,
                    "active_alert_id": self.active_alert_id,
                    "active_incident_uuid": self.active_incident_uuid,
                    "countdown_active": countdown_active,
                    "countdown_seconds_left": round(countdown_left, 1),
                    "source_status": "Active",
                    "zone_breach": self.detector.zone_breached,
                    "siren_enabled": self.siren_enabled,
                    "test_mode": config.TEST_MODE,
                    "dry_run": config.DRY_RUN,
                    "recipient_phone": config.ALERT_RECIPIENT_PHONE,
                    "alert_stage": self.detector.alert_stage,
                    "handedness": self.detector.handedness,
                    "clarity_score": round(self.detector.clarity_score, 1),
                    "night_mode": self.detector.night_mode,
                    "edge_mode": self.edge_manager.edge_mode_enabled,
                    "bandwidth_saved_percent": bw_stats["bandwidth_saved_percent"],
                    "verified_contacts_count": len(verified_contacts),
                    "stage1_frames": self.detector.stage1_frame_count,
                    "stage2_frames": self.detector.stage2_frame_count,
                    "stage3_frames": self.detector.stage3_frame_count,
                    "camera_health": self.camera.get_health_report(),
                }

    def auto_dispatch_alert(self, alert_id: int) -> None:
        """Dispatches SMS alert and updates database status to 'Sent'."""
        loc = get_camera_location()
        database.update_alert_status(alert_id, "Sent", notes="Dispatched to emergency contacts")
        broadcast_res = self.alert_sender.send_emergency_broadcast(
            camera_id="CAM-01",
            location=loc,
            confidence=self.detector.confidence_score,
            snapshot_filename=self.last_snapshot_filename,
        )
        if self.active_incident_uuid:
            database.update_incident_delivery_status(
                self.active_incident_uuid,
                f"Dispatched (SMS to {broadcast_res['total_sent']} contacts)",
            )
        database.log_audit_event(
            "Emergency-Dispatch",
            "ALERT_DISPATCHED",
            f"Alert ID {alert_id}",
            details=f"Dispatched to {broadcast_res['total_sent']} contacts",
        )

    def cancel_alert(self, alert_id: int) -> bool:
        """Cancels a pending countdown alert."""
        with self.lock:
            if self.active_alert_id == alert_id:
                self.active_alert_id = None
        database.log_audit_event("User-Safe", "ALERT_CANCELLED", f"Alert ID {alert_id}")
        return database.update_alert_status(alert_id, "Cancelled", notes="User pressed 'I'm Safe, Cancel'")

    def confirm_alert_now(self, alert_id: int) -> bool:
        """Instantly confirms and sends a pending alert without waiting for countdown."""
        with self.lock:
            if self.active_alert_id == alert_id:
                self.active_alert_id = None
        self.auto_dispatch_alert(alert_id)
        return True


# Instantiate global streamer service
stream_service = CameraStreamService()


# ==============================================================================
# FLASK ROUTES: WEB VIEWS & VIDEO FEED
# ==============================================================================
@app.route("/")
def index():
    """Renders the main single-page dashboard application."""
    return render_template("index.html", config=config)


@app.route("/video_feed")
def video_feed():
    """Multipart MJPEG video stream."""
    def generate():
        while True:
            with stream_service.lock:
                frame_data = stream_service.current_frame_jpeg

            if frame_data:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_data + b"\r\n"
                )
            time.sleep(0.04)  # ~25 FPS stream delivery

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/evidence/<path:filename>")
def serve_evidence(filename: str):
    """Serves captured JPEG snapshots and incident MP4 video files."""
    database.log_audit_event("Auditor", "EVIDENCE_ACCESSED", filename)
    return send_from_directory(config.EVIDENCE_DIR, filename)


# ==============================================================================
# REST API: TELEMETRY & SYSTEM METRICS
# ==============================================================================
@app.route("/api/telemetry")
def api_telemetry():
    """Returns real-time computer vision status, finger counts, 3-stage alert status, and health."""
    with stream_service.lock:
        return jsonify(stream_service.telemetry)


@app.route("/api/cameras")
def api_cameras():
    """Returns surveillance camera network statuses for the control room."""
    cams = database.get_all_cameras()
    return jsonify(cams)


@app.route("/api/metrics")
def api_metrics():
    """Returns dashboard metrics (total cameras, active alerts, alerts today)."""
    metrics = database.get_dashboard_metrics()
    return jsonify(metrics)


@app.route("/api/alerts")
def api_alerts():
    """Returns alert logs from SQLite with optional filtering."""
    status_filter = request.args.get("status")
    search = request.args.get("search")
    alerts = database.get_all_alerts(limit=100, status_filter=status_filter, search=search)
    return jsonify(alerts)


@app.route("/api/alert/cancel", methods=["POST"])
def api_cancel_alert():
    """Cancels a pending countdown alert."""
    data = request.get_json() or {}
    alert_id = data.get("alert_id") or stream_service.active_alert_id

    if alert_id:
        success = stream_service.cancel_alert(int(alert_id))
        return jsonify({"success": success, "message": "Alert cancelled. Marked safe."})
    return jsonify({"success": False, "message": "No active alert to cancel."}), 400


@app.route("/api/alert/confirm", methods=["POST"])
def api_confirm_alert():
    """Immediately confirms an alert and dispatches SMS."""
    data = request.get_json() or {}
    alert_id = data.get("alert_id") or stream_service.active_alert_id
    if alert_id:
        success = stream_service.confirm_alert_now(int(alert_id))
        return jsonify({"success": success, "message": "Emergency alert dispatched."})
    return jsonify({"success": False, "message": "No active alert."}), 400


@app.route("/api/alert/simulate", methods=["POST"])
def api_simulate_alert():
    """Simulates a distress alert capturing live GPS coordinates and target phone for hackathon demo."""
    data = request.get_json() or {}
    cam_id = data.get("camera_id", "CAM-01")

    cameras = {c["id"]: c for c in database.get_all_cameras()}
    target_cam = cameras.get(cam_id) or cameras.get("CAM-01") or {
        "id": "CAM-01",
        "name": "Local AI Camera (Your Device)",
        "city": "Noida / Delhi NCR",
        "latitude": config.CAMERA_LATITUDE,
        "longitude": config.CAMERA_LONGITUDE,
    }

    cam_id_actual = target_cam.get("id", "CAM-01")
    cam_name = target_cam.get("name", "Local AI Camera (Your Device)")
    lat = float(target_cam.get("latitude", config.CAMERA_LATITUDE))
    lon = float(target_cam.get("longitude", config.CAMERA_LONGITUDE))
    loc_address = (
        target_cam.get("installation_location")
        or target_cam.get("location_address")
        or f"{cam_name}, {target_cam.get('city', 'Noida')}, India"
    )

    target_phone = data.get("phone") or config.ALERT_RECIPIENT_PHONE or "+919876543210"
    incident_uuid = f"INC-SIM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"

    # 1. Dispatch emergency SMS / WhatsApp message via SMSAlertSender
    from alerts.location import get_camera_location
    loc_obj = get_camera_location(
        name=cam_name,
        address=loc_address,
        lat=lat,
        lon=lon,
        camera_id=cam_id_actual,
    )
    sms_sender = stream_service.alert_sender
    sms_sent = sms_sender.send_distress_alert(
        event_name="Signal for Help (Demo Dispatch)",
        location=loc_obj,
        camera_id=cam_id_actual,
        confidence=0.98,
        target_override=target_phone,
    )

    delivery_status = f"Dispatched (SMS/WhatsApp to {target_phone})" if sms_sent else f"Simulated Demo (Target: {target_phone})"

    # 2. Save permanent record into SQLite incidents table
    inc_id = database.create_incident(
        incident_uuid=incident_uuid,
        camera_id=cam_id_actual,
        camera_name=cam_name,
        location_address=loc_address,
        latitude=lat,
        longitude=lon,
        stage="RED",
        confidence=0.98,
        gesture_breakdown=json.dumps({"stage1_open": 1.0, "stage2_thumb": 0.98, "stage3_fist": 0.98}),
        notes=f"Emergency SOS dispatched to {target_phone} at GPS [{lat:.6f} N, {lon:.6f} E].",
    )
    database.update_incident_delivery_status(incident_uuid, delivery_status)

    # 3. Save permanent record into SQLite alert_logs table
    alert_id = database.log_alert(
        camera_id=cam_id_actual,
        camera_name=cam_name,
        location_address=loc_address,
        latitude=lat,
        longitude=lon,
        gesture_type="Signal for Help (SOS Confirmed)",
        confidence=0.98,
        status="Sent",
        snapshot_path="",
        notes=f"Dispatched to emergency contact {target_phone}",
    )

    # 4. Update camera status in SQLite database
    database.set_camera_status(cam_id_actual, "Alert")
    database.log_audit_event(
        "Emergency-Operator",
        "DEMO_ALERT_DISPATCHED",
        f"Incident {incident_uuid}",
        details=f"Target: {target_phone}, GPS: {lat:.6f}, {lon:.6f}",
    )

    return jsonify({
        "success": True,
        "alert_id": alert_id,
        "incident_id": inc_id,
        "incident_uuid": incident_uuid,
        "camera": target_cam,
        "target_phone": target_phone,
        "latitude": lat,
        "longitude": lon,
        "coordinates_str": f"{lat:.6f} N, {lon:.6f} E",
        "location_address": loc_address,
        "maps_url": loc_obj.maps_url,
        "delivery_status": delivery_status,
        "message": f"🚨 Emergency Alert Dispatched! Saved to SQLite database & sent to {target_phone} at GPS [{lat:.6f} N, {lon:.6f} E].",
    })


@app.route("/api/camera/resolve", methods=["POST"])
def api_resolve_camera():
    """Marks an alerting camera as resolved."""
    data = request.get_json() or {}
    cam_id = data.get("camera_id")
    if cam_id:
        database.set_camera_status(cam_id, "Resolved")
        return jsonify({"success": True})
    return jsonify({"success": False}), 400


# ==============================================================================
# REST API: EMERGENCY CONTACT REGISTRATION & OTP VERIFICATION
# ==============================================================================
@app.route("/api/contacts", methods=["GET"])
def api_get_contacts():
    """Returns all registered emergency contacts."""
    contacts = database.get_emergency_contacts()
    return jsonify({"success": True, "contacts": contacts})


@app.route("/api/contacts/add", methods=["POST"])
def api_add_contact():
    """Registers a new emergency contact and generates an initial verification OTP."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    rel = data.get("relationship", "Primary Contact").strip()

    if not name or not phone:
        return jsonify({"success": False, "message": "Name and phone are required."}), 400

    cid = database.add_emergency_contact(name, phone, rel)
    otp = f"{random.randint(100000, 999999)}"
    database.set_contact_otp(cid, otp, expiry_minutes=config.OTP_EXPIRY_MINUTES)
    stream_service.alert_sender.send_otp_sms(phone, otp)

    database.log_audit_event("User", "CONTACT_ADDED", f"Contact {name} ({phone})")

    return jsonify({
        "success": True,
        "contact_id": cid,
        "message": "Contact registered. Verification OTP dispatched.",
        "simulated_otp": otp if config.DRY_RUN else None,
    })


@app.route("/api/contacts/send-otp", methods=["POST"])
def api_send_otp():
    """Generates and sends a new OTP for a contact."""
    data = request.get_json() or {}
    cid = data.get("contact_id")
    if not cid:
        return jsonify({"success": False, "message": "contact_id required"}), 400

    contacts = {c["id"]: c for c in database.get_emergency_contacts()}
    contact = contacts.get(int(cid))
    if not contact:
        return jsonify({"success": False, "message": "Contact not found"}), 404

    otp = f"{random.randint(100000, 999999)}"
    database.set_contact_otp(int(cid), otp, expiry_minutes=config.OTP_EXPIRY_MINUTES)
    stream_service.alert_sender.send_otp_sms(contact["phone"], otp)

    return jsonify({
        "success": True,
        "message": f"New OTP sent to {contact['phone']}.",
        "simulated_otp": otp if config.DRY_RUN else None,
    })


@app.route("/api/contacts/verify-otp", methods=["POST"])
def api_verify_otp():
    """Verifies entered OTP and marks emergency contact active."""
    data = request.get_json() or {}
    cid = data.get("contact_id")
    code = data.get("otp_code", "")

    if not cid or not code:
        return jsonify({"success": False, "message": "contact_id and otp_code required"}), 400

    success, msg = database.verify_contact_otp(int(cid), str(code))
    if success:
        database.log_audit_event("User", "CONTACT_VERIFIED", f"Contact ID {cid}")
        return jsonify({"success": True, "message": msg})
    return jsonify({"success": False, "message": msg}), 400


@app.route("/api/contacts/delete", methods=["POST"])
def api_delete_contact():
    """Removes an emergency contact."""
    data = request.get_json() or {}
    cid = data.get("contact_id")
    if cid:
        database.delete_emergency_contact(int(cid))
        database.log_audit_event("User", "CONTACT_DELETED", f"Contact ID {cid}")
        return jsonify({"success": True, "message": "Contact removed."})
    return jsonify({"success": False, "message": "contact_id required"}), 400


# ==============================================================================
# REST API: HUMAN-IN-THE-LOOP INCIDENT VERIFICATION CONSOLE
# ==============================================================================
@app.route("/api/incidents", methods=["GET"])
def api_get_incidents():
    """Returns verified incident evidence packages for the operator console."""
    status_filter = request.args.get("status")
    incidents = database.get_all_incidents(limit=50, status_filter=status_filter)
    return jsonify({"success": True, "incidents": incidents})


@app.route("/api/incidents/<int:incident_id>", methods=["GET"])
def api_get_incident_detail(incident_id: int):
    """Retrieves full details and evidence links for a specific incident."""
    inc = database.get_incident_by_id(incident_id)
    if not inc:
        return jsonify({"success": False, "message": "Incident not found"}), 404

    cross_links = database.get_linked_cameras_for_incident(incident_id)
    return jsonify({"success": True, "incident": inc, "linked_cameras": cross_links})


@app.route("/api/incidents/action", methods=["POST"])
def api_incident_operator_action():
    """Records operator action: 'Confirmed Emergency', 'Continue Monitoring', 'False Alarm', 'Resolved'."""
    data = request.get_json() or {}
    incident_id = data.get("incident_id")
    action = data.get("action")  # 'Confirmed Emergency', 'Continue Monitoring', 'False Alarm', 'Resolved'
    operator_id = data.get("operator_id", config.DEFAULT_OPERATOR_ID)
    notes = data.get("notes", "")

    if not incident_id or not action:
        return jsonify({"success": False, "message": "incident_id and action required"}), 400

    database.update_incident_operator_action(int(incident_id), action, operator_id, notes)
    database.log_audit_event(
        "Operator",
        f"INCIDENT_ACTION_{action.upper().replace(' ', '_')}",
        f"Incident {incident_id}",
        details=f"By {operator_id}: {notes}",
    )

    # If action is Confirmed Emergency, dispatch emergency broadcast to contacts
    if action == "Confirmed Emergency":
        inc = database.get_incident_by_id(int(incident_id))
        if inc:
            loc = get_camera_location_by_id(inc.get("camera_id", "CAM-01"))
            stream_service.alert_sender.send_emergency_broadcast(
                camera_id=inc.get("camera_id", "CAM-01"),
                location=loc,
                confidence=inc.get("confidence", 0.96),
                snapshot_filename=inc.get("evidence_snapshot"),
            )

    return jsonify({"success": True, "message": f"Incident marked as '{action}' by {operator_id}."})


@app.route("/api/incidents/cross-camera", methods=["POST"])
def api_link_cross_camera():
    """Associates a nearby camera observation into the primary incident timeline."""
    data = request.get_json() or {}
    primary_id = data.get("primary_incident_id")
    linked_cam_id = data.get("linked_camera_id")
    observation = data.get("observation", "Associated incident timeline observation")
    operator_id = data.get("operator_id", config.DEFAULT_OPERATOR_ID)

    if not primary_id or not linked_cam_id:
        return jsonify({"success": False, "message": "primary_incident_id and linked_camera_id required"}), 400

    link_id = database.link_cross_camera_event(int(primary_id), linked_cam_id, observation, operator_id)
    database.log_audit_event(
        "Operator",
        "CROSS_CAMERA_LINKED",
        f"Incident {primary_id} -> Cam {linked_cam_id}",
        details=observation,
    )
    return jsonify({"success": True, "link_id": link_id, "message": "Cross-camera continuity updated."})


# ==============================================================================
# REST API: LEARN FROM FALSE ALARMS & MODEL EVALUATION BENCHMARK
# ==============================================================================
@app.route("/api/false-alarms", methods=["GET"])
def api_get_false_alarm_stats():
    """Returns false alarm distributions and model feedback stats."""
    stats = database.get_false_alarm_statistics()
    return jsonify({"success": True, "statistics": stats})


@app.route("/api/false-alarms/report", methods=["POST"])
def api_report_false_alarm():
    """Logs false alarm feedback with activity classification for model improvement."""
    data = request.get_json() or {}
    inc_id = data.get("incident_id")
    cam_id = data.get("camera_id", "CAM-01")
    activity = data.get("actual_activity", "other")
    notes = data.get("notes", "")
    reporter = data.get("reported_by", config.DEFAULT_OPERATOR_ID)

    fid = database.log_false_alarm_feedback(
        incident_id=int(inc_id) if inc_id else None,
        camera_id=cam_id,
        reported_by=reporter,
        gesture_classified_as="Signal for Help",
        actual_activity=activity,
        notes=notes,
    )
    database.log_audit_event("Operator", "FALSE_ALARM_FEEDBACK_LOGGED", f"Incident {inc_id} Activity: {activity}")

    return jsonify({"success": True, "feedback_id": fid, "message": "False alarm telemetry saved for model retraining."})


@app.route("/api/benchmark/run", methods=["POST"])
def api_run_benchmark():
    """Executes the NO-SOS false-alarm protection evaluation suite and returns metrics."""
    results = stream_service.benchmark_evaluator.run_benchmark()
    database.log_audit_event(
        "Admin",
        "BENCHMARK_EVALUATION_RUN",
        "Signal-for-Help Model",
        details=f"F1: {results['f1_score']} FPR: {results['false_positive_rate']}",
    )
    return jsonify({
        "success": True,
        "metrics": results,
        "results": results.get("results", results.get("cases", [])),
        "benchmark": results,
    })


# ==============================================================================
# REST API: CAMERA HEALTH & NETWORK INTEGRATION LAYER
# ==============================================================================
@app.route("/api/camera/health", methods=["GET"])
def api_camera_health():
    """Returns diagnostic health metrics for all monitored cameras."""
    cams = database.get_all_cameras()
    local_report = stream_service.camera.get_health_report() if stream_service.camera else {}

    return jsonify({
        "success": True,
        "local_camera": local_report,
        "network_cameras": cams,
    })


@app.route("/api/camera/network/register", methods=["POST"])
def api_register_camera():
    """Registers an authorized new CCTV/IP/RTSP surveillance camera."""
    data = request.get_json() or {}
    cid = data.get("camera_id")
    name = data.get("name")
    city = data.get("city", "Delhi NCR")
    lat = float(data.get("latitude", 28.6280))
    lon = float(data.get("longitude", 77.3649))
    org = data.get("organization", "Authorized Municipal Surveillance")
    spot = data.get("installation_location", "Perimeter Pole")
    zone = data.get("zone", "Zone A")
    cam_type = data.get("camera_type", "CCTV-RTSP")

    if not cid or not name:
        return jsonify({"success": False, "message": "camera_id and name required"}), 400

    database.register_camera(cid, name, city, lat, lon, org, spot, zone, cam_type)
    database.log_audit_event("Admin", "CAMERA_REGISTERED", f"Camera {cid} ({name})")
    return jsonify({"success": True, "message": f"Camera {cid} integrated into security network."})


# ==============================================================================
# REST API: EDGE AI MODE & GEOSPATIAL DATA LAYER
# ==============================================================================
@app.route("/api/edge/status", methods=["GET"])
def api_edge_status():
    """Returns Edge AI mode status and real-time bandwidth reduction telemetry."""
    metrics = stream_service.edge_manager.get_bandwidth_metrics()
    return jsonify({"success": True, "metrics": metrics})


@app.route("/api/edge/toggle", methods=["POST"])
def api_edge_toggle():
    """Toggles Edge AI mode on or off."""
    data = request.get_json() or {}
    enabled = data.get("enabled", True)
    stream_service.edge_manager.set_edge_mode(enabled)
    database.log_audit_event("Admin", "EDGE_MODE_TOGGLED", f"Enabled: {enabled}")
    return jsonify({"success": True, "edge_mode_enabled": stream_service.edge_manager.edge_mode_enabled})


@app.route("/api/edge/ingest", methods=["POST"])
def api_edge_ingest():
    """Endpoint for authorized remote Edge AI nodes to post SOS event packets."""
    payload = request.get_json() or {}
    cam_id = payload.get("camera_id", "EDGE-NODE-01")
    conf = float(payload.get("confidence", 0.95))
    stage = payload.get("alert_stage", "RED")

    inc_id = f"EDGE-INC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    database.create_incident(
        incident_uuid=inc_id,
        camera_id=cam_id,
        camera_name=f"Edge Node ({cam_id})",
        location_address=payload.get("location", "Remote Edge Camera Node"),
        latitude=28.6280,
        longitude=77.3649,
        stage=stage,
        confidence=conf,
        notes="Transmitted via decentralized Edge AI node",
    )
    database.log_audit_event("EdgeNode", "EDGE_ALERT_INGESTED", f"Node {cam_id}")

    return jsonify({"success": True, "incident_uuid": inc_id, "message": "Edge alert verified and ingested."})


@app.route("/api/geospatial/context", methods=["GET"])
def api_geospatial_context():
    """Returns satellite map metadata and macro-level environmental context."""
    meta = stream_service.geospatial.get_layer_metadata()
    zone = stream_service.geospatial.get_zone_context(config.CAMERA_LATITUDE, config.CAMERA_LONGITUDE)
    return jsonify({"success": True, "metadata": meta, "zone_context": zone})


@app.route("/api/audit/logs", methods=["GET"])
def api_audit_logs():
    """Returns privacy-first compliance audit trail."""
    logs = database.get_recent_audit_logs(limit=50)
    return jsonify({"success": True, "logs": logs})


@app.route("/api/video/upload", methods=["POST"])
def api_video_upload():
    """Accepts uploaded prerecorded CCTV video file for presentation/demo mode."""
    if "video" not in request.files:
        return jsonify({"success": False, "message": "No video file provided"}), 400

    file = request.files["video"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No selected file"}), 400

    upload_dir = config.BASE_DIR / "samples"
    upload_dir.mkdir(parents=True, exist_ok=True)
    clean_name = f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    target_path = upload_dir / clean_name
    file.save(str(target_path))

    # Switch stream service to this uploaded video
    success = stream_service.switch_camera_source(str(target_path))
    database.log_audit_event("Operator", "DEMO_VIDEO_UPLOADED", clean_name)

    return jsonify({
        "success": success,
        "filename": clean_name,
        "message": "Demo CCTV video uploaded and active in stream player.",
    })


# ==============================================================================
# REST API: SETTINGS & EXPORT
# ==============================================================================
@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """Gets or updates application settings."""
    if request.method == "POST":
        data = request.get_json() or {}
        if "sensitivity" in data:
            val = float(data["sensitivity"])
            stream_service.detector.set_sensitivity(val)
            stream_service.decision_engine.set_sensitivity(val)
        if "mode" in data:
            stream_service.detector.set_mode(str(data["mode"]))
        if "countdown_duration" in data:
            stream_service.countdown_duration = max(3.0, float(data["countdown_duration"]))
        if "siren_enabled" in data:
            stream_service.siren_enabled = bool(data["siren_enabled"])
        if "test_mode" in data:
            config.TEST_MODE = bool(data["test_mode"])
        if "dry_run" in data:
            config.DRY_RUN = bool(data["dry_run"])
            stream_service.alert_sender.dry_run = config.DRY_RUN
        if "alert_recipient_phone" in data:
            config.ALERT_RECIPIENT_PHONE = str(data["alert_recipient_phone"]).strip()
            stream_service.alert_sender.recipient_phone = config.ALERT_RECIPIENT_PHONE
        if "cctv_night_mode" in data:
            stream_service.detector.set_night_mode(bool(data["cctv_night_mode"]))
        if "edge_ai_enabled" in data:
            stream_service.edge_manager.set_edge_mode(bool(data["edge_ai_enabled"]))

        return jsonify({"success": True, "message": "Settings updated successfully."})

    return jsonify({
        "sensitivity": stream_service.detector.sensitivity,
        "mode": stream_service.detector.mode,
        "countdown_duration": stream_service.countdown_duration,
        "siren_enabled": stream_service.siren_enabled,
        "test_mode": config.TEST_MODE,
        "dry_run": config.DRY_RUN,
        "alert_recipient_phone": config.ALERT_RECIPIENT_PHONE,
        "camera_source": str(config.CAMERA_SOURCE),
        "cctv_night_mode": stream_service.detector.night_mode,
        "edge_ai_enabled": stream_service.edge_manager.edge_mode_enabled,
    })


@app.route("/api/alerts/export")
def api_export_alerts():
    """Exports alert logs to a downloadable CSV file."""
    alerts = database.get_all_alerts(limit=500)
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Alert ID",
        "Timestamp",
        "Camera ID",
        "Camera Name",
        "Location Address",
        "Latitude",
        "Longitude",
        "Gesture Type",
        "Confidence",
        "Status",
        "Snapshot",
        "Notes",
    ])

    for a in alerts:
        writer.writerow([
            a["id"],
            a["timestamp"],
            a["camera_id"],
            a["camera_name"],
            a["location_address"],
            a["latitude"],
            a["longitude"],
            a["gesture_type"],
            f"{a['confidence']:.2f}",
            a["status"],
            a["snapshot_path"] or "None",
            a["notes"] or "",
        ])

    csv_data = output.getvalue()
    response = make_response(csv_data)
    response.headers["Content-Disposition"] = "attachment; filename=safety_camera_alert_logs.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("=" * 65)
    logger.info("Starting Smart AI Safety Camera Web Application")
    logger.info("Dashboard URL: http://127.0.0.1:%d", port)
    logger.info("=" * 65)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
