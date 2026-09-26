"""Booking orchestrator — tries cheapest option, falls back on failure/timeout."""

from __future__ import annotations

import asyncio
import logging
import time

from playwright.async_api import Browser, async_playwright

from ride_smart.comparator import RideRecommendation, recommend
from ride_smart.config import get_settings
from ride_smart.geocoder import geocode
from ride_smart.models import (
    BookingAttempt,
    BookingResult,
    BookingStatus,
    Location,
    RideComparison,
    RideQuote,
)
from ride_smart.providers import get_providers
from ride_smart.providers.base import RideProvider

logger = logging.getLogger(__name__)


class RideOrchestrator:
    """Coordinates the full flow: fetch quotes -> compare -> book."""

    def __init__(self) -> None:
        self.providers = get_providers()
        self._provider_map = {p.name: p for p in self.providers}
        self._browser: Browser | None = None

    async def __aenter__(self):
        settings = get_settings()
        pw = await async_playwright().start()
        self._pw = pw
        try:
            self._browser = await pw.chromium.launch(
                headless=settings.headless,
            )
        except Exception:
            # Visible browser can fail on Windows in some contexts;
            # fall back to headless automatically.
            logger.warning("Visible browser launch failed, retrying headless")
            self._browser = await pw.chromium.launch(headless=True)
        return self

    async def __aexit__(self, *exc):
        for p in self.providers:
            await p.cleanup()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def fetch_all_quotes(
        self, pickup: Location, dropoff: Location
    ) -> RideComparison:
        """Query all providers in parallel and collect quotes."""
        comparison = RideComparison(pickup=pickup, dropoff=dropoff)

        tasks = [
            provider.safe_fetch_quotes(self._browser, pickup, dropoff)
            for provider in self.providers
        ]
        results = await asyncio.gather(*tasks)

        for provider, quotes in zip(self.providers, results):
            if quotes:
                comparison.quotes.extend(quotes)
            else:
                comparison.errors[provider.name.value] = "No quotes returned"

        logger.info(
            f"Got {len(comparison.quotes)} total quotes, "
            f"{len(comparison.errors)} provider errors"
        )
        return comparison

    async def find_best_ride(
        self, pickup_addr: str, dropoff_addr: str
    ) -> tuple[RideComparison, RideRecommendation]:
        """Full comparison flow: geocode -> fetch quotes -> recommend."""
        pickup = geocode(pickup_addr)
        dropoff = geocode(dropoff_addr)
        logger.info(f"Route: {pickup.address} -> {dropoff.address}")

        comparison = await self.fetch_all_quotes(pickup, dropoff)
        recommendation = recommend(comparison)
        return comparison, recommendation

    async def book_with_fallback(
        self, recommendation: RideRecommendation
    ) -> BookingResult:
        """Try booking the top pick; on timeout/failure, fall back to the
        next option. Continues until a booking confirms or all options
        are exhausted."""
        settings = get_settings()
        result = BookingResult()
        max_attempts = min(
            settings.max_booking_attempts,
            len(recommendation.ranked_options),
        )

        for i in range(max_attempts):
            quote = recommendation.ranked_options[i]
            provider = self._provider_map.get(quote.provider)
            if not provider:
                continue

            logger.info(
                f"Attempt {i + 1}/{max_attempts}: "
                f"booking {quote.display_name} at ₹{quote.price:.0f}"
            )

            attempt = await self._try_booking(
                provider, quote, settings.booking_timeout
            )
            result.add_attempt(attempt)

            if attempt.status == BookingStatus.CONFIRMED:
                logger.info(f"Booking confirmed: {quote.display_name}")
                break

            logger.warning(
                f"{quote.display_name} failed ({attempt.status.value}): "
                f"{attempt.failure_reason}. Trying next option..."
            )

        if not result.is_booked:
            logger.error("All booking attempts failed.")

        return result

    async def _try_booking(
        self, provider: RideProvider, quote: RideQuote, timeout: int
    ) -> BookingAttempt:
        attempt = BookingAttempt(quote=quote, status=BookingStatus.SEARCHING)

        try:
            await provider.initiate_booking(self._browser, quote)
        except Exception as e:
            attempt.status = BookingStatus.FAILED
            attempt.failure_reason = f"Could not initiate booking: {e}"
            return attempt

        start = time.monotonic()
        poll_interval = 5

        while time.monotonic() - start < timeout:
            try:
                status = await provider.check_booking_status(self._browser)
            except Exception:
                status = "searching"

            attempt.wait_seconds = int(time.monotonic() - start)

            if status == "confirmed":
                attempt.status = BookingStatus.CONFIRMED
                return attempt
            if status == "failed":
                attempt.status = BookingStatus.FAILED
                attempt.failure_reason = "Provider reported no drivers/unavailable"
                return attempt

            await asyncio.sleep(poll_interval)

        attempt.status = BookingStatus.TIMEOUT
        attempt.failure_reason = f"No confirmation after {timeout}s"
        return attempt


