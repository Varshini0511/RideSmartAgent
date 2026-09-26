"""LLM-powered ride booking agent using Groq API."""

from __future__ import annotations

import json
import os
from datetime import datetime

from ride_smart.ai.ride_history import (
    get_all_history,
    get_frequent_routes,
    get_hourly_prices,
    get_price_stats,
    get_user_choices,
)


def _get_groq_client():
    try:
        from groq import Groq
    except ImportError:
        return None
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    return Groq(api_key=api_key)


def _build_system_prompt() -> str:
    routes = get_frequent_routes(5)
    choices = get_user_choices(20)

    route_info = ""
    if routes:
        route_info = "Frequent routes:\n"
        for r in routes:
            route_info += f"  - {r['pickup_addr']} → {r['drop_addr']} ({r['trip_count']} trips)\n"

    pref_info = ""
    if choices:
        providers = {}
        for c in choices:
            p = c["chosen_provider"]
            providers[p] = providers.get(p, 0) + 1
        pref_info = "Provider preferences: " + ", ".join(
            f"{k}: {v} times" for k, v in sorted(providers.items(), key=lambda x: -x[1])
        )

    return f"""You are RideSmartAgent, an AI assistant for ride-hailing in Chennai.
You help users compare prices across Uber, Ola, Rapido, and Namma Yatri,
find the best deals, and make booking decisions.

Current time: {datetime.now().strftime('%A %H:%M')}

{route_info}
{pref_info}

You can help with:
- Comparing current prices across providers
- Suggesting when to book based on price patterns
- Recommending the best provider for a route
- Explaining surge pricing and ETAs
- Answering questions about ride history

Keep responses concise. Use ₹ for prices. Be direct with recommendations."""


def _build_context_from_history(pickup: str, dropoff: str) -> str:
    parts = []

    for provider in ("uber", "ola", "rapido", "namma_yatri"):
        stats = get_price_stats(pickup, dropoff, provider)
        if stats and stats["sample_count"] > 0:
            parts.append(
                f"{provider.replace('_', ' ').title()}: "
                f"avg ₹{stats['avg_price']:.0f} "
                f"(₹{stats['min_price']:.0f}-₹{stats['max_price']:.0f}), "
                f"{stats['sample_count']} trips"
            )

    if parts:
        return "Historical prices for this route:\n" + "\n".join(parts)
    return ""


def chat(
    user_message: str,
    conversation_history: list[dict] | None = None,
    current_quotes: list[dict] | None = None,
    pickup: str = "",
    dropoff: str = "",
) -> str | None:
    client = _get_groq_client()
    if not client:
        return None

    messages = [{"role": "system", "content": _build_system_prompt()}]

    if pickup and dropoff:
        ctx = _build_context_from_history(pickup, dropoff)
        if ctx:
            messages.append({"role": "system", "content": ctx})

    if current_quotes:
        quote_text = "Current quotes:\n"
        for q in current_quotes:
            quote_text += f"  - {q.get('provider', '?')}: ₹{q.get('price', 0):.0f} {q.get('vehicle_type', '')} ({q.get('eta_minutes', '?')} min)\n"
        messages.append({"role": "system", "content": quote_text})

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=messages,
            temperature=0.4,
            max_tokens=500,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Agent error: {e}"


def get_recommendation(
    quotes: list[dict],
    pickup: str = "",
    dropoff: str = "",
) -> str | None:
    if not quotes:
        return None

    prompt = (
        "Given these current ride options, which should I book right now? "
        "Consider price, ETA, and my past preferences. Be brief."
    )
    return chat(
        prompt,
        current_quotes=quotes,
        pickup=pickup,
        dropoff=dropoff,
    )


def analyze_surge(
    quotes: list[dict],
    pickup: str = "",
    dropoff: str = "",
) -> str | None:
    prompt = (
        "Analyze the current pricing. Is there surge? "
        "Should I wait or book now? Compare to historical prices."
    )
    return chat(
        prompt,
        current_quotes=quotes,
        pickup=pickup,
        dropoff=dropoff,
    )
