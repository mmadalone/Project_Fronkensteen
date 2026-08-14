#!/bin/bash
# scripts/sync_bundle.sh
# ---------------------------------------------------------------------------
# Rebuilds custom_components/project_fronkensteen/bundle/ from the repo's
# authoritative directories. Called by .github/workflows/release.yaml on
# tag push; the resulting bundle is what HACS users install (the wizard
# inside the integration copies subsets of bundle/* into a user's HA
# config dirs at install time).
#
# This used to live inline in the local sync script
# (~/_Claude Projects/ha-master-sync-to-repo.sh). Extracted to CI on
# 2026-05-02 so releases are reproducible from the repo's authoritative
# state, not whatever a developer last ran locally.
# ---------------------------------------------------------------------------
set -euo pipefail

# Resolve REPO to an absolute path. The patched-component zip step does
# `cd "$src"` before invoking zip, so a relative $BUNDLE would resolve
# to the wrong location and zip exits 15 ("cannot open output file").
REPO_ARG="${1:-.}"
REPO="$(cd "$REPO_ARG" && pwd -P)"
BUNDLE="$REPO/custom_components/project_fronkensteen/bundle"

if [[ ! -d "$REPO/custom_components/project_fronkensteen" ]]; then
  echo "ERROR: $REPO/custom_components/project_fronkensteen not found"
  exit 1
fi

echo "Building HACS installer bundle..."
rm -rf "$BUNDLE"
mkdir -p \
  "$BUNDLE/pyscript" \
  "$BUNDLE/pyscript/modules" \
  "$BUNDLE/pyscript_templates" \
  "$BUNDLE/packages" \
  "$BUNDLE/blueprints_automation" \
  "$BUNDLE/blueprints_script" \
  "$BUNDLE/helpers" \
  "$BUNDLE/scripts"

# Pyscript modules
#
# shared_utils.py MUST land in bundle/pyscript/modules/. const.py declares it as
# "modules/shared_utils.py" inside PYSCRIPT_FILES, so installer.py resolves it
# relative to the `pyscript` bundle subdir. It previously went to
# bundle/pyscript_modules/, which is not a BUNDLE_TO_DEST key and was read by
# nothing — so this `core` file never installed and every install logged
# "Missing from bundle".
cp "$REPO"/pyscript/*.py "$BUNDLE/pyscript/"
cp "$REPO/pyscript/modules/shared_utils.py" "$BUNDLE/pyscript/modules/"

# Config templates
cp "$REPO"/pyscript/*.template "$BUNDLE/pyscript_templates/"

# Packages
cp "$REPO"/packages/ai_*.yaml "$BUNDLE/packages/"

# Blueprints (stored at the repo root in automation/ and script/)
cp "$REPO"/automation/*.yaml "$BUNDLE/blueprints_automation/"
cp "$REPO"/script/*.yaml "$BUNDLE/blueprints_script/"

# Helper definitions
cp "$REPO"/helpers/helpers_*.yaml "$BUNDLE/helpers/"

# Scripts (sqlite-vec recompile helper)
cp "$REPO/scripts/recompile_vec0.sh" "$BUNDLE/scripts/"

# Patched HACS components — shipped as .zip only.
#
# installer.py consumes COMPONENT_ZIPS exclusively (installer.py:317, :359).
# The pre-extracted bundle/<comp>/ directories this used to also produce were
# read by nothing: ELEVENLABS_TTS_FILES / EOC_FILES feed only COMPONENT_RENAMES,
# which installer.py:277 applies to files coming from get_files_for_groups(),
# and that never yields those dirs. They were ~30 dead files in every download.
#
# manifest.json is renamed to manifest.json.bundle inside the zip so hassfest
# doesn't scan the bundled component as a second integration during CI;
# installer.py:92-95 reverses the rename on extraction.
for comp in elevenlabs_custom_tts extended_openai_conversation; do
  src="$REPO/source_components/$comp"
  if [[ ! -d "$src" ]]; then
    echo "  skipping $comp (no source dir at $src)"
    continue
  fi

  (
    cd "$src"
    cp manifest.json manifest.json.bundle 2>/dev/null || true
    zip -r "$BUNDLE/${comp}.zip" . \
      -x "*.pyc" "__pycache__/*" "README.md" "manifest.json" >/dev/null
    rm -f manifest.json.bundle
  )
  echo "  ${comp}.zip"
done

echo "Bundle: $(find "$BUNDLE" -type f | wc -l | tr -d ' ') files"