async def run_race_booking(
    pickup: Location,
    dropoff: Location,
    candidates: list[RideQuote],
    price_range: float = 50.0,
    status_callback=None,
) -> dict:
    """Try booking similar-priced rides across providers simultaneously.

    Picks the cheapest option per provider (within *price_range* of the
    overall best).  Opens browser sessions for each, navigates to the
    provider's page, selects the ride type, clicks book, and polls.
    First confirmed booking wins — others are abandoned.
    """
    if not candidates:
        return {"status": "failed", "reason": "No rides to book"}

    best_price = candidates[0].price
    eligible = [q for q in candidates if q.price <= best_price + price_range]

    per_provider: dict[ProviderName, RideQuote] = {}
    for q in eligible:
        if q.provider not in per_provider:
            per_provider[q.provider] = q

    if not per_provider:
        return {"status": "failed", "reason": "No eligible providers"}

    def _report(msg: str):
        logger.info(msg)
        if status_callback:
            status_callback(msg)

    settings = get_settings()

    # Track what happened to each provider
    provider_status: dict[str, dict] = {
        p.value: {"name": p.value.replace("_", " ").title(),
                  "price": q.price,
                  "vehicle": q.vehicle_type,
                  "result": "pending"}
        for p, q in per_provider.items()
    }

    async with RideOrchestrator() as orch:
        active: dict[ProviderName, tuple[RideProvider, RideQuote]] = {}

        _report(f"Opening {len(per_provider)} provider(s): "
                + ", ".join(p.value.title() for p in per_provider))

        for prov_name, quote in per_provider.items():
            provider = orch._provider_map.get(prov_name)
            if not provider:
                provider_status[prov_name.value]["result"] = "not available"
                continue
            try:
                if hasattr(provider, "prepare_for_booking"):
                    await provider.prepare_for_booking(
                        orch._browser, pickup, dropoff
                    )
                else:
                    page = await provider._ensure_page(orch._browser)
                    deep_link = provider.get_deep_link(pickup, dropoff)
                    await page.goto(deep_link, wait_until="domcontentloaded")
                    await page.wait_for_timeout(5000)

                active[prov_name] = (provider, quote)
                provider_status[prov_name.value]["result"] = "page ready"
                _report(f"  ✓ {prov_name.value.title()} page ready")
            except Exception as e:
                provider_status[prov_name.value]["result"] = f"failed to open: {e}"
                _report(f"  ✗ {prov_name.value.title()}: {e}")

        if not active:
            return {"status": "failed", "reason": "Could not open any provider",
                    "provider_status": provider_status}

        _report("Selecting ride types and initiating booking…")

        for prov_name, (provider, quote) in active.items():
            try:
                await provider.initiate_booking(orch._browser, quote)
                provider_status[prov_name.value]["result"] = "booking initiated"
                _report(f"  🚀 {prov_name.value.title()}: booking initiated (₹{quote.price:.0f})")
            except Exception as e:
                provider_status[prov_name.value]["result"] = f"booking failed: {e}"
                _report(f"  ✗ {prov_name.value.title()} booking failed: {e}")

        _report("Waiting for driver confirmation…")

        timeout = settings.booking_timeout
        start = time.monotonic()

        while time.monotonic() - start < timeout and active:
            failed_names: list[ProviderName] = []

            for prov_name, (provider, quote) in list(active.items()):
                try:
                    status = await provider.check_booking_status(orch._browser)
                except Exception:
                    status = "searching"

                if status == "confirmed":
                    wait = int(time.monotonic() - start)
                    provider_status[prov_name.value]["result"] = "booked"
                    _report(
                        f"🎉 {prov_name.value.title()} confirmed in {wait}s! "
                        "Cancelling others…"
                    )
                    for other_name, (other_prov, _) in active.items():
                        if other_name != prov_name:
                            provider_status[other_name.value]["result"] = "cancelled"
                            try:
                                await other_prov.cleanup()
                            except Exception:
                                pass
                    return {
                        "status": "confirmed",
                        "provider": prov_name.value,
                        "vehicle_type": quote.vehicle_type,
                        "price": quote.price,
                        "wait_seconds": wait,
                        "provider_status": provider_status,
                    }

                if status == "failed":
                    provider_status[prov_name.value]["result"] = "no drivers"
                    _report(f"  ✗ {prov_name.value.title()}: no drivers")
                    failed_names.append(prov_name)

            for name in failed_names:
                active.pop(name, None)

            await asyncio.sleep(3)

        for prov_name in active:
            provider_status[prov_name.value]["result"] = "timed out"

        return {
            "status": "timeout" if active else "failed",
            "reason": (
                f"No driver confirmed within {settings.booking_timeout}s"
                if active
                else "All providers failed to find drivers"
            ),
            "tried": [n.value for n in per_provider],
            "provider_status": provider_status,
        }


async def run_full_flow(
    pickup: str | Location,
    dropoff: str | Location,
    auto_book: bool = False,
) -> dict:
    """End-to-end flow callable from the CLI or Streamlit UI.

    Accepts address strings (will geocode) or Location objects (used directly).
    Returns a dict with comparison, recommendation, and optionally
    booking result.
    """
    async with RideOrchestrator() as orch:
        pickup_loc = geocode(pickup) if isinstance(pickup, str) else pickup
        dropoff_loc = geocode(dropoff) if isinstance(dropoff, str) else dropoff
        logger.info(f"Route: {pickup_loc.address} -> {dropoff_loc.address}")

        comparison = await orch.fetch_all_quotes(pickup_loc, dropoff_loc)
        recommendation = recommend(comparison)

        output = {
            "comparison": comparison,
            "recommendation": recommendation,
            "booking": None,
        }

        if auto_book and recommendation.top_pick:
            booking = await orch.book_with_fallback(recommendation)
            output["booking"] = booking

        return output
