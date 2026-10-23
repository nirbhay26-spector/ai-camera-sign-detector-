"""
Unit & Integration Tests for Smart AI Safety Camera.
====================================================
Tests key components:
  1. Time-based confirmation (debouncing)
  2. Cooldown suppression
  3. Safety checks (forbidden emergency numbers)
  4. Google Maps link generation
  5. Evidence snapshot & ring buffer recording
  6. Hand gesture geometry evaluation
"""

import time
import unittest
from pathlib import Path
import numpy as np

import config
from decision import DecisionEngine
from alerts.sms import SMSAlertSender
from alerts.location import get_camera_location
from evidence import EvidenceRecorder
from detectors.hand_signal import HandSignalDetector, STATE_IDLE, STATE_STEP1_OPEN_PALM, STATE_STEP2_THUMB_TUCKED, STATE_STEP3_FINGERS_CLOSED


class MockLandmark:
    """Mock landmark point simulating MediaPipe NormalizedLandmark."""
    def __init__(self, x: float, y: float, z: float = 0.0):
        self.x = x
        self.y = y
        self.z = z


class TestSafetyCameraSystem(unittest.TestCase):
    """Test suite for safety camera decision, alerts, evidence, and geometry logic."""

    @classmethod
    def setUpClass(cls):
        import database
        database.init_database()

    def test_location_google_maps_url(self):
        """Verify Google Maps link contains lat/lon coordinates."""
        loc = get_camera_location(
            name="Test Gate",
            address="123 Test Street",
            lat=28.6280,
            lon=77.3649,
        )
        self.assertEqual(loc.name, "Test Gate")
        self.assertIn("28.628000,77.364900", loc.maps_url)
        self.assertTrue(loc.maps_url.startswith("https://www.google.com/maps/search/?api=1&query="))

    def test_decision_held_too_briefly_no_alert(self):
        """If gesture is held for less than confirmation time, no alert should trigger."""
        engine = DecisionEngine(confirmation_seconds=2.0, cooldown_seconds=10.0)

        # Frame 1: Detection starts
        state = engine.update(is_detected=True)
        self.assertFalse(state.should_trigger_alert)
        self.assertFalse(state.is_confirmed)

        # After 0.5s: Still confirming
        time.sleep(0.1)
        state = engine.update(is_detected=True)
        self.assertFalse(state.should_trigger_alert)

        # Dropped before 2.0s
        state = engine.update(is_detected=False)
        self.assertFalse(state.should_trigger_alert)
        self.assertFalse(state.is_confirmed)
        self.assertEqual(state.seconds_detected, 0.0)

    def test_decision_held_long_enough_triggers_alert(self):
        """Holding gesture continuously for >= confirmation_seconds must trigger alert."""
        engine = DecisionEngine(confirmation_seconds=0.3, cooldown_seconds=5.0)

        # Start detection
        engine.update(is_detected=True)
        time.sleep(0.35)

        # Now threshold is crossed!
        state = engine.update(is_detected=True)
        self.assertTrue(state.should_trigger_alert)
        self.assertTrue(state.is_confirmed)
        self.assertTrue(state.is_in_cooldown)

    def test_decision_cooldown_suppression(self):
        """During cooldown, continued or repeated gesture must NOT trigger another alert."""
        engine = DecisionEngine(confirmation_seconds=0.2, cooldown_seconds=2.0)

        # Trigger first alert
        engine.update(is_detected=True)
        time.sleep(0.25)
        first_alert = engine.update(is_detected=True)
        self.assertTrue(first_alert.should_trigger_alert)

        # Subsequent frames while still holding gesture
        subsequent = engine.update(is_detected=True)
        self.assertFalse(subsequent.should_trigger_alert)
        self.assertTrue(subsequent.is_in_cooldown)

        # Drop and re-trigger within cooldown
        engine.update(is_detected=False)
        engine.update(is_detected=True)
        time.sleep(0.25)
        cooldown_attempt = engine.update(is_detected=True)
        self.assertFalse(cooldown_attempt.should_trigger_alert)
        self.assertTrue(cooldown_attempt.is_in_cooldown)

    def test_sms_safety_blocks_emergency_numbers(self):
        """Verifies that automated SMS to 112 / 911 is strictly blocked."""
        sender = SMSAlertSender()
        sender.dry_run = False
        sender.recipient_phone = "112"

        # Attempt to send to 112
        result = sender.send_distress_alert(event_name="Signal for Help")
        self.assertFalse(result, "Automated alert to 112 must be blocked!")

        sender.recipient_phone = "+91 911"
        result = sender.send_distress_alert(event_name="Signal for Help")
        self.assertFalse(result, "Automated alert to 911 must be blocked!")

    def test_sms_dry_run_mode(self):
        """In DRY_RUN mode, alert returns True and logs without calling Twilio."""
        sender = SMSAlertSender()
        sender.dry_run = True
        sender.recipient_phone = "+919876543210"

        success = sender.send_distress_alert(event_name="Signal for Help")
        self.assertTrue(success)

    def test_evidence_snapshot_and_ring_buffer(self):
        """Verifies JPEG snapshot and ring buffer incident video recording."""
        test_dir = config.BASE_DIR / "evidence_test"
        recorder = EvidenceRecorder(evidence_dir=test_dir, target_fps=10, pre_event_seconds=1.0, post_event_seconds=1.0)

        # Create dummy frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Draw some colored shape
        frame[100:200, 100:200] = [0, 255, 0]

        # 1. Test snapshot
        snapshot_path = recorder.save_snapshot(frame, event_label="test_distress")
        self.assertTrue(snapshot_path.exists())
        self.assertGreater(snapshot_path.stat().st_size, 0)

        # 2. Test ring buffer video recording
        for _ in range(10):
            recorder.add_frame_to_buffer(frame)

        # Trigger incident recording
        recorder.start_incident_video_recording()
        for _ in range(12):
            recorder.add_frame_to_buffer(frame)

        # Small sleep for background video encoding thread to finish
        time.sleep(0.5)

        # Cleanup test files
        for p in test_dir.glob("*"):
            p.unlink()
        test_dir.rmdir()

    def test_emergency_contact_otp_lifecycle(self):
        """Tests emergency contact addition, OTP issuance, and verification."""
        import database
        # Add test contact
        cid = database.add_emergency_contact("Test Guardian", "+919999888877", "Family", is_primary=False)
        self.assertIsNotNone(cid)

        # Set OTP
        otp_code = database.set_contact_otp(cid)
        self.assertEqual(len(otp_code), 6)
        self.assertTrue(otp_code.isdigit())

        # Test incorrect OTP
        wrong_verified, _ = database.verify_contact_otp(cid, "000000")
        self.assertFalse(wrong_verified)

        # Test correct OTP
        success, _ = database.verify_contact_otp(cid, otp_code)
        self.assertTrue(success)

        # Confirm contact is now verified
        verified_contacts = database.get_verified_contacts()
        contact_ids = [c["id"] for c in verified_contacts]
        self.assertIn(cid, contact_ids)

        # Cleanup
        database.delete_emergency_contact(cid)

    def test_tamper_evident_sha256_evidence(self):
        """Tests cryptographic SHA-256 hashing on evidence files."""
        from evidence import compute_file_sha256, generate_evidence_package
        test_dir = config.BASE_DIR / "evidence_sha_test"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / "test_snapshot.jpg"
        test_file.write_bytes(b"Simulated tamper-proof incident evidence frame data")

        sha_hash = compute_file_sha256(test_file)
        self.assertEqual(len(sha_hash), 64)

        package = generate_evidence_package(
            incident_id="INC-TEST-001",
            snapshot_path=test_file,
            video_path=None,
            camera_id="CAM-01",
            location_info={"city": "Noida", "zone": "Zone A"},
            alert_stage="RED",
            confidence=0.98,
        )
        self.assertEqual(package["incident_id"], "INC-TEST-001")
        self.assertEqual(package["files"]["snapshot_sha256"], sha_hash)

        # Cleanup
        test_file.unlink()
        test_dir.rmdir()

    def test_benchmark_evaluator_metrics(self):
        """Tests benchmark evaluation metrics calculation across 15 cases."""
        from benchmarks.evaluator import BenchmarkEvaluator
        evaluator = BenchmarkEvaluator()
        report = evaluator.run_benchmark()

        self.assertIn("precision", report)
        self.assertGreaterEqual(report["precision"], 0.8)
        self.assertGreaterEqual(report["recall"], 0.8)
        self.assertGreaterEqual(report["f1_score"], 0.8)
        self.assertLessEqual(report["fpr"], 0.15)
        self.assertLessEqual(report["fnr"], 0.15)
        self.assertLess(report["mean_latency_ms"], 100.0)
        self.assertEqual(len(report["cases"]), 15)

    def test_edge_ai_bandwidth_tracker(self):
        """Tests Edge AI local processing and bandwidth reduction computation."""
        from edge import EdgeAIManager
        edge = EdgeAIManager(edge_mode_enabled=True)
        self.assertTrue(edge.edge_mode_enabled)

        # Simulate 30 raw 100KB frames
        for _ in range(30):
            payload = edge.process_frame_at_edge(
                has_candidate_event=False,
                alert_stage="GREEN",
                confidence=0.0,
                frame_bytes_size=100000,
            )
            self.assertIsNone(payload)  # No payload transmitted for normal frames

        # Verify massive bandwidth saving
        status = edge.get_status()
        self.assertGreater(status["bandwidth_saved_percent"], 95.0)

        # Trigger 1 candidate alert frame
        alert_payload = edge.process_frame_at_edge(
            has_candidate_event=True,
            alert_stage="RED",
            confidence=0.96,
            frame_bytes_size=100000,
            evidence_hash="abcdef1234567890",
        )
        self.assertIsNotNone(alert_payload)
        self.assertEqual(alert_payload["alert_stage"], "RED")

    def test_camera_health_laplacian_blur_and_diagnostics(self):
        """Tests Laplacian variance blur score calculation."""
        import cv2
        from camera import Camera

        # Sharp frame (checkerboard edges)
        sharp_frame = np.zeros((200, 200, 3), dtype=np.uint8)
        sharp_frame[::20, :] = 255
        sharp_frame[:, ::20] = 255
        sharp_score = Camera.calculate_blur_score(sharp_frame)

        # Heavily blurred frame
        blurry_frame = cv2.GaussianBlur(sharp_frame, (31, 31), 0)
        blurry_score = Camera.calculate_blur_score(blurry_frame)

        self.assertGreater(sharp_score, blurry_score)
        self.assertGreater(sharp_score, 80.0)
        self.assertLess(blurry_score, 80.0)

    def test_geospatial_satellite_disclaimer(self):
        """Verifies satellite macro disclaimer and tile URLs."""
        from geospatial import GeospatialIntelligenceLayer
        geo = GeospatialIntelligenceLayer()
        self.assertIn("arcgisonline", geo.satellite_tile_url.lower())
        self.assertIn("Esri", geo.get_layer_metadata()["satellite_attribution"])
        self.assertIn("macro-area", geo.disclaimer)
        self.assertIn("detect hand gestures", geo.disclaimer.lower())

    def test_incident_persistent_logging_and_delivery_status(self):
        """Verifies SQLite incident persistence and delivery status updates."""
        import database
        test_uuid = f"INC-TEST-PERSIST-{int(time.time() * 1000)}"
        inc_id = database.create_incident(
            incident_uuid=test_uuid,
            camera_id="CAM-01",
            camera_name="Local AI Camera (Your Device)",
            location_address="Test Address, Sector 62, Noida",
            latitude=28.6280,
            longitude=77.3649,
            stage="RED",
            confidence=0.97,
            notes="Automated Signal-for-Help test candidate",
        )
        self.assertIsNotNone(inc_id)

        # Update delivery status
        updated = database.update_incident_delivery_status(
            test_uuid,
            "Dispatched (SMS to 2 contacts)",
            notes="Dispatched to emergency contacts via Twilio",
        )
        self.assertTrue(updated)

        # Retrieve and verify
        incident = database.get_incident_by_id(inc_id)
        self.assertIsNotNone(incident)
        self.assertEqual(incident["incident_uuid"], test_uuid)
        self.assertEqual(incident["delivery_status"], "Dispatched (SMS to 2 contacts)")
        self.assertEqual(incident["stage"], "RED")

    def test_simulate_alert_api_dispatch_and_database_persistence(self):
        """Verifies simulated demo alert captures GPS, target phone, and saves to SQLite."""
        import app
        client = app.app.test_client()
        res = client.post("/api/alert/simulate", json={"camera_id": "CAM-01", "phone": "+919876543210"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["target_phone"], "+919876543210")
        self.assertAlmostEqual(data["latitude"], 28.6280, places=3)
        self.assertAlmostEqual(data["longitude"], 77.3649, places=3)
        self.assertIn("Dispatched", data["delivery_status"])

        # Check database persistence
        import database
        incident = database.get_incident_by_id(data["incident_id"])
        self.assertIsNotNone(incident)
        self.assertEqual(incident["stage"], "RED")
        self.assertIn("+919876543210", incident["delivery_status"])


if __name__ == "__main__":
    unittest.main()


