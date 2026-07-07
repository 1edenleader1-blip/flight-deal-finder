"""
main.py

Entry point. Loads config.yaml, runs every saved search against the Duffel
API, ranks results, builds the email, and sends it. Run manually with:

    python main.py

or let the GitHub Actions workflow run it weekly.
"""

import sys
import yaml

from flight_search import search_route, rank_and_trim, FlightSearchError
from emailer import build_html, send_email


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    defaults = config.get("defaults", {})
    searches = config.get("searches", [])
    email_cfg = config.get("email", {})

    if not searches:
        print("No searches defined in config.yaml — nothing to do.")
        sys.exit(0)

    results_by_search = {}

    for search_cfg in searches:
        name = search_cfg.get("name", f"{search_cfg.get('origin')} -> {search_cfg.get('destination')}")
        top_n = search_cfg.get("results_per_search", defaults.get("results_per_search", 5))
        print(f"Searching: {name} ...")
        try:
            itineraries = search_route(search_cfg, defaults)
            top = rank_and_trim(itineraries, top_n)
            print(f"  -> {len(itineraries)} raw results, {len(top)} kept")
            results_by_search[name] = top
        except FlightSearchError as e:
            print(f"  !! Search failed: {e}")
            results_by_search[name] = []

    html = build_html(results_by_search)

    subject_prefix = email_cfg.get("subject_prefix", "Weekly Flight Deals")
    import datetime as dt
    subject = f"{subject_prefix} — {dt.date.today().strftime('%d %b %Y')}"

    recipients = email_cfg.get("recipients", [])
    if not recipients:
        print("No recipients configured in config.yaml under email.recipients — skipping send.")
        print(html)
        sys.exit(0)

    send_email(subject, html, recipients)
    print(f"Email sent to: {', '.join(recipients)}")


if __name__ == "__main__":
    main()
