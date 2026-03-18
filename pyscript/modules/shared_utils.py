"""Shared utility functions for pyscript modules.

Helper functions shared across multiple pyscript modules.
Imported via: from shared_utils import build_result_entity_name, load_entity_config
Imported via: from shared_utils import discover_persons, get_person_slugs, get_person_tracker, get_person_config
"""
import time
from pathlib import Path

import yaml

_CONFIG_PATH = Path("/config/pyscript/entity_config.yaml")
_config_cache: dict | None = None


def load_entity_config() -> dict:
    """Load entity_config.yaml. Cached after first read.

    Returns the full config dict, or empty dict on error.
    Call reload_entity_config() to force re-read after file changes.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        with open(_CONFIG_PATH) as f:
            _config_cache = yaml.safe_load(f) or {}
    except Exception:
        _config_cache = {}
    return _config_cache


def reload_entity_config() -> dict:
    """Force re-read of entity_config.yaml. Returns the new config."""
    global _config_cache
    _config_cache = None
    return load_entity_config()


def parse_csv_helper(entity_id: str, prefix: str = "") -> list:
    """Read a CSV input_text helper and return a list of stripped, non-empty values.

    Args:
        entity_id: Full entity ID of the input_text helper.
        prefix: Optional domain prefix to auto-prepend (e.g. "media_player.").

    Returns:
        List of strings. Empty list on error or if helper is unavailable.
    """
    try:
        raw = state.get(entity_id) or ""  # noqa: F821
        if raw and raw not in ("unknown", "unavailable", ""):
            result = []
            for s in raw.split(","):
                s = s.strip()
                if s:
                    if prefix and not s.startswith(prefix):
                        s = prefix + s
                    result.append(s)
            return result
    except Exception:
        pass
    return []


# ── Person Discovery (Task 22) ──────────────────────────────────────────────

_persons_cache: dict | None = None
_persons_cache_ts: float = 0.0
_PERSONS_CACHE_TTL = 300  # 5 minutes


def discover_persons() -> dict[str, dict]:
    """Discover persons from HA person.* entities, overlay non-discoverable config.

    Returns: {"miquel": {"entity_id": "person.miquel", "friendly_name": "Miquel",
              "trackers": ["device_tracker.oppo_a60"], "state": "home",
              "slug": "miquel", "calendar": "...", "notify_service": "...", ...}, ...}
    """
    global _persons_cache, _persons_cache_ts
    now = time.monotonic()
    if _persons_cache is not None and (now - _persons_cache_ts) < _PERSONS_CACHE_TTL:
        return _persons_cache

    # Discover from person.* entities
    persons = {}
    try:
        for eid in state.names("person"):  # noqa: F821
            slug = eid.split(".", 1)[1]
            attrs = state.getattr(eid) or {}  # noqa: F821
            persons[slug] = {
                "entity_id": eid,
                "slug": slug,
                "friendly_name": attrs.get("friendly_name", slug.title()),
                "trackers": attrs.get("device_trackers", []),
                "state": state.get(eid),  # noqa: F821
            }
    except Exception:
        pass

    # Overlay non-discoverable config from entity_config.yaml
    cfg = load_entity_config()
    overlay = cfg.get("persons", {})
    for slug, pdata in persons.items():
        pdata.update(overlay.get(slug, {}))

    _persons_cache = persons
    _persons_cache_ts = now
    return persons


def reload_persons() -> dict[str, dict]:
    """Force cache invalidation and re-discover persons."""
    global _persons_cache
    _persons_cache = None
    return discover_persons()


def get_person_slugs() -> list[str]:
    """Return sorted list of person slugs (e.g. ['jessica', 'miquel'])."""
    return sorted(discover_persons().keys())


def get_person_tracker(slug: str) -> str | None:
    """Return the primary device tracker for a person slug, or None."""
    p = discover_persons().get(slug)
    return p["trackers"][0] if p and p.get("trackers") else None


def get_person_config(slug: str, key: str, default=None):
    """Return a config value for a person slug (e.g. 'calendar', 'notify_service')."""
    return discover_persons().get(slug, {}).get(key, default)


# ── Entity Name Helper ──────────────────────────────────────────────────────

def build_result_entity_name(entity_id: str) -> dict:
    """Build a friendly_name dict from a sensor/result entity ID.

    Args:
        entity_id: Full entity ID (e.g. "sensor.ai_duck_manager_result").

    Returns:
        Dict with "friendly_name" key for use in state.set(new_attributes=...).
    """
    tail = entity_id.split(".")[-1]
    parts = [part.capitalize() for part in tail.split("_") if part]
    return {"friendly_name": " ".join(parts) or tail}
