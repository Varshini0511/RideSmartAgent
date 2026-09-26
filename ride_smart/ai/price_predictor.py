"""Price prediction — learns from ride history to forecast prices."""

from __future__ import annotations

import math
from datetime import datetime

from ride_smart.ai.ride_history import get_all_history, get_hourly_prices


def predict_price(
    pickup_addr: str,
    drop_addr: str,
    provider: str,
    target_hour: int | None = None,
    target_day: int | None = None,
) -> dict | None:
    """Predict price for a route/provider/time using historical averages.

    Returns dict with predicted_price, confidence, sample_count,
    price_range (min, max), or None if insufficient data.
    """
    now = datetime.now()
    hour = target_hour if target_hour is not None else now.hour
    day = target_day if target_day is not None else now.weekday()

    history = get_all_history(500)
    if not history:
        return None

    route_data = [
        r for r in history
        if r["pickup_addr"] == pickup_addr
        and r["drop_addr"] == drop_addr
        and r["provider"] == provider
    ]
    if not route_data:
        return None

    exact_hour = [r for r in route_data if r["hour"] == hour]
    nearby_hour = [r for r in route_data if abs(r["hour"] - hour) <= 1]
    same_day = [r for r in route_data if r["day_of_week"] == day]

    if exact_hour:
        prices = [r["price"] for r in exact_hour]
        confidence = min(0.9, 0.5 + len(prices) * 0.05)
    elif nearby_hour:
        prices = [r["price"] for r in nearby_hour]
        confidence = min(0.7, 0.3 + len(prices) * 0.04)
    elif same_day:
        prices = [r["price"] for r in same_day]
        confidence = min(0.5, 0.2 + len(prices) * 0.03)
    else:
        prices = [r["price"] for r in route_data]
        confidence = min(0.3, 0.1 + len(prices) * 0.02)

    avg = sum(prices) / len(prices)
    std = math.sqrt(sum((p - avg) ** 2 for p in prices) / len(prices)) if len(prices) > 1 else 0

    return {
        "predicted_price": round(avg, 0),
        "confidence": round(confidence, 2),
        "sample_count": len(prices),
        "price_range": (round(min(prices), 0), round(max(prices), 0)),
        "std_dev": round(std, 1),
    }


def best_time_to_book(
    pickup_addr: str, drop_addr: str, provider: str
) -> dict | None:
    """Find the cheapest hour to book based on historical data."""
    hourly = get_hourly_prices(pickup_addr, drop_addr, provider)
    if not hourly or len(hourly) < 3:
        return None

    cheapest = min(hourly, key=lambda h: h["avg_price"])
    most_expensive = max(hourly, key=lambda h: h["avg_price"])

    return {
        "cheapest_hour": cheapest["hour"],
        "cheapest_avg": round(cheapest["avg_price"], 0),
        "expensive_hour": most_expensive["hour"],
        "expensive_avg": round(most_expensive["avg_price"], 0),
        "savings": round(most_expensive["avg_price"] - cheapest["avg_price"], 0),
        "hourly_data": hourly,
    }


def surge_probability(
    pickup_addr: str, drop_addr: str, hour: int | None = None
) -> dict:
    """Estimate surge probability at a given hour from historical data."""
    if hour is None:
        hour = datetime.now().hour

    history = get_all_history(500)
    route_at_hour = [
        r for r in history
        if r["pickup_addr"] == pickup_addr
        and r["drop_addr"] == drop_addr
        and r["hour"] == hour
    ]

    if not route_at_hour:
        return {"probability": 0.0, "sample_count": 0, "confidence": "low"}

    surged = sum(1 for r in route_at_hour if r.get("surge", 1.0) > 1.0)
    total = len(route_at_hour)
    prob = surged / total

    confidence = "low" if total < 5 else "medium" if total < 15 else "high"

    return {
        "probability": round(prob, 2),
        "sample_count": total,
        "surged_count": surged,
        "confidence": confidence,
    }
