"""Send push notifications via a self-hosted ntfy.sh server."""

import httpx


def _format_specs(listing: dict) -> str:
    parts = []
    for label, key in [
        ("Year", "year"),
        ("Price", "price"),
        ("Engine", "engine"),
        ("Power", "power"),
        ("Transmission", "transmission"),
        ("Fuel", "fuel"),
        ("Mileage", "mileage"),
        ("Tailgate", "tailgate"),
        ("Type", "vehicle_type"),
        ("Reg", "registration"),
        ("Colour", "color"),
    ]:
        val = listing.get(key)
        if val:
            parts.append(f"{label}: {val}")
    return " | ".join(parts) if parts else ""


def notify(listing: dict, site: dict, config: dict) -> None:
    server = config["ntfy_server"].rstrip("/")
    topic = site.get("ntfy_topic") or config.get("ntfy_topic", "campervans")
    url = f"{server}/{topic}"

    site_name = site.get("name", "Unknown site")
    title = f"NEW: {listing['title']}"
    specs = _format_specs(listing)
    body = f"[{site_name}]\n{specs}\n{listing['url']}".strip() if specs else f"[{site_name}]\n{listing['url']}"

    headers = {
        "Title": title[:250],
        "Priority": "high",
        "Tags": "van,bell",
        "Click": listing["url"],
    }

    with httpx.Client(timeout=15) as client:
        resp = client.post(url, content=body.encode(), headers=headers)
        resp.raise_for_status()
