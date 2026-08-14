"""Spotify Connect desktop-token health monitor.

WHY THIS EXISTS
  SpotifyPlus can only wake an *inactive* Spotify Connect device (Sonos,
  Chromecast) when a Spotify Desktop Player OAuth token is present at
  /config/.storage/spotifyplus_tokens.json. Without it the service raises
  "Spotify Desktop Client Application access token was not authorized".

  The token self-maintains: the access token lasts ~1 hour and the library
  refreshes it and writes the new one back to the same file. It only dies if
  the *refresh* token is invalidated — a Spotify password change, or revoking
  access at spotify.com/account/apps.

  That failure is silent: music-follow-me transfers to an unoccupied room just
  stop working. This module turns it into a visible sensor.

  Regenerate with scratchpad/spotify_desktop_token.py (browser required — the
  flow cannot run on the HA box), then copy the file back to .storage/.

Sensor:
  sensor.ai_spotify_connect_token_status
    ok | stale | missing | unreadable | disabled
    attrs: expires_at, age_hours, profile_id, checked

Pyscript notes:
  - AP-55: open() is blocked in regular pyscript context -> @pyscript_executor
  - AP-71: pyscript builtins (state.set/log) cannot be called from executor
    context, so the executor returns plain data and the async caller writes.
  - AP-57: no generator expressions.
"""

RESULT_ENTITY = "sensor.ai_spotify_connect_token_status"
TOKEN_PATH = "/config/.storage/spotifyplus_tokens.json"
STALE_AFTER_HOURS = 48


@pyscript_executor  # noqa: F821
def _read_token_file(path):
    """Read the token store. Returns (status, expires_at, profile_id).

    Runs as native Python — file I/O is not permitted in regular pyscript.
    """
    import json as _json

    try:
        with open(path, "r") as fh:
            data = _json.load(fh)
    except FileNotFoundError:
        return ("missing", 0.0, "")
    except (ValueError, OSError):
        return ("unreadable", 0.0, "")

    if not isinstance(data, dict) or not data:
        return ("unreadable", 0.0, "")

    # Key layout: "<providerId>/<clientId>/<loginId>"
    newest_exp = 0.0
    profile = ""
    for key in sorted(data.keys()):
        entry = data.get(key)
        if not isinstance(entry, dict):
            continue
        try:
            exp = float(entry.get("expires_at") or 0)
        except (TypeError, ValueError):
            exp = 0.0
        if exp >= newest_exp:
            newest_exp = exp
            parts = key.split("/")
            profile = parts[-1] if parts else ""

    if newest_exp <= 0:
        return ("unreadable", 0.0, profile)
    return ("found", newest_exp, profile)


def _evaluate(status, expires_at, now_ts):
    """Classify token health. Pure function — trivially testable."""
    if status != "found":
        return (status, 0.0)
    age_hours = (now_ts - expires_at) / 3600.0
    # The library refreshes ~hourly and rewrites expires_at, so a value far in
    # the past means refresh has stopped, not that the token merely lapsed.
    if age_hours > STALE_AFTER_HOURS:
        return ("stale", age_hours)
    return ("ok", age_hours)


async def _publish(status, expires_at, age_hours, profile):
    import datetime

    icons = {
        "ok": "mdi:spotify",
        "stale": "mdi:key-alert",
        "missing": "mdi:key-remove",
        "unreadable": "mdi:file-alert",
        "disabled": "mdi:key-off",
    }
    state.set(  # noqa: F821
        RESULT_ENTITY,
        status,
        new_attributes={
            "icon": icons.get(status, "mdi:key"),
            "friendly_name": "AI Spotify Connect Token Status",
            "expires_at": round(expires_at, 0),
            "age_hours": round(age_hours, 1),
            "profile_id": profile,
            "checked": datetime.datetime.now().isoformat(timespec="seconds"),
        },
    )


async def _run_check():
    import time

    status, expires_at, profile = await _read_token_file(TOKEN_PATH)
    verdict, age_hours = _evaluate(status, expires_at, time.time())
    await _publish(verdict, expires_at, age_hours, profile)

    if verdict in ("stale", "missing", "unreadable"):
        log.warning(  # noqa: F821
            f"spotify_connect_token: {verdict} "
            f"(age {age_hours:.1f}h, profile={profile or '?'}) — "
            f"Connect transfers to inactive speakers will fail until the "
            f"desktop token is regenerated"
        )
    else:
        log.info(  # noqa: F821
            f"spotify_connect_token: ok (refreshed {age_hours:.1f}h ago)"
        )
    return verdict


@time_trigger("cron(17 6 * * *)")  # noqa: F821
def spotify_connect_token_daily():
    """Daily health check — offset off the hour to avoid the startup herd."""
    task.create(_run_check)  # noqa: F821  (pass the func, never call it)


@time_trigger("startup")  # noqa: F821
def spotify_connect_token_startup():
    """Seed the sensor at boot so it is never 'unknown'."""
    task.create(_run_check)  # noqa: F821  (pass the func, never call it)


@service  # noqa: F821
def spotify_connect_token_check():
    """yaml
    name: Spotify Connect Token Check
    description: >-
      Check the Spotify Desktop Player token used to wake inactive Spotify
      Connect speakers, and update sensor.ai_spotify_connect_token_status.
    """
    task.create(_run_check)  # noqa: F821  (pass the func, never call it)
