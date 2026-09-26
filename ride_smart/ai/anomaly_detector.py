"""Price anomaly detection — flags unusual pricing."""

from __future__ import annotations

import math

from ride_smart.ai.ride_history import get_all_history, get_price_stats


def detect_anomalies(
    quotes: list[dict],
    pickup_addr: str,
    drop_addr: str,
    threshold: float = 2.0,
) -> list[dict]:
    """Flag quotes whose price deviates significantly from historical average.

    threshold: number of standard deviations to consider anomalous.
    Returns list of flagged quotes with reason and severity.
    """
    history = get_all_history(500)
    if not history:
        return []

    provider_prices: dict[str, list[float]] = {}
    for r in history:
        if r["pickup_addr"] == pickup_addr and r["drop_addr"] == drop_addr:
            p = r["provider"]
            provider_prices.setdefault(p, []).append(r["price"])

    anomalies = []
    for q in quotes:
        provider = q.get("provider", "")
        price = q.get("price", 0)
        hist_prices = provider_prices.get(provider, [])

        if len(hist_prices) < 3:
            continue

        avg = sum(hist_prices) / len(hist_prices)
        std = math.sqrt(sum((p - avg) ** 2 for p in hist_prices) / len(hist_prices))

        if std == 0:
            continue

        z_score = (price - avg) / std

        if abs(z_score) >= threshold:
            direction = "higher" if z_score > 0 else "lower"
            pct_diff = ((price - avg) / avg) * 100

            severity = "warning" if abs(z_score) < 3 else "alert"

            anomalies.append({
                "provider": provider,
                "vehicle_type": q.get("vehicle_type", ""),
                "current_price": price,
                "avg_price": round(avg, 0),
                "z_score": round(z_score, 2),
                "pct_diff": round(pct_diff, 1),
                "direction": direction,
                "severity": severity,
                "message": (
                    f"{provider.replace('_', ' ').title()} is "
                    f"{abs(pct_diff):.0f}% {direction} than usual "
                    f"(₹{price:.0f} vs avg ₹{avg:.0f})"
                ),
            })

    return sorted(anomalies, key=lambda a: abs(a["z_score"]), reverse=True)


def is_surge_likely(
    pickup_addr: str, drop_addr: str, current_prices: dict[str, float]
) -> dict:
    """Compare current prices against historical to detect live surge."""
    surge_providers = []
    normal_providers = []

    for provider, price in current_prices.items():
        stats = get_price_stats(pickup_addr, drop_addr, provider)
        if not stats or stats["sample_count"] < 3:
            continue

        ratio = price / stats["avg_price"]
        if ratio > 1.3:
            surge_providers.append({
                "provider": provider,
                "current": price,
                "avg": stats["avg_price"],
                "ratio": round(ratio, 2),
            })
        else:
            normal_providers.append(provider)

    return {
        "is_surge": len(surge_providers) > 0,
        "surge_providers": surge_providers,
        "normal_providers": normal_providers,
    }
