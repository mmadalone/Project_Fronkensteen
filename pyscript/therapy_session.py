"""Therapy Session Engine — QS-5 Therapy Mode Framework.

Persona-agnostic session state management for individual and couple therapy.
Tracks session numbers, turn history (couple mode), and session summaries.
Persists session data to L2 memory with QS-5 owner isolation.

Services:
  pyscript.therapy_session_start   — Initialize session, load history
  pyscript.therapy_session_end     — Generate summary, save to L2, cleanup
  pyscript.therapy_save_turn       — Log a conversation turn
  pyscript.therapy_session_report  — Generate .md report file
  pyscript.therapy_session_status  — Read-only status query
"""
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared_utils import (
    build_result_entity_name,
    resolve_active_user,
    resolve_memory_owner,
)

# ── Constants ──────────────────────────────────────────────────────────────

RESULT_ENTITY = "sensor.ai_therapy_status"
DEFAULT_TURN_HISTORY_SIZE = 15
REPORT_DIR = Path("/config/www/therapy_reports")

result_entity_name: dict[str, str] = {}


def _ensure_result_entity_name() -> None:
    """Ensure result_entity_name is populated."""
    global result_entity_name
    if not result_entity_name:
        result_entity_name = build_result_entity_name(RESULT_ENTITY)


def _set_status(state_value: str, **attrs: Any) -> None:
    """Set the therapy status sensor."""
    _ensure_result_entity_name()
    attrs.update(result_entity_name)
    state.set(RESULT_ENTITY, value=state_value, new_attributes=attrs)  # noqa: F821


def _is_test_mode() -> bool:
    """Check if test mode is active."""
    try:
        return str(
            state.get("input_boolean.ai_test_mode") or "off"  # noqa: F821
        ).lower() == "on"
    except NameError:
        return False


def _utcnow_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(UTC).isoformat()


# ── Session State (in-memory, backed by sensor attributes) ─────────────

_session: dict[str, Any] = {
    "active": False,
    "session_number": 0,
    "session_type": "individual",
    "therapist": "",
    "active_speaker": "",
    "turn_history": [],
    "session_start": "",
    "couple_users": "",
    "resumed": False,
    "turn_history_size": DEFAULT_TURN_HISTORY_SIZE,
}


def _publish_sensor() -> None:
    """Publish current session state to the sensor."""
    st = "active" if _session["active"] else "idle"
    _set_status(
        st,
        session_number=_session["session_number"],
        session_type=_session["session_type"],
        therapist=_session["therapist"],
        active_speaker=_session["active_speaker"],
        turn_history=_session["turn_history"],
        session_start=_session["session_start"],
        couple_users=_session["couple_users"],
        resumed=_session["resumed"],
    )


# ── Checkpoint (L2 memory for crash recovery) ─────────────────────────

async def _save_checkpoint(user: str) -> None:
    """Persist session state to L2 for crash recovery."""
    key = f"therapy:active_session:{user}"
    val = json.dumps({
        "session_number": _session["session_number"],
        "session_type": _session["session_type"],
        "therapist": _session["therapist"],
        "turn_count": len(_session["turn_history"]),
        "turn_history": _session["turn_history"][-10:],  # last 10 for space
        "started_at": _session["session_start"],
        "couple_users": _session["couple_users"],
    }, separators=(",", ":"))
    try:
        await pyscript.memory_set(  # noqa: F821
            key=key,
            value=val,
            scope="session",
            expiration_days=1,
            tags="therapy checkpoint recovery",
            force_new=True,
        )
    except Exception as exc:
        log.warning(f"therapy: checkpoint save failed: {exc}")  # noqa: F821


async def _load_checkpoint(user: str) -> dict[str, Any] | None:
    """Load crash recovery checkpoint if one exists."""
    key = f"therapy:active_session:{user}"
    try:
        result = await pyscript.memory_get(key=key)  # noqa: F821
        if isinstance(result, dict) and result.get("status") == "ok":
            val = result.get("value", "")
            if val:
                return json.loads(val)
    except Exception:
        pass
    return None


async def _clear_checkpoint(user: str) -> None:
    """Remove the crash recovery checkpoint."""
    key = f"therapy:active_session:{user}"
    try:
        await pyscript.memory_forget(key=key)  # noqa: F821
    except Exception:
        pass


# ── Services ──────────────────────────────────────────────────────────

