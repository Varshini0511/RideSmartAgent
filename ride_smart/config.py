"""Configuration for RideSmartAgent."""

from __future__ import annotations

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class RideSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Price threshold: if cheapest cab exceeds this, switch to auto
    cab_price_threshold: float = Field(380.0, alias="CAB_PRICE_THRESHOLD")

    # Booking timeout: seconds to wait before considering a booking stuck
    booking_timeout: int = Field(120, alias="BOOKING_TIMEOUT")

    # Seconds to wait for price quotes from each provider
    quote_timeout: int = Field(60, alias="QUOTE_TIMEOUT")

    # Max booking attempts before giving up entirely
    max_booking_attempts: int = Field(4, alias="MAX_BOOKING_ATTEMPTS")

    # Playwright settings
    headless: bool = Field(True, alias="HEADLESS_BROWSER")
    browser_type: str = Field("chromium", alias="BROWSER_TYPE")

    # User data dirs for persistent login sessions per provider
    user_data_dir: str = Field("browser_sessions", alias="USER_DATA_DIR")

    # Google API key for Places/Geocoding (optional, falls back to Nominatim)
    google_maps_api_key: str = Field(
        "", validation_alias="GOOGLE_API_KEY",
    )

    # Default city (for better geocoding results)
    default_city: str = Field("Bengaluru", alias="DEFAULT_CITY")

    # Logging
    log_level: str = Field("INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> RideSettings:
    return RideSettings()
