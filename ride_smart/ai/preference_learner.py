"""Preference learning — tracks and learns user booking patterns."""

from __future__ import annotations

from collections import Counter

from ride_smart.ai.ride_history import get_all_history, get_user_choices


def learn_preferences() -> dict:
    """Analyze user's booking choices to learn preferences."""
    choices = get_user_choices(200)
    if not choices:
        return {"has_data": False}

    provider_counts = Counter(c["chosen_provider"] for c in choices)
    total = sum(provider_counts.values())

    chose_cheapest = sum(
        1 for c in choices
        if c.get("cheapest_provider") and c["chosen_provider"] == c["cheapest_provider"]
    )

    overpaid = []
    for c in choices:
        if c.get("cheapest_price") and c["chosen_price"] > c["cheapest_price"]:
            overpaid.append(c["chosen_price"] - c["cheapest_price"])

    avg_overpay = sum(overpaid) / len(overpaid) if overpaid else 0

    return {
        "has_data": True,
        "total_bookings": total,
        "provider_preferences": {
            p: {"count": count, "pct": round(count / total * 100, 1)}
            for p, count in provider_counts.most_common()
        },
        "favorite_provider": provider_counts.most_common(1)[0][0] if provider_counts else None,
        "price_sensitivity": {
            "chose_cheapest_pct": round(chose_cheapest / total * 100, 1) if total else 0,
            "avg_overpay": round(avg_overpay, 0),
            "times_overpaid": len(overpaid),
        },
        "is_price_sensitive": chose_cheapest / total > 0.7 if total else True,
    }


def personalized_ranking(quotes: list[dict]) -> list[dict]:
    """Re-rank quotes based on learned preferences."""
    prefs = learn_preferences()
    if not prefs.get("has_data"):
        return sorted(quotes, key=lambda q: q.get("price", float("inf")))

    provider_prefs = prefs.get("provider_preferences", {})
    is_price_sensitive = prefs.get("is_price_sensitive", True)

    def score(q: dict) -> float:
        price = q.get("price", float("inf"))
        provider = q.get("provider", "")

        pref_data = provider_prefs.get(provider, {})
        pref_boost = pref_data.get("pct", 0) / 100

        if is_price_sensitive:
            return price * (1 - pref_boost * 0.1)
        else:
            return price * (1 - pref_boost * 0.25)

    return sorted(quotes, key=score)


def should_wait_for_better_price(
    current_best: float, pickup_addr: str, drop_addr: str
) -> dict:
    """Advise whether to wait based on historical patterns."""
    history = get_all_history(500)

    route_prices = [
        r["price"] for r in history
        if r["pickup_addr"] == pickup_addr
        and r["drop_addr"] == drop_addr
    ]

    if len(route_prices) < 5:
        return {"should_wait": False, "reason": "Not enough data"}

    avg = sum(route_prices) / len(route_prices)
    min_price = min(route_prices)

    if current_best > avg * 1.3:
        return {
            "should_wait": True,
            "reason": f"Current ₹{current_best:.0f} is {((current_best - avg) / avg * 100):.0f}% above average ₹{avg:.0f}",
            "typical_price": round(avg, 0),
            "best_seen": round(min_price, 0),
        }

    return {
        "should_wait": False,
        "reason": f"₹{current_best:.0f} is near or below average ₹{avg:.0f}",
        "typical_price": round(avg, 0),
    }