@service(supports_response="only")  # noqa: F821
async def therapy_session_start(
    user: str = "",
    session_type: str = "individual",
    therapist: str = "doctor_portuondo",
    couple_users: str = "",
    turn_history_size: int = DEFAULT_TURN_HISTORY_SIZE,
):
    """
    yaml
    name: Therapy Session Start
    description: >-
      Initialize a therapy session. Loads session history from L2 memory,
      checks for crash recovery checkpoint, and publishes session state.
    fields:
      user:
        name: User
        description: Person slug for individual session (auto-resolved if empty).
        default: ""
        selector:
          text:
      session_type:
        name: Session Type
        description: '"individual" or "couple".'
        default: individual
        selector:
          select:
            options:
              - individual
              - couple
      therapist:
        name: Therapist
        description: Therapist persona slug.
        default: doctor_portuondo
        selector:
          text:
      couple_users:
        name: Couple Users
        description: Comma-separated user slugs for couple session.
        default: ""
        selector:
          text:
      turn_history_size:
        name: Turn History Size
        description: Max turns to keep in rolling buffer.
        default: 15
        selector:
          number:
            min: 5
            max: 50
    """
    if _is_test_mode():
        log.info("therapy [TEST]: would start session")  # noqa: F821
        return {"status": "test_mode_skip"}

    t_start = time.monotonic()

    if not user:
        user = resolve_active_user()

    session_key = user if session_type == "individual" else "couple"

    # ── Check for crash recovery checkpoint ──
    checkpoint = await _load_checkpoint(session_key)
    resumed = False
    restored_turns: list[dict[str, str]] = []
    if checkpoint:
        resumed = True
        restored_turns = checkpoint.get("turn_history", [])
        log.info(  # noqa: F821
            "therapy: resuming interrupted session %s (turn %d)",
            checkpoint.get("session_number", "?"),
            checkpoint.get("turn_count", 0),
        )

    # ── Load session count from L2 ──
    count_key = f"therapy:session_count:{session_key}"
    session_number = 1
    try:
        result = await pyscript.memory_get(key=count_key, owner=user)  # noqa: F821
        if isinstance(result, dict) and result.get("status") == "ok":
            session_number = int(result.get("value", "0")) + 1
    except Exception:
        pass

    if resumed and checkpoint:
        session_number = checkpoint.get("session_number", session_number)

    # ── Load last session summary from L2 ──
    last_summary = ""
    try:
        result = await pyscript.memory_search(  # noqa: F821
            query=f"therapy session {session_key}",
            limit=1,
            owner=user,
        )
        if isinstance(result, dict) and result.get("status") == "ok":
            results = result.get("results", [])
            if results and not results[0].get("restricted"):
                last_summary = results[0].get("value", "")[:500]
    except Exception:
        pass

    # ── Initialize session state ──
    now_iso = _utcnow_iso()
    _session.update({
        "active": True,
        "session_number": session_number,
        "session_type": session_type,
        "therapist": therapist,
        "active_speaker": user if session_type == "individual" else "",
        "turn_history": restored_turns,
        "session_start": now_iso,
        "couple_users": couple_users,
        "resumed": resumed,
        "turn_history_size": max(5, min(turn_history_size, 50)),
    })

    # ── Set helpers ──
    try:
        await service.call(  # noqa: F821
            "input_datetime", "set_datetime",
            entity_id="input_datetime.ai_therapy_session_start",
            datetime=now_iso[:19],
        )
    except Exception:
        pass

    _publish_sensor()

    elapsed = round((time.monotonic() - t_start) * 1000)
    return {
        "status": "ok",
        "session_number": session_number,
        "session_type": session_type,
        "therapist": therapist,
        "last_summary": last_summary,
        "resumed": resumed,
        "restored_turn_count": len(restored_turns),
        "elapsed_ms": elapsed,
    }


