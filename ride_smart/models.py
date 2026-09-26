"""Domain models for ride comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RideType(str, Enum):
    CAB = "cab"
    AUTO = "auto"


class BookingStatus(str, Enum):
    PENDING = "pending"
    SEARCHING = "searching"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ProviderName(str, Enum):
    UBER = "uber"
    OLA = "ola"
    RAPIDO = "rapido"
    NAMMA_YATRI = "namma_yatri"


@dataclass
class Location:
    address: str
    latitude: float | None = None
    longitude: float | None = None

    @property
    def has_coords(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass
class RideQuote:
    provider: ProviderName
    ride_type: RideType
    price: float
    currency: str = "INR"
    eta_minutes: int | None = None
    distance_km: float | None = None
    duration_minutes: int | None = None
    surge_multiplier: float = 1.0
    vehicle_type: str = ""
    booking_url: str = ""
    deep_link: str = ""

    @property
    def display_name(self) -> str:
        surge = f" ({self.surge_multiplier}x surge)" if self.surge_multiplier > 1.0 else ""
        return f"{self.provider.value.replace('_', ' ').title()} {self.ride_type.value.title()}{surge}"

    @property
    def is_surge(self) -> bool:
        return self.surge_multiplier > 1.0


@dataclass
class RideComparison:
    pickup: Location
    dropoff: Location
    quotes: list[RideQuote] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def cab_quotes(self) -> list[RideQuote]:
        return sorted(
            [q for q in self.quotes if q.ride_type == RideType.CAB],
            key=lambda q: q.price,
        )

    @property
    def auto_quotes(self) -> list[RideQuote]:
        return sorted(
            [q for q in self.quotes if q.ride_type == RideType.AUTO],
            key=lambda q: q.price,
        )

    @property
    def all_sorted(self) -> list[RideQuote]:
        return sorted(self.quotes, key=lambda q: q.price)

    @property
    def cheapest_cab(self) -> RideQuote | None:
        cabs = self.cab_quotes
        return cabs[0] if cabs else None

    @property
    def cheapest_auto(self) -> RideQuote | None:
        autos = self.auto_quotes
        return autos[0] if autos else None


@dataclass
class BookingAttempt:
    quote: RideQuote
    status: BookingStatus = BookingStatus.PENDING
    driver_name: str = ""
    driver_phone: str = ""
    vehicle_number: str = ""
    wait_seconds: int = 0
    failure_reason: str = ""


@dataclass
class BookingResult:
    attempts: list[BookingAttempt] = field(default_factory=list)
    final: BookingAttempt | None = None

    @property
    def is_booked(self) -> bool:
        return self.final is not None and self.final.status == BookingStatus.CONFIRMED

    def add_attempt(self, attempt: BookingAttempt) -> None:
        self.attempts.append(attempt)
        if attempt.status == BookingStatus.CONFIRMED:
            self.final = attempt
