"""ETA prediction — compares predicted vs actual ETAs over time."""

from __future__ import annotations

from datetime import datetime

from ride_smart.ai.ride_history import get_all_history


def predict_eta(
    pickup_addr: str,
    drop_addr: str,
    provider: str,
    hour: int | None = None,
) -> dict | None:
    """Predict ETA based on historical data for this route/provider/hour."""
    if hour is None:
        hour = datetime.now().hour

    history = get_all_history(500)
    route_data = [
        r for r in history
        if r["pickup_addr"] == pickup_addr
        and r["drop_addr"] == drop_addr
        and r["provider"] == provider
        and r.get("eta_minutes") is not None
    ]

    if not route_data:
        return None

    exact_hour = [r for r in route_data if r["hour"] == hour]
    nearby = [r for r in route_data if abs(r["hour"] - hour) <= 2]

    data = exact_hour or nearby or route_data
    etas = [r["eta_minutes"] for r in data]

    avg_eta = sum(etas) / len(etas)

    rush_hours = {8, 9, 17, 18, 19}
    is_rush = hour in rush_hours
    if is_rush and not exact_hour:
        avg_eta *= 1.3

    return {
        "predicted_eta": round(avg_eta, 0),
        "sample_count": len(data),
        "min_eta": min(etas),
        "max_eta": max(etas),
        "is_rush_hour": is_rush,
        "confidence": "high" if len(data) >= 10 else "medium" if len(data) >= 5 else "low",
    }


def eta_reliability(provider: str) -> dict | None:
    """Score how reliable a provider's ETA estimates are."""
    history = get_all_history(500)
    provider_data = [
        r for r in history
        if r["provider"] == provider
        and r.get("eta_minutes") is not None
    ]

    if len(provider_data) < 5:
        return None

    etas = [r["eta_minutes"] for r in provider_data]
    avg = sum(etas) / len(etas)
    variance = sum((e - avg) ** 2 for e in etas) / len(etas)

    consistency = max(0, 1 - (variance / (avg * avg))) if avg > 0 else 0

    return {
        "provider": provider,
        "avg_eta": round(avg, 1),
        "consistency_score": round(consistency, 2),
        "sample_count": len(provider_data),
        "rating": "reliable" if consistency > 0.7 else "moderate" if consistency > 0.4 else "variable",
    }
