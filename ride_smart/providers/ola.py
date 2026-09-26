"""Ola provider — navigates book.olacabs.com via deep link and extracts prices."""

from __future__ import annotations

import logging
import re

from playwright.async_api import Browser, Page

from ride_smart.models import Location, ProviderName, RideQuote, RideType
from ride_smart.providers.base import RideProvider

logger = logging.getLogger(__name__)


class OlaProvider(RideProvider):
    name = ProviderName.OLA
    base_url = "https://book.olacabs.com"

    async def fetch_quotes(
        self, browser: Browser, pickup: Location, dropoff: Location
    ) -> list[RideQuote]:
        page = await self._ensure_page(browser)

        deep = self.get_deep_link(pickup, dropoff)
        await page.goto(deep, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        await self._dismiss_app_popup(page)
        await self._ensure_destination(page, dropoff)
        await self._dismiss_app_popup(page)

        await page.wait_for_timeout(5000)
        await self._screenshot_debug(page, "quotes")

        text = await self._get_page_text_robust(page)
        logger.info(f"Ola: text length={len(text)}, has ₹={'₹' in text}")

        quotes = self._parse_quotes(text)
        if not quotes:
            quotes = await self._extract_prices_js(page)
        if not quotes:
            quotes = await self._extract_prices_all_frames(page)
        if not quotes:
            quotes = await self._scrape_ride_cards(page)

        return quotes

    async def _dismiss_app_popup(self, page: Page) -> None:
        """Dismiss the 'Get smoother experience on OLA app' popup."""
        try:
            # Try "Continue on web" link
            for sel in (
                'text="Continue on web"',
                'a:has-text("Continue on web")',
                'button:has-text("Continue on web")',
            ):
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(500)
                    return

            # Try close (X) button on the popup
            for sel in (
                '[class*="close"]',
                'button[aria-label="Close"]',
                '[class*="modal"] button >> nth=0',
            ):
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(500)
                    return
        except Exception:
            pass

    async def _ensure_destination(self, page: Page, dropoff: Location) -> None:
        """Fill destination field if the deep link didn't pre-fill it."""
        try:
            # The TO field is a clickable area (div), not a regular input.
            # Click on it to open the search interface.
            to_area = page.locator('text="Search for a locality or landmark"')
            if await to_area.count() == 0:
                # Destination might already be filled
                return

            await to_area.click()
            await page.wait_for_timeout(500)

            # After clicking, a search input should appear
            search_input = page.locator('input[type="text"], input[type="search"]')
            count = await search_input.count()
            if count > 0:
                field = search_input.last
                await field.fill(dropoff.address)
                await page.wait_for_timeout(1500)

                dest = dropoff.address.split()[0]
                for text_pat in (
                    f"{dropoff.address}, Chennai",
                    f"{dropoff.address}",
                    "Chennai, Tamil Nadu",
                    "Chennai Tamil Nadu",
                ):
                    sug = page.get_by_text(text_pat, exact=False).first
                    if await sug.count() > 0 and await sug.is_visible():
                        await sug.click()
                        await page.wait_for_timeout(1500)
                        return

                for sug_sel in (
                    '[class*="suggestion"]',
                    '[class*="search"] li',
                    '[class*="result"]',
                    'li',
                ):
                    sug = page.locator(sug_sel).first
                    if await sug.count() > 0 and await sug.is_visible():
                        await sug.click()
                        await page.wait_for_timeout(1500)
                        return

                await field.press("Enter")
                await page.wait_for_timeout(1000)
        except Exception as e:
            logger.debug(f"Ola: could not fill destination: {e}")

    async def _expand_ride_category(self, page: Page) -> None:
        """Click on a ride category (Mini, Auto, etc.) to see prices."""
        try:
            for label in ("Mini", "Auto", "Sedan", "Prime Sedan"):
                btn = page.get_by_text(label, exact=True).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    return
        except Exception:
            pass

    async def _get_page_text_robust(self, page: Page) -> str:
        """Try multiple methods to extract page text (Ola uses Shadow DOM)."""
        # Method 1: standard innerText
        try:
            text = await page.inner_text("body")
            if text.strip() and '₹' in text:
                return text
        except Exception:
            pass

        # Method 2: JavaScript textContent
        try:
            text = await page.evaluate("() => document.body?.textContent || ''")
            if text.strip() and '₹' in text:
                return text
        except Exception:
            pass

        # Method 3: documentElement innerText
        try:
            text = await page.evaluate("() => document.documentElement?.innerText || ''")
            if text.strip() and '₹' in text:
                return text
        except Exception:
            pass

        # Method 4: all frames text
        text = await self._get_all_frames_text(page)
        if text.strip() and '₹' in text:
            return text

        # Method 5: raw HTML source
        try:
            html = await page.content()
            if '₹' in html:
                import re
                visible = re.sub(r'<[^>]+>', ' ', html)
                visible = re.sub(r'\s+', ' ', visible).strip()
                return visible
        except Exception:
            pass

        # Method 6: Shadow DOM traversal (Ola renders in Shadow DOM)
        try:
            text = await page.evaluate("""() => {
                function collectText(node) {
                    let text = '';
                    if (node.shadowRoot) {
                        text += collectText(node.shadowRoot);
                    }
                    if (node.nodeType === Node.TEXT_NODE) {
                        text += node.textContent;
                    }
                    if (node.childNodes) {
                        for (const child of node.childNodes) {
                            text += collectText(child);
                        }
                    }
                    return text;
                }
                return collectText(document.documentElement);
            }""")
            if text.strip() and '₹' in text:
                return text
        except Exception:
            pass

        logger.debug("Ola: all text extraction methods failed")
        return text or ""

    async def _wait_for_prices_any_frame(self, page: Page, timeout_ms: int = 20000) -> None:
        """Wait until ₹ appears in any frame's text."""
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            for frame in page.frames:
                try:
                    has_price = await frame.evaluate(
                        "() => (document.body?.innerText || '').includes('₹')"
                    )
                    if has_price:
                        return
                except Exception:
                    continue
            await page.wait_for_timeout(500)
        logger.debug("Ola: no ₹ found in any frame within timeout")

    async def _get_all_frames_text(self, page: Page) -> str:
        """Get text from all frames (main + iframes)."""
        all_text = []
        for frame in page.frames:
            try:
                ft = await frame.evaluate("() => document.body?.innerText || ''")
                if ft and ft.strip():
                    logger.debug(f"Ola: frame '{frame.name or frame.url}' text length={len(ft)}")
                    all_text.append(ft)
            except Exception:
                continue
        return "\n".join(all_text)

    async def _extract_prices_all_frames(self, page: Page) -> list[RideQuote]:
        """Try JS price extraction in every frame."""
        for frame in page.frames:
            try:
                data = await frame.evaluate("""() => {
                    const results = [];
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT, null, false
                    );
                    let node;
                    while (node = walker.nextNode()) {
                        const text = node.textContent.trim();
                        const m = text.match(/[₹\\u20B9]\\s*([\\d,]+)/);
                        if (m) {
                            let ctx = '';
                            let el = node.parentElement;
                            for (let i = 0; i < 5 && el; i++) {
                                ctx = (el.textContent || '').substring(0, 200) + ' ' + ctx;
                                el = el.parentElement;
                            }
                            results.push({price: m[1].replace(',', ''), context: ctx.substring(0, 300)});
                        }
                    }
                    return results;
                }""")
                if data:
                    logger.debug(f"Ola: frame '{frame.name or frame.url}' has {len(data)} prices")
                    quotes: list[RideQuote] = []
                    for item in data:
                        try:
                            price = float(item["price"])
                            if price < 20 or price > 5000:
                                continue
                            ctx = item["context"].lower()
                            if self._is_wallet_or_promo(ctx):
                                continue
                            ride_type = self._classify(ctx)
                            vehicle = self._vehicle_name(ctx)
                            eta = self._extract_eta(ctx)
                            quotes.append(RideQuote(
                                provider=ProviderName.OLA,
                                ride_type=ride_type,
                                price=price,
                                vehicle_type=vehicle,
                                eta_minutes=eta,
                            ))
                        except (ValueError, KeyError):
                            continue
                    if quotes:
                        return self._deduplicate(quotes)
            except Exception:
                continue
        return []

    async def _extract_prices_js(self, page: Page) -> list[RideQuote]:
        """Extract prices via JavaScript DOM traversal as fallback."""
        try:
            data = await page.evaluate("""() => {
                const results = [];
                // Walk all text nodes looking for ₹ or &#8377; prices
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null, false
                );
                let node;
                while (node = walker.nextNode()) {
                    const text = node.textContent.trim();
                    // Match ₹ followed by digits
                    const m = text.match(/[₹\\u20B9]\\s*([\\d,]+)/);
                    if (m) {
                        // Get context from parent elements
                        let ctx = '';
                        let el = node.parentElement;
                        for (let i = 0; i < 5 && el; i++) {
                            ctx = (el.textContent || '').substring(0, 200) + ' ' + ctx;
                            el = el.parentElement;
                        }
                        results.push({price: m[1].replace(',', ''), context: ctx.substring(0, 300)});
                    }
                }
                return results;
            }""")
            logger.debug(f"Ola JS: found {len(data)} price nodes")
            quotes: list[RideQuote] = []
            for item in data:
                try:
                    price = float(item["price"])
                    if price < 20 or price > 5000:
                        continue
                    ctx = item["context"].lower()
                    if self._is_wallet_or_promo(ctx):
                        logger.debug(f"Ola JS: skipping wallet/promo: {ctx[:60]}")
                        continue
                    logger.debug(f"Ola JS: price={price}, context={ctx[:80]}")
                    ride_type = self._classify(ctx)
                    vehicle = self._vehicle_name(ctx)
                    eta = self._extract_eta(ctx)
                    quotes.append(RideQuote(
                        provider=ProviderName.OLA,
                        ride_type=ride_type,
                        price=price,
                        vehicle_type=vehicle,
                        eta_minutes=eta,
                    ))
                except (ValueError, KeyError):
                    continue
            return self._deduplicate(quotes)
        except Exception as e:
            logger.debug(f"Ola JS extraction failed: {e}")
            return []

    _SKIP_KEYWORDS = (
        "ola money", "wallet", "balance", "cashback", "coupon",
        "discount", "offer", "reward", "referral", "promo",
        "top up", "topup", "recharge", "pay later", "credit",
    )

    @classmethod
    def _is_wallet_or_promo(cls, context: str) -> bool:
        return any(kw in context for kw in cls._SKIP_KEYWORDS)

    def _parse_quotes(self, page_text: str) -> list[RideQuote]:
        quotes: list[RideQuote] = []
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]

        for i, line in enumerate(lines):
            prices = self.extract_prices_from_text(line)
            if not prices:
                continue
            logger.debug(f"Ola: found price(s) {prices} in line: {line[:80]}")

            context = " ".join(lines[max(0, i - 5) : i + 1]).lower()

            if self._is_wallet_or_promo(context):
                logger.debug(f"Ola: skipping wallet/promo price in: {context[:60]}")
                continue

            ride_type = self._classify(context)
            vehicle = self._vehicle_name(context)
            eta = self._extract_eta(context)

            for price in prices:
                if price < 20 or price > 5000:
                    continue
                quotes.append(RideQuote(
                    provider=ProviderName.OLA,
                    ride_type=ride_type,
                    price=price,
                    vehicle_type=vehicle,
                    eta_minutes=eta,
                ))

        return self._deduplicate(quotes)

    async def _scrape_ride_cards(self, page: Page) -> list[RideQuote]:
        quotes: list[RideQuote] = []
        selectors = [
            '[class*="ride-type"]',
            '[class*="category-card"]',
            '[class*="vehicle-card"]',
            '[class*="cab-type"]',
            '[class*="fare"]',
            'div[role="radio"]',
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
                        text_lower = text.lower()
                        if self._is_wallet_or_promo(text_lower):
                            continue
                        ride_type = self._classify(text_lower)
                        vehicle = self._vehicle_name(text_lower)
                        eta = self._extract_eta(text_lower)
                        quotes.append(RideQuote(
                            provider=ProviderName.OLA,
                            ride_type=ride_type,
                            price=prices[0],
                            vehicle_type=vehicle,
                            eta_minutes=eta,
                        ))
                except Exception:
                    continue
            if quotes:
                break

        return self._deduplicate(quotes)

    @staticmethod
    def _extract_eta(text: str) -> int | None:
        m = re.search(r'(\d+)\s*min', text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _classify(text: str) -> RideType:
        if any(kw in text for kw in ("auto", "rick", "three wheel", "tuk")):
            return RideType.AUTO
        if any(kw in text for kw in ("bike", "moto")):
            return RideType.AUTO
        return RideType.CAB

    @staticmethod
    def _vehicle_name(text: str) -> str:
        for label in ("ola auto", "auto", "mini", "sedan", "prime sedan",
                       "prime suv", "prime", "lux", "share", "bike"):
            if label in text:
                return "Ola " + label.title()
        return "Ola Cab"

    @staticmethod
    def _deduplicate(quotes: list[RideQuote]) -> list[RideQuote]:
        seen: set[float] = set()
        result = []
        for q in quotes:
            if q.price not in seen:
                seen.add(q.price)
                result.append(q)
        return result

    async def select_ride_type(self, page: Page, vehicle_type: str) -> bool:
        """Click the matching ride-type card so it's selected before booking."""
        target = vehicle_type.lower().replace("ola ", "").strip()

        for label in [target, target.title(), vehicle_type, vehicle_type.title()]:
            btn = page.get_by_text(label, exact=False).first
            try:
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    logger.info(f"Ola: selected ride type '{label}'")
                    return True
            except Exception:
                continue

        logger.debug(f"Ola: could not select ride type '{vehicle_type}'")
        return False

    async def prepare_for_booking(self, browser: Browser, pickup: Location, dropoff: Location) -> Page:
        """Navigate to deep link, dismiss popups, ensure destination — ready to book."""
        page = await self._ensure_page(browser)
        deep = self.get_deep_link(pickup, dropoff)
        await page.goto(deep, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await self._dismiss_app_popup(page)
        await self._ensure_destination(page, dropoff)
        await self._dismiss_app_popup(page)
        await page.wait_for_timeout(5000)
        return page

    async def initiate_booking(self, browser: Browser, quote: RideQuote) -> str:
        page = await self._ensure_page(browser)

        if quote.vehicle_type:
            await self.select_ride_type(page, quote.vehicle_type)
            await page.wait_for_timeout(500)

        for sel in ('button:has-text("Book")', 'button:has-text("Confirm")',
                     'button:has-text("Ride Now")'):
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click()
                break
        return page.url

    async def check_booking_status(self, browser: Browser) -> str:
        page = await self._ensure_page(browser)
        text = (await self._get_full_page_text(page)).lower()
        if any(kw in text for kw in ("arriving", "driver assigned", "otp", "on the way")):
            return "confirmed"
        if any(kw in text for kw in ("no drivers", "unavailable", "try again")):
            return "failed"
        return "searching"

    def get_deep_link(self, pickup: Location, dropoff: Location) -> str:
        link = "https://book.olacabs.com/"
        if pickup.has_coords and dropoff.has_coords:
            link += f"?lat={pickup.latitude}&lng={pickup.longitude}"
            link += f"&dlat={dropoff.latitude}&dlng={dropoff.longitude}"
        return link