@service(supports_response="only")  # noqa: F821
async def therapy_session_end(
    user: str = "",
    session_type: str = "",
    therapist: str = "",
    session_number: int = 0,
    summary: str = "",
):
    """
    yaml
    name: Therapy Session End
    description: >-
      End a therapy session. Saves session summary to L2 memory,
      increments session counter, clears checkpoint.
    fields:
      user:
        name: User
        description: Person slug (auto-resolved if empty).
        default: ""
        selector:
          text:
      session_type:
        name: Session Type
        description: '"individual" or "couple".'
        default: ""
        selector:
          text:
      therapist:
        name: Therapist
        default: ""
        selector:
          text:
      session_number:
        name: Session Number
        default: 0
        selector:
          number:
            min: 0
            max: 9999
      summary:
        name: Summary
        description: Session summary text (from LLM or auto-generated).
        default: ""
        selector:
          text:
            multiline: true
    """
    if _is_test_mode():
        log.info("therapy [TEST]: would end session")  # noqa: F821
        return {"status": "test_mode_skip"}

    t_start = time.monotonic()

    # Fall back to active session state
    if not user:
        user = resolve_active_user()
    if not session_type:
        session_type = _session.get("session_type", "individual")
    if not therapist:
        therapist = _session.get("therapist", "unknown")
    if not session_number:
        session_number = _session.get("session_number", 0)

    session_key = user if session_type == "individual" else "couple"
    scope = "user" if session_type == "individual" else "couple"
    owner = resolve_memory_owner(user, scope)
    now_iso = _utcnow_iso()
    ts_compact = now_iso[:19].replace(":", "").replace("-", "").replace("T", "_")

    # ── Save session summary ──
    summary_text = summary or f"Session {session_number} with {therapist}"
    summary_key = f"therapy:session:{session_key}:{ts_compact}"
    try:
        await pyscript.memory_set(  # noqa: F821
            key=summary_key,
            value=summary_text,
            scope=scope,
            owner=owner,
            expiration_days=0,
            tags=f"therapy session {session_key} {therapist}",
            force_new=True,
        )
    except Exception as exc:
        log.warning(f"therapy: summary save failed: {exc}")  # noqa: F821

    # ── Update session counter ──
    count_key = f"therapy:session_count:{session_key}"
    try:
        await pyscript.memory_set(  # noqa: F821
            key=count_key,
            value=str(session_number),
            scope=scope,
            owner=owner,
            expiration_days=0,
            tags=f"therapy meta {session_key}",
            force_new=True,
        )
    except Exception as exc:
        log.warning(f"therapy: counter save failed: {exc}")  # noqa: F821

    # ── Set last session datetime ──
    try:
        await service.call(  # noqa: F821
            "input_datetime", "set_datetime",
            entity_id="input_datetime.ai_therapy_last_session",
            datetime=now_iso[:19],
        )
    except Exception:
        pass

    # ── Clear checkpoint ──
    await _clear_checkpoint(session_key)

    # ── Reset session state ──
    _session.update({
        "active": False,
        "session_number": 0,
        "session_type": "individual",
        "therapist": "",
        "active_speaker": "",
        "turn_history": [],
        "session_start": "",
        "couple_users": "",
        "resumed": False,
    })
    _publish_sensor()

    elapsed = round((time.monotonic() - t_start) * 1000)
    return {
        "status": "ok",
        "session_number": session_number,
        "summary_key": summary_key,
        "elapsed_ms": elapsed,
    }


@service(supports_response="only")  # noqa: F821
async def therapy_save_turn(
    speaker: str = "",
    content: str = "",
):
    """
    yaml
    name: Therapy Save Turn
    description: >-
      Log a therapy session turn. Called by the LLM after each patient speaks.
      Updates turn history and active speaker in the session sensor.
    fields:
      speaker:
        name: Speaker
        description: Who spoke (person slug from HA).
        required: true
        selector:
          text:
      content:
        name: Content
        description: Brief 5-10 word summary of what was said.
        required: true
        selector:
          text:
    """
    if not _session.get("active"):
        return {"status": "error", "error": "no_active_session"}

    speaker_norm = (speaker or "").strip().lower()
    content_norm = (content or "").strip()[:100]

    if not speaker_norm or not content_norm:
        return {"status": "error", "error": "missing_speaker_or_content"}

    # Append to rolling buffer
    _session["turn_history"].append({"s": speaker_norm, "c": content_norm})

    # Cap at configured size
    max_size = _session.get("turn_history_size", DEFAULT_TURN_HISTORY_SIZE)
    if len(_session["turn_history"]) > max_size:
        _session["turn_history"] = _session["turn_history"][-max_size:]

    # Update active speaker
    _session["active_speaker"] = speaker_norm

    _publish_sensor()

    # Periodic checkpoint (every 3 turns)
    if len(_session["turn_history"]) % 3 == 0:
        session_key = (
            _session.get("couple_users", "").split(",")[0].strip()
            if _session.get("session_type") == "couple"
            else resolve_active_user()
        )
        if _session.get("session_type") == "couple":
            session_key = "couple"
        await _save_checkpoint(session_key)

    return {"status": "ok", "turn_count": len(_session["turn_history"])}


