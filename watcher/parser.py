"""
HTML parsing for campervan listing pages.

Each parser returns a list of dicts with at minimum:
  id  — stable unique identifier (usually the listing URL)
  url — full URL to the detail page
  title — listing title

After fetching the detail page, enrich_from_detail() adds spec fields (best-effort).

To add a new site type:
  1. Write parse_<type>_index(html, site) -> list[dict]
  2. Write enrich_<type>_detail(listing, html, site) -> dict  (or reuse a generic one)
  3. Register both in INDEX_PARSERS and DETAIL_ENRICHERS at the bottom.
"""

import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Shared regex helpers
# ---------------------------------------------------------------------------

def _extract_price(text: str) -> str | None:
    m = re.search(r"£[\d,]+", text)
    return m.group(0) if m else None


def _extract_mileage(text: str) -> str | None:
    m = re.search(r"([\d,]+)\s*miles?", text, re.IGNORECASE)
    return m.group(0) if m else None


def _extract_year(text: str) -> str | None:
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return m.group(0) if m else None


def _extract_engine(text: str) -> str | None:
    # e.g. "2.0 TDI", "2.0L TDCi", "1.9 TDI", "2.5 TDI", "2.0L 150BHP Euro6"
    m = re.search(r"\b(\d\.\d\s*(?:L\s*)?(?:TDI|TDCi|TSI|TFSI|HDi|CDTi|dCi|BlueHDi)?)\b", text, re.IGNORECASE)
    return m.group(0).strip() if m else None


def _extract_transmission(text: str) -> str | None:
    m = re.search(r"\b(automatic|manual|dsg|auto)\b", text, re.IGNORECASE)
    return m.group(0).title() if m else None


def _extract_tailgate(text: str) -> str | None:
    m = re.search(r"\b(tailgate|barn\s*doors?|split\s*doors?)\b", text, re.IGNORECASE)
    return m.group(0).title() if m else None


def _extract_power(text: str) -> str | None:
    m = re.search(r"\b(\d{2,3})\s*(bhp|ps|hp|kw)\b", text, re.IGNORECASE)
    return m.group(0) if m else None


def _all_text(element) -> str:
    return " ".join(element.stripped_strings)


def _enrich_from_text(listing: dict[str, Any], text: str) -> None:
    """Fill spec fields from free-form text. Non-destructive — never overwrites existing values."""
    if not listing.get("price"):
        listing["price"] = _extract_price(text)
    if not listing.get("mileage"):
        listing["mileage"] = _extract_mileage(text)
    if not listing.get("year"):
        listing["year"] = _extract_year(text)
    if not listing.get("engine"):
        listing["engine"] = _extract_engine(text)
    if not listing.get("transmission"):
        listing["transmission"] = _extract_transmission(text)
    if not listing.get("tailgate"):
        listing["tailgate"] = _extract_tailgate(text)
    if not listing.get("power"):
        listing["power"] = _extract_power(text)


# ---------------------------------------------------------------------------
# WooCommerce parser — Holbrook Customs and similar stores
# ---------------------------------------------------------------------------

def parse_woocommerce_index(html: str, site: dict) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    listings = []

    cards = soup.select(site.get("listing_selector", "li.product"))
    for card in cards:
        link_el = card.select_one("h2.woocommerce-loop-product__title")
        if not link_el:
            continue
        anchor = link_el.find_parent("a") or card.select_one("a[href]")
        if not anchor:
            continue

        url = anchor.get("href", "").strip()
        if not url or url == "#":
            continue

        title = _all_text(link_el)
        listing: dict[str, Any] = {"id": url, "url": url, "title": title}
        _enrich_from_text(listing, title)

        # Thumbnail from the product card image
        img = card.select_one("img.attachment-woocommerce_thumbnail")
        if img:
            listing["image_url"] = img.get("src", "").strip()

        listings.append(listing)

    return listings


def enrich_woocommerce_detail(listing: dict[str, Any], html: str, site: dict) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one("h1.product_title, h1.entry-title")
    if title_el:
        listing["title"] = _all_text(title_el)

    # Collect spec bullet points from sections under h2 headings
    spec_lines: list[str] = []
    for heading in soup.select("h2"):
        sibling = heading.find_next_sibling()
        while sibling and sibling.name in ("ul", "p", "div"):
            spec_lines.append(sibling.get_text(" ", strip=True))
            sibling = sibling.find_next_sibling()
            if sibling and sibling.name == "h2":
                break

    all_spec_text = " ".join(spec_lines)
    combined = f"{listing.get('title', '')} {all_spec_text} {soup.get_text(' ', strip=True)}"
    _enrich_from_text(listing, combined)
    listing["specs_raw"] = spec_lines
    return listing


