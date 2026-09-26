"""Price comparison engine with cab-to-auto fallback logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ride_smart.config import get_settings
from ride_smart.models import RideComparison, RideQuote, RideType

logger = logging.getLogger(__name__)


@dataclass
class RideRecommendation:
    """The agent's recommendation after comparing all quotes."""
    ranked_options: list[RideQuote] = field(default_factory=list)
    switched_to_auto: bool = False
    reason: str = ""

    @property
    def top_pick(self) -> RideQuote | None:
        return self.ranked_options[0] if self.ranked_options else None

    def next_option(self, skip_index: int) -> RideQuote | None:
        idx = skip_index + 1
        return self.ranked_options[idx] if idx < len(self.ranked_options) else None


def recommend(comparison: RideComparison) -> RideRecommendation:
    """Apply the decision logic:

    1. Sort all cab quotes by price.
    2. If the cheapest cab is within the threshold (default ₹380),
       rank all options: cheapest cab first, then remaining cabs,
       then autos as fallback.
    3. If ALL cabs exceed the threshold, switch to auto —
       rank autos by price, then cabs as fallback.
    4. If no quotes at all, return empty recommendation.
    """
    settings = get_settings()
    threshold = settings.cab_price_threshold

    cabs = comparison.cab_quotes
    autos = comparison.auto_quotes

    if not cabs and not autos:
        return RideRecommendation(
            reason="No ride quotes available from any provider."
        )

    cheapest_cab = cabs[0] if cabs else None
    cheapest_auto = autos[0] if autos else None

    # Decision: cab or auto?
    if cheapest_cab and cheapest_cab.price <= threshold:
        # Cab is affordable — prefer cabs, with autos as fallback
        ranked = cabs + autos
        reason = (
            f"Cheapest cab is ₹{cheapest_cab.price:.0f} "
            f"({cheapest_cab.display_name}) — within your ₹{threshold:.0f} budget."
        )
        return RideRecommendation(
            ranked_options=ranked,
            switched_to_auto=False,
            reason=reason,
        )

    if cheapest_cab and cheapest_cab.price > threshold:
        if cheapest_auto:
            # All cabs too expensive, switch to auto
            ranked = autos + cabs
            reason = (
                f"All cabs exceed ₹{threshold:.0f} "
                f"(cheapest: ₹{cheapest_cab.price:.0f}). "
                f"Switching to auto — cheapest is ₹{cheapest_auto.price:.0f} "
                f"({cheapest_auto.display_name})."
            )
            return RideRecommendation(
                ranked_options=ranked,
                switched_to_auto=True,
                reason=reason,
            )
        else:
            # Cabs expensive but no autos available
            ranked = cabs
            reason = (
                f"All cabs exceed ₹{threshold:.0f} "
                f"(cheapest: ₹{cheapest_cab.price:.0f}) "
                f"but no autos are available. Listing cabs anyway."
            )
            return RideRecommendation(
                ranked_options=ranked,
                switched_to_auto=False,
                reason=reason,
            )

    # Only autos available (no cabs at all)
    ranked = autos
    reason = (
        f"No cab quotes available. "
        f"Cheapest auto is ₹{cheapest_auto.price:.0f} "
        f"({cheapest_auto.display_name})."
    )
    return RideRecommendation(
        ranked_options=ranked,
        switched_to_auto=True,
        reason=reason,
    )
