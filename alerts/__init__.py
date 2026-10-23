"""Alerts package for Smart AI Safety Camera."""

from alerts.location import LocationInfo, get_camera_location
from alerts.sms import SMSAlertSender

__all__ = ["LocationInfo", "get_camera_location", "SMSAlertSender"]