# ---------------------------------------------------------------------------
# Endless Summer Wales parser — custom VehicleManager CMS
# Specs are structured key-value pairs on both index and detail pages.
# ---------------------------------------------------------------------------

def parse_esw_index(html: str, site: dict) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    listings = []
    base_url = site["url"]

    for card in soup.select("div.row_auto.VEH-row"):
        anchor = card.select_one('a[href*="/view_vehicle/"]')
        if not anchor:
            continue

        url = urljoin(base_url, anchor.get("href", "").strip())
        if not url:
            continue

        # Title link in the text column
        title_el = card.select_one("a.category")
        title = _all_text(title_el) if title_el else anchor.get("title", "").strip()

        listing: dict[str, Any] = {"id": url, "url": url, "title": title}

        # Thumbnail from the card image
        img = card.select_one("img.little")
        if img:
            src = img.get("src", "").strip()
            if src:
                listing["image_url"] = urljoin(base_url, src)

        # Structured specs available on the index card
        spec_map = _parse_esw_spec_icons(card)
        listing.update(spec_map)

        # Skip sold listings
        if card.select_one("span.price:-soup-contains('SOLD')") or \
                "sold" in card.get_text().lower():
            listing["sold"] = True

        listings.append(listing)

    return listings


def _parse_esw_spec_icons(container) -> dict[str, Any]:
    """Extract structured specs from ESW's icon+span layout."""
    specs: dict[str, Any] = {}
    spec_block = container.select_one("div.vm_type_catlist")
    if not spec_block:
        return specs

    for div in spec_block.select("div"):
        icon = div.select_one("i")
        span = div.select_one("span:not(.col_10)")
        if not icon or not span:
            continue
        icon_classes = " ".join(icon.get("class", []))
        value = span.get_text(strip=True)
        if not value:
            continue

        if "fa-calendar" in icon_classes:
            specs["year"] = value
        elif "fa-tachometer" in icon_classes:
            specs["mileage"] = value + " miles"
        elif "fa-cog" in icon_classes:
            specs["transmission"] = value.title()
        elif "fa-gas-pump" in icon_classes:
            specs["fuel"] = value.title()
        elif "fa-wrench" in icon_classes:
            specs["engine"] = value

    # Price
    price_el = container.select_one("div.vm_price span.col_07")
    if price_el:
        price_text = price_el.get_text(strip=True)
        if price_text and "SOLD" not in price_text.upper():
            specs["price"] = f"£{price_text}"

    return specs


def enrich_esw_detail(listing: dict[str, Any], html: str, site: dict) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # Title
    title_el = soup.select_one("h1")
    if title_el:
        listing["title"] = _all_text(title_el)

    # Structured spec table: label in col_01, value in col_02
    spec_container = soup.select_one("div.vm_mainblock.wrapperSpecifications")
    if spec_container:
        for row in spec_container.select("div.row_inline"):
            label_el = row.select_one("span.col_01")
            value_el = row.select_one("span.col_02")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).rstrip(":").lower()
            value = value_el.get_text(strip=True)

            if "transmission" in label and not listing.get("transmission"):
                listing["transmission"] = value.title()
            elif "fuel" in label and not listing.get("fuel"):
                listing["fuel"] = value.title()
            elif "engine" in label and not listing.get("engine"):
                listing["engine"] = value
            elif "mileage" in label and not listing.get("mileage"):
                listing["mileage"] = value + " miles"
            elif "registration" in label and not listing.get("registration"):
                listing["registration"] = value
            elif "vehicle type" in label and not listing.get("vehicle_type"):
                listing["vehicle_type"] = value

    # Fall back to regex for anything still missing
    _enrich_from_text(listing, soup.get_text(" ", strip=True))
    return listing


# ---------------------------------------------------------------------------
# Wix / T1 Conversions parser
# Specs are in sibling richtext divs with font_7 labels + values.
# ---------------------------------------------------------------------------