@pyscript_executor  # noqa: F821
def _generate_report_sync(
    user: str,
    session_type: str,
    session_number: int,
    summary: str,
    therapist: str,
    turns: list[dict[str, str]],
    session_date: str,
    output_dir: str,
) -> dict[str, Any]:
    """Generate a .md therapy session report (runs in executor thread)."""
    import os as _os

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    slug = user if session_type == "individual" else "couple"
    filename = f"session_{slug}_{session_number}.md"
    filepath = out_path / filename

    lines = [
        "# Therapy Session Report",
        "",
        f"**Session:** #{session_number} | **Type:** {session_type.title()} "
        f"| **Date:** {session_date[:10]}",
        f"**Therapist:** {therapist} | **Turns:** {len(turns)}",
        "",
        "## Summary",
        "",
        summary or "No summary available.",
        "",
    ]

    if turns:
        lines.append("## Conversation Turns")
        lines.append("")
        for t in turns:
            speaker = t.get("s", "?").title()
            content = t.get("c", "")
            lines.append(f"- **[{speaker}]** {content}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated: {session_date}*")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    rel_path = f"/local/therapy_reports/{filename}"

    return {"filepath": str(filepath), "url": rel_path, "filename": filename}


@service(supports_response="only")  # noqa: F821
async def therapy_session_report(
    user: str = "",
    session_number: int = 0,
    session_type: str = "",
    output_dir: str = "",
):
    """
    yaml
    name: Therapy Session Report
    description: >-
      Generate a therapy session report in markdown format.
      Returns the file path and download URL.
    fields:
      user:
        name: User
        description: Person slug (auto-resolved if empty).
        default: ""
        selector:
          text:
      session_number:
        name: Session Number
        description: Session to report on. 0 = most recent.
        default: 0
        selector:
          number:
            min: 0
            max: 9999
      session_type:
        name: Session Type
        default: ""
        selector:
          text:
      output_dir:
        name: Output Directory
        default: ""
        selector:
          text:
    """
    if _is_test_mode():
        log.info("therapy [TEST]: would generate report")  # noqa: F821
        return {"status": "test_mode_skip"}

    if not user:
        user = resolve_active_user()
    if not session_type:
        session_type = "individual"
    if not output_dir:
        output_dir = str(REPORT_DIR)

    session_key = user if session_type == "individual" else "couple"

    # ── Resolve session number ──
    if session_number == 0:
        count_key = f"therapy:session_count:{session_key}"
        try:
            result = await pyscript.memory_get(key=count_key, owner=user)  # noqa: F821
            if isinstance(result, dict) and result.get("status") == "ok":
                session_number = int(result.get("value", "0"))
        except Exception:
            pass
    if session_number == 0:
        return {"status": "error", "error": "no_sessions_found"}

    # ── Load session summary ──
    summary = ""
    therapist = "unknown"
    session_date = _utcnow_iso()
    try:
        result = await pyscript.memory_search(  # noqa: F821
            query=f"therapy session {session_key}",
            limit=5,
            owner=user,
        )
        if isinstance(result, dict) and result.get("status") == "ok":
            for r in result.get("results", []):
                if not r.get("restricted"):
                    summary = r.get("value", "")
                    session_date = r.get("created_at", session_date)
                    tags = r.get("tags", "")
                    for tag in tags.split():
                        if tag not in (
                            "therapy", "session", session_key, "couple"
                        ):
                            therapist = tag
                    break
    except Exception:
        pass

    # ── Load turn history from checkpoint (if available) ──
    turns: list[dict[str, str]] = []
    checkpoint = await _load_checkpoint(session_key)
    if checkpoint and checkpoint.get("session_number") == session_number:
        turns = checkpoint.get("turn_history", [])

    # ── Generate report ──
    report = _generate_report_sync(
        user=user,
        session_type=session_type,
        session_number=session_number,
        summary=summary,
        therapist=therapist,
        turns=turns,
        session_date=session_date,
        output_dir=output_dir,
    )

    return {
        "status": "ok",
        "session_number": session_number,
        "filepath": report.get("filepath", ""),
        "url": report.get("url", ""),
        "filename": report.get("filename", ""),
    }


@service(supports_response="only")  # noqa: F821
async def therapy_session_status():
    """
    yaml
    name: Therapy Session Status
    description: >-
      Return current therapy session state (read-only).
    """
    return {
        "status": "ok",
        "active": _session.get("active", False),
        "session_number": _session.get("session_number", 0),
        "session_type": _session.get("session_type", "individual"),
        "therapist": _session.get("therapist", ""),
        "active_speaker": _session.get("active_speaker", ""),
        "turn_count": len(_session.get("turn_history", [])),
        "session_start": _session.get("session_start", ""),
        "couple_users": _session.get("couple_users", ""),
        "resumed": _session.get("resumed", False),
    }


# ── Startup: publish idle sensor ──────────────────────────────────────

@time_trigger("startup")  # noqa: F821
async def _therapy_startup():
    """Publish idle sensor on startup."""
    _publish_sensor()
