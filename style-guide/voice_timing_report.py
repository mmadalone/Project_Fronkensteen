#!/usr/bin/env python3
"""Voice turn timing report — is the satellite tracking real audio, or timing out?

WHY THIS EXISTS
---------------
The ESPHome Voice PE firmware arms a 2000 ms "playing" watchdog when HA hands
it a TTS URL (voice_assistant.cpp:747-757). If audio has not begun by then the
device FABRICATES an AnnounceFinished, HA marks the satellite idle, and the mic
re-arms over the still-playing reply — which has been observed executing tool
calls from mis-transcribed room audio. The timer is device-side and cannot be
changed or suppressed from Home Assistant.

Two HA-side fixes have moved the needle:
  2026-08-18 13:40  streaming TTS   audio_start 4.4s -> 1.08-2.39s, ~10.5% still failed
  2026-08-19 02:24  silent lead-in  audio_start -> 0.19-0.23s, margin 0.16s -> ~1.8s

The lead-in works by removing HA's OWN cost from the critical path: the
satellite negotiates FLAC/48k, so every reply is transcoded mp3->flac, and
ffmpeg's mp3 demuxer emits nothing until ~1.4s of audio DURATION has arrived
(measured on this system: 2215 ms to first FLAC byte without the pre-roll,
45 ms with it).

WHAT IT MEASURES
----------------
From the recorder DB, which persists across restarts (`ha core logs` is a ring
buffer that does not). Nothing runs on the TTS hot path.

    audio_start = PLAY 'playing'  -  SAT 'responding'   <- the real predictor
    responding  = SAT 'idle'      -  SAT 'responding'

Outcomes are CLASSIFIED, not thresholded — the watchdog has a narrow signature
(responding 1.85-2.35s) and lumping every short turn in with it makes a fixed
system still look broken:
    tracked  — satellite followed real audio
    TIMED OUT (2s watchdog) — the bug this file exists for
    aborted audio — generation truncated; a DIFFERENT fault, do not conflate

It refuses to report a threshold when the two populations overlap. That guard
has already caught two flaws in its own method.

USAGE
-----
    python voice_timing_report.py [--days 3] [--pre-leadin] [--all]

Reads the DB read-only over SMB (copies first, so it never fights the WAL
writer). Safe to run any time, including while HA is running.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
import tempfile
import shutil

# Satellite <-> media_player pairs to analyse.
PAIRS = [
    ("Workshop",
     "assist_satellite.home_assistant_voice_0905c5_assist_satellite",
     "media_player.home_assistant_voice_workshop_media_player_esp"),
    ("Living Room",
     "assist_satellite.home_assistant_voice_0a0109_assist_satellite",
     "media_player.home_assistant_voice_living_room_media_player_esp"),
]

# A turn whose `responding` state ended before this is the timer firing, not
# real audio -- no reply this system produces is under ~5 s of speech.
TIMEOUT_CEILING_S = 2.6

# Only audio starting within this long of the responding edge belongs to the
# turn. Without this bound the search happily grabs music that started minutes
# later and reports it as a 73-second time-to-audio.
AUDIO_WINDOW_S = 12.0

# The streaming TTS fix landed here. Turns before it are a different system --
# they timed out regardless of audio timing -- and mixing them in destroys the
# separation the report exists to measure.
STREAMING_FIX = dt.datetime(2026, 8, 18, 13, 40)

# The silent lead-in landed here. It collapses audio_start to ~0.2s, so turns
# either side of it are again different systems. Pass --all to see both.
LEADIN_FIX = dt.datetime(2026, 8, 19, 2, 24)

# The 2000ms firmware watchdog has a narrow, unmistakable signature: responding
# ends at 2.0s +/- a little. Anything much SHORTER is a different fault (aborted
# or truncated audio), and lumping the two together is how a fixed system still
# looks broken. Classify, do not threshold.
TIMER_LO, TIMER_HI = 1.85, 2.35
ABORTED_AUDIO_S = 1.0


def load_states(db: str, entity_ids: list[str], since_ts: float):
    """Return {entity_id: [(state, ts), ...]} ordered by time."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out: dict[str, list[tuple[str, float]]] = {}
        for eid in entity_ids:
            row = con.execute(
                "SELECT metadata_id FROM states_meta WHERE entity_id=?", (eid,)
            ).fetchone()
            if not row:
                out[eid] = []
                continue
            out[eid] = con.execute(
                "SELECT state, last_updated_ts FROM states "
                "WHERE metadata_id=? AND last_updated_ts>=? ORDER BY last_updated_ts",
                (row[0], since_ts),
            ).fetchall()
        return out
    finally:
        con.close()


