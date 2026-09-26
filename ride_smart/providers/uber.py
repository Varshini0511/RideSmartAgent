"""Uber provider — navigates m.uber.com via deep link and extracts prices."""

from __future__ import annotations

import logging
import re

from playwright.async_api import Browser, Page

from ride_smart.models import Location, ProviderName, RideQuote, RideType
from ride_smart.providers.base import RideProvider

logger = logging.getLogger(__name__)


class UberProvider(RideProvider):
    name = ProviderName.UBER
    base_url = "https://m.uber.com"

    async def fetch_quotes(
        self, browser: Browser, pickup: Location, dropoff: Location
    ) -> list[RideQuote]:
        page = await self._ensure_page(browser)

        try:
            await page.goto("https://m.uber.com", wait_until="domcontentloaded")
        except Exception:
            logger.warning("Uber: failed to load m.uber.com")
            return []

        await page.wait_for_timeout(4000)
        await self._dismiss_app_banner(page)

        route_set = await self._enter_route(page, pickup, dropoff)
        if not route_set:
            await self._screenshot_debug(page, "no_route")
            return []

        text = await self._wait_for_prices(page, timeout_ms=20000)
        await self._screenshot_debug(page, "quotes")

        quotes = await self._scrape_ride_cards_dom(page)
        if not quotes:
            quotes = self._parse_quotes(text)
        if not quotes:
            quotes = await self._scrape_ride_cards(page)

        return quotes

    async def _dismiss_app_banner(self, page: Page) -> None:
        """Dismiss 'open in app' or cookie banners."""
        try:
            for sel in (
                'button:has-text("Continue")',
                'button:has-text("Not now")',
                'button:has-text("Stay on web")',
                '[data-testid="cookie-banner"] button',
                'button[aria-label="Close"]',
            ):
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(500)
                    break
        except Exception:
            pass

    async def _enter_route(self, page: Page, pickup: Location, dropoff: Location) -> bool:
        """Enter pickup and dropoff through Uber's mobile web UI.

        Returns True if the route was successfully entered.
        """
        try:
            url = page.url
            if "/go/" in url or "product-selection" in url:
                page_text = await self._get_full_page_text(page)
                if '₹' in page_text and not any(kw in page_text.lower() for kw in (
                    "enter pickup location", "ride as you like",
                    "more ways to use uber", "your day, your way",
                )):
                    return True

            await self._screenshot_debug(page, "before_pickup")

            pickup_clicked = await self._click_element(page, [
                page.get_by_text("Enter pickup location"),
                page.get_by_placeholder("Enter pickup location"),
                page.locator('[data-testid="pickup-input"]'),
                page.locator('input[placeholder*="pickup" i]'),
                page.locator('[class*="SearchInput"]'),
                page.locator('[class*="search-input"]'),
            ])

            if not pickup_clicked:
                pickup_clicked = await page.evaluate("""() => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        const text = (el.textContent || '').trim();
                        if (text === 'Enter pickup location' ||
                            (el.placeholder && el.placeholder.toLowerCase().includes('pickup'))) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if pickup_clicked:
                    await page.wait_for_timeout(1000)

            if not pickup_clicked:
                logger.info("Uber: could not find pickup field, trying Ride button first")
                ride_btn = await self._click_element(page, [
                    page.get_by_text("Ride", exact=True),
                    page.locator('[data-testid*="ride"]'),
                ])
                if ride_btn:
                    await page.wait_for_timeout(2000)
                    pickup_clicked = await self._click_element(page, [
                        page.get_by_text("Enter pickup location"),
                        page.get_by_placeholder("Enter pickup location"),
                        page.locator('input[placeholder*="pickup" i]'),
                    ])

            if not pickup_clicked:
                logger.info("Uber: could not find pickup field")
                return False

            await page.wait_for_timeout(1500)
            await self._screenshot_debug(page, "after_pickup_click")

            # Step 2: Type pickup address in the search input
            if not await self._type_and_select(page, pickup.address):
                logger.info("Uber: could not enter pickup address")
                return False

            await page.wait_for_timeout(2000)
            await self._dismiss_app_banner(page)
            await self._screenshot_debug(page, "after_pickup_select")

            # Step 3: Look for the destination field
            dest_clicked = await self._click_element(page, [
                page.get_by_text("Where to?"),
                page.get_by_placeholder("Where to?"),
                page.get_by_placeholder("Search destination"),
                page.locator('input[placeholder*="Where" i]'),
                page.locator('input[placeholder*="destination" i]'),
                page.locator('[data-testid="destination-input"]'),
            ])

            if not dest_clicked:
                # After pickup, Uber may auto-show destination input
                dest_clicked = await self._click_element(page, [
                    page.locator('input[type="text"]').last,
                    page.locator('input[type="search"]').last,
                ])

            if not dest_clicked:
                logger.info("Uber: could not find destination field")
                return False

            await page.wait_for_timeout(1000)

            # Step 4: Type dropoff address and select suggestion
            if not await self._type_and_select(page, dropoff.address):
                logger.info("Uber: could not enter destination address")
                return False

            await page.wait_for_timeout(3000)
            await self._screenshot_debug(page, "after_dest_select")
            return True

        except Exception as e:
            logger.info(f"Uber: could not enter route: {e}")
            return False

    async def _click_element(self, page: Page, locators: list) -> bool:
        """Try each locator in order, click the first visible one."""
        for loc in locators:
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.click()
                    return True
            except Exception:
                continue
        return False

    async def _type_and_select(self, page: Page, address: str) -> bool:
        """Type an address into the currently focused search field and select a suggestion."""
        try:
            # Find the active/visible text input
            for sel in (
                'input:focus',
                'input[type="text"]',
                'input[type="search"]',
                'input[placeholder*="Search" i]',
                'input[placeholder*="Enter" i]',
                'input[placeholder*="Add" i]',
            ):
                field = page.locator(sel).first
                if await field.count() > 0 and await field.is_visible():
                    await field.fill("")
                    await field.type(address, delay=50)
                    await page.wait_for_timeout(2500)

                    # Click first suggestion from the dropdown
                    for sug_sel in (
                        'li[role="option"]',
                        '[data-testid*="suggestion"]',
                        '[data-testid*="result"]',
                        '[data-baseweb*="menu"] li',
                        '[class*="suggestion"]',
                        '[class*="result"]',
                        'ul[role="listbox"] li',
                        'ul li',
                    ):
                        sug = page.locator(sug_sel).first
                        if await sug.count() > 0 and await sug.is_visible():
                            await sug.click()
                            await page.wait_for_timeout(1500)
                            return True

                    # If no suggestion found, try pressing Enter
                    await field.press("Enter")
                    await page.wait_for_timeout(1500)
                    return True

            logger.info("Uber: no text input found for address entry")
            return False
        except Exception as e:
            logger.debug(f"Uber: _type_and_select failed: {e}")
            return False

    async def _scrape_ride_cards_dom(self, page: Page) -> list[RideQuote]:
        """Primary extraction: read each ride card from the DOM individually.

        Uber renders ride options as <li data-testid="product_selector.list_item">
        inside a listbox. Each card's innerText contains the ride name, price,
        ETA, and description — parsed per-card so nothing bleeds between rides.
        """
        try:
            cards = await page.evaluate("""() => {
                const items = document.querySelectorAll(
                    '[data-testid="product_selector.list_item"]'
                );
                if (!items.length) return [];
                return Array.from(items).map(el => el.innerText);
            }""")
        except Exception:
            return []

        if not cards:
            return []

        quotes: list[RideQuote] = []
        for card_text in cards:
            prices = self.extract_prices_from_text(card_text)
            if not prices:
                continue

            text_lower = card_text.lower()

            # Skip parcel / delivery / promo cards
            if any(kw in text_lower for kw in (
                "parcel", "delivery", "courier", "send packages",
                "intercity", "outstation", "rental",
            )):
                continue

            ride_type = self._classify(text_lower)
            vehicle = self._vehicle_name(text_lower)
            eta = self._extract_eta(text_lower)

            price = prices[0]
            if price < 20 or price > 5000:
                continue

            quotes.append(RideQuote(
                provider=ProviderName.UBER,
                ride_type=ride_type,
                price=price,
                vehicle_type=vehicle,
                eta_minutes=eta,
            ))

        return self._deduplicate(quotes)

    def _parse_quotes(self, page_text: str) -> list[RideQuote]:
        """Parse ride options from the full page text.

        Uber's mobile web shows ride options as blocks with name + price,
        e.g.:
            UberGo
            4 min away
            ₹249
        """
        quotes: list[RideQuote] = []
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]

        for i, line in enumerate(lines):
            prices = self.extract_prices_from_text(line)
            if not prices:
                continue

            # Narrow context (2 lines back) to avoid bleeding keywords
            # from neighboring ride cards
            context = " ".join(lines[max(0, i - 2) : i + 1]).lower()

            # Skip promo/banner text that contains ₹ but isn't a ride price
            promo_keywords = ("% off", "coverage", "delivery", "courier", "parcel", "insure")
            if any(kw in context for kw in promo_keywords):
                continue

            ride_type = self._classify(context)
            vehicle = self._vehicle_name(context)
            eta = self._extract_eta(context)

            for price in prices:
                if price < 20 or price > 5000:
                    continue
                quotes.append(RideQuote(
                    provider=ProviderName.UBER,
                    ride_type=ride_type,
                    price=price,
                    vehicle_type=vehicle,
                    eta_minutes=eta,
                ))

        return self._deduplicate(quotes)

    async def _scrape_ride_cards(self, page: Page) -> list[RideQuote]:
        """Fallback: try to find ride option elements by common patterns."""
        quotes: list[RideQuote] = []
        # Try various selectors that Uber has used
        selectors = [
            '[data-testid*="product"]',
            '[class*="VehicleOption"]',
            '[class*="fare"]',
            'div[role="radio"]',
            'li[role="option"]',
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
                            provider=ProviderName.UBER,
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
        if any(kw in text for kw in ("auto", "tuk", "rick", "three wheel")):
            return RideType.AUTO
        if any(kw in text for kw in ("moto", "bike", "two wheel")):
            return RideType.AUTO
        return RideType.CAB

    @staticmethod
    def _vehicle_name(text: str) -> str:
        for label in ("bike saver", "go sedan", "uber go ac", "go ac",
                       "uber go", "ubergo", "premier xl", "uber premier",
                       "premier", "uber xl", "uberxl", "uber auto",
                       "uber moto", "uber intercity", "uber reserve",
                       "wait & save", "wait and save", "comfort",
                       "bike", "auto"):
            if label in text:
                clean = label.replace("uber ", "").replace("uber", "")
                return "Uber " + (clean or label).strip().title()
        return "Uber Cab"

    @staticmethod
    def _extract_eta(text: str) -> int | None:
        m = re.search(r'(\d+)\s*min', text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _deduplicate(quotes: list[RideQuote]) -> list[RideQuote]:
        seen: set[float] = set()
        result = []
        for q in quotes:
            if q.price not in seen:
                seen.add(q.price)
                result.append(q)
        return result

    async def prepare_for_booking(self, browser: Browser, pickup: Location, dropoff: Location) -> Page:
        """Navigate to deep link, dismiss banners, wait for ride options."""
        page = await self._ensure_page(browser)
        deep = self.get_deep_link(pickup, dropoff)
        await page.goto(deep, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await self._dismiss_app_banner(page)
        await page.wait_for_timeout(5000)
        return page

    async def select_ride_type(self, page: Page, vehicle_type: str) -> bool:
        """Click the matching ride card so it's selected before booking."""
        target = vehicle_type.lower().replace("uber ", "").strip()

        cards = page.locator('[data-testid="product_selector.list_item"]')
        count = await cards.count()
        for i in range(count):
            try:
                card = cards.nth(i)
                text = (await card.inner_text()).lower()
                if target in text:
                    await card.click()
                    await page.wait_for_timeout(1000)
                    logger.info(f"Uber: selected ride type '{target}'")
                    return True
            except Exception:
                continue

        btn = page.get_by_text(vehicle_type, exact=False).first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click()
            await page.wait_for_timeout(1000)
            return True

        logger.debug(f"Uber: could not select ride type '{vehicle_type}'")
        return False

    async def initiate_booking(self, browser: Browser, quote: RideQuote) -> str:
        page = await self._ensure_page(browser)

        if quote.vehicle_type:
            await self.select_ride_type(page, quote.vehicle_type)
            await page.wait_for_timeout(500)

        for sel in ('button:has-text("Confirm")', 'button:has-text("Request")',
                     'button[data-testid="confirm-button"]'):
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click()
                break
        return page.url

    async def check_booking_status(self, browser: Browser) -> str:
        page = await self._ensure_page(browser)
        text = (await self._get_full_page_text(page)).lower()
        if any(kw in text for kw in ("arriving", "on the way", "driver", "otp", "meet at")):
            return "confirmed"
        if any(kw in text for kw in ("no drivers", "unavailable", "try again", "cancelled")):
            return "failed"
        return "searching"

    def get_deep_link(self, pickup: Location, dropoff: Location) -> str:
        from urllib.parse import quote
        base = "https://m.uber.com/ul/"
        params = f"?action=setPickup&pickup[formatted_address]={quote(pickup.address)}"
        if pickup.has_coords:
            params += f"&pickup[latitude]={pickup.latitude}&pickup[longitude]={pickup.longitude}"
        params += f"&dropoff[formatted_address]={quote(dropoff.address)}"
        if dropoff.has_coords:
            params += f"&dropoff[latitude]={dropoff.latitude}&dropoff[longitude]={dropoff.longitude}"
        return base + params
