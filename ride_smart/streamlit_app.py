"""Streamlit UI for RideSmartAgent — compare real ride prices across
Uber, Ola, Rapido & Namma Yatri and book the best option.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote as urlquote

import folium
import streamlit as st

logging.basicConfig(level=logging.INFO, force=True)
from streamlit_folium import st_folium

from ride_smart.comparator import RideRecommendation, recommend
from ride_smart.config import get_settings
from ride_smart.location_search import LocationSuggestion, geocode_address, search_location
from ride_smart.models import (
    Location,
    ProviderName,
    RideComparison,
    RideQuote,
    RideType,
)
from ride_smart.ai import (
    save_comparison,
    save_user_choice,
    get_frequent_routes,
    detect_anomalies,
    should_wait_for_better_price,
    predict_price,
    best_time_to_book,
    suggest_routes,
    detect_commute_pattern,
    learn_preferences,
    eta_reliability,
    chat as ai_chat,
    get_recommendation as ai_recommend,
    analyze_surge as ai_analyze_surge,
)

st.set_page_config(
    page_title="RideSmartAgent",
    page_icon="🚗",
    layout="wide",
)

settings = get_settings()

# ── Session state init ──────────────────────────────────────────────
for key in ("pickup_loc", "dropoff_loc", "last_result", "booking_confirmed",
            "booking_result", "booking_logs", "ai_chat_history",
            "comparison_id"):
    if key not in st.session_state:
        st.session_state[key] = None
if "ai_chat_history" not in st.session_state or st.session_state["ai_chat_history"] is None:
    st.session_state["ai_chat_history"] = []


def _location_picker(label: str, icon: str, placeholder: str, state_key: str):
    st.markdown(f"**{icon} {label}**")

    selected: LocationSuggestion | None = st.session_state.get(state_key)

    if selected:
        st.success(f"✓ {selected.short_name}", icon=icon)
        if st.button(f"Change {label.lower()}", key=f"clear_{state_key}"):
            st.session_state[state_key] = None
            st.session_state["last_result"] = None
            st.rerun()
        return

    query = st.text_input(
        f"Search {label.lower()}",
        placeholder=placeholder,
        key=f"{state_key}_query",
        label_visibility="collapsed",
    )

    if not query or len(query.strip()) < 2:
        return

    results = search_location(query, limit=8)

    if not results:
        st.caption("No match found in database.")
        if st.button(f"📍 Locate \"{query}\" on map", key=f"{state_key}_geocode"):
            with st.spinner("Looking up address..."):
                geo = geocode_address(query)
            if geo:
                st.session_state[state_key] = geo
                st.rerun()
            else:
                st.error("Could not find this address. Try adding more detail (e.g. street, area, city).")
        return

    options: dict[str, LocationSuggestion] = {}
    for sug in results:
        display = f"{sug.short_name} — {sug.display_name}" if sug.short_name != sug.display_name else sug.short_name
        if len(display) > 60:
            display = display[:57] + "..."
        options[display] = sug

    choice = st.selectbox(
        "Select location",
        options=["— Select —"] + list(options.keys()),
        key=f"{state_key}_select",
        label_visibility="collapsed",
    )

    if choice and choice != "— Select —":
        st.session_state[state_key] = options[choice]
        st.rerun()

    if len(results) < 3:
        st.caption("Not what you're looking for?")
        if st.button(f"📍 Locate \"{query}\" on map", key=f"{state_key}_geocode"):
            with st.spinner("Looking up address..."):
                geo = geocode_address(query)
            if geo:
                st.session_state[state_key] = geo
                st.rerun()
            else:
                st.error("Could not find this address. Try adding more detail.")


# ── Sidebar ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    threshold = st.number_input(
        "Cab price threshold (₹)",
        min_value=100.0,
        max_value=2000.0,
        value=settings.cab_price_threshold,
        step=10.0,
        help="If all cabs exceed this price, switch to auto",
    )
    st.divider()
    headless = st.checkbox("Headless browsers", value=settings.headless, key="headless")
    st.divider()
    st.caption(f"City: {settings.default_city}")

    # Login status
    from pathlib import Path
    st.markdown("**Login Status**")
    for prov, name, url in [
        (ProviderName.UBER, "Uber", "https://m.uber.com"),
        (ProviderName.OLA, "Ola", "https://book.olacabs.com"),
        (ProviderName.RAPIDO, "Rapido", "https://www.rapido.bike"),
        (ProviderName.NAMMA_YATRI, "Namma Yatri", "https://nammayatri.in"),
    ]:
        session_file = Path(settings.user_data_dir) / prov.value / "state.json"
        if session_file.exists():
            st.caption(f"✅ {name} — logged in")
        else:
            st.caption(f"⚠️ {name} — not logged in")
            st.link_button(f"Login to {name}", url, use_container_width=True)

    st.divider()
    st.caption("💡 First time? Run in terminal:")
    st.code("python -m ride_smart.login_setup", language="bash")

    # ── AI Chat ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("**🤖 AI Assistant**")
    ai_query = st.text_input(
        "Ask AI",
        placeholder="Should I wait? Is this surge?",
        key="ai_chat_input",
        label_visibility="collapsed",
    )
    if ai_query:
        pickup_name = st.session_state.get("pickup_loc")
        dropoff_name = st.session_state.get("dropoff_loc")
        p_addr = pickup_name.short_name if pickup_name else ""
        d_addr = dropoff_name.short_name if dropoff_name else ""

        current_quotes = None
        last = st.session_state.get("last_result")
        if last and last.get("recommendation"):
            current_quotes = [
                {"provider": q.provider.value, "price": q.price,
                 "vehicle_type": q.vehicle_type, "eta_minutes": q.eta_minutes}
                for q in last["recommendation"].ranked_options
            ]

        with st.spinner("Thinking..."):
            reply = ai_chat(
                ai_query,
                conversation_history=st.session_state["ai_chat_history"],
                current_quotes=current_quotes,
                pickup=p_addr,
                dropoff=d_addr,
            )

        if reply:
            st.session_state["ai_chat_history"].append(
                {"role": "user", "content": ai_query}
            )
            st.session_state["ai_chat_history"].append(
                {"role": "assistant", "content": reply}
            )
            st.markdown(reply)
        else:
            st.caption("AI not available — set GROQ_API_KEY in .env")

    # ── Preference insights ─────────────────────────────────────────
    prefs = learn_preferences()
    if prefs.get("has_data"):
        with st.expander("📊 Your Ride Preferences"):
            fav = prefs.get("favorite_provider", "").replace("_", " ").title()
            st.caption(f"Favorite: **{fav}** ({prefs['total_bookings']} bookings)")
            ps = prefs.get("price_sensitivity", {})
            st.caption(f"Chose cheapest: {ps.get('chose_cheapest_pct', 0)}%")
            if ps.get("avg_overpay", 0) > 0:
                st.caption(f"Avg extra paid: ₹{ps['avg_overpay']:.0f}")


# ── Header ──────────────────────────────────────────────────────────
st.title("🚗 RideSmartAgent")
st.caption("Compare rides across Uber, Ola, Rapido & Namma Yatri")

# ── Location pickers ────────────────────────────────────────────────
col_pickup, col_drop = st.columns(2)

with col_pickup:
    _location_picker("Pickup", "📍", "e.g. T Nagar, Adyar, OMR", "pickup_loc")

with col_drop:
    _location_picker("Drop", "🏁", "e.g. Guindy, Velachery, ECR", "dropoff_loc")


# ── Map ─────────────────────────────────────────────────────────────
pickup_loc: LocationSuggestion | None = st.session_state.pickup_loc
dropoff_loc: LocationSuggestion | None = st.session_state.dropoff_loc

CITY_CENTERS = {
    "Chennai": (13.0827, 80.2707),
    "Bengaluru": (12.9716, 77.5946),
    "Mumbai": (19.0760, 72.8777),
    "Delhi": (28.6139, 77.2090),
    "Hyderabad": (17.3850, 78.4867),
}
default_center = CITY_CENTERS.get(settings.default_city, (13.0827, 80.2707))

if pickup_loc and dropoff_loc:
    center_lat = (pickup_loc.latitude + dropoff_loc.latitude) / 2
    center_lng = (pickup_loc.longitude + dropoff_loc.longitude) / 2
    m = folium.Map(location=[center_lat, center_lng], zoom_start=12)
elif pickup_loc:
    m = folium.Map(location=[pickup_loc.latitude, pickup_loc.longitude], zoom_start=14)
elif dropoff_loc:
    m = folium.Map(location=[dropoff_loc.latitude, dropoff_loc.longitude], zoom_start=14)
else:
    m = folium.Map(location=list(default_center), zoom_start=12)

if pickup_loc:
    folium.Marker(
        [pickup_loc.latitude, pickup_loc.longitude],
        popup=f"Pickup: {pickup_loc.short_name}",
        tooltip="Pickup",
        icon=folium.Icon(color="green", icon="play", prefix="fa"),
    ).add_to(m)

if dropoff_loc:
    folium.Marker(
        [dropoff_loc.latitude, dropoff_loc.longitude],
        popup=f"Drop: {dropoff_loc.short_name}",
        tooltip="Drop",
        icon=folium.Icon(color="red", icon="stop", prefix="fa"),
    ).add_to(m)

if pickup_loc and dropoff_loc:
    folium.PolyLine(
        [[pickup_loc.latitude, pickup_loc.longitude],
         [dropoff_loc.latitude, dropoff_loc.longitude]],
        color="#4285F4",
        weight=3,
        opacity=0.8,
        dash_array="8",
    ).add_to(m)
    m.fit_bounds([
        [pickup_loc.latitude, pickup_loc.longitude],
        [dropoff_loc.latitude, dropoff_loc.longitude],
    ], padding=[40, 40])

st_folium(m, use_container_width=True, height=300, returned_objects=[])

# ── Guard ───────────────────────────────────────────────────────────
both_selected = pickup_loc is not None and dropoff_loc is not None

if not both_selected:
    st.info("Select both pickup and drop locations above to compare rides.")

    # ── Smart route suggestions ─────────────────────────────────
    suggested = suggest_routes(5)
    if suggested:
        st.markdown("#### 🧠 Suggested Routes")
        st.caption("Based on your ride history and current time:")
        for s in suggested:
            col_route, col_info = st.columns([3, 1])
            with col_route:
                st.markdown(f"📍 {s['pickup']} → 🏁 {s['dropoff']}")
            with col_info:
                st.caption(f"{s['trip_count']} trips · avg ₹{s['avg_price']:.0f}")

    commute = detect_commute_pattern()
    if commute and commute.get("is_commute"):
        st.markdown("#### 🏠↔🏢 Detected Commute")
        st.caption(f"Home: {commute['home']} → Work: {commute['work']}")

    st.stop()

# ── Build Location objects and deep links ───────────────────────────
p_loc = Location(
    address=pickup_loc.short_name,
    latitude=pickup_loc.latitude,
    longitude=pickup_loc.longitude,
)
d_loc = Location(
    address=dropoff_loc.short_name,
    latitude=dropoff_loc.latitude,
    longitude=dropoff_loc.longitude,
)


def _deep_link(provider: ProviderName) -> str:
    pa, pla, plo = urlquote(p_loc.address), p_loc.latitude, p_loc.longitude
    da, dla, dlo = urlquote(d_loc.address), d_loc.latitude, d_loc.longitude

    if provider == ProviderName.UBER:
        return (
            f"https://m.uber.com/ul/?action=setPickup"
            f"&pickup[formatted_address]={pa}"
            f"&pickup[latitude]={pla}&pickup[longitude]={plo}"
            f"&dropoff[formatted_address]={da}"
            f"&dropoff[latitude]={dla}&dropoff[longitude]={dlo}"
        )
    if provider == ProviderName.OLA:
        return f"https://book.olacabs.com/?lat={pla}&lng={plo}&dlat={dla}&dlng={dlo}"
    if provider == ProviderName.RAPIDO:
        return (
            f"https://www.rapido.bike/ride-estimate"
            f"?pickupLat={pla}&pickupLng={plo}"
            f"&dropLat={dla}&dropLng={dlo}"
        )
    if provider == ProviderName.NAMMA_YATRI:
        return (
            f"https://nammayatri.in/ridebook"
            f"?srcLat={pla}&srcLon={plo}"
            f"&destLat={dla}&destLon={dlo}"
        )
    return ""


PROVIDER_STYLE = {
    ProviderName.UBER: {"icon": "🚕", "color": "#000000", "name": "Uber", "source": "live"},
    ProviderName.OLA: {"icon": "🟢", "color": "#6BC24A", "name": "Ola", "source": "live"},
    ProviderName.RAPIDO: {"icon": "🟡", "color": "#FFD700", "name": "Rapido", "source": "estimate"},
    ProviderName.NAMMA_YATRI: {"icon": "🟠", "color": "#FF6B00", "name": "Namma Yatri", "source": "estimate"},
}


# ── Compare Rides button ──────────────────────────────────────────
st.divider()

if st.button(
    "🔍 Compare Rides",
    type="primary",
    use_container_width=True,
    key="compare_btn",
):
    import os
    os.environ["CAB_PRICE_THRESHOLD"] = str(threshold)
    os.environ["HEADLESS_BROWSER"] = str(headless).lower()

    from ride_smart.orchestrator import run_full_flow

    with st.spinner("Fetching live prices from Uber & Ola..."):
        result = asyncio.run(
            run_full_flow(p_loc, d_loc, auto_book=False)
        )

    st.session_state["last_result"] = result
    st.session_state["booking_confirmed"] = None

    # Auto-save comparison to ride history
    try:
        comp: RideComparison = result["comparison"]
        comp_id = save_comparison(
            comp.pickup, comp.dropoff, comp.quotes,
        )
        st.session_state["comparison_id"] = comp_id
    except Exception:
        pass

# ── Show results ──────────────────────────────────────────────────
result = st.session_state.get("last_result")
if not result:
    st.stop()

comparison: RideComparison = result["comparison"]
recommendation: RideRecommendation = result["recommendation"]

if not recommendation.ranked_options:
    st.warning("No ride quotes found. Make sure you're logged into Uber and Ola (check sidebar).")
    if comparison.errors:
        with st.expander("⚠ Provider Errors"):
            for provider, err in comparison.errors.items():
                st.error(f"{provider}: {err}")
    st.stop()

# ── Best option banner ────────────────────────────────────────────
best = recommendation.ranked_options[0]
if recommendation.switched_to_auto:
    st.warning(f"⚠ {recommendation.reason}")
else:
    st.success(f"✅ {recommendation.reason}")

# ── Group quotes by provider ──────────────────────────────────────
provider_quotes: dict[ProviderName, list[RideQuote]] = {}
for q in recommendation.ranked_options:
    provider_quotes.setdefault(q.provider, []).append(q)

# ── Booking result (show first, above ride cards) ─────────────────
booking_result = st.session_state.get("booking_result")

# ── Booking confirmation flow (show instead of ride cards) ────────
booking_quote = st.session_state.get("booking_confirmed")
if booking_quote:
    st.divider()
    st.subheader("📱 Confirm Booking")

    # Pick cheapest per provider within ₹50 of the selected ride
    best_price = booking_quote.price
    race_candidates: dict[ProviderName, RideQuote] = {}
    for q in recommendation.ranked_options:
        if q.price <= best_price + 50 and q.provider not in race_candidates:
            race_candidates[q.provider] = q

    st.markdown(
        f"📍 {pickup_loc.short_name} → 🏁 {dropoff_loc.short_name}"
    )

    st.markdown("**Rides that will be booked simultaneously:**")
    for prov, q in race_candidates.items():
        s = PROVIDER_STYLE.get(prov, {})
        icon = s.get("icon", "")
        name = s.get("name", prov.value)
        selected_tag = " ← your pick" if q is booking_quote else ""
        st.markdown(
            f"- {icon} **{name}** — {q.vehicle_type} — "
            f"**₹{q.price:.0f}**{selected_tag}"
        )

    st.caption(
        "First confirmed ride wins — all others are automatically cancelled."
    )

    col_go, col_cancel = st.columns(2)
    with col_go:
        if st.button("✅ Confirm & Book", key="confirm_booking",
                      type="primary", use_container_width=True):
            import os
            os.environ["HEADLESS_BROWSER"] = "false"

            # Save user's choice to history
            comp_id = st.session_state.get("comparison_id")
            if comp_id:
                cheapest = recommendation.ranked_options[0] if recommendation.ranked_options else None
                try:
                    save_user_choice(
                        comparison_id=comp_id,
                        chosen_provider=booking_quote.provider.value,
                        chosen_vehicle=booking_quote.vehicle_type,
                        chosen_price=booking_quote.price,
                        cheapest_provider=cheapest.provider.value if cheapest else None,
                        cheapest_price=cheapest.price if cheapest else None,
                    )
                except Exception:
                    pass

            from ride_smart.orchestrator import run_race_booking

            logs: list[str] = []
            status_area = st.empty()

            def _log(msg: str):
                logs.append(msg)
                status_area.markdown("\n\n".join(logs))

            with st.spinner("🚗 Booking your ride…"):
                booking_result = asyncio.run(
                    run_race_booking(
                        p_loc, d_loc,
                        recommendation.ranked_options,
                        price_range=50.0,
                        status_callback=_log,
                    )
                )

            st.session_state["booking_result"] = booking_result
            st.session_state["booking_confirmed"] = None
            st.rerun()

    with col_cancel:
        if st.button("← Back to results", key="cancel_booking", use_container_width=True):
            st.session_state["booking_confirmed"] = None
            st.rerun()

    st.stop()

elif booking_result:
    st.divider()
    status = booking_result["status"]

    if status == "confirmed":
        prov = booking_result["provider"].replace("_", " ").title()
        st.success(
            f"🎉 **Ride Booked Successfully!**\n\n"
            f"**{prov}** — {booking_result['vehicle_type']} — "
            f"**₹{booking_result['price']:.0f}**\n\n"
            f"📍 {pickup_loc.short_name} → 🏁 {dropoff_loc.short_name}\n\n"
            f"Driver confirmed in {booking_result['wait_seconds']}s"
        )
    elif status == "timeout":
        st.warning(
            f"⏱ {booking_result['reason']}\n\n"
            "Try opening the app manually:"
        )
        tried = booking_result.get("tried", [])
        if tried:
            cols = st.columns(len(tried))
            for col, prov_val in zip(cols, tried):
                prov = ProviderName(prov_val)
                with col:
                    st.link_button(
                        f"Open {PROVIDER_STYLE[prov]['name']}",
                        _deep_link(prov),
                        use_container_width=True,
                    )
    else:
        st.error(f"❌ {booking_result.get('reason', 'Booking failed')}")
        st.link_button("Open best provider manually", _deep_link(best.provider))

    # Per-provider breakdown
    prov_status = booking_result.get("provider_status", {})
    if prov_status:
        st.markdown("**What happened with each provider:**")
        for prov_key, info in prov_status.items():
            result = info["result"]
            icon = {"booked": "✅", "cancelled": "🚫", "no drivers": "❌",
                    "timed out": "⏱", "booking initiated": "🔄",
                    }.get(result, "⚠️")
            st.markdown(
                f"- {icon} **{info['name']}** ({info['vehicle']}, ₹{info['price']:.0f}) "
                f"— {result}"
            )

    if st.button("Clear result", key="clear_booking"):
        st.session_state["booking_result"] = None
        st.rerun()

    st.divider()

# ── Show each provider's rides ───────────────────────────────────
for provider in [ProviderName.UBER, ProviderName.OLA, ProviderName.RAPIDO, ProviderName.NAMMA_YATRI]:
    quotes = provider_quotes.get(provider)
    if not quotes:
        continue

    style = PROVIDER_STYLE[provider]
    source_tag = " *(estimated)*" if style.get("source") == "estimate" else " *(live)*"
    st.markdown(f"### {style['icon']} {style['name']}{source_tag}")

    for q in quotes:
        is_best = q is best
        ride_emoji = "🚗" if q.ride_type == RideType.CAB else "🛺"

        col_type, col_detail, col_price, col_action = st.columns([1, 4, 2, 2])
        with col_type:
            st.markdown(f"### {ride_emoji}")
        with col_detail:
            badge = " 🏆 **Best Price**" if is_best else ""
            st.markdown(f"**{q.vehicle_type or q.display_name}**{badge}")
            details = []
            if q.eta_minutes:
                details.append(f"🕐 {q.eta_minutes} min")
            if q.is_surge:
                details.append(f"⚡ {q.surge_multiplier}x surge")
            if details:
                st.caption(" · ".join(details))
        with col_price:
            color = "#00c853" if is_best else "#ffffff"
            size = "1.8em" if is_best else "1.4em"
            st.markdown(
                f"<p style='color:{color}; text-align:right; font-size:{size}; "
                f"font-weight:bold; margin:8px 0;'>₹{q.price:.0f}</p>",
                unsafe_allow_html=True,
            )
        with col_action:
            is_estimated = style.get("source") == "estimate"
            if is_estimated:
                st.link_button(
                    "📱 Open app",
                    _deep_link(provider),
                    use_container_width=True,
                )
            elif is_best:
                if st.button("🚀 Book this!", key=f"book_{provider.value}_{q.price}",
                              type="primary", use_container_width=True):
                    st.session_state["booking_confirmed"] = q
                    st.session_state["booking_result"] = None
                    st.rerun()
            else:
                if st.button(f"Book", key=f"book_{provider.value}_{q.price}",
                              use_container_width=True):
                    st.session_state["booking_confirmed"] = q
                    st.session_state["booking_result"] = None
                    st.rerun()
        st.divider()

# ── AI Insights ──────────────────────────────────────────────────
st.divider()
st.markdown("### 🧠 AI Insights")

ai_col1, ai_col2 = st.columns(2)

with ai_col1:
    # Price anomaly detection
    quote_dicts = [
        {"provider": q.provider.value, "price": q.price,
         "vehicle_type": q.vehicle_type}
        for q in recommendation.ranked_options
    ]
    anomalies = detect_anomalies(
        quote_dicts, p_loc.address, d_loc.address
    )
    if anomalies:
        st.markdown("**⚠️ Price Alerts**")
        for a in anomalies:
            icon = "🔴" if a["severity"] == "alert" else "🟡"
            st.markdown(f"{icon} {a['message']}")
    else:
        st.caption("✅ All prices look normal for this route")

    # Should wait recommendation
    wait_advice = should_wait_for_better_price(
        best.price, p_loc.address, d_loc.address
    )
    if wait_advice.get("should_wait"):
        st.warning(f"⏳ **Consider waiting** — {wait_advice['reason']}")
    elif wait_advice.get("typical_price"):
        st.success(f"👍 Good price — typical is ₹{wait_advice['typical_price']:.0f}")

with ai_col2:
    # Price prediction for each provider
    predictions_found = False
    for provider in [ProviderName.UBER, ProviderName.OLA]:
        pred = predict_price(p_loc.address, d_loc.address, provider.value)
        if pred and pred["sample_count"] >= 3:
            predictions_found = True
            conf_pct = int(pred["confidence"] * 100)
            st.markdown(
                f"**{provider.value.title()} forecast:** "
                f"₹{pred['predicted_price']:.0f} "
                f"(±₹{pred['std_dev']:.0f}, {conf_pct}% confidence)"
            )

    # Best time to book
    timing = best_time_to_book(p_loc.address, d_loc.address, best.provider.value)
    if timing and timing["savings"] > 10:
        st.info(
            f"💡 **Best time:** {timing['cheapest_hour']}:00 "
            f"(avg ₹{timing['cheapest_avg']:.0f}) — "
            f"save ₹{timing['savings']:.0f} vs {timing['expensive_hour']}:00"
        )

    if not predictions_found and not timing:
        st.caption("📈 AI predictions will appear after a few ride comparisons")

    # ETA reliability
    for provider in [ProviderName.UBER, ProviderName.OLA]:
        rel = eta_reliability(provider.value)
        if rel and rel["sample_count"] >= 5:
            st.caption(
                f"🕐 {provider.value.title()} ETA: "
                f"avg {rel['avg_eta']:.0f} min ({rel['rating']})"
            )

# AI recommendation from LLM
if quote_dicts:
    with st.expander("🤖 AI Recommendation"):
        if st.button("Get AI analysis", key="ai_rec_btn"):
            with st.spinner("Analyzing with AI..."):
                rec = ai_recommend(
                    quote_dicts,
                    pickup=p_loc.address,
                    dropoff=d_loc.address,
                )
            if rec:
                st.markdown(rec)
            else:
                st.caption("Set GROQ_API_KEY in .env for AI recommendations")

# ── App-only providers note ───────────────────────────────────────
app_only_providers = {"rapido", "namma_yatri"}
missing_providers = [
    PROVIDER_STYLE[ProviderName(p)]["name"]
    for p in app_only_providers
    if ProviderName(p) not in provider_quotes
]
if missing_providers:
    with st.expander(f"📱 {', '.join(missing_providers)} — check in app"):
        st.caption("These providers don't have web login. Open them directly:")
        cols = st.columns(len(missing_providers))
        for col, name in zip(cols, missing_providers):
            prov = next(p for p, s in PROVIDER_STYLE.items() if s["name"] == name)
            with col:
                st.link_button(f"Open {name}", _deep_link(prov), use_container_width=True)

# ── Provider errors ───────────────────────────────────────────────
if comparison.errors:
    web_errors = {k: v for k, v in comparison.errors.items() if k not in app_only_providers}
    if web_errors:
        with st.expander("⚠ Provider Errors"):
            for provider, err in web_errors.items():
                st.error(f"{provider}: {err}")
