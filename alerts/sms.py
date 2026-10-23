"""
SMS Alerting Module using Twilio.
=================================
This module delivers instant SMS distress notifications to the owner's phone.

SAFETY & LEGAL NOTICE FOR DEVELOPERS:
------------------------------------
- NEVER configure automated emergency numbers (such as 112 in India or 911 in the US).
  In India and most countries, automated bot calls/texts to emergency dispatchers
  are prohibited by law and subject to legal penalties.
- In Version 1, alerts are strictly intended for the system owner / designated
  security contact.
- When `DRY_RUN=True` in `.env`, no network calls are made and no Twilio credits
  are consumed. The full message is printed to the console for testing.
"""

import logging
from typing import Optional, Dict, Any
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

import config
from alerts.location import LocationInfo, get_camera_location

logger = logging.getLogger(__name__)

# List of emergency numbers that must NEVER be called or texted by automated systems
FORBIDDEN_EMERGENCY_NUMBERS = {"112", "911", "999", "100", "101", "102", "108"}


class SMSAlertSender:
    """Dispatches SMS alerts via Twilio with safety protections."""

    def __init__(self):
        self.account_sid = config.TWILIO_ACCOUNT_SID
        self.auth_token = config.TWILIO_AUTH_TOKEN
        self.from_phone = config.TWILIO_PHONE_NUMBER
        self.recipient_phone = config.ALERT_RECIPIENT_PHONE
        self.dry_run = config.DRY_RUN
        self.test_mode = config.TEST_MODE

        self._client: Optional[Client] = None
        if not self.dry_run:
            if self.account_sid and self.auth_token:
                try:
                    self._client = Client(self.account_sid, self.auth_token)
                    logger.info("Twilio client initialized successfully.")
                except Exception as e:
                    logger.error("Failed to initialize Twilio client: %s", e)
            else:
                logger.warning(
                    "Twilio credentials missing in .env! Defaulting to DRY_RUN mode."
                )
                self.dry_run = True

    def send_distress_alert(
        self,
        event_name: str = "Signal for Help",
        location: Optional[LocationInfo] = None,
        snapshot_filename: Optional[str] = None,
        camera_id: str = "CAM-01",
        confidence: float = 0.96,
        target_override: Optional[str] = None,
    ) -> bool:
        """Sends an emergency SMS alert formatted to the official SOS intelligence template.

        Args:
            event_name: Label of the detected event.
            location: Optional LocationInfo instance (defaults to camera location).
            snapshot_filename: Optional filename of the saved snapshot.
            camera_id: Identifier of the capturing camera.
            confidence: Confidence score of the detection.
            target_override: Optional phone number override.

        Returns:
            True if alert was sent (or logged in DRY_RUN), False on error.
        """
        loc = location or get_camera_location()
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

        # Official SOS Intelligence SMS Format (Requirement 5)
        # 🚨 POSSIBLE EMERGENCY
        # SOS hand signal detected
        # Time: [TIME]
        # Camera: [CAMERA ID]
        # Location: [LOCATION]
        # Confidence: [CONFIDENCE]
        # Map: [SECURE MAP LINK]
        # Please check immediately.
        message_body = (
            "🚨 POSSIBLE EMERGENCY\n"
            "SOS hand signal detected\n"
            f"Time: {now_str}\n"
            f"Camera: {camera_id}\n"
            f"Location: {loc.address}\n"
            f"Confidence: {int(confidence * 100)}%\n"
            f"Map: {loc.maps_url}\n"
            "Please check immediately."
        )
        if snapshot_filename:
            message_body += f"\nEvidence Snapshot: {snapshot_filename}"

        target_number = (target_override or self.recipient_phone).strip()
        clean_target = "".join(filter(str.isdigit, target_number))

        # ----------------------------------------------------------------------
        # 1. SAFETY & COMPLIANCE CHECKS
        # ----------------------------------------------------------------------
        if clean_target in FORBIDDEN_EMERGENCY_NUMBERS:
            logger.critical(
                "BLOCKED: Attempted to send automated alert to emergency services (%s)! "
                "Automated emergency calls are illegal.",
                target_number,
            )
            return False

        if not target_number:
            logger.error("Recipient phone is empty! Cannot dispatch alert.")
            return False

        # ----------------------------------------------------------------------
        # 2. DRY RUN SIMULATION (Testing without spending credits)
        # ----------------------------------------------------------------------
        if self.dry_run:
            logger.info("=" * 60)
            logger.info(">>> DRY RUN ALERT (No SMS sent, saving credits) <<<")
            logger.info("TO: %s", target_number)
            logger.info("FROM: %s (Simulated)", self.from_phone or "TWILIO_DEMO")
            logger.info("MESSAGE:\n%s", message_body)
            logger.info("=" * 60)
            return True

        # ----------------------------------------------------------------------
        # 3. LIVE TWILIO API DISPATCH
        # ----------------------------------------------------------------------
        if not self._client:
            logger.error("Twilio client is not initialized. Cannot send live SMS.")
            return False

        try:
            logger.info("Dispatching live SMS to %s via Twilio...", target_number)
            message = self._client.messages.create(
                body=message_body,
                from_=self.from_phone,
                to=target_number,
            )
            logger.info("SMS delivered successfully! Twilio SID: %s", message.sid)
            return True
        except TwilioRestException as te:
            logger.error("Twilio REST error occurred: %s (Code: %s)", te.msg, te.code)
            return False
        except Exception as e:
            logger.error("Unexpected error sending Twilio SMS: %s", e)
            return False

    def send_emergency_broadcast(
        self,
        camera_id: str,
        location: Optional[LocationInfo] = None,
        confidence: float = 0.96,
        snapshot_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Broadcasts SOS alert to all verified emergency contacts registered in the system."""
        import database
        contacts = database.get_verified_contacts()
        if not contacts:
            # Fallback to configured recipient
            success = self.send_distress_alert(
                location=location,
                snapshot_filename=snapshot_filename,
                camera_id=camera_id,
                confidence=confidence,
            )
            return {"total_sent": 1 if success else 0, "contacts": [self.recipient_phone]}

        dispatched_count = 0
        contact_numbers = []
        for c in contacts:
            phone = c["phone"]
            contact_numbers.append(phone)
            ok = self.send_distress_alert(
                location=location,
                snapshot_filename=snapshot_filename,
                camera_id=camera_id,
                confidence=confidence,
                target_override=phone,
            )
            if ok:
                dispatched_count += 1

        return {
            "total_sent": dispatched_count,
            "total_contacts": len(contacts),
            "contacts": contact_numbers,
        }

    def send_otp_sms(self, phone: str, otp_code: str) -> bool:
        """Sends OTP verification code to a newly registered emergency contact."""
        target_number = phone.strip()
        body = (
            f"🛡️ Smart AI Safety Camera Verification Code: {otp_code}\n"
            f"Enter this code in your security console to activate emergency distress alerts."
        )
        if self.dry_run:
            logger.info("=" * 60)
            logger.info(">>> DRY RUN OTP SMS (Simulated) <<<")
            logger.info("TO: %s", target_number)
            logger.info("OTP CODE: %s", otp_code)
            logger.info("=" * 60)
            return True

        if not self._client:
            logger.warning("Twilio not configured for live OTP. DRY RUN fallback.")
            return True

        try:
            self._client.messages.create(body=body, from_=self.from_phone, to=target_number)
            return True
        except Exception as e:
            logger.error("Failed to send OTP SMS: %s", e)
            return False
