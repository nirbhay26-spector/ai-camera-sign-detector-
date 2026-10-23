"""
Location & Google Maps Integration Module.
==========================================
This module resolves camera coordinates and formats Google Maps links
for inclusion in emergency alert SMS messages.

For first-year CSE students:
----------------------------
In Version 1, each fixed camera has a configured physical street address
and latitude/longitude in `.env`.
In future versions (e.g., mobile camera or drone), the `get_current_location()`
function can easily read live GPS coordinates from a serial GPS dongle or phone API.
"""

from dataclasses import dataclass
from typing import Optional
import config


@dataclass
class LocationInfo:
    """Represents the physical location and intelligence metadata of the camera."""

    name: str
    address: str
    latitude: float
    longitude: float
    maps_url: str
    organization: str = "Public Safety & Municipal Surveillance Division"
    installation_location: str = "Main Entrance Overhead Pole 1"
    zone: str = "Zone A - Main Campus"
    camera_id: str = "CAM-01"


def get_camera_location(
    name: Optional[str] = None,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    organization: Optional[str] = None,
    installation_location: Optional[str] = None,
    zone: Optional[str] = None,
    camera_id: str = "CAM-01",
) -> LocationInfo:
    """Builds a standardized LocationInfo object with a clickable Google Maps link.

    Args:
        name: Human-friendly location label.
        address: Postal / street address.
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        organization: Managing public safety agency or building authority.
        installation_location: Specific physical spot (e.g. 'Pole 4 North').
        zone: Operational security sector/zone.
        camera_id: Unique hardware identifier.

    Returns:
        LocationInfo containing the address and Google Maps query link.
    """
    loc_name = name or config.CAMERA_LOCATION_NAME
    loc_address = address or config.CAMERA_LOCATION_ADDRESS
    loc_lat = lat if lat is not None else config.CAMERA_LATITUDE
    loc_lon = lon if lon is not None else config.CAMERA_LONGITUDE

    maps_url = f"https://www.google.com/maps/search/?api=1&query={loc_lat:.6f},{loc_lon:.6f}"

    return LocationInfo(
        name=loc_name,
        address=loc_address,
        latitude=loc_lat,
        longitude=loc_lon,
        maps_url=maps_url,
        organization=organization or config.DEFAULT_ORGANIZATION,
        installation_location=installation_location or "Overhead Surveillance Mount",
        zone=zone or "Zone A - Campus Grid",
        camera_id=camera_id,
    )


def get_camera_location_by_id(camera_id: str) -> LocationInfo:
    """Looks up camera location intelligence from the database."""
    import database
    cams = {c["id"]: c for c in database.get_all_cameras()}
    if camera_id in cams:
        c = cams[camera_id]
        return get_camera_location(
            name=c.get("name"),
            address=f"{c.get('name')}, {c.get('city')}, India",
            lat=c.get("latitude"),
            lon=c.get("longitude"),
            organization=c.get("organization"),
            installation_location=c.get("installation_location"),
            zone=c.get("zone"),
            camera_id=camera_id,
        )
    return get_camera_location(camera_id=camera_id)


# ---------------------------------------------------------------------------
# FUTURE EXPANSION STUB (Version 4: Live Hardware GPS / Phone GPS)
# ---------------------------------------------------------------------------
def get_live_gps_coordinates() -> Optional[tuple]:
    """Stub for reading live coordinates from a USB/NMEA GPS module.

    To implement:
      import serial
      Read $GPGGA strings from /dev/ttyUSB0 and parse lat/lon.
    """
    # Currently returns None, falling back to fixed camera coordinates in config
    return None