def parse_wix_index(html: str, site: dict) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    listings = []
    base_url = "https://www.t1conversions.com"

    seen_urls: set[str] = set()
    for anchor in soup.select('a[data-testid="linkElement"][href*="/vans-for-sale/"]'):
        href = anchor.get("href", "").strip()
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)

        url = urljoin(base_url, href)

        # Find the h2 title within the same section, ignoring "SOLD" badges
        title = ""
        section = anchor.find_parent("section")
        if section:
            for h2 in section.select("h2.wixui-rich-text__text"):
                candidate = _all_text(h2)
                # Skip pure SOLD badges — real titles contain year or van make
                if candidate and candidate.upper() not in ("SOLD", "AVAILABLE", ""):
                    title = candidate
                    break
        if not title:
            # Fall back to the URL slug, humanised
            slug = href.rstrip("/").split("/")[-1].replace("-", " ").title()
            title = slug or url

        listing: dict[str, Any] = {"id": url, "url": url, "title": title}
        _enrich_from_text(listing, title)

        # Thumbnail from the section image
        section = anchor.find_parent("section")
        if section:
            img = section.select_one("img[src]")
            if img:
                listing["image_url"] = img.get("src", "").strip()

        listings.append(listing)

    return listings


def enrich_wix_detail(listing: dict[str, Any], html: str, site: dict) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # Title from h1
    title_el = soup.select_one("h1.wixui-rich-text__text")
    if title_el:
        listing["title"] = _all_text(title_el)

    # Price: an h2 containing £
    for h2 in soup.select("h2.wixui-rich-text__text"):
        text = h2.get_text(strip=True)
        if "£" in text and not listing.get("price"):
            listing["price"] = text
            break

    # Structured specs: label divs (font_7) followed by value divs (font_7)
    # Walk all richtext divs and pair "Label:" text with the next non-label value
    rich_divs = soup.select('div[data-testid="richTextElement"]')
    label_map = {
        "year": "year",
        "mileage": "mileage",
        "gearbox": "transmission",
        "transmission": "transmission",
        "fuel type": "fuel",
        "engine size": "engine",
        "colour": "color",
        "color": "color",
    }

    for i, div in enumerate(rich_divs):
        text = div.get_text(strip=True).rstrip(":")
        key = text.lower()
        if key in label_map and i + 1 < len(rich_divs):
            field = label_map[key]
            if not listing.get(field):
                value = rich_divs[i + 1].get_text(strip=True)
                # Make sure next div isn't another label
                if value and not value.lower().rstrip(":") in label_map:
                    listing[field] = value

    # Fall back to regex for anything still missing
    _enrich_from_text(listing, soup.get_text(" ", strip=True))
    return listing


# ---------------------------------------------------------------------------
# Welsh Coast Campers parser — WordPress with custom van post type
# All specs are structured on the index card; detail page adds feature list.
# ---------------------------------------------------------------------------

def parse_wcc_index(html: str, site: dict) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    listings = []

    for card in soup.select("article.van"):
        anchor = card.select_one('a.button.button--small[href*="/conversions/"]')
        if not anchor:
            continue

        url = anchor.get("href", "").strip()
        if not url:
            continue

        title_el = card.select_one("h3.van-info__title")
        title = _all_text(title_el) if title_el else url

        listing: dict[str, Any] = {"id": url, "url": url, "title": title}

        # Price
        price_el = card.select_one("p.van-info__price")
        if price_el:
            listing["price"] = price_el.get_text(strip=True)

        # Structured specs from labelled list items
        for li in card.select("ul.van-info__specs li"):
            label_el = li.select_one("span")
            if not label_el:
                continue
            label = label_el.get_text(strip=True).rstrip(":").lower()
            # Value is the text node after the span
            value = li.get_text(strip=True).replace(label_el.get_text(strip=True), "").strip()
            if not value or value in ("-", "TBC", "N/A"):
                continue
            if "engine" in label and not listing.get("engine"):
                listing["engine"] = value
            elif "trans" in label and not listing.get("transmission"):
                listing["transmission"] = value
            elif "fuel" in label and not listing.get("fuel"):
                listing["fuel"] = value
            elif "mileage" in label and not listing.get("mileage"):
                listing["mileage"] = value + " miles"
            elif "reg" in label and not listing.get("registration"):
                listing["registration"] = value

        # Year from title
        _enrich_from_text(listing, title)

        # Thumbnail
        img = card.select_one("div.van-image img")
        if img:
            listing["image_url"] = img.get("src", "").strip()

        listings.append(listing)

    return listings


def enrich_wcc_detail(listing: dict[str, Any], html: str, site: dict) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # Feature checklist items (e.g. "Pop Top Roof", "Tailgate", "4 Berth")
    features = [
        _all_text(span)
        for span in soup.select("div.conversion-items ul.grid li span")
        if span.get_text(strip=True)
    ]
    if features:
        listing["specs_raw"] = features
        # Check for tailgate in features
        for f in features:
            if not listing.get("tailgate") and re.search(r"tailgate|barn door", f, re.IGNORECASE):
                listing["tailgate"] = f

    return listing


