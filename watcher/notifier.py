"""Send push notifications via a self-hosted ntfy.sh server."""

import httpx
import os


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

    # ntfy headers must be ASCII — replace common Unicode chars with equivalents
    safe_title = (
        title
        .replace("–", "-")   # en dash
        .replace("—", "-")   # em dash
        .replace("‘", "'")   # left single quote
        .replace("’", "'")   # right single quote
        .replace("“", '"')   # left double quote
        .replace("”", '"')   # right double quote
        .replace("£", "GBP ") # £
        .encode("ascii", "replace").decode("ascii")  # replace any remaining non-ASCII with ?
    )[:250]

    headers = {
        "Title": safe_title,
        "Priority": "high",
        "Tags": "van,bell",
        "Click": listing["url"],
        "Host": config["ntfy_host"],
    }

    auth = None
    username = os.environ.get("NTFY_USERNAME")
    password = os.environ.get("NTFY_PASSWORD")
    if username and password:
        auth = (username, password)

    with httpx.Client(timeout=15, auth=auth) as client:
        resp = client.post(url, content=body.encode(), headers=headers)
        resp.raise_for_status()
