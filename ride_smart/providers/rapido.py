"""Rapido provider — navigates rapido.bike via deep link and extracts prices."""

from __future__ import annotations

import logging
import re

from playwright.async_api import Browser, Page

from ride_smart.models import Location, ProviderName, RideQuote, RideType
from ride_smart.providers.base import RideProvider

logger = logging.getLogger(__name__)


class RapidoProvider(RideProvider):
    name = ProviderName.RAPIDO
    base_url = "https://www.rapido.bike"

    def _parse_quotes(self, page_text: str) -> list[RideQuote]:
        quotes: list[RideQuote] = []
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]

        for i, line in enumerate(lines):
            prices = self.extract_prices_from_text(line)
            if not prices:
                continue

            context = " ".join(lines[max(0, i - 5) : i + 1]).lower()
            ride_type = self._classify(context)
            vehicle = self._vehicle_name(context)

            for price in prices:
                if price < 20 or price > 5000:
                    continue
                quotes.append(RideQuote(
                    provider=ProviderName.RAPIDO,
                    ride_type=ride_type,
                    price=price,
                    vehicle_type=vehicle,
                ))

        return self._deduplicate(quotes)

    async def _scrape_ride_cards(self, page: Page) -> list[RideQuote]:
        quotes: list[RideQuote] = []
        selectors = [
            '[class*="ride-option"]',
            '[class*="service-card"]',
            '[class*="vehicle"]',
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
                            provider=ProviderName.RAPIDO,
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
        if any(kw in text for kw in ("bike", "two wheel", "moto")):
            return RideType.AUTO
        return RideType.CAB

    @staticmethod
    def _vehicle_name(text: str) -> str:
        for label in ("rapido auto", "auto", "rapido bike", "bike",
                       "rapido cab", "cab", "rapido taxi"):
            if label in text:
                return "Rapido " + label.replace("rapido ", "").title()
        return "Rapido"

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
        for sel in ('button:has-text("Book")', 'button:has-text("Confirm")'):
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click()
                break
        return page.url

    async def check_booking_status(self, browser: Browser) -> str:
        page = await self._ensure_page(browser)
        text = (await self._get_full_page_text(page)).lower()
        if any(kw in text for kw in ("arriving", "driver", "otp", "captain")):
            return "confirmed"
        if any(kw in text for kw in ("no captain", "unavailable", "try again")):
            return "failed"
        return "searching"

    # Marketing page keywords — means we didn't land on a ride estimate page
    _MARKETING_KEYWORDS = ("india's #1", "download", "install now",
                           "ride-hailing app", "first ride")

    async def fetch_quotes(
        self, browser: Browser, pickup: Location, dropoff: Location
    ) -> list[RideQuote]:
        from ride_smart.fare_estimator import estimate_rapido

        quotes = estimate_rapido(pickup, dropoff)
        if quotes:
            logger.info(f"Rapido: estimated {len(quotes)} fare(s) from distance")
        else:
            logger.info("Rapido: could not estimate (missing coordinates)")
        return quotes

    def get_deep_link(self, pickup: Location, dropoff: Location) -> str:
        # Rapido's web booking (app-first, but web fallback exists)
        if pickup.has_coords and dropoff.has_coords:
            return (
                f"https://www.rapido.bike/ride-estimate"
                f"?pickupLat={pickup.latitude}&pickupLng={pickup.longitude}"
                f"&dropLat={dropoff.latitude}&dropLng={dropoff.longitude}"
            )
        return "https://www.rapido.bike/"
