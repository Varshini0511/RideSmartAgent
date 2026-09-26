"""Namma Yatri provider — navigates nammayatri.in via deep link and extracts prices.

Namma Yatri is open-source (ONDC/Beckn protocol), so its web interface
is relatively stable and the most automation-friendly of the four.
"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Browser, Page

from ride_smart.models import Location, ProviderName, RideQuote, RideType
from ride_smart.providers.base import RideProvider

logger = logging.getLogger(__name__)


class NammaYatriProvider(RideProvider):
    name = ProviderName.NAMMA_YATRI
    base_url = "https://nammayatri.in"

    # Stats-page keywords that indicate we landed on the wrong page
    _STATS_KEYWORDS = ("completed trips", "online drivers", "drivers' earnings",
                       "registered users", "enabled drivers", "public services",
                       "open data", "all time", "on-going trips")

    async def fetch_quotes(
        self, browser: Browser, pickup: Location, dropoff: Location
    ) -> list[RideQuote]:
        from ride_smart.fare_estimator import estimate_namma_yatri

        quotes = estimate_namma_yatri(pickup, dropoff)
        if quotes:
            logger.info(f"Namma Yatri: estimated {len(quotes)} fare(s) from distance")
        else:
            logger.info("Namma Yatri: could not estimate (missing coordinates)")
        return quotes

    def _parse_quotes(self, page_text: str) -> list[RideQuote]:
        quotes: list[RideQuote] = []
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]

        for i, line in enumerate(lines):
            prices = self.extract_prices_from_text(line)
            if not prices:
                continue

            context = " ".join(lines[max(0, i - 5) : i + 1]).lower()

            # Skip lines that look like stats, not ride fares
            if any(kw in context for kw in ("cr", "lakh", "users", "trips", "drivers")):
                continue

            ride_type = self._classify(context)
            vehicle = self._vehicle_name(context)

            for price in prices:
                if price < 20 or price > 5000:
                    continue
                quotes.append(RideQuote(
                    provider=ProviderName.NAMMA_YATRI,
                    ride_type=ride_type,
                    price=price,
                    vehicle_type=vehicle,
                ))

        return self._deduplicate(quotes)

    async def _scrape_ride_cards(self, page: Page) -> list[RideQuote]:
        quotes: list[RideQuote] = []
        selectors = [
            '[class*="ride-option"]',
            '[class*="estimate"]',
            '[class*="service"]',
            '[class*="vehicle-card"]',
            '[class*="fare"]',
        ]
        for sel in selectors:
            els = page.locator(sel)
            count = await els.count()
            if count == 0:
                continue
            for i in range(min(count, 10)):
                try:
                    text = await els.nth(i).inner_text()
                    prices = self.extract_prices_from_text(text)
                    if prices:
                        ride_type = self._classify(text.lower())
                        vehicle = self._vehicle_name(text.lower())
                        quotes.append(RideQuote(
                            provider=ProviderName.NAMMA_YATRI,
                            ride_type=ride_type,
                            price=prices[0],
                            vehicle_type=vehicle,
                        ))
                except Exception:
                    continue
            if quotes:
                break

        return self._deduplicate(quotes)

    @staticmethod
    def _classify(text: str) -> RideType:
        if any(kw in text for kw in ("auto", "rick", "three wheel")):
            return RideType.AUTO
        return RideType.CAB

    @staticmethod
    def _vehicle_name(text: str) -> str:
        for label in ("auto", "cab", "sedan", "suv", "hatchback",
                       "non-ac", "ac cab", "book any", "ac auto"):
            if label in text:
                return "Namma Yatri " + label.title()
        return "Namma Yatri"

    @staticmethod
    def _deduplicate(quotes: list[RideQuote]) -> list[RideQuote]:
        seen: set[float] = set()
        result = []
        for q in quotes:
            if q.price not in seen:
                seen.add(q.price)
                result.append(q)
        return result

    async def initiate_booking(self, browser: Browser, quote: RideQuote) -> str:
        page = await self._ensure_page(browser)
        for sel in ('button:has-text("Book")', 'button:has-text("Confirm")',
                     'button:has-text("Request")'):
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click()
                break
        return page.url

    async def check_booking_status(self, browser: Browser) -> str:
        page = await self._ensure_page(browser)
        text = (await self._get_full_page_text(page)).lower()
        if any(kw in text for kw in ("arriving", "driver", "otp", "ride confirmed")):
            return "confirmed"
        if any(kw in text for kw in ("no driver", "unavailable", "try again")):
            return "failed"
        return "searching"

    def get_deep_link(self, pickup: Location, dropoff: Location) -> str:
        # Namma Yatri is app-only; use their app deep link scheme
        if pickup.has_coords and dropoff.has_coords:
            return (
                f"https://nammayatri.in/ridebook"
                f"?srcLat={pickup.latitude}&srcLon={pickup.longitude}"
                f"&destLat={dropoff.latitude}&destLon={dropoff.longitude}"
            )
        return "https://nammayatri.in"
