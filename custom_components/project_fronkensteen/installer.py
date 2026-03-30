"""File installer for Project Fronkensteen.

Copies bundled files from the integration directory to the correct
locations under /config/. Handles first-time install, updates, and repair.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant

from .const import (
    BUNDLE_TO_DEST,
    CODE_SUBDIRS,
    ELEVENLABS_RENAME,
    HELPER_FILES,
    SKIP_ON_UPDATE_SUBDIRS,
    get_files_for_groups,
)

_LOGGER = logging.getLogger(__name__)


def _bundle_path(hass: HomeAssistant) -> Path:
    """Return the path to the bundle directory inside this integration."""
    return Path(__file__).parent / "bundle"


def _dest_path(hass: HomeAssistant, target_subdir: str) -> Path:
    """Return the destination path under /config/."""
    if target_subdir:
        return Path(hass.config.path(target_subdir))
    return Path(hass.config.path())


def _file_hash(path: Path) -> str | None:
    """Return SHA-256 hash of a file, or None if it doesn't exist."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_file(src: Path, dst: Path) -> None:
    """Copy a single file, creating parent directories as needed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    _LOGGER.debug("Copied %s -> %s", src.name, dst)


# ── Template placeholders ───────────────────────────────────────────────────
# Templates use {{PLACEHOLDER}} syntax to avoid collision with real content.

_TEMPLATE_SUBS = {
    "{{PERSON_SLUG}}": "person_slug",
    "{{DISPLAY_NAME}}": "display_name",
    "{{TTS_PRONUNCIATION}}": "tts_pronunciation",
    "{{DEFAULT_SPEAKER}}": "default_speaker",
    "{{HOUSEHOLD_MEMBERS}}": "household_members",
    "{{PETS}}": "pets",
    "{{PREFERRED_LANGUAGE}}": "preferred_language",
}


def _copy_template(src: Path, dst: Path, config_data: dict | None) -> None:
    """Copy a template file, substituting {{PLACEHOLDER}} values."""
    content = src.read_text(encoding="utf-8")

    if config_data:
        for placeholder, key in _TEMPLATE_SUBS.items():
            value = config_data.get(key, "")
            if value:
                content = content.replace(placeholder, value)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")
    _LOGGER.debug("Template -> %s", dst)


# ── Helper merge ────────────────────────────────────────────────────────────


def _merge_helpers(src: Path, dst: Path) -> dict:
    """Compare bundle helper file against existing.

    Returns {new_keys: [...], existing_keys: [...], file: str}.
    Does NOT modify any files.
    """
    report = {"new_keys": [], "existing_keys": [], "file": src.name}

    src_text = src.read_text(encoding="utf-8")
    src_lines = [l for l in src_text.split("\n") if not l.strip().startswith("#")]
    src_data = yaml.safe_load("\n".join(src_lines)) or {}

    if not dst.exists():
        report["new_keys"] = list(src_data.keys())
        return report

    dst_text = dst.read_text(encoding="utf-8")
    dst_lines = [l for l in dst_text.split("\n") if not l.strip().startswith("#")]
    dst_data = yaml.safe_load("\n".join(dst_lines)) or {}

    for key in src_data:
        if key in dst_data:
            report["existing_keys"].append(key)
        else:
            report["new_keys"].append(key)

    return report


def _apply_helper_merge(src: Path, dst: Path, keys_to_add: list[str]) -> int:
    """Append new helper entries from src to dst.

    Extracts the YAML block for each key (preserving preceding comments)
    and appends to the destination file. Returns entries added.
    """
    if not keys_to_add:
        return 0

    src_text = src.read_text(encoding="utf-8")
    lines = src_text.split("\n")
    added = 0

    blocks_to_add = []
    for key in keys_to_add:
        block_lines = []
        in_block = False
        pending_comments = []

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("#") and not in_block:
                pending_comments.append(line)
                continue

            if line.startswith(f"{key}:"):
                in_block = True
                block_lines.extend(pending_comments)
                block_lines.append(line)
                pending_comments = []
                continue

            if in_block:
                if line and not line[0].isspace() and not stripped.startswith("#"):
                    break
                block_lines.append(line)
            else:
                pending_comments = []

        if block_lines:
            blocks_to_add.append("\n".join(block_lines))
            added += 1

    if blocks_to_add:
        dst_text = dst.read_text(encoding="utf-8")
        if not dst_text.endswith("\n"):
            dst_text += "\n"
        dst_text += "\n# ── Added by Project Fronkensteen installer ──\n\n"
        dst_text += "\n\n".join(blocks_to_add)
        dst_text += "\n"
        dst.write_text(dst_text, encoding="utf-8")

    return added


# ── Core operations ─────────────────────────────────────────────────────────


def _process_file(
    bundle_subdir: str,
    filename: str,
    src: Path,
    dest_dir: Path,
    household_data: dict | None,
    mode: str,
) -> str:
    """Process a single file. Returns 'copied', 'skipped', or 'merged'.

    mode: 'install' (first time) or 'update' (HACS version change).
    """
    # Config templates: only on first install, only if target missing
    if bundle_subdir == "pyscript_templates":
        target_name = filename.replace(".template", "")
        dst = dest_dir / target_name
        if dst.exists():
            return "skipped"
        _copy_template(src, dst, household_data)
        return "copied"

    # Scripts: only if target missing
    if bundle_subdir == "scripts":
        dst = dest_dir / filename
        if dst.exists():
            return "skipped"
        _copy_file(src, dst)
        try:
            dst.chmod(dst.stat().st_mode | 0o755)
        except OSError:
            pass  # Non-Unix platforms
        return "copied"

    # Helpers: merge new entries
    if bundle_subdir == "helpers":
        dst = dest_dir / filename
        if not dst.exists():
            _copy_file(src, dst)
            return "copied"
        merge = _merge_helpers(src, dst)
        if merge["new_keys"]:
            _apply_helper_merge(src, dst, merge["new_keys"])
            _LOGGER.info("Merged %d new helpers into %s", len(merge["new_keys"]), filename)
            return "merged"
        return "skipped"

    # Skip templates/scripts on update
    if mode == "update" and bundle_subdir in SKIP_ON_UPDATE_SUBDIRS:
        return "skipped"

    # Code files — apply renames (e.g., manifest.json.bundle -> manifest.json)
    target_name = ELEVENLABS_RENAME.get(filename, filename)
    dst = dest_dir / target_name
    if mode == "update" and dst.exists() and _file_hash(src) == _file_hash(dst):
        return "skipped"
    _copy_file(src, dst)
    return "copied"


async def install(
    hass: HomeAssistant,
    selected_groups: list[str],
    household_data: dict | None = None,
) -> dict:
    """First-time installation. Returns {copied, skipped, errors}."""
    report = {"copied": 0, "skipped": 0, "errors": []}

    def _do_install() -> dict:
        bundle = _bundle_path(hass)
        if not bundle.is_dir():
            report["errors"].append(f"Bundle directory not found: {bundle}")
            return report

        for bundle_subdir, filenames in get_files_for_groups(selected_groups).items():
            dest_subdir = BUNDLE_TO_DEST.get(bundle_subdir, bundle_subdir)
            src_dir = bundle / bundle_subdir
            dest_dir = _dest_path(hass, dest_subdir)

            for filename in filenames:
                src = src_dir / filename
                if not src.is_file():
                    report["errors"].append(f"Missing from bundle: {bundle_subdir}/{filename}")
                    continue
                result = _process_file(bundle_subdir, filename, src, dest_dir, household_data, "install")
                if result in ("copied", "merged"):
                    report["copied"] += 1
                else:
                    report["skipped"] += 1

        return report

    return await hass.async_add_executor_job(_do_install)


async def update(
    hass: HomeAssistant,
    old_version: str,
    new_version: str,
    selected_groups: list[str],
) -> dict:
    """Update after HACS version change. Re-copies code, preserves configs."""
    report = {"copied": 0, "skipped": 0, "errors": []}

    def _do_update() -> dict:
        bundle = _bundle_path(hass)
        if not bundle.is_dir():
            report["errors"].append(f"Bundle directory not found: {bundle}")
            return report

        for bundle_subdir, filenames in get_files_for_groups(selected_groups).items():
            dest_subdir = BUNDLE_TO_DEST.get(bundle_subdir, bundle_subdir)
            src_dir = bundle / bundle_subdir
            dest_dir = _dest_path(hass, dest_subdir)

            for filename in filenames:
                src = src_dir / filename
                if not src.is_file():
                    continue
                result = _process_file(bundle_subdir, filename, src, dest_dir, None, "update")
                if result in ("copied", "merged"):
                    report["copied"] += 1
                else:
                    report["skipped"] += 1

        _LOGGER.info("Update %s -> %s: %d copied, %d skipped", old_version, new_version, report["copied"], report["skipped"])
        return report

    return await hass.async_add_executor_job(_do_update)


async def verify(hass: HomeAssistant, selected_groups: list[str]) -> dict:
    """Verify installation. Returns {missing, outdated, ok, errors}."""
    result = {"missing": [], "outdated": [], "ok": [], "errors": []}

    def _do_verify() -> dict:
        bundle = _bundle_path(hass)
        if not bundle.is_dir():
            result["errors"].append(f"Bundle directory not found: {bundle}")
            return result

        for bundle_subdir, filenames in get_files_for_groups(selected_groups).items():
            dest_subdir = BUNDLE_TO_DEST.get(bundle_subdir, bundle_subdir)
            src_dir = bundle / bundle_subdir
            dest_dir = _dest_path(hass, dest_subdir)

            for filename in filenames:
                src = src_dir / filename
                target_name = filename.replace(".template", "") if bundle_subdir == "pyscript_templates" else filename
                dst = dest_dir / target_name
                path_label = f"{dest_subdir}/{target_name}" if dest_subdir else target_name

                if not dst.exists():
                    result["missing"].append(path_label)
                elif bundle_subdir in CODE_SUBDIRS:
                    if src.is_file() and _file_hash(src) != _file_hash(dst):
                        result["outdated"].append(path_label)
                    else:
                        result["ok"].append(path_label)
                else:
                    result["ok"].append(path_label)

        return result

    return await hass.async_add_executor_job(_do_verify)


async def repair(hass: HomeAssistant, selected_groups: list[str]) -> dict:
    """Re-copy missing or outdated code files. Never touches user configs."""
    verification = await verify(hass, selected_groups)
    report = {"repaired": 0, "errors": verification["errors"]}

    def _do_repair() -> dict:
        bundle = _bundle_path(hass)
        targets = set(verification["missing"] + verification["outdated"])

        for bundle_subdir, filenames in get_files_for_groups(selected_groups).items():
            if bundle_subdir not in CODE_SUBDIRS:
                continue
            dest_subdir = BUNDLE_TO_DEST[bundle_subdir]
            src_dir = bundle / bundle_subdir
            dest_dir = _dest_path(hass, dest_subdir)

            for filename in filenames:
                path_label = f"{dest_subdir}/{filename}" if dest_subdir else filename
                if path_label in targets:
                    src = src_dir / filename
                    if src.is_file():
                        _copy_file(src, dest_dir / filename)
                        report["repaired"] += 1

        return report

    return await hass.async_add_executor_job(_do_repair)


async def merge_helpers(hass: HomeAssistant) -> dict:
    """Analyze all helper files. Returns {files: [...], total_new: int}."""
    def _do() -> dict:
        bundle = _bundle_path(hass)
        src_dir = bundle / "helpers"
        dest_dir = _dest_path(hass, "")
        result = {"files": [], "total_new": 0}

        if not src_dir.is_dir():
            return result

        for filename in HELPER_FILES:
            src = src_dir / filename
            if not src.is_file():
                continue
            report = _merge_helpers(src, dest_dir / filename)
            result["files"].append(report)
            result["total_new"] += len(report["new_keys"])

        return result

    return await hass.async_add_executor_job(_do)


async def apply_helper_merge(hass: HomeAssistant, approved_keys: dict[str, list[str]]) -> dict:
    """Apply approved helper merges. Returns {added: int}."""
    def _do() -> dict:
        bundle = _bundle_path(hass)
        src_dir = bundle / "helpers"
        dest_dir = _dest_path(hass, "")
        total = 0

        for filename, keys in approved_keys.items():
            src = src_dir / filename
            dst = dest_dir / filename
            if src.is_file():
                total += _apply_helper_merge(src, dst, keys)

        return {"added": total}

    return await hass.async_add_executor_job(_do)
