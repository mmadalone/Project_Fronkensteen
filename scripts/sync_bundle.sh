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
  "$BUNDLE/pyscript_modules/modules" \
  "$BUNDLE/pyscript_templates" \
  "$BUNDLE/packages" \
  "$BUNDLE/blueprints_automation" \
  "$BUNDLE/blueprints_script" \
  "$BUNDLE/helpers" \
  "$BUNDLE/scripts"

# Pyscript modules
cp "$REPO"/pyscript/*.py "$BUNDLE/pyscript/" 2>/dev/null || true
cp "$REPO/pyscript/modules/shared_utils.py" \
   "$BUNDLE/pyscript_modules/modules/" 2>/dev/null || true

# Config templates
cp "$REPO"/pyscript/*.template "$BUNDLE/pyscript_templates/" 2>/dev/null || true

# Packages
cp "$REPO"/packages/ai_*.yaml "$BUNDLE/packages/" 2>/dev/null || true

# Blueprints (stored at the repo root in automation/ and script/)
cp "$REPO"/automation/*.yaml "$BUNDLE/blueprints_automation/" 2>/dev/null || true
cp "$REPO"/script/*.yaml "$BUNDLE/blueprints_script/" 2>/dev/null || true

# Helper definitions
cp "$REPO"/helpers/helpers_*.yaml "$BUNDLE/helpers/" 2>/dev/null || true

# Scripts (sqlite-vec recompile helper)
cp "$REPO/scripts/recompile_vec0.sh" "$BUNDLE/scripts/" 2>/dev/null || true

# Patched HACS components.
#   - .zip for manual distribution
#   - pre-extracted directory for the installer wizard to copy from
# manifest.json is renamed to manifest.json.bundle in BOTH outputs so
# hassfest doesn't scan them as separate integrations during CI.
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

  mkdir -p "$BUNDLE/$comp"
  rsync -a \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='README.md' \
    "$src/" "$BUNDLE/$comp/"
  if [[ -f "$BUNDLE/$comp/manifest.json" ]]; then
    mv "$BUNDLE/$comp/manifest.json" "$BUNDLE/$comp/manifest.json.bundle"
  fi
done

echo "Bundle: $(find "$BUNDLE" -type f | wc -l | tr -d ' ') files"
