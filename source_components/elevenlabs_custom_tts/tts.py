"""ElevenLabs TTS platform."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from elevenlabs import VoiceSettings
from elevenlabs.core import ApiError

from homeassistant.components.tts import (
    TextToSpeechEntity,
    TTSAudioRequest,
    TTSAudioResponse,
    TtsAudioType,
    Voice,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
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
    MODELS_WITHOUT_LANGUAGE_CODE,
    TTS_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# Upper bound on a single streamed generation. Generous: measured
# end-to-end is ~6.5s for 195 chars, but the budget also spans the
# consumer pulling chunks, so keep well clear of normal replies.
STREAM_TIMEOUT_S = 120

# HA pops these before calling the engine UNLESS we declare them supported
# (tts/__init__.py). String literals rather than imports so an HA-core rename
# cannot break module import.
ATTR_PREFERRED_FORMAT = "preferred_format"
ATTR_PREFERRED_SAMPLE_RATE = "preferred_sample_rate"
ATTR_PREFERRED_SAMPLE_CHANNELS = "preferred_sample_channels"
ATTR_PREFERRED_SAMPLE_BYTES = "preferred_sample_bytes"

# Silent 44.1 kHz mono MP3, 1.6 s.
#
# The ESPHome Voice PE arms a 2000 ms "playing" watchdog when HA hands it the
# TTS URL (voice_assistant.cpp:747-757). If audio has not begun by then the
# firmware FABRICATES an AnnounceFinished, HA marks the satellite idle, and the
# device re-arms the microphone OVER the still-playing reply -- which has been
# observed executing tool calls from mis-transcribed room audio.
#
# HA cannot suppress that: the fabricated and honest messages are byte-identical
# on the wire, and the mic opens on the ESP32 before HA is notified. What HA DOES
# control is when audio starts. The satellite negotiates FLAC/48k, so every reply
# is transcoded mp3->flac, and ffmpeg's mp3 demuxer emits nothing until ~1.4 s of
# audio DURATION has arrived. Measured on this system: 2215 ms to first FLAC byte
# without this pre-roll, 45 ms with it.
#
# Yielding this first satisfies the demuxer immediately. The device reaches
# ANNOUNCING in ~50 ms, and the watchdog -- which re-arms every loop while
# playing -- becomes a sliding window that never fires. Margin to the deadline
# goes from ~0.19 s to ~1.7 s. Cost is ~0.25 s of added lead-in in the typical
# case, and it is FASTER than today whenever ElevenLabs is slow.
LEAD_IN_PATH = Path(__file__).parent / "leadin_1600ms.mp3"
LEAD_IN_SWITCH = "input_boolean.ai_tts_leadin_enabled"

# Voice mood modulation (Project Fronkensteen): profile name -> agent identifier
MOOD_PROFILE_MAP_PATH = "/config/pyscript/voice_mood_profile_map.json"
MOOD_SWITCH = "input_boolean.ai_voice_mood_enabled"

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


def _merge_options(
    defaults: dict[str, Any],
    profile: dict[str, Any] | None,
    mood: dict[str, Any],
    call_options: dict[str, Any],
) -> dict[str, Any]:
    """Decide the final TTS settings: defaults < profile < mood < per-call overrides.

    defaults:     integration-wide defaults (always contains every key)
    profile:      the selected voice profile's settings, or None if no profile was used
    mood:         voice-mood values for the profile's agent (e.g. {"stability": 0.3})
    call_options: options passed in the tts.speak call, with voice/voice_profile
                  already stripped when they only selected the profile

    HA's TTS layer merges this entity's default_options INTO the call options
    before calling us, so they arrive carrying the defaults (notably
    model_id=DEFAULT_MODEL) as if they were deliberate overrides. Merged last,
    they silently beat the voice profile, which forced every profile onto
    eleven_multilingual_v2 and made v3 audio tags like [exhales] get read aloud
    as words. With a profile, only values that differ from the defaults count
    as overrides, so a genuine per-call override still wins.
    """
    if profile is None:
        return {**defaults, **call_options}
    overrides = {k: v for k, v in call_options.items() if defaults.get(k) != v}
    return {**defaults, **profile, **mood, **overrides}


class ElevenLabsTTSProvider(TextToSpeechEntity):
    """ElevenLabs TTS provider."""

    def __init__(self, hass: HomeAssistant, client, config_entry: ConfigEntry) -> None:
        """Initialize ElevenLabs TTS provider."""
        self.hass = hass
        self._client = client
        self._config_entry = config_entry
        # Shown in the UI; also slugifies to the tts.elevenlabs_custom_tts entity_id
        self._attr_name = "ElevenLabs Custom TTS"
        # Voice mood profile map (profile name -> agent identifier), loaded in async_added_to_hass
        self._mood_profile_map: dict[str, str] = {}
        # Satellite lead-in pre-roll bytes, loaded in async_added_to_hass
        self._lead_in_cache = b""

    async def async_added_to_hass(self) -> None:
        """Load the mood profile map and the lead-in clip off the event loop."""
        self._mood_profile_map = await self.hass.async_add_executor_job(
            self._load_mood_profile_map_sync
        )
        try:
            self._lead_in_cache = await self.hass.async_add_executor_job(
                LEAD_IN_PATH.read_bytes
            )
            _LOGGER.info(
                "Satellite lead-in loaded (%d bytes)", len(self._lead_in_cache)
            )
        except Exception as err:  # missing file must degrade, never raise
            self._lead_in_cache = b""
            _LOGGER.warning("Satellite lead-in unavailable (%s) — disabled", err)

    @staticmethod
    def _load_mood_profile_map_sync() -> dict:
        """Load profile->agent map from JSON config (runs in executor thread)."""
        import json as _json
        try:
            with open(MOOD_PROFILE_MAP_PATH, "r") as f:
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
    def unique_id(self) -> str:
        """Return a unique ID for this TTS entity."""
        # One entity per config entry; a fixed ID collides with multiple API keys
        return f"{DOMAIN}_{self._config_entry.entry_id}"

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
            "apply_text_normalization",
            # Declared ONLY so HA hands these to us instead of popping them.
            # We never act on them beyond gating the lead-in below. Conversion
            # behaviour and cache keys are unchanged either way.
            ATTR_PREFERRED_FORMAT,
            ATTR_PREFERRED_SAMPLE_RATE,
            ATTR_PREFERRED_SAMPLE_CHANNELS,
            ATTR_PREFERRED_SAMPLE_BYTES,
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
            # The voice_id in Voice() becomes the identifier used in the Assist pipeline;
            # when selected, it is passed back to us as the "voice" option
            voices.append(
                Voice(
                    voice_id=profile_name,
                    name=profile_name,
                )
            )
            _LOGGER.debug("Added voice profile '%s' (ElevenLabs voice: %s) to supported voices",
                         profile_name, voice_id)

        return voices

    def _voice_mood(self, voice_profile_name: str) -> tuple[dict[str, Any], str]:
        """Return (mood options, tag prefix) for a profile's agent, or ({}, "")."""
        mood_options: dict[str, Any] = {}
        mood_tag_prefix = ""
        if not self._mood_profile_map:
            return mood_options, mood_tag_prefix
        try:
            kill_switch = self.hass.states.get(MOOD_SWITCH)
            if not kill_switch or kill_switch.state != "on":
                return mood_options, mood_tag_prefix
            agent = self._mood_profile_map.get(voice_profile_name.lower().strip())
            if not agent:
                return mood_options, mood_tag_prefix
            # Stability: the one VoiceSettings param v3 respects
            stability = self.hass.states.get(f"input_number.ai_voice_mood_{agent}_stability")
            if stability and stability.state not in ("unknown", "unavailable", ""):
                mood_options["stability"] = float(stability.state)
            # Tag prefix: for non-agent text (notifications, announcements)
            tags = self.hass.states.get(f"sensor.ai_voice_mood_{agent}_tags")
            if tags and tags.state not in ("unknown", "unavailable", ""):
                mood_tag_prefix = tags.state.strip()
            if mood_options or mood_tag_prefix:
                _LOGGER.debug(
                    "Voice mood for '%s' (agent=%s): opts=%s tags='%s'",
                    voice_profile_name, agent, mood_options, mood_tag_prefix,
                )
        except Exception as exc:
            _LOGGER.warning("Voice mood failed: %s", exc)
            return {}, ""
        return mood_options, mood_tag_prefix

    def _prepare_request(
        self, message: str, language: str, options: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], str, str | None]:
        """Resolve profile, mood and option precedence into request params.

        Shared by the buffered path (async_get_tts_audio) and the streaming
        path (async_stream_tts_audio) so both apply identical profile
        resolution, voice-mood modulation and option precedence.
        """
        if options is None:
            options = {}

        # Get voice profiles from config entry
        voice_profiles = self._config_entry.options.get("voice_profiles", {})

        _LOGGER.debug(
            "ElevenLabs Custom TTS: options=%s, available_profiles=%s",
            {k: v for k, v in options.items() if k != "message"},
            list(voice_profiles.keys()),
        )

        # Profile resolution: explicit voice_profile > voice matching a profile name > raw voice ID
        profile = None
        voice_profile_name = options.get("voice_profile")
        # The Assist pipeline passes the selected profile as "voice"
        if not voice_profile_name and "voice" in options:
            voice_profile_name = options["voice"]

        if voice_profile_name and voice_profiles:
            if voice_profile_name in voice_profiles:
                profile = voice_profiles[voice_profile_name].copy()
            else:
                # Case-insensitive fallback
                for pname, pdata in voice_profiles.items():
                    if pname.lower().strip() == voice_profile_name.lower().strip():
                        profile = pdata.copy()
                        voice_profile_name = pname
                        break

            if profile is not None:
                _LOGGER.info("Using voice profile '%s' (voice_id=%s)",
                            voice_profile_name, profile.get("voice", "?"))
            else:
                # HA merges default_options into every call, so "voice" is always
                # present; only an unmatched non-default value is worth a warning.
                is_default_voice = voice_profile_name == self.default_options["voice"]
                _LOGGER.log(
                    logging.DEBUG if is_default_voice else logging.WARNING,
                    "Voice '%s' did not match any profile %s — treating as raw voice ID",
                    voice_profile_name, list(voice_profiles.keys()),
                )

        mood_options: dict[str, Any] = {}
        mood_tag_prefix = ""
        if profile is not None:
            mood_options, mood_tag_prefix = self._voice_mood(voice_profile_name)

        call_options = dict(options)
        call_options.pop("voice_profile", None)
        if profile is not None and "voice_profile" not in options:
            # "voice" only selected the profile; it is not an ElevenLabs voice ID
            call_options.pop("voice", None)
        merged_options = _merge_options(self.default_options, profile, mood_options, call_options)
        if profile is None:
            voice_profile_name = None

        voice_id = merged_options["voice"]
        model_id = merged_options["model_id"]
        stability = merged_options["stability"]
        similarity_boost = merged_options["similarity_boost"]
        style = merged_options["style"]
        speed = merged_options["speed"]
        use_speaker_boost = merged_options["use_speaker_boost"]
        apply_text_normalization = merged_options["apply_text_normalization"]

        # Inject the mood tag prefix into untagged text (notifications, announcements).
        # Agent conversation replies already carry their own tags, so skip those.
        if mood_tag_prefix and "[" not in message:
            message = f"{mood_tag_prefix} {message}"

        voice_settings = VoiceSettings(
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
            speed=speed,
        )

        convert_params = {
            "text": message,
            "voice_id": voice_id,
            "model_id": model_id,
            "voice_settings": voice_settings,
            "apply_text_normalization": apply_text_normalization,
        }
        if model_id not in MODELS_WITHOUT_LANGUAGE_CODE:
            convert_params["language_code"] = language
        return convert_params, voice_id, voice_profile_name

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any] | None = None
    ) -> TtsAudioType:
        """Load TTS audio from ElevenLabs as one buffered blob.

        Retained for any caller not on the streaming path. Uses
        text_to_speech.convert(), whose endpoint renders the entire clip
        server-side before returning a byte.
        """
        _LOGGER.debug("TTS request received for message length: %d", len(message))
        convert_params, voice_id, voice_profile_name = self._prepare_request(
            message, language, options
        )
        model_id = convert_params["model_id"]

        try:
            async with asyncio.timeout(TTS_TIMEOUT):
                # Collect all audio bytes from the async generator
                chunks = [
                    chunk async for chunk in self._client.text_to_speech.convert(**convert_params)
                ]
        except TimeoutError as err:
            raise HomeAssistantError("Timed out generating ElevenLabs TTS audio") from err
        except ApiError as err:
            # err.body carries ElevenLabs' explanation (e.g. unsupported setting for a model)
            raise HomeAssistantError(
                f"ElevenLabs API error {err.status_code}: {err.body}"
            ) from err

        audio_bytes = b"".join(chunks)
        if not audio_bytes:
            raise HomeAssistantError("No audio data received from ElevenLabs")

        _LOGGER.debug(
            "Generated %d bytes of audio for voice %s with model %s%s",
            len(audio_bytes),
            voice_id,
            model_id,
            f" using profile '{voice_profile_name}'" if voice_profile_name else "",
        )
        return ("mp3", audio_bytes)

    def _lead_in_bytes(self, options: dict[str, Any] | None) -> bytes:
        """Silent MP3 pre-roll, or b'' when it must not be used.

        Gated on a caller having negotiated a non-wav preferred format -- i.e.
        the ESPHome media_player ANNOUNCEMENT path, the only path carrying the
        2000 ms device watchdog. Deliberately excluded:
          * tts_queue / tts.speak / play_media -> no preferred_format at all
          * ESPHome SPEAKER path -> "wav", PCM pushed over the API, no watchdog
        So Sonos, Alexa and every notification are untouched by construction.
        """
        fmt = (options or {}).get(ATTR_PREFERRED_FORMAT)
        if not fmt or fmt == "wav":
            return b""
        kill = self.hass.states.get(LEAD_IN_SWITCH)
        if kill is not None and kill.state == "off":
            return b""
        return self._lead_in_cache

    async def async_stream_tts_audio(
        self, request: TTSAudioRequest
    ) -> TTSAudioResponse:
        """Stream audio from ElevenLabs as it is generated.

        Why this exists: text_to_speech.convert() posts to
        /v1/text-to-speech/{voice_id}, which renders the whole clip
        server-side before sending anything, so time-to-first-byte grows
        with the text. Measured 2026-08-18: 1.23s for 23 chars, 4.24s for
        158, 4.41s for 195. text_to_speech.stream() posts to the /stream
        variant, whose first byte arrives in a flat ~0.8s regardless of
        length. Passing those chunks straight through lets the speaker
        start on the first one instead of waiting for the last.

        This matters beyond comfort: the ESPHome satellite reports
        "finished speaking" on a fixed ~2.0s timer and re-arms its mic
        49-70ms later. With a ~4.4s first byte the microphone opened over
        silence and the reply landed in an already-dead session.

        NOTE: overriding this method also makes HA report
        async_supports_streaming_input() == True. That only enables
        token-by-token INPUT when the conversation agent ALSO sets
        supports_streaming (assist_pipeline/pipeline.py, stream_response).
        Extended OpenAI Conversation does not set it, so the full reply is
        still joined below before any request is made -- which is what
        keeps the speech sanitiser and the mood-tag "[" check operating on
        complete text. Do not assume that still holds if EOC ever gains
        streaming support.
        """
        message = "".join([chunk async for chunk in request.message_gen])
        convert_params, voice_id, voice_profile_name = self._prepare_request(
            message, request.language, request.options
        )
        profile_note = (
            f" using profile '{voice_profile_name}'" if voice_profile_name else ""
        )

        lead_in = self._lead_in_bytes(request.options)

        async def _audio_stream() -> AsyncGenerator[bytes]:
            total = 0
            if lead_in:
                # NOT counted in `total`: the no-audio raise at the end of this
                # method must still fire when ElevenLabs returns nothing, or HA
                # caches a silent clip under the deterministic key forever.
                _LOGGER.debug(
                    "Prepending %d-byte silent lead-in", len(lead_in)
                )
                yield lead_in
            # The deadline is enforced per await on ElevenLabs, never across a
            # yield: a timeout context spanning yields would fire inside
            # whatever the consumer task is doing between chunks.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + STREAM_TIMEOUT_S
            chunks = aiter(self._client.text_to_speech.stream(**convert_params))
            try:
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError
                    try:
                        chunk = await asyncio.wait_for(anext(chunks), remaining)
                    except StopAsyncIteration:
                        break
                    if not chunk:
                        continue
                    if total == 0:
                        _LOGGER.info(
                            "First audio chunk (%d bytes) from ElevenLabs for "
                            "voice %s%s",
                            len(chunk), voice_id, profile_note,
                        )
                    total += len(chunk)
                    yield chunk
            except TimeoutError as err:
                _LOGGER.error("Timeout streaming TTS audio after %d bytes", total)
                raise HomeAssistantError(
                    "Timed out streaming ElevenLabs TTS audio"
                ) from err
            except ApiError as err:
                # Status + ElevenLabs' explanation only; str(err) dumps every header
                _LOGGER.error(
                    "ElevenLabs API error %s after %d bytes: %s",
                    err.status_code, total, err.body,
                )
                raise HomeAssistantError(
                    f"ElevenLabs API error {err.status_code}: {err.body}"
                ) from err
            finally:
                aclose = getattr(chunks, "aclose", None)
                if aclose is not None:
                    await aclose()

            if not total:
                # Must RAISE, not return. A bare return is a clean generator
                # exit, which HA reads as "succeeded with 0 bytes": it then
                # writes a 0-byte mp3 into /config/tts under the deterministic
                # sha1(message)+options key and serves that silence forever,
                # surviving restarts. Raising propagates into
                # _load_data_into_cache's except, which pops the mem cache and
                # returns BEFORE the disk write -- matching the base contract
                # at tts/entity.py.
                raise HomeAssistantError(
                    f"No TTS from {self.entity_id} for '{message[:64]}'"
                )

            _LOGGER.info(
                "Streamed %d bytes of audio for voice %s%s",
                total, voice_id, profile_note,
            )

        return TTSAudioResponse("mp3", _audio_stream())
