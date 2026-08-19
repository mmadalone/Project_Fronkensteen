"""Project Fronkensteen — HACS installer integration.

Bundles and installs pyscript modules, packages, blueprints, helpers,
and config templates for the Project Fronkensteen AI voice assistant system.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from . import installer, seeder
from .const import DOMAIN, VERSION

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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

        # A repair can restore a helper file containing helpers this install has
        # never seen, which arrive with no value at all. Seeding here gives them
        # their defaults. Existing helpers are safe: seeder skips any entity it
        # has seeded before AND any whose value is no longer the bare fallback.
        seeded = 0
        store = hass.data.get(DOMAIN, {}).get("store")
        if store is not None:
            record = await store.async_load() or {}
            done = record.get("seeded_helpers", [])
            seed_report = await seeder.seed(hass, done)
            if seed_report["seeded"]:
                record["seeded_helpers"] = sorted(set(done) | set(seed_report["seeded"]))
                await store.async_save(record)
            seeded = len(seed_report["seeded"]) - seed_report["skipped"]
            result["errors"] = result["errors"] + seed_report["errors"]

        return {
            "repaired": result["repaired"],
            "helpers_seeded": seeded,
            "errors": result["errors"],
        }

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
    # Fail loudly if the payload is missing, BEFORE anything is persisted.
    #
    # installer.install()/update() only append "Bundle directory not found" to
    # report["errors"], which the code below logs as a warning while still
    # saving {"version": VERSION}. The entry then loads green having copied
    # nothing, and because storage now records the current version, a corrected
    # re-release at the same version takes the `else` branch and never retries.
    # Raising here leaves storage untouched so HA retries setup instead.
    bundle = installer._bundle_path(hass)  # pure path join, no I/O
    if not await hass.async_add_executor_job(bundle.is_dir):
        raise ConfigEntryNotReady(f"Bundle directory not found: {bundle}")

    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    stored = await store.async_load()

    features = entry.data.get("features", [])
    household = entry.data.get("household", {})
    speakers = entry.data.get("speakers", {})
    config_data = {**household, **speakers}

    # Carry a running record rather than saving fresh literals, so keys a branch
    # does not care about (notably seeded_helpers) survive an install or update
    # instead of being silently dropped.
    record = dict(stored or {})
    is_first_install = not stored

    async def _save(**changes) -> None:
        record.update(changes)
        await store.async_save(record)

    if not stored:
        _LOGGER.info("Installing Project Fronkensteen v%s", VERSION)
        report = await installer.install(hass, features, config_data)
        _LOGGER.info(
            "Install complete: %d copied, %d skipped, %d errors",
            report["copied"], report["skipped"], len(report["errors"]),
        )
        for err in report["errors"]:
            _LOGGER.warning("Install error: %s", err)
        await _save(version=VERSION, features=features)

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
        await _save(version=VERSION, features=features)

    else:
        _LOGGER.debug("Project Fronkensteen v%s already installed", VERSION)

    # Make features available to services registered in async_setup
    hass.data[DOMAIN]["store"] = store
    hass.data[DOMAIN]["features"] = features

    # Decide ONCE whether this installation is eligible for first-run defaults.
    #
    # Only a genuinely new install is. An existing one already holds chosen
    # values -- including deliberate ones that happen to equal the fallback, so
    # "is it still at the fallback?" cannot tell the two apart. Seeding such an
    # install would overwrite real settings: on the config this was built
    # against, exactly one helper would have been silently flipped back, and it
    # was the one whose stray `initial:` had just been removed to stop that very
    # thing. So an upgrade adopts the whole manifest as already-seeded, which
    # still leaves helpers ADDED by a later version to be seeded normally.
    if "seeded_helpers" not in record:
        adopted = [] if is_first_install else sorted(await seeder.manifest_ids(hass))
        if adopted:
            _LOGGER.info(
                "Existing installation: adopting %d helpers as already configured; "
                "first-run defaults will apply only to helpers added later",
                len(adopted),
            )
        await _save(seeded_helpers=adopted)

    # The helpers are YAML-defined, so on the boot where they were just written
    # they do not exist as entities yet -- they appear on the NEXT boot. Hence
    # this runs on every setup and seeds whatever is present and untouched;
    # anything absent is left for a later boot. EVENT_HOMEASSISTANT_STARTED (not
    # EVENT_HOMEASSISTANT_START) is required -- the earlier event fires before
    # YAML platforms have finished loading.
    async def _seed(_event: Event | None = None) -> None:
        current = await store.async_load() or {}
        done = current.get("seeded_helpers", [])
        report = await seeder.seed(hass, done)
        if not report["seeded"]:
            return
        current["seeded_helpers"] = sorted(set(done) | set(report["seeded"]))
        await store.async_save(current)

    if hass.is_running:
        await _seed()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _seed)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload. Does NOT remove installed files or services."""
    hass.data.get(DOMAIN, {}).pop("features", None)
    hass.data.get(DOMAIN, {}).pop("store", None)
    return True
