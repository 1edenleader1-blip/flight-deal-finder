"""
flight_search.py

Queries the Travelpayouts Data API (https://www.travelpayouts.com/) to find
the cheapest way to fly a route across a wide date window.

Two kinds of query run for every sampled month in the window:

  1. Round-trip calendar: cheapest single-ticket round trip for each day of
     the month, for a fixed length of stay (v1/prices/calendar).
  2. One-way candidates (GraphQL): cheapest one-way fares for that month, in
     each direction separately (prices_one_way).

Combining the cheapest outbound one-way + cheapest inbound one-way (even
from two different airlines, provided the gap between them falls inside
your nights range) is the "mix and match" logic — this is the manual
equivalent of what's sometimes called virtual interlining. Whichever is
cheaper overall (the single round-trip ticket, or the combined pair) wins.

IMPORTANT CAVEAT (also in the email + README): a self-transfer itinerary is
TWO SEPARATE BOOKINGS on two separate airlines/tickets. If the first flight
is delayed and you miss the second, neither airline is obligated to rebook
you the way they would on a single ticket. The tool flags these clearly.

NOTE: Travelpayouts serves this data from a cache of recent real searches
(refreshed within the last ~48 hours to 7 days), not a live GDS query like
Duffel. It's meant for exactly this kind of "what's roughly cheap and
when" deal-spotting — always verify the exact price before booking.
"""

import os
import datetime as dt

import requests

BASE_URL = "https://api.travelpayouts.com"
GRAPHQL_URL = f"{BASE_URL}/graphql/v1/query"


class FlightSearchError(Exception):
    pass


def _get_token() -> str:
    token = os.environ.get("TRAVELPAYOUTS_TOKEN")
    if not token:
        raise FlightSearchError(
            "TRAVELPAYOUTS_TOKEN environment variable is not set. "
            "Sign up free at https://www.travelpayouts.com/, grab your API "
            "token from your account's API section, and add it as a "
            "GitHub Secret named TRAVELPAYOUTS_TOKEN."
        )
    return token


def _headers():
    return {"X-Access-Token": _get_token()}


def _month_strings(window_days: int) -> list[str]:
    """Returns 'YYYY-MM' strings for every month touched by the search window."""
    today = dt.date.today()
    end = today + dt.timedelta(days=window_days)
    months = []
    cur = today.replace(day=1)
    while cur <= end:
        months.append(cur.strftime("%Y-%m"))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return months


def _round_trip_calendar(origin: str, destination: str, month: str, nights: int, currency: str) -> list[dict]:
    """Cheapest round-trip price for each day of `month`, for a fixed length of stay."""
    params = {
        "origin": origin,
        "destination": destination,
        "depart_date": month,
        "calendar_type": "departure_date",
        "length": nights,
        "currency": currency,
    }
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/prices/calendar", params=params, headers=_headers(), timeout=20
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"  !! round-trip calendar request failed for {origin}->{destination} {month}: {e}")
        return []

    if not payload.get("success"):
        return []

    results = []
    for depart_date, entry in (payload.get("data") or {}).items():
        if not entry:
            continue
        results.append({
            "depart_date": depart_date,
            "return_date": entry.get("return_at", "")[:10],
            "price": entry.get("price"),
            "currency": currency,
            "airlines": [entry.get("airline")] if entry.get("airline") else [],
            "stops": entry.get("transfers", 0),
            "booking_type": "single_ticket",
            "booking_links": [],
        })
    return results


def _one_way_candidates(origin: str, destination: str, month: str, currency: str, limit: int = 8) -> list[dict]:
    """Cheapest one-way fares found for `month`, via GraphQL, cheapest first."""
    query = """
    query($origin: String!, $destination: String!, $month: String!, $limit: Int!) {
      prices_one_way(
        params: { origin: $origin, destination: $destination, depart_months: $month }
        paging: { limit: $limit, offset: 0 }
        sorting: VALUE_ASC
      ) {
        departure_at
        value
        trip_duration
        ticket_link
      }
    }
    """
    variables = {
        "origin": origin,
        "destination": destination,
        "month": f"{month}-01",
        "limit": limit,
    }
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables},
            headers={**_headers(), "Content-Type": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"  !! one-way GraphQL request failed for {origin}->{destination} {month}: {e}")
        return []

    raw = (payload.get("data") or {}).get("prices_one_way") or []
    candidates = []
    for item in raw:
        departure_at = item.get("departure_at", "")
        if not departure_at:
            continue
        link = item.get("ticket_link", "")
        booking_link = f"https://www.aviasales.com/search/{link.lstrip('/')}" if link else None
        candidates.append({
            "date": departure_at[:10],
            "price": item.get("value"),
            "booking_link": booking_link,
        })
    return candidates


def _combine_self_transfer(out_candidates: list[dict], in_candidates: list[dict],
                            nights_min: int, nights_max: int, currency: str) -> list[dict]:
    """Pairs up outbound/inbound one-ways that fall inside the nights window."""
    combos = []
    for o in out_candidates:
        try:
            depart_date = dt.date.fromisoformat(o["date"])
        except ValueError:
            continue
        for i in in_candidates:
            try:
                return_date = dt.date.fromisoformat(i["date"])
            except ValueError:
                continue
            nights = (return_date - depart_date).days
            if nights_min <= nights <= nights_max:
                combos.append({
                    "depart_date": o["date"],
                    "return_date": i["date"],
                    "price": round((o["price"] or 0) + (i["price"] or 0), 2),
                    "currency": currency,
                    "airlines": [],
                    "stops": None,
                    "booking_type": "self_transfer",
                    "booking_links": [l for l in [o.get("booking_link"), i.get("booking_link")] if l],
                })
    combos.sort(key=lambda c: c["price"])
    return combos[:20]  # keep the search space this returns bounded


def search_route(search_cfg: dict, defaults: dict) -> list[dict]:
    """
    Runs both the round-trip and self-transfer searches across every month
    in the configured window, and returns everything found, cheapest first.
    """
    origin = search_cfg["origin"]
    destination = search_cfg["destination"]
    currency = search_cfg.get("currency", defaults.get("currency", "USD"))
    window_days = search_cfg.get("search_window_days", defaults.get("search_window_days", 365))

    nights_cfg = search_cfg.get("nights", {})
    nights_min = nights_cfg.get("min", 7)
    nights_max = nights_cfg.get("max", nights_min)
    nights_options = sorted({nights_min, nights_max})

    months = _month_strings(window_days)

    all_results = []

    for month in months:
        for nights in nights_options:
            all_results.extend(_round_trip_calendar(origin, destination, month, nights, currency))

        out_candidates = _one_way_candidates(origin, destination, month, currency)
        in_candidates = _one_way_candidates(destination, origin, month, currency)
        all_results.extend(
            _combine_self_transfer(out_candidates, in_candidates, nights_min, nights_max, currency)
        )

    all_results = [r for r in all_results if r.get("price")]
    all_results.sort(key=lambda r: r["price"])
    return all_results


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
