#!/usr/bin/env python3
"""
Campervan listing watcher.

Usage:
  python watcher.py           # run continuously (reads interval from sites.yaml)
  python watcher.py --once    # run a single check and exit
"""

import argparse
import logging
import time
from pathlib import Path

import httpx
import yaml

import parser as listing_parser
import notifier
import state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SITES_FILE = Path(__file__).parent / "sites.yaml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CampervanWatcher/1.0; "
        "+https://github.com/user/campervanwatcher)"
    )
}


def load_config() -> dict:
    with open(SITES_FILE) as f:
        return yaml.safe_load(f)


def fetch(url: str) -> str:
    with httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def check_site(site: dict, config: dict, saved_state: dict) -> dict:
    site_name = site["name"]
    site_key = site["url"]
    seen_ids: set[str] = set(saved_state.get(site_key, []))

    log.info("Checking %s (%s)", site_name, site["url"])

    try:
        index_html = fetch(site["url"])
    except Exception as e:
        log.error("Failed to fetch index for %s: %s", site_name, e)
        return saved_state

    listings = listing_parser.parse_index(index_html, site)
    log.info("  Found %d listings on index page", len(listings))

    new_ids: list[str] = []
    for listing in listings:
        if listing["id"] not in seen_ids:
            new_ids.append(listing["id"])

    if not new_ids:
        log.info("  No new listings.")
    else:
        log.info("  %d new listing(s) found!", len(new_ids))

    for listing in listings:
        if listing["id"] not in new_ids:
            continue

        log.info("  New listing: %s", listing["title"])

        # Fetch detail page to enrich specs
        try:
            detail_html = fetch(listing["url"])
            listing_parser.enrich_from_detail(listing, detail_html, site)
        except Exception as e:
            log.warning("  Could not fetch detail page for %s: %s", listing["url"], e)

        # Send notification
        try:
            notifier.notify(listing, site, config)
            log.info("  Notified: %s", listing["title"])
        except Exception as e:
            log.error("  Failed to notify for %s: %s", listing["url"], e)

    # Update seen IDs — store all current listing IDs so removed listings
    # don't re-trigger if they come back
    all_current_ids = [l["id"] for l in listings]
    saved_state[site_key] = all_current_ids

    return saved_state


def run_once(config: dict) -> None:
    current_state = state.load()
    for site in config["sites"]:
        current_state = check_site(site, config, current_state)
    state.save(current_state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Campervan listing watcher")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    config = load_config()

    if args.once:
        run_once(config)
        return

    interval_seconds = config.get("check_interval_minutes", 30) * 60
    log.info("Starting watcher. Checking every %d minutes.", interval_seconds // 60)

    while True:
        try:
            run_once(config)
        except Exception as e:
            log.error("Unexpected error during check: %s", e)
        log.info("Sleeping for %d minutes...", interval_seconds // 60)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
