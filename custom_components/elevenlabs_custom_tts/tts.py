"""ElevenLabs TTS platform."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import async_timeout
from elevenlabs import VoiceSettings
from elevenlabs.core import ApiError

from homeassistant.components.tts import TextToSpeechEntity, TtsAudioType, Voice
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    DEFAULT_MODEL,
    DEFAULT_STABILITY,
    DEFAULT_SIMILARITY_BOOST,
    DEFAULT_STYLE,
    DEFAULT_SPEED,
    DEFAULT_USE_SPEAKER_BOOST,
    DEFAULT_APPLY_TEXT_NORMALIZATION,
)

_LOGGER = logging.getLogger(__name__)

SUPPORT_LANGUAGES = ["en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh", "ja", "hu", "ko"]

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ElevenLabs TTS platform via config entry."""
    # Get the client from the integration data
    if DOMAIN not in hass.data or config_entry.entry_id not in hass.data[DOMAIN]:
        _LOGGER.error("ElevenLabs integration not loaded")
        return
        
    client = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([ElevenLabsTTSProvider(hass, client, config_entry)])


class ElevenLabsTTSProvider(TextToSpeechEntity):
    """ElevenLabs TTS provider."""

    def __init__(self, hass: HomeAssistant, client, config_entry: ConfigEntry) -> None:
        """Initialize ElevenLabs TTS provider."""
        self.hass = hass
        self._client = client
        self._config_entry = config_entry
        # Set the entity name for entity ID generation
        self._name = "elevenlabs_custom_tts"
        # Set the friendly name that should appear in UI and registry
        self._attr_name = "ElevenLabs Custom TTS"
        self._friendly_name = "ElevenLabs Custom TTS"

        # ── Voice mood profile map (profile name → agent identifier) ──
        self._mood_profile_map = {}

    async def async_added_to_hass(self) -> None:
        """Load mood profile map asynchronously when entity is added."""
        self._mood_profile_map = await self.hass.async_add_executor_job(
            self._load_mood_profile_map_sync
        )

    @staticmethod
    def _load_mood_profile_map_sync() -> dict:
        """Load profile→agent map from JSON config (runs in executor thread)."""
        import json as _json
        try:
            with open("/config/pyscript/voice_mood_profile_map.json", "r") as f:
                data = _json.load(f)
            _LOGGER.debug("Loaded mood profile map: %s", list(data.keys()))
            return data
        except FileNotFoundError:
            _LOGGER.debug("No mood profile map found — mood modulation disabled")
            return {}
        except Exception as exc:
            _LOGGER.warning("Failed to load mood profile map: %s", exc)
            return {}

    @property
    def name(self) -> str:
        """Return the name of the entity (for entity ID)."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this TTS entity."""
        return f"{DOMAIN}_tts"

    @property
    def default_language(self) -> str:
        """Return the default language."""
        return "en"

    @property
    def supported_languages(self) -> list[str]:
        """Return list of supported languages."""
        return SUPPORT_LANGUAGES

    @property
    def supported_options(self) -> list[str]:
        """Return list of supported options."""
        return [
            "voice_profile",
            "voice",
            "model_id", 
            "stability",
            "similarity_boost",
            "style",
            "speed",
            "use_speaker_boost",
            "apply_text_normalization"
        ]

    @property
    def default_options(self) -> dict[str, Any]:
        """Return dict of default options."""
        voice_profiles = self._config_entry.options.get("voice_profiles", {})
        first_profile = next(iter(voice_profiles.values()), None)
        default_voice = first_profile.get("voice", "21m00Tcm4TlvDq8ikWAM") if first_profile else "21m00Tcm4TlvDq8ikWAM"
        return {
            "voice": default_voice,  # First configured profile; Rachel as final fallback
            "model_id": DEFAULT_MODEL,
            "stability": DEFAULT_STABILITY,
            "similarity_boost": DEFAULT_SIMILARITY_BOOST,
            "style": DEFAULT_STYLE,
            "speed": DEFAULT_SPEED,
            "use_speaker_boost": DEFAULT_USE_SPEAKER_BOOST,
            "apply_text_normalization": DEFAULT_APPLY_TEXT_NORMALIZATION,
        }

    @callback
    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        """Return list of supported voices for Assist pipeline."""
        voice_profiles = self._config_entry.options.get("voice_profiles", {})

        if not voice_profiles:
            _LOGGER.debug("No voice profiles configured, hiding voice picker")
            return None  # None hides picker; [] shows empty picker and triggers clearing

        voices = []
        for profile_name, profile_data in voice_profiles.items():
            voice_id = profile_data.get("voice", "")
            voices.append(
                Voice(
                    voice_id=profile_name,
                    name=profile_name,
                )
            )
            _LOGGER.debug("Added voice profile '%s' (ElevenLabs voice: %s) to supported voices",
                         profile_name, voice_id)

        return voices

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any] | None = None
    ) -> TtsAudioType:
        """Load TTS audio file from ElevenLabs."""
        if options is None:
            options = {}

        # Get voice profiles from config entry
        voice_profiles = self._config_entry.options.get("voice_profiles", {})

        _LOGGER.debug(
            "ElevenLabs Custom TTS: options=%s, available_profiles=%s",
            {k: v for k, v in options.items() if k != "message"},
            list(voice_profiles.keys()),
        )

        # --- Profile resolution ---
        # Priority: explicit voice_profile > voice matching profile name > raw voice ID
        profile_options = None
        voice_profile_name = options.get("voice_profile")

        # If no explicit voice_profile, check if "voice" matches a profile name
        if not voice_profile_name and "voice" in options:
            voice_profile_name = options["voice"]

        # Look up profile (exact match first, then case-insensitive)
        if voice_profile_name and voice_profiles:
            if voice_profile_name in voice_profiles:
                profile_options = voice_profiles[voice_profile_name].copy()
            else:
                # Case-insensitive fallback
                for pname, pdata in voice_profiles.items():
                    if pname.lower().strip() == voice_profile_name.lower().strip():
                        profile_options = pdata.copy()
                        voice_profile_name = pname
                        break

            if profile_options:
                _LOGGER.info("Using voice profile '%s' (voice_id=%s)",
                            voice_profile_name, profile_options.get("voice", "?"))
            else:
                _LOGGER.warning(
                    "Voice '%s' did not match any profile %s — treating as raw voice ID",
                    voice_profile_name, list(voice_profiles.keys()),
                )

        # ── Voice mood modulation (v3): stability + tag prefix ──
        mood_options = {}
        mood_tag_prefix = ""
        if profile_options and voice_profile_name and self._mood_profile_map:
            try:
                kill_switch = self.hass.states.get(
                    "input_boolean.ai_voice_mood_enabled"
                )
                if kill_switch and kill_switch.state == "on":
                    _agent = self._mood_profile_map.get(voice_profile_name.lower().strip())
                    if _agent:
                        # Stability — the one VoiceSettings param v3 respects
                        _st = self.hass.states.get(
                            f"input_number.ai_voice_mood_{_agent}_stability"
                        )
                        if _st and _st.state not in ("unknown", "unavailable", ""):
                            mood_options["stability"] = float(_st.state)
                        # Tag prefix — for non-agent text (notifications, announcements)
                        _tags = self.hass.states.get(
                            f"sensor.ai_voice_mood_{_agent}_tags"
                        )
                        if _tags and _tags.state not in ("unknown", "unavailable", ""):
                            mood_tag_prefix = _tags.state.strip()
                        if mood_options or mood_tag_prefix:
                            _LOGGER.debug(
                                "Voice mood for '%s' (agent=%s): opts=%s tags='%s'",
                                voice_profile_name, _agent, mood_options, mood_tag_prefix,
                            )
            except Exception as exc:
                _LOGGER.warning("Voice mood failed: %s", exc)

        # Build merged options: defaults < profile < mood < per-request overrides
        # When "voice" was used to select a profile, exclude it from overrides
        # so the profile's actual voice UUID isn't overwritten by the profile name
        exclude_keys = {"voice_profile"}
        if profile_options and "voice_profile" not in options:
            # voice was used for profile matching — don't let it override the UUID
            exclude_keys.add("voice")
        api_options = {k: v for k, v in options.items() if k not in exclude_keys}
        if profile_options:
            merged_options = {**self.default_options, **profile_options, **mood_options, **api_options}
        else:
            merged_options = {**self.default_options, **api_options}
        
        voice_id = merged_options["voice"]
        model_id = merged_options["model_id"]
        stability = merged_options["stability"]
        similarity_boost = merged_options["similarity_boost"]
        style = merged_options["style"]
        speed = merged_options["speed"]
        use_speaker_boost = merged_options["use_speaker_boost"]
        apply_text_normalization = merged_options["apply_text_normalization"]

        # Inject mood tag prefix for non-tagged text (notifications, announcements).
        # Agent conversation responses already contain tags — skip those.
        if mood_tag_prefix and "[" not in message:
            message = f"{mood_tag_prefix} {message}"

        voice_settings = VoiceSettings(
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
            speed=speed,
        )
        
        try:
            with async_timeout.timeout(30):
                # Prepare conversion parameters
                convert_params = {
                    "text": message,
                    "voice_id": voice_id,
                    "model_id": model_id,
                    "voice_settings": voice_settings,
                    "language_code": language,
                    "apply_text_normalization": apply_text_normalization,
                }
                
                # Generate audio with ElevenLabs (async generator)
                audio_generator = self._client.text_to_speech.convert(**convert_params)
                
                # Collect all audio bytes from async generator
                audio_bytes = b""
                async for chunk in audio_generator:
                    audio_bytes += chunk
                
                if not audio_bytes:
                    _LOGGER.error("No audio data received from ElevenLabs")
                    return None
                    
                _LOGGER.info(
                    "Successfully generated %d bytes of audio for voice %s%s",
                    len(audio_bytes),
                    voice_id,
                    f" using profile '{voice_profile_name}'" if voice_profile_name else ""
                )
                
                return ("mp3", audio_bytes)
                
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout generating TTS audio")
            return None
        except ApiError as err:
            _LOGGER.error("ElevenLabs API error: %s", err)
            return None
        except Exception as err:
            _LOGGER.error("Error generating TTS audio: %s", err)
            return None