"""Geocode addresses to lat/lng for deep links and map display."""

from __future__ import annotations

import logging

from geopy.geocoders import GoogleV3, Nominatim

from ride_smart.config import get_settings
from ride_smart.models import Location

logger = logging.getLogger(__name__)


def geocode(address: str) -> Location:
    """Convert an address string to a Location with coordinates.

    Tries Google Maps API first (if key is set), falls back to
    OpenStreetMap's Nominatim (free, no key required).
    """
    settings = get_settings()
    full_address = f"{address}, {settings.default_city}, India"

    if settings.google_maps_api_key:
        try:
            geo = GoogleV3(api_key=settings.google_maps_api_key)
            result = geo.geocode(full_address)
            if result:
                return Location(
                    address=address,
                    latitude=result.latitude,
                    longitude=result.longitude,
                )
        except Exception as e:
            logger.warning(f"Google geocoding failed: {e}")

    try:
        geo = Nominatim(user_agent="ride_smart_agent")
        result = geo.geocode(full_address)
        if result:
            return Location(
                address=address,
                latitude=result.latitude,
                longitude=result.longitude,
            )
    except Exception as e:
        logger.warning(f"Nominatim geocoding failed: {e}")

    return Location(address=address)
