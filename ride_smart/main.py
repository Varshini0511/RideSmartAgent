"""CLI entry point for RideSmartAgent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ride_smart.config import get_settings
from ride_smart.orchestrator import run_full_flow


def _print_header():
    print("""
 ╔══════════════════════════════════════════╗
 ║       🚗  RideSmartAgent  🛺            ║
 ║  Compare rides across Uber, Ola,        ║
 ║  Rapido & Namma Yatri instantly         ║
 ╚══════════════════════════════════════════╝
""")


def _print_recommendation(result: dict):
    recommendation = result["recommendation"]
    comparison = result["comparison"]

    print(f"\n{'=' * 55}")
    print(f"  Route: {comparison.pickup.address}")
    print(f"      → {comparison.dropoff.address}")
    print(f"{'=' * 55}")

    print(f"\n  📊 Decision: {recommendation.reason}")

    if recommendation.switched_to_auto:
        print("  ⚠  Switched to AUTO (cabs too expensive)")

    print(f"\n  {'─' * 50}")
    print(f"  {'Rank':<5} {'Option':<25} {'Price':<10} {'ETA'}")
    print(f"  {'─' * 50}")

    for i, quote in enumerate(recommendation.ranked_options, 1):
        eta = f"{quote.eta_minutes} min" if quote.eta_minutes else "—"
        marker = " ★" if i == 1 else ""
        print(f"  {i:<5} {quote.display_name:<25} ₹{quote.price:<9.0f} {eta}{marker}")

    print(f"  {'─' * 50}")

    if comparison.errors:
        print(f"\n  ⚠ Provider errors:")
        for provider, err in comparison.errors.items():
            print(f"    • {provider}: {err}")

    # Booking result
    booking = result.get("booking")
    if booking:
        print(f"\n  📱 Booking Result:")
        for i, attempt in enumerate(booking.attempts, 1):
            status_icon = {
                "confirmed": "✅",
                "timeout": "⏱",
                "failed": "❌",
            }.get(attempt.status.value, "⏳")
            print(
                f"    {i}. {attempt.quote.display_name} "
                f"₹{attempt.quote.price:.0f} — {status_icon} {attempt.status.value}"
            )
            if attempt.failure_reason:
                print(f"       {attempt.failure_reason}")

        if booking.is_booked:
            final = booking.final
            print(f"\n  ✅ Booked: {final.quote.display_name} at ₹{final.quote.price:.0f}")
        else:
            print(f"\n  ❌ All booking attempts failed. Open manually:")
            top = recommendation.top_pick
            if top:
                provider_map = {
                    "uber": "Uber",
                    "ola": "Ola",
                    "rapido": "Rapido",
                    "namma_yatri": "Namma Yatri",
                }
                print(f"     Cheapest: {provider_map.get(top.provider.value, top.provider.value)} at ₹{top.price:.0f}")


def _interactive_mode():
    """Interactive loop: keep asking for routes."""
    _print_header()
    settings = get_settings()
    print(f"  Cab budget threshold: ₹{settings.cab_price_threshold:.0f}")
    print(f"  City: {settings.default_city}\n")

    while True:
        try:
            pickup = input("  📍 Pickup location: ").strip()
            if not pickup:
                continue
            if pickup.lower() in ("quit", "exit", "q"):
                print("  Bye!")
                break

            dropoff = input("  📍 Drop location:   ").strip()
            if not dropoff:
                continue

            auto_book_input = input("  🔄 Auto-book cheapest? (y/N): ").strip().lower()
            auto_book = auto_book_input in ("y", "yes")

            print("\n  ⏳ Fetching quotes from all providers...\n")

            result = asyncio.run(
                run_full_flow(pickup, dropoff, auto_book=auto_book)
            )
            _print_recommendation(result)
            print()

        except KeyboardInterrupt:
            print("\n  Bye!")
            break
        except Exception as e:
            print(f"\n  ❌ Error: {e}\n")


def main():
    parser = argparse.ArgumentParser(
        description="RideSmartAgent — find the cheapest ride across apps"
    )
    parser.add_argument("--pickup", "-p", help="Pickup location")
    parser.add_argument("--drop", "-d", help="Drop location")
    parser.add_argument(
        "--book", action="store_true",
        help="Auto-book the cheapest option (with fallback)"
    )
    parser.add_argument(
        "--threshold", type=float,
        help="Cab price threshold for switching to auto"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run browsers in headless mode"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.threshold:
        import os
        os.environ["CAB_PRICE_THRESHOLD"] = str(args.threshold)

    if args.headless:
        import os
        os.environ["HEADLESS_BROWSER"] = "true"

    if args.pickup and args.drop:
        _print_header()
        print(f"  ⏳ Fetching quotes from all providers...\n")
        result = asyncio.run(
            run_full_flow(args.pickup, args.drop, auto_book=args.book)
        )
        _print_recommendation(result)
    else:
        _interactive_mode()


if __name__ == "__main__":
    main()
