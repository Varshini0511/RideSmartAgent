"""One-time login setup — opens a visible browser for each provider so the
user can log in manually. Sessions are saved for automatic reuse.
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import async_playwright

from ride_smart.models import ProviderName
from ride_smart.providers import get_providers

logger = logging.getLogger(__name__)

# All providers with web interfaces
WEB_LOGIN_PROVIDERS = {
    ProviderName.UBER,
    ProviderName.OLA,
    ProviderName.RAPIDO,
    ProviderName.NAMMA_YATRI,
}

PROVIDER_LOGIN_URLS = {
    ProviderName.UBER: "https://m.uber.com",
    ProviderName.OLA: "https://book.olacabs.com",
    ProviderName.RAPIDO: "https://www.rapido.bike",
    ProviderName.NAMMA_YATRI: "https://nammayatri.in",
}


async def setup_login(provider_name: str | None = None) -> None:
    """Open a visible browser and navigate to the provider's login page.

    The user logs in manually. When they press Enter in the terminal,
    the session is saved to disk.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)

    providers = get_providers()
    if provider_name:
        providers = [p for p in providers if p.name.value == provider_name]
    else:
        providers = [p for p in providers if p.name in WEB_LOGIN_PROVIDERS]

    if not providers:
        print("\n⚠ No providers to set up.")
        await browser.close()
        await pw.stop()
        return

    print("\n📱 Login Setup — All Providers")
    print("   A browser will open for each provider.")
    print("   Log in with your phone number, then press Enter.\n")

    for provider in providers:
        login_url = PROVIDER_LOGIN_URLS.get(provider.name, provider.base_url)

        logger.info(f"Opening {provider.name.value} for login...")
        ctx = await browser.new_context(
            viewport={"width": 414, "height": 896},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = await ctx.new_page()
        await page.goto(login_url, wait_until="domcontentloaded")

        print(f"\n{'='*50}")
        print(f"  Log into {provider.name.value.upper()}")
        print(f"  URL: {login_url}")
        print(f"  Log in with your phone number / OTP.")
        print(f"  Press Enter here when done...")
        print(f"{'='*50}")

        await asyncio.get_event_loop().run_in_executor(None, input)

        session_file = provider.session_dir / "state.json"
        await ctx.storage_state(path=str(session_file))
        logger.info(f"Session saved for {provider.name.value} at {session_file}")
        print(f"  ✓ Session saved for {provider.name.value}")

        await page.close()
        await ctx.close()

    await browser.close()
    await pw.stop()
    print("\n✅ Login setup complete! Sessions are saved for automatic reuse.")


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(setup_login(name))
