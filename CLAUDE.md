# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

A containerised web scraper that monitors multiple campervan-for-sale listing pages and sends push notifications via a self-hosted ntfy.sh server when new listings appear. Designed to run 24/7 on an Unraid server via Docker Compose.

- **ntfy server**: `https://ntfy.taildbe21.ts.net/` (self-hosted, accessible over Tailscale)
- **Target device**: iOS (iPhone) via the ntfy iOS app
- Example monitored page: `https://www.holbrookcustoms.com/campersforsale/`

## Architecture

```
docker-compose.yml
watcher/
  Dockerfile
  watcher.py        # main entrypoint — loops over sites, diffs, notifies
  parser.py         # per-site HTML parsers + spec extraction
  notifier.py       # ntfy HTTP POST
  state.py          # load/save state.json
  sites.yaml        # list of sites to monitor (user-editable)
  requirements.txt
data/
  state.json        # persisted via Docker volume mount
```

### Core flow

1. **Load** site definitions from `sites.yaml`
2. **Fetch** each listing page with `httpx` or `requests`
3. **Parse** HTML with `BeautifulSoup` to extract listing identifiers (URL, title, or a stable ID)
4. **Diff** against previously saved state in `state.json`
5. **Notify** via HTTP POST to the ntfy server for each new listing
6. **Save** updated state back to `state.json`
7. **Sleep** for the configured interval and repeat

### Parser types

| `parser` value | Used for | Index strategy | Detail strategy |
|---|---|---|--|
| `woocommerce` | Holbrook Customs | `li.product` cards, title in `h2.woocommerce-loop-product__title` | Specs under `h2` headings → `ul`/`p` siblings |
| `esw` | Endless Summer Wales | `div.row_auto.VEH-row` cards with icon-based spec divs | `div.vm_mainblock.wrapperSpecifications` key-value rows |
| `wix` | T1 Conversions | `a[data-testid="linkElement"][href*="/vans-for-sale/"]` links | `font_7` label/value richtext div pairs |

### Adding a new site

1. Add an entry to `sites.yaml` with the appropriate `parser` type.
2. If no existing parser fits, add `parse_<type>_index` and `enrich_<type>_detail` functions to `parser.py` and register them in `INDEX_PARSERS` / `DETAIL_ENRICHERS`.

```yaml
sites:
  - name: "My New Site"
    url: "https://example.com/campervans"
    parser: "woocommerce"   # or esw / wix / custom type
    ntfy_topic: "campervans"
```

## Docker / Running

```bash
# Build and start (detached)
docker compose up -d --build

# View logs
docker compose logs -f

# Run watcher once without Docker (for dev/testing)
pip install -r watcher/requirements.txt
python watcher/watcher.py --once

# Restart after editing sites.yaml (no rebuild needed)
docker compose restart
```

State is persisted via a named volume (or bind mount) so it survives container restarts.

## ntfy Notification Format

POST to `https://ntfy.taildbe21.ts.net/<topic>`:

```
Title: <listing title>
Priority: high
Tags: van
Body: <listing URL>
```

## Key Design Decisions

- **No database** — `state.json` is sufficient; a full DB would be over-engineering for this scale.
- **Per-site CSS selectors** — sites differ in structure, so selectors live in config rather than code.
- **Single container** — one Python process loops over all sites sequentially; no need for separate workers.
- **Unraid deployment** — `docker-compose.yml` is the primary deployment artifact; state volume must be mapped to a persistent Unraid path.
