"""
flight_search.py

Queries the Duffel API (https://duffel.com) to find the cheapest way to fly
a route across a wide date window.

For every sampled (depart_date, return_date) pair, this runs THREE searches:
  1. A round-trip search (single ticket, one or two airlines via alliances)
  2. A one-way search for the outbound leg only
  3. A one-way search for the inbound leg only

Combining the cheapest outbound + cheapest inbound (even from two totally
unrelated airlines) is how we "mix and match" — this is the manual
equivalent of what's sometimes called virtual interlining. Whichever is
cheaper (the single round-trip ticket, or the combined self-transfer pair)
wins for that date combination.

IMPORTANT CAVEAT (also in the email + README): a self-transfer itinerary is
TWO SEPARATE BOOKINGS on two separate airlines. If the first flight is
delayed and you miss the second, neither airline is obligated to rebook you
the way they would on a single ticket. The tool flags these clearly.
"""

import os
import re
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE_URL = "https://api.duffel.com"
DUFFEL_VERSION = "v2"


class FlightSearchError(Exception):
    pass


def _get_api_key() -> str:
    key = os.environ.get("DUFFEL_API_KEY")
    if not key:
        raise FlightSearchError(
            "DUFFEL_API_KEY environment variable is not set. "
            "Sign up free at https://app.duffel.com/ and add your access "
            "token as a GitHub Secret named DUFFEL_API_KEY."
        )
    return key


def _headers():
    return {
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "Duffel-Version": DUFFEL_VERSION,
        "Authorization": f"Bearer {_get_api_key()}",
    }


def _parse_iso8601_duration(duration_str: str) -> float:
    """Parses e.g. 'PT11H30M' -> 11.5 (hours). Returns 0.0 if unparseable."""
    if not duration_str:
        return 0.0
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration_str)
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return round(hours + minutes / 60, 1)


def _create_offer_request(slices: list, cabin_class: str, adults: int, supplier_timeout: int = 12000) -> list:
    """POSTs an offer request to Duffel and returns the raw list of offers (unsorted)."""
    payload = {
        "data": {
            "slices": slices,
            "passengers": [{"type": "adult"} for _ in range(adults)],
            "cabin_class": cabin_class,
        }
    }
    params = {"return_offers": "true", "supplier_timeout": supplier_timeout}

    resp = requests.post(
        f"{BASE_URL}/air/offer_requests",
        params=params,
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        # Don't hard-fail the whole search over one bad date combo (e.g. no
        # availability) — just return no offers for it.
        return []
    return resp.json().get("data", {}).get("offers", [])


def _normalize_offer(offer: dict) -> dict:
    airlines = set()
    stops = 0
    duration_hours = 0.0
    for sl in offer.get("slices", []):
        segs = sl.get("segments", [])
        stops += max(len(segs) - 1, 0)
        duration_hours += _parse_iso8601_duration(sl.get("duration"))
        for seg in segs:
            carrier = seg.get("operating_carrier", {}).get("name")
            if carrier:
                airlines.add(carrier)

    return {
        "price": float(offer.get("total_amount", 0)),
        "currency": offer.get("total_currency"),
        "airlines": sorted(airlines),
        "stops": stops,
        "duration_hours": round(duration_hours, 1),
    }


def _cheapest(offers: list, max_stopovers: int) -> dict | None:
    normalized = [_normalize_offer(o) for o in offers]
    normalized = [n for n in normalized if n["stops"] <= max_stopovers]
    if not normalized:
        return None
    return min(normalized, key=lambda n: n["price"])


def _search_one_date_combo(search_cfg: dict, defaults: dict, depart_date: dt.date, return_date: dt.date) -> dict | None:
    origin = search_cfg["origin"]
    destination = search_cfg["destination"]
    cabin = search_cfg.get("cabin", "economy")
    adults = search_cfg.get("adults", defaults.get("adults", 1))
    max_stopovers = search_cfg.get("max_stopovers", defaults.get("max_stopovers", 2))

    dep_str = depart_date.strftime("%Y-%m-%d")
    ret_str = return_date.strftime("%Y-%m-%d")

    # 1. Single-ticket round trip
    rt_offers = _create_offer_request(
        slices=[
            {"origin": origin, "destination": destination, "departure_date": dep_str},
            {"origin": destination, "destination": origin, "departure_date": ret_str},
        ],
        cabin_class=cabin,
        adults=adults,
    )
    rt_best = _cheapest(rt_offers, max_stopovers)

    # 2 & 3. Mix-and-match: cheapest outbound one-way + cheapest inbound one-way,
    # possibly on two different airlines.
    out_offers = _create_offer_request(
        slices=[{"origin": origin, "destination": destination, "departure_date": dep_str}],
        cabin_class=cabin,
        adults=adults,
    )
    in_offers = _create_offer_request(
        slices=[{"origin": destination, "destination": origin, "departure_date": ret_str}],
        cabin_class=cabin,
        adults=adults,
    )
    out_best = _cheapest(out_offers, max_stopovers)
    in_best = _cheapest(in_offers, max_stopovers)

    mixed = None
    if out_best and in_best and out_best["currency"] == in_best["currency"]:
        mixed = {
            "price": round(out_best["price"] + in_best["price"], 2),
            "currency": out_best["currency"],
            "airlines": sorted(set(out_best["airlines"]) | set(in_best["airlines"])),
            "stops": out_best["stops"] + in_best["stops"],
            "duration_hours": round(out_best["duration_hours"] + in_best["duration_hours"], 1),
        }

    candidates = []
    if rt_best:
        candidates.append({**rt_best, "booking_type": "single_ticket"})
    if mixed:
        candidates.append({**mixed, "booking_type": "self_transfer"})

    if not candidates:
        return None

    best = min(candidates, key=lambda c: c["price"])
    best["depart_date"] = dep_str
    best["return_date"] = ret_str
    return best


def search_route(search_cfg: dict, defaults: dict) -> list[dict]:
    """
    Samples dates across the search window for one saved search, running
    round-trip and one-way (self-transfer) queries for each, and returns a
    list of the best result found per date combo, cheapest first.
    """
    window_days = search_cfg.get("search_window_days", defaults.get("search_window_days", 365))
    interval_days = search_cfg.get("date_sample_interval_days", defaults.get("date_sample_interval_days", 14))

    nights_cfg = search_cfg.get("nights", {})
    nights_min = nights_cfg.get("min", 7)
    nights_max = nights_cfg.get("max", nights_min)
    nights_options = sorted({nights_min, nights_max})  # test the two ends of the range

    today = dt.date.today()
    num_samples = max(window_days // interval_days, 1)
    depart_dates = [today + dt.timedelta(days=interval_days * i) for i in range(1, num_samples + 1)]

    combos = [(d, d + dt.timedelta(days=n)) for d in depart_dates for n in nights_options]

    results = []
    max_workers = search_cfg.get("max_parallel_requests", defaults.get("max_parallel_requests", 6))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_search_one_date_combo, search_cfg, defaults, dep, ret): (dep, ret)
            for dep, ret in combos
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                dep, ret = futures[future]
                print(f"  !! search failed for {dep} -> {ret}: {e}")
                result = None
            if result:
                results.append(result)

    results.sort(key=lambda r: r["price"])
    return results


def rank_and_trim(results: list[dict], top_n: int) -> list[dict]:
    """Dedupe near-identical dates and keep the top N cheapest distinct options."""
    seen = set()
    trimmed = []
    for r in results:
        key = (r["depart_date"], r["return_date"])
        if key in seen:
            continue
        seen.add(key)
        trimmed.append(r)
        if len(trimmed) >= top_n:
            break
    return trimmed