# ---------------------------------------------------------------------------
# Wild Tracks Campervans parser — WooCommerce + Avada theme
# Specs are in JSON-LD schema on the detail page; index has price + sold badge.
# ---------------------------------------------------------------------------

def parse_wildtracks_index(html: str, site: dict) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    listings = []

    for card in soup.select("li.product-grid-view.product"):
        anchor = card.select_one("h4.fusion-rollover-title a.fusion-rollover-title-link")
        if not anchor:
            continue

        url = anchor.get("href", "").strip()
        if not url:
            continue

        title = _all_text(anchor)
        listing: dict[str, Any] = {"id": url, "url": url, "title": title}

        # Price
        price_el = card.select_one("span.woocommerce-Price-amount")
        if price_el:
            listing["price"] = "£" + price_el.get_text(strip=True).replace("£", "").strip()

        # Sold badge
        sold_el = card.select_one(".fusion-out-of-stock .fusion-position-text")
        if sold_el and "sold" in sold_el.get_text(strip=True).lower():
            listing["sold"] = True

        # Thumbnail — try data-orig-src first (lazy-load), fall back to src
        img = card.select_one("img.wp-post-image")
        if img:
            listing["image_url"] = (
                img.get("data-orig-src") or img.get("src", "")
            ).strip()

        _enrich_from_text(listing, title)
        listings.append(listing)

    return listings


def enrich_wildtracks_detail(listing: dict[str, Any], html: str, site: dict) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # Parse JSON-LD schema — description field contains newline-separated specs
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, AttributeError):
            continue
        if data.get("@type") != "Product":
            continue

        desc = data.get("description", "")
        for line in desc.splitlines():
            line = line.strip()
            if not line:
                continue
            if not listing.get("mileage") and re.search(r"\d+\s*mi", line, re.IGNORECASE):
                listing["mileage"] = line
            elif not listing.get("transmission") and re.search(r"\b(automatic|manual|dsg)\b", line, re.IGNORECASE):
                listing["transmission"] = line.title()
            elif not listing.get("fuel") and re.search(r"\b(diesel|petrol|electric|hybrid)\b", line, re.IGNORECASE):
                listing["fuel"] = line.title()
            elif not listing.get("engine") and re.search(r"\d+\.\d+", line):
                listing["engine"] = line

        # Price and image from schema if not already set
        offer = (data.get("offers") or [{}])
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        if not listing.get("price") and offer.get("price"):
            listing["price"] = f"£{offer['price']}"
        if not listing.get("image_url") and data.get("image"):
            listing["image_url"] = data["image"]

        break  # only need first Product schema

    # Tailgate and other features from the free-text description divs
    feature_divs = soup.select("div.fusion-content-tb div")
    features = [d.get_text(strip=True).lstrip("–").strip() for d in feature_divs if d.get_text(strip=True)]
    if features:
        listing.setdefault("specs_raw", features)
        for f in features:
            if not listing.get("tailgate") and re.search(r"tailgate|barn door", f, re.IGNORECASE):
                listing["tailgate"] = f.title()

    return listing


# ---------------------------------------------------------------------------
# Parser registry — add new parser types here
# ---------------------------------------------------------------------------

INDEX_PARSERS = {
    "woocommerce": parse_woocommerce_index,
    "esw": parse_esw_index,
    "wix": parse_wix_index,
    "wcc": parse_wcc_index,
    "wildtracks": parse_wildtracks_index,
}

DETAIL_ENRICHERS = {
    "woocommerce": enrich_woocommerce_detail,
    "esw": enrich_esw_detail,
    "wix": enrich_wix_detail,
    "wcc": enrich_wcc_detail,
    "wildtracks": enrich_wildtracks_detail,
}


def parse_index(html: str, site: dict) -> list[dict[str, Any]]:
    parser_type = site.get("parser", "woocommerce")
    parser = INDEX_PARSERS.get(parser_type)
    if not parser:
        raise ValueError(f"Unknown parser type: {parser_type!r}")
    return parser(html, site)


def enrich_from_detail(listing: dict[str, Any], html: str, site: dict) -> dict[str, Any]:
    parser_type = site.get("parser", "woocommerce")
    enricher = DETAIL_ENRICHERS.get(parser_type, enrich_woocommerce_detail)
    return enricher(listing, html, site)
