"""Project Fronkensteen — HACS installer integration.

Bundles and installs pyscript modules, packages, blueprints, helpers,
and config templates for the Project Fronkensteen AI voice assistant system.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.storage import Store

from . import installer
from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = DOMAIN


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Project Fronkensteen — register services.

    Services are registered here (not in async_setup_entry) so they remain
    available for automation validation even if the config entry is unloaded.
    """
    hass.data.setdefault(DOMAIN, {})

    async def _handle_check(call: ServiceCall) -> dict:
        if "features" not in hass.data.get(DOMAIN, {}):
            return {"error": "not_configured"}
        result = await installer.verify(hass, hass.data[DOMAIN]["features"])
        return {
            "version": VERSION,
            "missing": len(result["missing"]),
            "outdated": len(result["outdated"]),
            "ok": len(result["ok"]),
            "errors": result["errors"],
            "missing_files": result["missing"],
            "outdated_files": result["outdated"],
        }

    async def _handle_repair(call: ServiceCall) -> dict:
        if "features" not in hass.data.get(DOMAIN, {}):
            return {"error": "not_configured"}
        result = await installer.repair(hass, hass.data[DOMAIN]["features"])
        return {"repaired": result["repaired"], "errors": result["errors"]}

    async def _handle_status(call: ServiceCall) -> dict:
        features = hass.data.get(DOMAIN, {}).get("features", [])
        return {
            "version": VERSION,
            "features": features,
            "feature_count": len(features),
            "configured": "features" in hass.data.get(DOMAIN, {}),
        }

    async def _handle_check_helpers(call: ServiceCall) -> dict:
        result = await installer.merge_helpers(hass)
        return {
            "total_new": result["total_new"],
            "files": [
                {"file": f["file"], "new": f["new_keys"], "existing": len(f["existing_keys"])}
                for f in result["files"]
                if f["new_keys"]
            ],
        }

    hass.services.async_register(
        DOMAIN, "check_installation", _handle_check,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "repair_installation", _handle_repair,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "get_status", _handle_status,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "check_helpers", _handle_check_helpers,
        supports_response=SupportsResponse.ONLY,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Project Fronkensteen from a config entry."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    stored = await store.async_load()

    features = entry.data.get("features", [])
    household = entry.data.get("household", {})
    speakers = entry.data.get("speakers", {})
    config_data = {**household, **speakers}

    if not stored:
        _LOGGER.info("Installing Project Fronkensteen v%s", VERSION)
        report = await installer.install(hass, features, config_data)
        _LOGGER.info(
            "Install complete: %d copied, %d skipped, %d errors",
            report["copied"], report["skipped"], len(report["errors"]),
        )
        for err in report["errors"]:
            _LOGGER.warning("Install error: %s", err)
        await store.async_save({"version": VERSION, "features": features})

    elif stored.get("version") != VERSION:
        old = stored.get("version", "unknown")
        _LOGGER.info("Updating Project Fronkensteen %s -> %s", old, VERSION)
        report = await installer.update(hass, old, VERSION, features)
        _LOGGER.info(
            "Update complete: %d copied, %d skipped, %d errors",
            report["copied"], report["skipped"], len(report["errors"]),
        )
        for err in report["errors"]:
            _LOGGER.warning("Update error: %s", err)
        await store.async_save({"version": VERSION, "features": features})

    else:
        _LOGGER.debug("Project Fronkensteen v%s already installed", VERSION)

    # Make features available to services registered in async_setup
    hass.data[DOMAIN]["store"] = store
    hass.data[DOMAIN]["features"] = features

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload. Does NOT remove installed files or services."""
    hass.data.get(DOMAIN, {}).pop("features", None)
    hass.data.get(DOMAIN, {}).pop("store", None)
    return True
