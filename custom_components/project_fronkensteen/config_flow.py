"""Config flow for Project Fronkensteen installer."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import DOMAIN, FEATURE_GROUPS, VERSION

_LOGGER = logging.getLogger(__name__)


def _pyscript_installed(hass: HomeAssistant) -> bool:
    """Check if pyscript integration is loaded."""
    return "pyscript" in hass.config.components or "pyscript" in (
        entry.domain for entry in hass.config_entries.async_entries()
    )


class ProjectFronkensteenFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Project Fronkensteen."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._features: dict[str, bool] = {}
        self._household: dict[str, str] = {}
        self._speakers: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Welcome and prerequisites check."""
        errors: dict[str, str] = {}
        description_placeholders = {"version": VERSION}

        if not _pyscript_installed(self.hass):
            errors["base"] = "pyscript_not_installed"

        if user_input is not None:
            if not errors:
                return await self.async_step_features()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Feature group selection."""
        if user_input is not None:
            self._features = {
                key: user_input.get(key, True) for key in FEATURE_GROUPS
            }
            return await self.async_step_household()

        schema = vol.Schema(
            {vol.Optional(key, default=True): bool for key in FEATURE_GROUPS}
        )

        return self.async_show_form(
            step_id="features",
            data_schema=schema,
        )

    async def async_step_household(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Household setup."""
        if user_input is not None:
            self._household = user_input
            return await self.async_step_speakers()

        schema = vol.Schema(
            {
                vol.Required("person_slug"): str,
                vol.Required("display_name"): str,
                vol.Optional("tts_pronunciation", default=""): str,
                vol.Optional("preferred_language", default="English"): vol.In(
                    ["English", "Spanish", "Catalan", "Dutch", "Portuguese", "French", "German", "Italian"]
                ),
                vol.Optional("household_members", default=""): str,
                vol.Optional("pets", default="none"): str,
            }
        )

        return self.async_show_form(
            step_id="household",
            data_schema=schema,
        )

    async def async_step_speakers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 4: Speaker and TTS setup."""
        if user_input is not None:
            self._speakers = user_input
            return await self.async_step_confirm()

        schema = vol.Schema(
            {
                vol.Required("default_speaker"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player"),
                ),
                vol.Optional("tts_provider", default="elevenlabs"): vol.In(
                    ["elevenlabs", "openai", "ha_cloud", "other"]
                ),
            }
        )

        return self.async_show_form(
            step_id="speakers",
            data_schema=schema,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 5: Review and install."""
        if user_input is not None:
            selected = [k for k, v in self._features.items() if v]

            return self.async_create_entry(
                title="Project Fronkensteen",
                data={
                    "version": VERSION,
                    "features": selected,
                    "household": self._household,
                    "speakers": self._speakers,
                },
            )

        selected = [k for k, v in self._features.items() if v]
        feature_names = [FEATURE_GROUPS[k] for k in selected]
        summary = ", ".join(feature_names) if feature_names else "Core only"

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "features": summary,
                "person": self._household.get("display_name", ""),
                "speaker": self._speakers.get("default_speaker", ""),
            },
        )

    # ── Reconfigure flow ────────────────────────────────────────────────
    # Allows changing features after initial setup. Uses the reconfigure
    # pattern (modifies entry.data) instead of options flow.

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure: choose what to change."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "features":
                return await self.async_step_reconfigure_features()
            if action == "reinstall":
                return await self.async_step_reconfigure_reinstall()
            return self.async_abort(reason="no_action")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="features"): vol.In(
                        {
                            "features": "Change feature selection",
                            "reinstall": "Reinstall all files",
                        }
                    ),
                }
            ),
        )

    async def async_step_reconfigure_features(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure: change feature groups."""
        entry = self._get_reconfigure_entry()
        current_features = entry.data.get("features", [])

        if user_input is not None:
            new_features = [k for k, v in user_input.items() if v]

            # Install files for newly-enabled groups
            added = set(new_features) - set(current_features)
            if added:
                from . import installer
                household = entry.data.get("household", {})
                speakers = entry.data.get("speakers", {})
                config_data = {**household, **speakers}
                await installer.install(self.hass, list(added), config_data)
                _LOGGER.info("Installed files for new feature groups: %s", added)

            return self.async_update_reload_and_abort(
                entry,
                data={**entry.data, "features": new_features},
            )

        schema = vol.Schema(
            {
                vol.Optional(key, default=key in current_features): bool
                for key in FEATURE_GROUPS
            }
        )

        return self.async_show_form(
            step_id="reconfigure_features",
            data_schema=schema,
        )

    async def async_step_reconfigure_reinstall(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure: reinstall all code files from bundle."""
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            from . import installer
            features = entry.data.get("features", [])
            household = entry.data.get("household", {})
            speakers = entry.data.get("speakers", {})
            config_data = {**household, **speakers}
            report = await installer.install(self.hass, features, config_data)
            _LOGGER.info("Reinstall: %d copied, %d skipped", report["copied"], report["skipped"])
            return self.async_update_reload_and_abort(entry, data=entry.data)

        return self.async_show_form(
            step_id="reconfigure_reinstall",
            data_schema=vol.Schema({}),
            description_placeholders={
                "warning": "This will overwrite all code files (pyscript, packages, blueprints). Your config files (entity_config, speaker config, helpers) will NOT be touched.",
            },
        )