def turns(sat: list[tuple[str, float]], play: list[tuple[str, float]]):
    """Pair each responding->idle span with the audio that played inside it."""
    out = []
    start = None
    for state, ts in sat:
        if state == "responding":
            start = ts
        elif state == "idle" and start is not None:
            # first 'playing' at or after the responding edge
            audio = next((t for s, t in play
                          if s == "playing" and start - 0.5 <= t <= start + AUDIO_WINDOW_S), None)
            end_audio = None
            if audio is not None:
                end_audio = next((t for s, t in play if s == "idle" and t > audio), None)
            out.append({
                "at": dt.datetime.fromtimestamp(start),
                "responding": ts - start,
                "audio_start": (audio - start) if audio is not None else None,
                "audio_len": (end_audio - audio) if (audio and end_audio) else None,
            })
            start = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=3.0)
    # mDNS name, not a hard-coded LAN IP: this file is published to a public
    # mirror. Override with --host or HA_HOST for a different setup.
    ap.add_argument("--host",
                    default=os.environ.get("HA_HOST", "homeassistant.local"))
    ap.add_argument("--all", action="store_true",
                    help="include turns from before the streaming fix (different system)")
    ap.add_argument("--pre-leadin", action="store_true",
                    help="include turns between the streaming fix and the lead-in")
    args = ap.parse_args()

    remote = rf"\\{args.host}\config\home-assistant_v2.db"
    if not os.path.exists(remote):
        print(f"cannot reach {remote}", file=sys.stderr)
        return 1

    # Copy before reading: the live DB is WAL and a remote read can trip on a
    # concurrent checkpoint. A copy is slower but never fights the writer.
    tmp = os.path.join(tempfile.gettempdir(), "ha_states_snapshot.db")
    shutil.copy2(remote, tmp)

    since = (dt.datetime.now() - dt.timedelta(days=args.days)).timestamp()
    rows = []
    for label, sat_id, play_id in PAIRS:
        data = load_states(tmp, [sat_id, play_id], since)
        for t in turns(data.get(sat_id, []), data.get(play_id, [])):
            t["room"] = label
            rows.append(t)
    rows.sort(key=lambda r: r["at"])
    cutoff = LEADIN_FIX if not args.pre_leadin else STREAMING_FIX
    pre = [r for r in rows if r["at"] < cutoff]
    if not args.all and pre:
        rows = [r for r in rows if r["at"] >= cutoff]
        print(f"note: excluded {len(pre)} turn(s) from before the streaming fix "
              f"({STREAMING_FIX:%Y-%m-%d %H:%M}) — pass --all to include them\n")

    # Only turns that actually produced audio can be judged.
    judged = [r for r in rows if r["audio_start"] is not None]
    timed_out = [r for r in judged if TIMER_LO <= r["responding"] <= TIMER_HI]
    aborted = [r for r in judged
               if r not in timed_out and r["responding"] < TIMER_LO
               and (r["audio_len"] or 0) < ABORTED_AUDIO_S]
    tracked = [r for r in judged if r not in timed_out and r not in aborted]

    print(f"Voice turn timing — last {args.days:g} day(s), {len(rows)} turns "
          f"({len(judged)} with audio)\n")
    print(f"{'when':<20}{'room':<13}{'audio@':>9}{'responding':>12}   verdict")
    print("-" * 74)
    for r in judged:
        if r in timed_out:
            verdict = "TIMED OUT (2s watchdog)"
        elif r in aborted:
            verdict = "aborted audio (%.2fs)" % (r["audio_len"] or 0)
        else:
            verdict = "tracked"
        print(f"{r['at']:%Y-%m-%d %H:%M:%S}  {r['room']:<13}"
              f"{r['audio_start']:>8.2f}s{r['responding']:>11.2f}s   {verdict}")

    print()
    if tracked:
        lo = min(r["audio_start"] for r in tracked)
        hi = max(r["audio_start"] for r in tracked)
        print(f"  tracked   n={len(tracked):<4} audio started {lo:.2f}-{hi:.2f}s after TTS")
    if aborted:
        print(f"  aborted   n={len(aborted):<4} audio played <{ABORTED_AUDIO_S}s "
              f"— truncated generation, NOT the watchdog")
    if timed_out:
        lo = min(r["audio_start"] for r in timed_out)
        hi = max(r["audio_start"] for r in timed_out)
        print(f"  TIMED OUT n={len(timed_out):<4} audio started {lo:.2f}-{hi:.2f}s after TTS")

    if tracked and timed_out:
        margin = min(r["audio_start"] for r in timed_out) - max(r["audio_start"] for r in tracked)
        print(f"\n  threshold lies between {max(r['audio_start'] for r in tracked):.2f}s "
              f"and {min(r['audio_start'] for r in timed_out):.2f}s "
              f"(gap {margin:.2f}s)")
        if margin < 0:
            print("  !! OVERLAP — audio-start alone no longer separates the two "
                  "outcomes. Something else is involved; do not tune a constant "
                  "on this data.")
    elif tracked:
        worst = max(r["audio_start"] for r in tracked)
        print(f"\n  no failures in this window. Closest approach: {worst:.2f}s.")
        print("  Margin is the thing to watch — a rising worst-case predicts "
              "failures before users notice them.")

    if judged:
        rate = 100.0 * len(tracked) / len(judged)
        print(f"\n  success rate: {len(tracked)}/{len(judged)}  ({rate:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
