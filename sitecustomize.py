from __future__ import annotations

import json
import tempfile
import time
from functools import lru_cache
from pathlib import Path


CACHE_TTL_SECONDS = 24 * 60 * 60
CACHE_DIR = Path(tempfile.gettempdir()) / "card-marketplace-listing-optimizer"
CACHE_FILE = CACHE_DIR / "scryfall_default_cards.json"
META_FILE = CACHE_DIR / "scryfall_default_cards_meta.json"
MODULE_NAMES = ("pricing_logic_bulk", "pricing_logic")


def _safe_json_load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_json_dump(path: Path, payload) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _load_cached_cards():
    meta = _safe_json_load(META_FILE)
    cards = _safe_json_load(CACHE_FILE)
    if not isinstance(meta, dict) or not isinstance(cards, list):
        return None
    fetched_at = float(meta.get("fetched_at", 0))
    if time.time() - fetched_at > CACHE_TTL_SECONDS:
        return None
    return cards


def _write_cache(cards, *, download_uri: str | None, updated_at: str | None) -> None:
    _safe_json_dump(CACHE_FILE, cards)
    _safe_json_dump(
        META_FILE,
        {
            "fetched_at": time.time(),
            "download_uri": download_uri,
            "updated_at": updated_at,
        },
    )


def _build_indexes(module, cards_payload):
    tcgplayer_lookup = {}
    name_lookup = {}
    for card in cards_payload:
        if not isinstance(card, dict):
            continue
        name = module.safe_text(card.get("name", ""))
        set_name = module.safe_text(card.get("set_name", ""))
        set_code = module.safe_text(card.get("set", "")).lower()
        collector_number = module.safe_text(card.get("collector_number", "")).lower()
        if not name or not set_name or not set_code or not collector_number:
            continue
        entry = {
            "name": name,
            "set_name": set_name,
            "set": set_code,
            "collector_number": collector_number,
            "released_at": module.safe_text(card.get("released_at", "0000-00-00")),
            "slug": module.slugify_for_url(name),
        }
        tcgplayer_id = module.safe_text(card.get("tcgplayer_id", ""))
        if tcgplayer_id:
            tcgplayer_lookup.setdefault(tcgplayer_id, []).append(entry)
        normalized_name = module.normalize_header(name)
        if normalized_name:
            name_lookup.setdefault(normalized_name, []).append(entry)
    return tcgplayer_lookup, name_lookup


def _install_catalog_cache(module) -> None:
    original_fetch_json = module.fetch_json
    bulk_url = getattr(module, "SCRYFALL_BULK_DATA_URL", "https://api.scryfall.com/bulk-data")

    @lru_cache(maxsize=1)
    def cached_load_scryfall_catalog():
        cached_cards = _load_cached_cards()
        if isinstance(cached_cards, list):
            return _build_indexes(module, cached_cards)

        bulk_payload = original_fetch_json(bulk_url)
        if not isinstance(bulk_payload, dict):
            raise ValueError("Unexpected response from Scryfall bulk-data endpoint.")

        bulk_objects = bulk_payload.get("data", [])
        target_object = next((item for item in bulk_objects if item.get("type") == "default_cards"), None)
        if not target_object or not target_object.get("download_uri"):
            raise ValueError("Scryfall default_cards bulk dataset was not available.")

        cards_payload = original_fetch_json(str(target_object["download_uri"]))
        if not isinstance(cards_payload, list):
            raise ValueError("Unexpected response while loading Scryfall default_cards bulk dataset.")

        _write_cache(
            cards_payload,
            download_uri=target_object.get("download_uri"),
            updated_at=target_object.get("updated_at"),
        )
        return _build_indexes(module, cards_payload)

    module.load_scryfall_catalog = cached_load_scryfall_catalog


for module_name in MODULE_NAMES:
    try:
        module = __import__(module_name)
    except Exception:
        continue
    try:
        _install_catalog_cache(module)
    except Exception:
        continue
