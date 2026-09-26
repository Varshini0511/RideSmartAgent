"""Fare estimation for app-only providers (Rapido, Namma Yatri).

Uses straight-line distance × road factor to approximate fares
based on published fare structures.
"""

from __future__ import annotations

import math

from ride_smart.models import Location, ProviderName, RideQuote, RideType

ROAD_FACTOR = 1.4  # straight-line → road distance multiplier


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_distance_km(pickup: Location, dropoff: Location) -> float | None:
    if not (pickup.has_coords and dropoff.has_coords):
        return None
    straight = _haversine_km(
        pickup.latitude, pickup.longitude,
        dropoff.latitude, dropoff.longitude,
    )
    return round(straight * ROAD_FACTOR, 1)


# ── Fare structures (Chennai, Sep 2026) ──────────────────────────
# Adjust these when rates change.

RAPIDO_FARES = [
    {
        "name": "Rapido Bike",
        "type": RideType.AUTO,
        "base": 15,
        "per_km": 5,
        "min_fare": 25,
    },
    {
        "name": "Rapido Auto",
        "type": RideType.AUTO,
        "base": 30,
        "per_km": 10,
        "min_fare": 40,
    },
]

NAMMA_YATRI_FARES = [
    {
        "name": "Namma Yatri Auto",
        "type": RideType.AUTO,
        "base": 25,
        "per_km": 15,
        "min_km": 1.8,
        "per_km_after": 12,
        "min_fare": 30,
    },
]


def estimate_rapido(pickup: Location, dropoff: Location) -> list[RideQuote]:
    dist = estimate_distance_km(pickup, dropoff)
    if dist is None:
        return []

    quotes = []
    for fare in RAPIDO_FARES:
        price = fare["base"] + fare["per_km"] * dist
        price = max(price, fare["min_fare"])
        quotes.append(RideQuote(
            provider=ProviderName.RAPIDO,
            ride_type=fare["type"],
            price=round(price),
            vehicle_type=fare["name"],
            distance_km=dist,
        ))
    return quotes


def estimate_namma_yatri(pickup: Location, dropoff: Location) -> list[RideQuote]:
    dist = estimate_distance_km(pickup, dropoff)
    if dist is None:
        return []

    quotes = []
    for fare in NAMMA_YATRI_FARES:
        min_km = fare.get("min_km", 0)
        if dist <= min_km:
            price = fare["base"]
        else:
            price = fare["base"] + fare["per_km"] * min_km
            price += fare.get("per_km_after", fare["per_km"]) * (dist - min_km)
        price = max(price, fare["min_fare"])
        quotes.append(RideQuote(
            provider=ProviderName.NAMMA_YATRI,
            ride_type=fare["type"],
            price=round(price),
            vehicle_type=fare["name"],
            distance_km=dist,
        ))
    return quotes
