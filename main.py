"""
Smart AI Safety Camera - Main Application.
==========================================
Real-time distress signal and suspicious activity detection system.

Features in Version 1:
  - Live camera stream (Webcam, USB camera, or RTSP/IP stream)
  - International "Signal for Help" hand gesture detection (MediaPipe)
  - Multi-step state machine (Open Palm -> Thumb Tucked -> Closed Fingers)
  - Continuous time confirmation (debouncing) to prevent false alarms
  - Alert cooldown period (no repeated spam)
  - Twilio SMS alerting with Google Maps location link
  - Evidence preservation: Automatic snapshot + pre/post-incident video clip ring buffer
  - Safe DRY_RUN mode for zero-cost testing

Keyboard Controls (in Preview Window):
  [Q] or [ESC] : Quit application
  [S]          : Save manual snapshot
  [R]          : Reset detection state machine
  [D]          : Toggle landmark annotations on/off

Author: Smart AI Safety Camera Team
Target Audience: First-Year CSE / Hackathon Developers
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path

# pyrefly: ignore[missing-import]
import cv2
# pyrefly: ignore[missing-import]
import numpy as np

import config
from camera import Camera
from detectors.hand_signal import HandSignalDetector
from decision import DecisionEngine
from alerts.sms import SMSAlertSender
from alerts.location import get_camera_location
from evidence import EvidenceRecorder

# Configure clean, informative logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SafetyCamera")


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments for running the software."""
    parser = argparse.ArgumentParser(
        description="Smart AI Safety Camera - Real-Time Distress Detection Software"
    )
    parser.add_argument(
        "--source",
        type=str,
        default=str(config.CAMERA_SOURCE),
        help="Camera source: integer webcam index (0, 1) or RTSP URL or video file path.",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="Scan and list all accessible camera devices on this machine, then exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate alerts without sending real Twilio SMS (saves credits).",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run in headless background mode without popping up an OpenCV preview window.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the Web Control Center Dashboard (Flask server at http://127.0.0.1:5000).",
    )
    return parser.parse_args()


def draw_software_hud(
    frame: np.ndarray,
    fps: float,
    source_str: str,
    show_debug: bool,
) -> np.ndarray:
    """Draws the top title bar and keybindings guide onto the camera frame."""
    h, w, _ = frame.shape
    annotated = frame.copy()

    # Top title bar
    cv2.rectangle(annotated, (0, 0), (w, 30), (30, 30, 30), -1)
    title_text = "SMART AI SAFETY CAMERA v1.0 | Signal for Help Detection"
    cv2.putText(
        annotated,
        title_text,
        (15, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    # Top-right stats (FPS & Source)
    mode_text = "[DRY_RUN]" if config.DRY_RUN else "[LIVE_SMS]"
    stats_text = f"FPS: {fps:.1f} | Cam: {source_str} {mode_text}"
    text_size = cv2.getTextSize(stats_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0]
    cv2.putText(
        annotated,
        stats_text,
        (w - text_size[0] - 15, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (0, 255, 255),
        1,
        cv2.LINE_AA,
    )

    # Hotkeys helper (just above bottom HUD)
    keys_text = "[Q] Quit  |  [S] Snapshot  |  [R] Reset  |  [D] Toggle Landmarks"
    cv2.putText(
        annotated,
        keys_text,
        (20, h - 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (180, 180, 180),
        1,
        cv2.LINE_AA,
    )

    return annotated


def run_safety_camera(args: argparse.Namespace) -> None:
    """Main execution loop for the Smart AI Safety Camera software."""
    # 1. Override DRY_RUN if requested via CLI flag
    if args.dry_run:
        config.DRY_RUN = True

    # 2. Parse Camera Source (integer if digit, else string)
    raw_source = args.source.strip()
    source = int(raw_source) if raw_source.isdigit() else raw_source

    logger.info("=" * 65)
    logger.info("   Starting Smart AI Safety Camera (Version 1)")
    logger.info("=" * 65)
    logger.info("Target Source: %s", source)
    logger.info("Target Rate  : %d FPS", config.TARGET_FPS)
    logger.info("Confirm Time : %.1f seconds", config.CONFIRMATION_SECONDS)
    logger.info("Cooldown     : %.1f seconds", config.COOLDOWN_SECONDS)
    logger.info("Mode         : %s", "DRY_RUN (Simulated Alerts)" if config.DRY_RUN else "LIVE SMS")
    logger.info("Location     : %s", config.CAMERA_LOCATION_ADDRESS)
    logger.info("=" * 65)

    # 3. Initialize Core Subsystems
    try:
        camera = Camera(source=source, target_fps=config.TARGET_FPS)
    except Exception as e:
        logger.critical("Cannot access camera source %s: %s", source, e)
        sys.exit(1)

    if not camera.is_opened:
        logger.critical(
            "Could not open camera '%s'. Run 'python main.py --list-cameras' to see available devices.",
            source,
        )
        sys.exit(1)

    detector = HandSignalDetector(state_timeout=config.STATE_EXPIRY_SECONDS)
    decision_engine = DecisionEngine(
        confirmation_seconds=config.CONFIRMATION_SECONDS,
        cooldown_seconds=config.COOLDOWN_SECONDS,
    )
    alert_sender = SMSAlertSender()
    evidence_recorder = EvidenceRecorder(
        evidence_dir=config.EVIDENCE_DIR,
        target_fps=config.TARGET_FPS,
        pre_event_seconds=config.PRE_EVENT_BUFFER_SECONDS,
        post_event_seconds=config.POST_EVENT_RECORD_SECONDS,
    )
    camera_location = get_camera_location()

    window_name = "Smart AI Safety Camera - Live Feed"
    if not args.no_gui:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    show_landmarks = True

    logger.info("Camera loop started. Press 'Q' or ESC in the preview window to exit.")

    try:
        while True:
            # Step A: Read frame from camera
            success, frame = camera.read_frame()
            if not success or frame is None:
                logger.warning("Frame read failed or video feed paused. Retrying...")
                time.sleep(0.05)
                continue

            # Step B: Record frame to pre/post-incident evidence ring buffer
            evidence_recorder.add_frame_to_buffer(frame)

            # Step C: Run gesture detection
            detection_result = detector.detect(frame)

            # Step D: Run time-based confirmation & cooldown decision logic
            decision_state = decision_engine.update(
                detection_result.is_detected,
                detection_result.alert_stage,
                detection_result.confidence,
            )

            # Step E: Trigger emergency alert if confirmation threshold is reached
            if decision_state.should_trigger_alert:
                logger.warning(">>> EMERGENCY EVENT TRIGGERED! PROCESSING ALERTS & EVIDENCE <<<")

                # 1. Save timestamped JPEG evidence snapshot
                snapshot_path = evidence_recorder.save_snapshot(frame, event_label="distress_signal")

                # 2. Trigger incident video recording (bundles pre-event buffer + post-event frames)
                evidence_recorder.start_incident_video_recording()

                # 3. Send SMS notification via Twilio (or log in DRY_RUN)
                alert_sender.send_distress_alert(
                    event_name="Signal for Help",
                    location=camera_location,
                    confidence=detection_result.confidence,
                    snapshot_filename=snapshot_path.name,
                )

            # Step F: Render visual overlays (HUD + skeleton annotations)
            if not args.no_gui:
                display_frame = frame.copy()

                # Draw MediaPipe hand landmarks and gesture state badges
                if show_landmarks:
                    display_frame = detector.draw_annotations(display_frame, detection_result)

                # Draw top status bar and FPS
                display_frame = draw_software_hud(
                    display_frame,
                    fps=camera.actual_fps,
                    source_str=str(source),
                    show_debug=show_landmarks,
                )

                # Draw bottom decision progress bar and emergency borders
                display_frame = decision_engine.draw_hud(display_frame, decision_state)

                # Display in OpenCV window
                cv2.imshow(window_name, display_frame)

                # Step G: Handle keyboard events
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q"), ord("Q")):
                    logger.info("Quit key pressed. Exiting...")
                    break
                elif key in (ord("s"), ord("S")):
                    manual_snap = evidence_recorder.save_snapshot(frame, event_label="manual")
                    logger.info("Manual snapshot captured: %s", manual_snap.name)
                elif key in (ord("r"), ord("R")):
                    detector.reset()
                    logger.info("Detection state machine reset to IDLE.")
                elif key in (ord("d"), ord("D")):
                    show_landmarks = not show_landmarks
                    logger.info("Toggled landmark display: %s", show_landmarks)

    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C).")
    finally:
        # Step H: Clean up all hardware and model resources
        logger.info("Shutting down subsystems...")
        camera.release()
        detector.close()
        if not args.no_gui:
            cv2.destroyAllWindows()
        logger.info("Software closed cleanly.")


def main():
    """Application entrypoint."""
    args = parse_arguments()

    # Handle camera discovery utility flag
    if args.list_cameras:
        print("\n" + "=" * 50)
        print("   SCANNING FOR CONNECTED CAMERAS")
        print("=" * 50)
        cameras = Camera.list_available_cameras(max_tested=6)
        if not cameras:
            print("No cameras detected! Make sure your webcam is plugged in and has camera permissions enabled.")
        else:
            for cam in cameras:
                print(f" Camera Index [{cam['index']}]: Resolution {cam['width']}x{cam['height']} - {cam['status']}")
            print("=" * 50)
            print("Tip: Run 'python main.py --source <INDEX>' to select a specific camera.")
        return

    if args.web:
        import app as web_app
        port = int(os.environ.get('PORT', 5000))
        print("\n" + "=" * 60)
        print(f" Starting Web Control Center at: http://127.0.0.1:{port}")
        print("=" * 60 + "\n")
        web_app.app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
        return

    run_safety_camera(args)


if __name__ == "__main__":
    main()
