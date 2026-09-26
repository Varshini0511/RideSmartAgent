"""Location search with multiple geocoding backends.

Provides Uber/Ola-quality location suggestions for any partial query
like 'T Nagar', 'OMR', 'Sholinganallur', street names, landmarks, etc.

Priority: Google Places API (if enabled) > Photon (free, no key) >
local DB + Nominatim fallback.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from ride_smart.config import get_settings

logger = logging.getLogger(__name__)

PLACES_AUTOCOMPLETE_NEW_URL = "https://places.googleapis.com/v1/places:autocomplete"
PLACE_DETAILS_NEW_URL = "https://places.googleapis.com/v1/places"
PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

CITY_COORDS = {
    "Chennai": (13.0827, 80.2707),
    "Bengaluru": (12.9716, 77.5946),
    "Mumbai": (19.0760, 72.8777),
    "Delhi": (28.6139, 77.2090),
    "Hyderabad": (17.3850, 78.4867),
}

# Local database of popular places — always returns results, like Ola/Uber
POPULAR_PLACES: dict[str, list[dict]] = {
    "Chennai": [
        {"name": "T Nagar", "full": "T Nagar, Chennai", "lat": 13.0418, "lon": 80.2341},
        {"name": "Adyar", "full": "Adyar, Chennai", "lat": 13.0012, "lon": 80.2565},
        {"name": "Velachery", "full": "Velachery, Chennai", "lat": 12.9815, "lon": 80.2180},
        {"name": "Guindy", "full": "Guindy, Chennai", "lat": 13.0067, "lon": 80.2206},
        {"name": "OMR (Old Mahabalipuram Road)", "full": "OMR, Sholinganallur, Chennai", "lat": 12.9010, "lon": 80.2279},
        {"name": "Sholinganallur", "full": "Sholinganallur, Chennai", "lat": 12.9010, "lon": 80.2279},
        {"name": "Anna Nagar", "full": "Anna Nagar, Chennai", "lat": 13.0850, "lon": 80.2101},
        {"name": "Mylapore", "full": "Mylapore, Chennai", "lat": 13.0368, "lon": 80.2676},
        {"name": "Tambaram", "full": "Tambaram, Chennai", "lat": 12.9249, "lon": 80.1000},
        {"name": "Porur", "full": "Porur, Chennai", "lat": 13.0382, "lon": 80.1564},
        {"name": "Vadapalani", "full": "Vadapalani, Chennai", "lat": 13.0512, "lon": 80.2126},
        {"name": "Chromepet", "full": "Chromepet, Chennai", "lat": 12.9516, "lon": 80.1462},
        {"name": "Pallavaram", "full": "Pallavaram, Chennai", "lat": 12.9675, "lon": 80.1491},
        {"name": "Medavakkam", "full": "Medavakkam, Chennai", "lat": 12.9209, "lon": 80.1924},
        {"name": "Perungudi", "full": "Perungudi, Chennai", "lat": 12.9612, "lon": 80.2409},
        {"name": "Thoraipakkam", "full": "Thoraipakkam, Chennai", "lat": 12.9326, "lon": 80.2341},
        {"name": "Thiruvanmiyur", "full": "Thiruvanmiyur, Chennai", "lat": 12.9830, "lon": 80.2594},
        {"name": "Nungambakkam", "full": "Nungambakkam, Chennai", "lat": 13.0569, "lon": 80.2425},
        {"name": "Egmore", "full": "Egmore, Chennai", "lat": 13.0732, "lon": 80.2609},
        {"name": "Central Railway Station", "full": "Chennai Central Railway Station", "lat": 13.0827, "lon": 80.2755},
        {"name": "Chennai Airport", "full": "Chennai International Airport (MAA)", "lat": 12.9941, "lon": 80.1709},
        {"name": "Koyambedu", "full": "Koyambedu, Chennai", "lat": 13.0694, "lon": 80.1948},
        {"name": "CMBT (Koyambedu Bus Stand)", "full": "CMBT Koyambedu Bus Stand, Chennai", "lat": 13.0694, "lon": 80.1968},
        {"name": "Ambattur", "full": "Ambattur, Chennai", "lat": 13.0982, "lon": 80.1545},
        {"name": "Avadi", "full": "Avadi, Chennai", "lat": 13.1067, "lon": 80.1017},
        {"name": "Perambur", "full": "Perambur, Chennai", "lat": 13.1112, "lon": 80.2383},
        {"name": "Washermanpet", "full": "Washermanpet, Chennai", "lat": 13.1186, "lon": 80.2847},
        {"name": "Besant Nagar", "full": "Besant Nagar, Chennai", "lat": 13.0002, "lon": 80.2668},
        {"name": "ECR (East Coast Road)", "full": "ECR, Neelankarai, Chennai", "lat": 12.9500, "lon": 80.2589},
        {"name": "Neelankarai", "full": "Neelankarai, Chennai", "lat": 12.9500, "lon": 80.2589},
        {"name": "Palavakkam", "full": "Palavakkam, Chennai", "lat": 12.9611, "lon": 80.2584},
        {"name": "Ashok Nagar", "full": "Ashok Nagar, Chennai", "lat": 13.0384, "lon": 80.2098},
        {"name": "KK Nagar", "full": "KK Nagar, Chennai", "lat": 13.0381, "lon": 80.2037},
        {"name": "Kodambakkam", "full": "Kodambakkam, Chennai", "lat": 13.0497, "lon": 80.2253},
        {"name": "Saidapet", "full": "Saidapet, Chennai", "lat": 13.0223, "lon": 80.2230},
        {"name": "Alandur", "full": "Alandur, Chennai", "lat": 13.0020, "lon": 80.2039},
        {"name": "Nanganallur", "full": "Nanganallur, Chennai", "lat": 12.9839, "lon": 80.1923},
        {"name": "Taramani", "full": "Taramani, Chennai", "lat": 12.9862, "lon": 80.2434},
        {"name": "IIT Madras", "full": "IIT Madras, Chennai", "lat": 12.9915, "lon": 80.2337},
        {"name": "Tidel Park", "full": "Tidel Park, Taramani, Chennai", "lat": 12.9871, "lon": 80.2466},
        {"name": "Sipcot IT Park", "full": "Sipcot IT Park, Siruseri, Chennai", "lat": 12.8358, "lon": 80.2263},
        {"name": "Navalur", "full": "Navalur, Chennai", "lat": 12.8455, "lon": 80.2267},
        {"name": "Siruseri", "full": "Siruseri, Chennai", "lat": 12.8358, "lon": 80.2263},
        {"name": "Kelambakkam", "full": "Kelambakkam, Chennai", "lat": 12.7872, "lon": 80.2209},
        {"name": "Mahabalipuram", "full": "Mahabalipuram, Chennai", "lat": 12.6172, "lon": 80.1927},
        {"name": "Mount Road (Anna Salai)", "full": "Anna Salai, Mount Road, Chennai", "lat": 13.0600, "lon": 80.2500},
        {"name": "Marina Beach", "full": "Marina Beach, Chennai", "lat": 13.0499, "lon": 80.2824},
        {"name": "Royapettah", "full": "Royapettah, Chennai", "lat": 13.0531, "lon": 80.2627},
        {"name": "Triplicane", "full": "Triplicane, Chennai", "lat": 13.0555, "lon": 80.2768},
        {"name": "George Town", "full": "George Town, Chennai", "lat": 13.0927, "lon": 80.2838},
        {"name": "Kilpauk", "full": "Kilpauk, Chennai", "lat": 13.0793, "lon": 80.2409},
        {"name": "Chetpet", "full": "Chetpet, Chennai", "lat": 13.0718, "lon": 80.2430},
        {"name": "Kotturpuram", "full": "Kotturpuram, Chennai", "lat": 13.0162, "lon": 80.2422},
        {"name": "Teynampet", "full": "Teynampet, Chennai", "lat": 13.0401, "lon": 80.2518},
        {"name": "Alwarpet", "full": "Alwarpet, Chennai", "lat": 13.0349, "lon": 80.2530},
        {"name": "West Mambalam", "full": "West Mambalam, Chennai", "lat": 13.0386, "lon": 80.2224},
        {"name": "Mogappair", "full": "Mogappair, Chennai", "lat": 13.0803, "lon": 80.1706},
        {"name": "Padi", "full": "Padi, Chennai", "lat": 13.0934, "lon": 80.2025},
        {"name": "Villivakkam", "full": "Villivakkam, Chennai", "lat": 13.1113, "lon": 80.2099},
        {"name": "Kolathur", "full": "Kolathur, Chennai", "lat": 13.1214, "lon": 80.2140},
        {"name": "Madhavaram", "full": "Madhavaram, Chennai", "lat": 13.1496, "lon": 80.2279},
        {"name": "Manali", "full": "Manali, Chennai", "lat": 13.1665, "lon": 80.2623},
        {"name": "Ennore", "full": "Ennore, Chennai", "lat": 13.2135, "lon": 80.3221},
        {"name": "Tondiarpet", "full": "Tondiarpet, Chennai", "lat": 13.1270, "lon": 80.2900},
        {"name": "Purasawalkam", "full": "Purasawalkam, Chennai", "lat": 13.0900, "lon": 80.2569},
        {"name": "Sowcarpet", "full": "Sowcarpet, Chennai", "lat": 13.0938, "lon": 80.2778},
        {"name": "Thousand Lights", "full": "Thousand Lights, Chennai", "lat": 13.0594, "lon": 80.2556},
        {"name": "Guindy National Park", "full": "Guindy National Park, Chennai", "lat": 13.0050, "lon": 80.2343},
        {"name": "Phoenix Market City", "full": "Phoenix Market City Mall, Velachery, Chennai", "lat": 12.9924, "lon": 80.2190},
        {"name": "Express Avenue Mall", "full": "Express Avenue Mall, Royapettah, Chennai", "lat": 13.0583, "lon": 80.2653},
        {"name": "VR Chennai", "full": "VR Chennai Mall, Anna Nagar, Chennai", "lat": 13.0905, "lon": 80.2156},
        {"name": "Forum Vijaya Mall", "full": "Forum Vijaya Mall, Vadapalani, Chennai", "lat": 13.0511, "lon": 80.2131},
        {"name": "Spencer Plaza", "full": "Spencer Plaza, Mount Road, Chennai", "lat": 13.0615, "lon": 80.2580},
        {"name": "DLF IT Park", "full": "DLF IT Park, Mount Poonamallee Road, Chennai", "lat": 13.0497, "lon": 80.1667},
        {"name": "RMZ Millenia", "full": "RMZ Millenia, Perungudi, Chennai", "lat": 12.9680, "lon": 80.2417},
        {"name": "Ramanujan IT City", "full": "Ramanujan IT City, Taramani, Chennai", "lat": 12.9883, "lon": 80.2456},
        {"name": "Apollo Hospital", "full": "Apollo Hospital, Greams Road, Chennai", "lat": 13.0610, "lon": 80.2520},
        {"name": "MIOT Hospital", "full": "MIOT International Hospital, Manapakkam, Chennai", "lat": 13.0210, "lon": 80.1690},
        {"name": "Fortis Malar Hospital", "full": "Fortis Malar Hospital, Adyar, Chennai", "lat": 13.0070, "lon": 80.2520},
        # Universities & colleges
        {"name": "Anna University", "full": "Anna University, Guindy, Chennai", "lat": 13.0125, "lon": 80.2353},
        {"name": "University of Madras", "full": "University of Madras, Chepauk, Chennai", "lat": 13.0627, "lon": 80.2798},
        {"name": "Loyola College", "full": "Loyola College, Nungambakkam, Chennai", "lat": 13.0626, "lon": 80.2337},
        {"name": "Stella Maris College", "full": "Stella Maris College, Cathedral Road, Chennai", "lat": 13.0568, "lon": 80.2368},
        {"name": "SRM University", "full": "SRM University, Kattankulathur, Chennai", "lat": 12.8230, "lon": 80.0444},
        {"name": "Sathyabama University", "full": "Sathyabama University, Sholinganallur, Chennai", "lat": 12.8711, "lon": 80.2209},
        {"name": "VIT Chennai", "full": "VIT Chennai, Kelambakkam", "lat": 12.8406, "lon": 80.1534},
        {"name": "Hindustan University", "full": "Hindustan University, Padur, Chennai", "lat": 12.7896, "lon": 80.2255},
        {"name": "MCC (Madras Christian College)", "full": "Madras Christian College, Tambaram, Chennai", "lat": 12.9190, "lon": 80.1218},
        # Railway & metro stations
        {"name": "Mambalam Railway Station", "full": "Mambalam Railway Station, Chennai", "lat": 13.0333, "lon": 80.2224},
        {"name": "Tambaram Railway Station", "full": "Tambaram Railway Station, Chennai", "lat": 12.9258, "lon": 80.1160},
        {"name": "Guindy Railway Station", "full": "Guindy Railway Station, Chennai", "lat": 13.0092, "lon": 80.2121},
        {"name": "Nungambakkam Railway Station", "full": "Nungambakkam Railway Station, Chennai", "lat": 13.0569, "lon": 80.2381},
        {"name": "Egmore Railway Station", "full": "Chennai Egmore Railway Station", "lat": 13.0774, "lon": 80.2604},
        # Hospitals
        {"name": "Kauvery Hospital", "full": "Kauvery Hospital, Alwarpet, Chennai", "lat": 13.0336, "lon": 80.2504},
        {"name": "SIMS Hospital", "full": "SIMS Hospital, Vadapalani, Chennai", "lat": 13.0498, "lon": 80.2098},
        {"name": "Vijaya Hospital", "full": "Vijaya Hospital, Vadapalani, Chennai", "lat": 13.0510, "lon": 80.2087},
        {"name": "Global Hospital", "full": "Global Hospital, Perumbakkam, Chennai", "lat": 12.9100, "lon": 80.2010},
        {"name": "Billroth Hospital", "full": "Billroth Hospital, Shenoy Nagar, Chennai", "lat": 13.0889, "lon": 80.2322},
        # More areas
        {"name": "Ramapuram", "full": "Ramapuram, Chennai", "lat": 13.0310, "lon": 80.1792},
        {"name": "Manapakkam", "full": "Manapakkam, Chennai", "lat": 13.0167, "lon": 80.1680},
        {"name": "Valasaravakkam", "full": "Valasaravakkam, Chennai", "lat": 13.0461, "lon": 80.1751},
        {"name": "Virugambakkam", "full": "Virugambakkam, Chennai", "lat": 13.0514, "lon": 80.1966},
        {"name": "Shenoy Nagar", "full": "Shenoy Nagar, Chennai", "lat": 13.0867, "lon": 80.2297},
        {"name": "Arumbakkam", "full": "Arumbakkam, Chennai", "lat": 13.0698, "lon": 80.2127},
        {"name": "Aminjikarai", "full": "Aminjikarai, Chennai", "lat": 13.0750, "lon": 80.2250},
        {"name": "Thiruverkadu", "full": "Thiruverkadu, Chennai", "lat": 13.0694, "lon": 80.1200},
        {"name": "Poonamallee", "full": "Poonamallee, Chennai", "lat": 13.0465, "lon": 80.0970},
        {"name": "Kundrathur", "full": "Kundrathur, Chennai", "lat": 12.9977, "lon": 80.0991},
        {"name": "Perumbakkam", "full": "Perumbakkam, Chennai", "lat": 12.9121, "lon": 80.2010},
        {"name": "Pallikaranai", "full": "Pallikaranai, Chennai", "lat": 12.9346, "lon": 80.2092},
        {"name": "Madipakkam", "full": "Madipakkam, Chennai", "lat": 12.9624, "lon": 80.1979},
        {"name": "Selaiyur", "full": "Selaiyur, Chennai", "lat": 12.9078, "lon": 80.1534},
        {"name": "Urapakkam", "full": "Urapakkam, Chennai", "lat": 12.8700, "lon": 80.0688},
        {"name": "Guduvanchery", "full": "Guduvanchery, Chennai", "lat": 12.8452, "lon": 80.0561},
        {"name": "Karapakkam", "full": "Karapakkam, OMR, Chennai", "lat": 12.9260, "lon": 80.2280},
        {"name": "Padur", "full": "Padur, OMR, Chennai", "lat": 12.8261, "lon": 80.2157},
        # Temples & landmarks
        {"name": "Kapaleeshwarar Temple", "full": "Kapaleeshwarar Temple, Mylapore, Chennai", "lat": 13.0338, "lon": 80.2693},
        {"name": "Parthasarathy Temple", "full": "Parthasarathy Temple, Triplicane, Chennai", "lat": 13.0558, "lon": 80.2763},
        {"name": "Valluvar Kottam", "full": "Valluvar Kottam, Nungambakkam, Chennai", "lat": 13.0501, "lon": 80.2373},
        # Government / offices
        {"name": "Chennai High Court", "full": "Madras High Court, Chennai", "lat": 13.0876, "lon": 80.2888},
        {"name": "Secretariat", "full": "Tamil Nadu Secretariat, Fort St George, Chennai", "lat": 13.0797, "lon": 80.2877},
        {"name": "US Consulate", "full": "US Consulate, Gemini Circle, Chennai", "lat": 13.0598, "lon": 80.2517},
    ],
}


@dataclass
class LocationSuggestion:
    display_name: str
    short_name: str
    latitude: float
    longitude: float
    place_id: str

    @property
    def label(self) -> str:
        return self.short_name


def search_location(
    query: str,
    limit: int = 8,
    city: str | None = None,
) -> list[LocationSuggestion]:
    """Search for locations matching a partial query.

    Uses Google Places API if an API key is configured (recommended),
    otherwise combines a local popular-places database with
    OpenStreetMap Nominatim for Uber/Ola-quality results.

    Results are ranked by query relevance, not source priority —
    a precise Nominatim match beats a loose local DB match.
    """
    if not query or len(query.strip()) < 2:
        return []

    settings = get_settings()
    api_key = settings.google_maps_api_key

    if api_key and not _google_api_failed:
        results = _google_places_search(query, api_key, limit, city)
        if results:
            return results

    search_city = city or settings.default_city
    local = _local_db_search(query, search_city, limit * 2)
    photon = _photon_search(query, limit, city)

    q = query.strip().lower()
    scored: list[tuple[float, LocationSuggestion]] = []

    for sug in local:
        scored.append((_relevance_score(q, sug), sug))
    for sug in photon:
        scored.append((_relevance_score(q, sug), sug))

    scored.sort(key=lambda x: x[0])

    merged: list[LocationSuggestion] = []
    for _, sug in scored:
        if _is_duplicate(sug, merged):
            continue
        merged.append(sug)
        if len(merged) >= limit:
            break

    # If not enough results, supplement with Nominatim
    if len(merged) < 3 and not photon:
        nominatim = _nominatim_search(query, limit - len(merged), city)
        for sug in nominatim:
            if not _is_duplicate(sug, merged):
                merged.append(sug)
            if len(merged) >= limit:
                break

    return merged


def geocode_address(
    address: str,
    city: str | None = None,
) -> LocationSuggestion | None:
    """Geocode a typed address to coordinates via Photon / Nominatim.

    Use this as a fallback when search_location doesn't return
    the user's exact address — lets them type any full address
    and get coordinates for it.
    """
    settings = get_settings()
    search_city = city or settings.default_city

    # Try Photon first (better results, no rate limit issues)
    photon = _photon_search(address, 1, city)
    if photon:
        return photon[0]

    # Fallback to Nominatim
    for q in (
        f"{address.strip()}, {search_city}, India",
        address.strip(),
    ):
        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"q": q, "format": "json", "limit": 1, "countrycodes": "in"},
                headers=_HEADERS,
                timeout=5,
            )
            resp.raise_for_status()
            results = resp.json()
        except Exception:
            continue

        if results:
            r = results[0]
            short = _shorten_name(r.get("display_name", ""), search_city)
            return LocationSuggestion(
                display_name=r.get("display_name", address),
                short_name=short,
                latitude=float(r["lat"]),
                longitude=float(r["lon"]),
                place_id=str(r.get("place_id", f"geo_{address}")),
            )

    return None


def _relevance_score(query: str, sug: LocationSuggestion) -> float:
    """Lower score = better match. Ranks by how closely the suggestion
    matches the full query, regardless of source."""
    name = sug.short_name.lower()
    display = sug.display_name.lower()

    if query == name:
        return 0.0
    if name.startswith(query):
        return 1.0
    if query in name:
        return 2.0
    if query in display:
        return 2.5

    q_tokens = set(query.split())
    name_tokens = set(name.replace("(", "").replace(")", "").replace(",", "").split())
    display_tokens = set(display.replace("(", "").replace(")", "").replace(",", "").split())

    name_overlap = len(q_tokens & name_tokens) / len(q_tokens) if q_tokens else 0
    display_overlap = len(q_tokens & display_tokens) / len(q_tokens) if q_tokens else 0

    if name_overlap >= 0.8:
        return 3.0
    if display_overlap >= 0.8:
        return 3.5
    if name_overlap > 0:
        return 4.0 + (1.0 - name_overlap)
    if display_overlap > 0:
        return 5.0 + (1.0 - display_overlap)

    return 10.0


def _is_duplicate(
    candidate: LocationSuggestion,
    existing: list[LocationSuggestion],
    coord_threshold: float = 0.003,
) -> bool:
    """Check if candidate is a duplicate of any existing suggestion."""
    c_name = candidate.short_name.lower().split(",")[0].strip()
    for ex in existing:
        ex_name = ex.short_name.lower().split(",")[0].strip()
        # Same name prefix
        if c_name == ex_name:
            return True
        # Very close coordinates (within ~300m)
        if (abs(candidate.latitude - ex.latitude) < coord_threshold
                and abs(candidate.longitude - ex.longitude) < coord_threshold):
            return True
    return False


def _local_db_search(
    query: str,
    city: str,
    limit: int,
) -> list[LocationSuggestion]:
    """Fuzzy match against the built-in popular places database."""
    places = POPULAR_PLACES.get(city, [])
    if not places:
        return []

    q = query.strip().lower()
    scored: list[tuple[int, dict]] = []

    for place in places:
        name_lower = place["name"].lower()
        full_lower = place["full"].lower()

        if q == name_lower:
            scored.append((0, place))
        elif name_lower.startswith(q):
            scored.append((1, place))
        elif q in name_lower:
            scored.append((2, place))
        elif q in full_lower:
            scored.append((3, place))
        else:
            # Token match: any word in the query matches any word in the name
            q_tokens = set(q.split())
            name_tokens = set(name_lower.replace("(", "").replace(")", "").split())
            if q_tokens & name_tokens:
                scored.append((4, place))

    scored.sort(key=lambda x: x[0])

    return [
        LocationSuggestion(
            display_name=p["full"],
            short_name=p["name"],
            latitude=p["lat"],
            longitude=p["lon"],
            place_id=f"local_{p['name'].lower().replace(' ', '_')}",
        )
        for _, p in scored[:limit]
    ]


# ── Photon (free geocoding, no API key needed) ────────────────────────

_PHOTON_HEADERS = {"User-Agent": "RideSmartAgent/0.1 (ride comparison app)"}


def _photon_search(
    query: str,
    limit: int = 5,
    city: str | None = None,
) -> list[LocationSuggestion]:
    """Search Photon (Komoot) — free geocoding based on OpenStreetMap."""
    settings = get_settings()
    search_city = city or settings.default_city
    center = CITY_COORDS.get(search_city)

    params: dict = {
        "q": query.strip(),
        "limit": limit,
        "lang": "en",
    }
    if center:
        params["lat"] = center[0]
        params["lon"] = center[1]

    try:
        resp = requests.get(
            PHOTON_URL, params=params, headers=_PHOTON_HEADERS, timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"Photon search failed for '{query}': {e}")
        return []

    suggestions: list[LocationSuggestion] = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        name = props.get("name", "")
        street = props.get("street", "")
        district = props.get("district", "")
        city_name = props.get("city", props.get("county", ""))
        state = props.get("state", "")

        if not name and not street:
            continue

        # Build display name from components
        parts = [p for p in (name, street, district, city_name) if p]
        display = ", ".join(parts)
        short = name or street or district

        # Skip results far from the target city
        if center:
            dist = abs(lat - center[0]) + abs(lon - center[1])
            if dist > 2.0:
                continue

        suggestions.append(LocationSuggestion(
            display_name=display,
            short_name=short,
            latitude=lat,
            longitude=lon,
            place_id=f"photon_{props.get('osm_id', '')}",
        ))

    return suggestions


# ── Google Places API ─────────────────────────────────────────────────
# Tries the New API first, then falls back to the Legacy API.

LEGACY_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
LEGACY_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

_google_api_failed = False


def _google_places_search(
    query: str,
    api_key: str,
    limit: int = 5,
    city: str | None = None,
) -> list[LocationSuggestion]:
    results = _google_places_new(query, api_key, limit, city)
    if results:
        return results
    return _google_places_legacy(query, api_key, limit, city)


def _google_places_new(
    query: str,
    api_key: str,
    limit: int = 5,
    city: str | None = None,
) -> list[LocationSuggestion]:
    settings = get_settings()
    search_city = city or settings.default_city
    center = CITY_COORDS.get(search_city, (13.0827, 80.2707))

    body = {
        "input": query.strip(),
        "locationBias": {
            "circle": {
                "center": {"latitude": center[0], "longitude": center[1]},
                "radius": 50000.0,
            }
        },
        "includedRegionCodes": ["in"],
        "languageCode": "en",
    }

    try:
        resp = requests.post(
            PLACES_AUTOCOMPLETE_NEW_URL,
            json=body,
            headers={
                "X-Goog-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        if "403" in str(e) or "401" in str(e):
            logger.info("Google Places API (New) not enabled, trying legacy")
        else:
            logger.warning(f"Google Places (New) autocomplete failed: {e}")
        return []

    suggestions_raw = data.get("suggestions", [])[:limit]
    suggestions = []

    for sug in suggestions_raw:
        pred = sug.get("placePrediction", {})
        if not pred:
            continue

        place_id = pred.get("placeId", "")
        main_text = pred.get("structuredFormat", {}).get("mainText", {}).get("text", "")
        secondary_text = pred.get("structuredFormat", {}).get("secondaryText", {}).get("text", "")
        full_text = pred.get("text", {}).get("text", "")

        short = main_text or full_text
        display = full_text or f"{main_text}, {secondary_text}"

        coords = _get_place_coords_new(place_id, api_key)
        if coords is None:
            continue

        suggestions.append(LocationSuggestion(
            display_name=display,
            short_name=short,
            latitude=coords[0],
            longitude=coords[1],
            place_id=place_id,
        ))

    return suggestions


def _get_place_coords_new(place_id: str, api_key: str) -> tuple[float, float] | None:
    try:
        url = f"{PLACE_DETAILS_NEW_URL}/{place_id}"
        resp = requests.get(
            url,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "location",
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Google Place Details (New) failed for {place_id}: {e}")
        return None

    loc = data.get("location", {})
    lat, lng = loc.get("latitude"), loc.get("longitude")
    if lat is not None and lng is not None:
        return (lat, lng)
    return None


def _google_places_legacy(
    query: str,
    api_key: str,
    limit: int = 5,
    city: str | None = None,
) -> list[LocationSuggestion]:
    """Legacy Google Places Autocomplete API (maps.googleapis.com)."""
    settings = get_settings()
    search_city = city or settings.default_city
    center = CITY_COORDS.get(search_city, (13.0827, 80.2707))

    params = {
        "input": query.strip(),
        "key": api_key,
        "location": f"{center[0]},{center[1]}",
        "radius": 50000,
        "components": "country:in",
        "language": "en",
    }

    try:
        resp = requests.get(LEGACY_AUTOCOMPLETE_URL, params=params, timeout=5)
        data = resp.json()
    except Exception as e:
        logger.warning(f"Google Places (Legacy) failed: {e}")
        return []

    status = data.get("status", "")
    if status != "OK":
        if status in ("REQUEST_DENIED", "OVER_QUERY_LIMIT"):
            global _google_api_failed
            _google_api_failed = True
            logger.info(f"Google Places API disabled ({status}) — using Photon + local DB")
        return []

    suggestions = []
    for pred in data.get("predictions", [])[:limit]:
        place_id = pred.get("place_id", "")
        description = pred.get("description", "")
        main_text = pred.get("structured_formatting", {}).get("main_text", "")

        coords = _get_place_coords_legacy(place_id, api_key)
        if coords is None:
            continue

        suggestions.append(LocationSuggestion(
            display_name=description,
            short_name=main_text or description.split(",")[0],
            latitude=coords[0],
            longitude=coords[1],
            place_id=place_id,
        ))

    return suggestions


def _get_place_coords_legacy(place_id: str, api_key: str) -> tuple[float, float] | None:
    try:
        resp = requests.get(
            LEGACY_DETAILS_URL,
            params={"place_id": place_id, "fields": "geometry", "key": api_key},
            timeout=5,
        )
        data = resp.json()
    except Exception:
        return None

    if data.get("status") != "OK":
        return None
    loc = data.get("result", {}).get("geometry", {}).get("location", {})
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is not None and lng is not None:
        return (lat, lng)
    return None


# ── Nominatim (multi-strategy for better results) ──────────────────

_HEADERS = {"User-Agent": "RideSmartAgent/0.1"}


def _nominatim_search(
    query: str,
    limit: int = 5,
    city: str | None = None,
) -> list[LocationSuggestion]:
    """Search Nominatim with multiple strategies and merge results."""
    settings = get_settings()
    search_city = city or settings.default_city
    center = CITY_COORDS.get(search_city)

    seen_ids: set[str] = set()
    all_suggestions: list[LocationSuggestion] = []

    # Strategy 1: query + city + India (general)
    _nominatim_query(
        f"{query.strip()}, {search_city}, India",
        limit, search_city, seen_ids, all_suggestions,
    )

    # Strategy 2: structured query with viewbox bias around city
    if center and len(all_suggestions) < limit:
        time.sleep(0.3)
        viewbox = (
            f"{center[1] - 0.3},{center[0] + 0.3},"
            f"{center[1] + 0.3},{center[0] - 0.3}"
        )
        _nominatim_query(
            query.strip(),
            limit - len(all_suggestions), search_city, seen_ids, all_suggestions,
            extra_params={"viewbox": viewbox, "bounded": 1},
        )

    # Strategy 3: just the raw query (for well-known places)
    if len(all_suggestions) < limit:
        time.sleep(0.3)
        _nominatim_query(
            f"{query.strip()}, India",
            limit - len(all_suggestions), search_city, seen_ids, all_suggestions,
        )

    # Strategy 4: street-level search (for specific addresses)
    if len(all_suggestions) < 2 and len(query.strip().split()) >= 2:
        time.sleep(0.3)
        _nominatim_query(
            query.strip(),
            limit - len(all_suggestions), search_city, seen_ids, all_suggestions,
            extra_params={"addressdetails": 1},
        )

    return all_suggestions[:limit]


def _nominatim_query(
    q: str,
    limit: int,
    city: str,
    seen_ids: set[str],
    out: list[LocationSuggestion],
    extra_params: dict | None = None,
) -> None:
    params = {
        "q": q,
        "format": "json",
        "addressdetails": 1,
        "limit": limit,
        "countrycodes": "in",
    }
    if extra_params:
        params.update(extra_params)

    try:
        resp = requests.get(
            NOMINATIM_URL, params=params, headers=_HEADERS, timeout=5,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        logger.warning(f"Nominatim search failed for '{q}': {e}")
        return

    for r in results:
        pid = str(r.get("place_id", ""))
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        short = _shorten_name(r.get("display_name", ""), city)
        out.append(LocationSuggestion(
            display_name=r.get("display_name", ""),
            short_name=short,
            latitude=float(r["lat"]),
            longitude=float(r["lon"]),
            place_id=pid,
        ))


def _shorten_name(full_name: str, city: str) -> str:
    parts = [p.strip() for p in full_name.split(",")]
    if len(parts) <= 2:
        return full_name

    skip = {"india", "tamil nadu", "karnataka", "telangana", "maharashtra",
            "andhra pradesh", "kerala", "west bengal", "gujarat", "rajasthan"}
    kept = []
    for part in parts:
        if part.lower() in skip:
            continue
        if part.strip().isdigit():
            continue
        kept.append(part)
        if len(kept) >= 3:
            break

    return ", ".join(kept) if kept else full_name
