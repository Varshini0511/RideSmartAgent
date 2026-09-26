"""Smart route suggestions — learns daily travel patterns."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from ride_smart.ai.ride_history import get_all_history, get_frequent_routes


def suggest_routes(limit: int = 5) -> list[dict]:
    """Suggest routes based on current time and past patterns."""
    now = datetime.now()
    current_hour = now.hour
    current_day = now.weekday()

    history = get_all_history(500)
    if not history:
        return []

    scored: dict[tuple[str, str], float] = {}

    for r in history:
        key = (r["pickup_addr"], r["drop_addr"])

        score = 1.0

        hour_diff = abs(r["hour"] - current_hour)
        if hour_diff <= 1:
            score += 3.0
        elif hour_diff <= 2:
            score += 1.5

        days_str = str(r.get("day_of_week", ""))
        if str(current_day) in days_str:
            score += 2.0

        scored[key] = scored.get(key, 0) + score

    ranked = sorted(scored.items(), key=lambda x: -x[1])[:limit]

    results = []
    for (pickup, dropoff), score in ranked:
        route_prices = [
            r["price"] for r in history
            if r["pickup_addr"] == pickup and r["drop_addr"] == dropoff
        ]
        results.append({
            "pickup": pickup,
            "dropoff": dropoff,
            "score": round(score, 1),
            "trip_count": len(route_prices),
            "avg_price": round(sum(route_prices) / len(route_prices), 0) if route_prices else 0,
        })

    return results


def detect_commute_pattern() -> dict | None:
    """Detect daily commute pattern (home ↔ work)."""
    history = get_all_history(500)
    if len(history) < 10:
        return None

    morning = [r for r in history if 6 <= r["hour"] <= 10]
    evening = [r for r in history if 17 <= r["hour"] <= 21]

    if not morning or not evening:
        return None

    morning_routes = Counter(
        (r["pickup_addr"], r["drop_addr"]) for r in morning
    )
    evening_routes = Counter(
        (r["pickup_addr"], r["drop_addr"]) for r in evening
    )

    top_morning = morning_routes.most_common(1)[0] if morning_routes else None
    top_evening = evening_routes.most_common(1)[0] if evening_routes else None

    if not top_morning or not top_evening:
        return None

    (m_pickup, m_drop), m_count = top_morning
    (e_pickup, e_drop), e_count = top_evening

    is_round_trip = (m_pickup == e_drop and m_drop == e_pickup)

    return {
        "morning_route": {"pickup": m_pickup, "dropoff": m_drop, "count": m_count},
        "evening_route": {"pickup": e_pickup, "dropoff": e_drop, "count": e_count},
        "is_commute": is_round_trip,
        "home": m_pickup if is_round_trip else None,
        "work": m_drop if is_round_trip else None,
    }
