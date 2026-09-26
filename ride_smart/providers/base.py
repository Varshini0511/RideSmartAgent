"""Abstract base class for ride-hailing providers."""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page

from ride_smart.config import get_settings
from ride_smart.models import Location, ProviderName, RideQuote

logger = logging.getLogger(__name__)

PRICE_RE = re.compile(r'₹\s*([\d,]+(?:\.\d{1,2})?)')


class RideProvider(ABC):
    """Base class every ride provider must implement.

    Each provider manages its own Playwright browser context with a
    persistent login session so the user only needs to log in once.
    """

    name: ProviderName
    base_url: str

    def __init__(self) -> None:
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def session_dir(self) -> Path:
        settings = get_settings()
        path = Path(settings.user_data_dir) / self.name.value
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _ensure_context(self, browser: Browser) -> BrowserContext:
        if self._context is None:
            self._context = await browser.new_context(
                storage_state=self._load_session(),
                viewport={"width": 414, "height": 896},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                user_agent=(
                    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Mobile Safari/537.36"
                ),
            )
        return self._context

    async def _ensure_page(self, browser: Browser) -> Page:
        if self._page is None or self._page.is_closed():
            ctx = await self._ensure_context(browser)
            self._page = await ctx.new_page()
        return self._page

    def _load_session(self) -> str | None:
        session_file = self.session_dir / "state.json"
        if session_file.exists():
            return str(session_file)
        return None

    async def save_session(self) -> None:
        if self._context:
            session_file = self.session_dir / "state.json"
            await self._context.storage_state(path=str(session_file))
            logger.info(f"Saved session for {self.name.value}")

    @abstractmethod
    async def fetch_quotes(
        self, browser: Browser, pickup: Location, dropoff: Location
    ) -> list[RideQuote]:
        """Fetch all available ride quotes (cab + auto) for this route."""

    @abstractmethod
    async def initiate_booking(
        self, browser: Browser, quote: RideQuote
    ) -> str:
        """Start the booking flow. Returns a booking URL or deep link."""

    @abstractmethod
    async def check_booking_status(self, browser: Browser) -> str:
        """Returns one of: 'confirmed', 'searching', 'failed'."""

    @abstractmethod
    def get_deep_link(self, pickup: Location, dropoff: Location) -> str:
        """Return a deep link / URL with the route pre-filled."""

    async def cleanup(self) -> None:
        if self._page and not self._page.is_closed():
            await self._page.close()
        if self._context:
            await self.save_session()
            await self._context.close()
        self._page = None
        self._context = None

    async def safe_fetch_quotes(
        self, browser: Browser, pickup: Location, dropoff: Location
    ) -> list[RideQuote]:
        try:
            settings = get_settings()
            quotes = await asyncio.wait_for(
                self.fetch_quotes(browser, pickup, dropoff),
                timeout=settings.quote_timeout,
            )
            logger.info(f"{self.name.value}: got {len(quotes)} quotes")
            return quotes
        except asyncio.TimeoutError:
            logger.warning(f"{self.name.value}: timed out fetching quotes")
            return []
        except Exception as e:
            logger.error(f"{self.name.value}: error fetching quotes: {e}")
            return []

    # ── Shared helpers ──────────────────────────────────────────────

    @staticmethod
    def extract_prices_from_text(text: str) -> list[float]:
        """Find all ₹XXX prices in a block of text."""
        matches = PRICE_RE.findall(text)
        return [float(m.replace(",", "")) for m in matches]

    async def _get_full_page_text(self, page: Page) -> str:
        """Extract all visible text from the page."""
        try:
            return await page.inner_text("body")
        except Exception:
            return await page.evaluate("() => document.body?.innerText || ''")

    async def _wait_for_prices(self, page: Page, timeout_ms: int = 15000) -> str:
        """Wait until at least one ₹ price appears on the page."""
        try:
            await page.wait_for_function(
                "() => (document.body?.innerText || '').includes('₹')",
                timeout=timeout_ms,
            )
        except Exception:
            logger.debug(f"{self.name.value}: no ₹ prices appeared within timeout")
        return await self._get_full_page_text(page)

    async def _screenshot_debug(self, page: Page, label: str) -> None:
        """Save a debug screenshot for troubleshooting."""
        try:
            path = self.session_dir / f"debug_{label}.png"
            await page.screenshot(path=str(path))
            logger.debug(f"{self.name.value}: saved debug screenshot to {path}")
        except Exception:
            pass
