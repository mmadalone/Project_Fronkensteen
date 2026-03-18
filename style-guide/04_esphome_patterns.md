# Home Assistant Style Guide — ESPHome Patterns

Section 6 — Device config structure, packages, secrets, wake words, naming, and archiving.

---

## 6. ESPHOME DEVICE PATTERNS

### 6.1 Config file structure (MANDATORY)
Every ESPHome device config MUST follow this section order. Keep sections visually separated with comments:

```yaml
# ── Identity ──────────────────────────────────────────
substitutions:
  name: home-assistant-voice-0905c5
  friendly_name: HA Workshop

# ── Base package ──────────────────────────────────────
packages:
  Nabu Casa.Home Assistant Voice PE:
    github://esphome/home-assistant-voice-pe/home-assistant-voice.yaml

# ── Core config ───────────────────────────────────────
esphome:
  name: ${name}
  name_add_mac_suffix: false
  friendly_name: ${friendly_name}
  area: Workshop          # Auto-assigns device to this HA area
  min_version: 2025.6.0   # Prevents compilation on older ESPHome versions

# ── Connectivity ──────────────────────────────────────
api:
  encryption:
    key: !secret api_key_workshop

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

# ── Device-specific extensions ────────────────────────
# (wake words, sensors, custom components, etc.)
```

**Section order:**
1. `substitutions` — identity variables
2. `packages` — base device packages (if using)
3. `esphome` — core device settings (including `area` and `min_version`)
4. `api` — API encryption
5. `wifi` — network config
6. Device-specific components (wake words, sensors, switches, etc.)
7. `debug` / diagnostic sensors (last — these are optional dev aids)

**`min_version`** — configs SHOULD include `min_version` inside the `esphome:` block. This prevents compilation against older ESPHome versions that lack features your config depends on. Set it to the oldest version that supports all features used in the config. Particularly important for package-based devices where a package update may introduce newer syntax.

> **Framework change (ESPHome 2026.1.0):** ESP-IDF is now the **default framework** for ESP32, ESP32-C3, ESP32-S2, and ESP32-S3 targets, replacing Arduino. This delivers up to 40% smaller binaries and faster compile times. Most configs need no changes — ESPHome handles the framework transparently. If you explicitly set `framework: type: arduino` in a config, it still works but you're opting out of the size/speed improvements. Only specify the framework explicitly if you depend on an Arduino-only library. Also new in 2026.1: automatic **WiFi roaming** (devices switch to stronger APs after connecting) — no config needed, it just works.

**`area`** — since ESPHome 2023.11.0, the `area` field auto-assigns the device to an HA area on adoption, eliminating manual registry edits. Use the exact HA area name (e.g., `Workshop`, `Living Room`). If the area doesn't exist in HA, it will be created automatically. (Note: ESPHome 2025.7.0 introduced sub-devices with the `devices:` block and per-device `area:` — see §6.12. The top-level `area:` field predates that by nearly two years.)

### 6.2 Substitutions (MANDATORY)
Every ESPHome config MUST use `substitutions` for values referenced in multiple places. At minimum:

```yaml
substitutions:
  name: home-assistant-voice-0905c5
  friendly_name: HA Workshop
```

**Rules:**
- `name` is the ESPHome device hostname — must be DNS-safe (lowercase, hyphens, no spaces).
- `friendly_name` is the human-readable name shown in HA and the ESPHome dashboard.
- Additional substitutions for any value repeated 2+ times (GPIO pins, thresholds, IP addresses).
- Reference with `${variable_name}` syntax throughout the config.

**Extended substitutions for complex devices:**

```yaml
substitutions:
  name: workshop-multisensor
  friendly_name: Workshop Multisensor
  update_interval: 30s
  i2c_sda: GPIO21
  i2c_scl: GPIO22
  temperature_offset: "-1.5"
```

### 6.3 GitHub packages — extending without replacing
When using a base package (like the Voice PE package), your config file **extends** the package — it does NOT replace it. ESPHome merges your local config on top of the package.

**Key rules for package extension:**
- Components with list values (like `micro_wake_word.models`) **merge by `id`** if components have an `id` field, otherwise they are **concatenated** to the package's list.
- Components with scalar values (like `wifi.ssid`) **override** the package's value.
- You only need to specify what's different or added — don't repeat anything the package already defines.

```yaml
# GOOD — only adds custom wake words, package's defaults remain
micro_wake_word:
  models:
    - id: hey_rick
      model: http://homeassistant.local:8123/local/microwake/hey_rick.json

# BAD — unnecessarily repeats the package's default models
micro_wake_word:
  models:
    - model: okay_nabu      # ← already in the package
    - model: hey_jarvis     # ← already in the package
    - id: hey_rick
      model: http://homeassistant.local:8123/local/microwake/hey_rick.json
```

**Detailed merge semantics:**

ESPHome packages merge your local config on top of the package. The behavior depends on the data type:

```yaml
# ── SCALAR OVERRIDE ──
# Your local value replaces the package's value entirely.
# Package defines: logger: level: WARN
# Your config:
logger:
  level: DEBUG       # → Result: DEBUG (your value wins)

# ── DICT MERGE ──
# Keys are merged recursively. Your keys override matching package keys;
# non-conflicting package keys are preserved.
# Package defines: esphome: {name: base, friendly_name: Base Device}
# Your config:
esphome:
  friendly_name: Workshop   # → Result: {name: base, friendly_name: Workshop}

# ── LIST with id: MERGE BY ID ──
# List items with matching `id` fields are merged (your values override).
# Items with new `id` values are APPENDED to the package's list.
# Package defines: micro_wake_word: models: [{id: okay_nabu, model: okay_nabu}]
# Your config:
micro_wake_word:
  models:
    - id: hey_rick
      model: http://homeassistant.local:8123/local/microwake/hey_rick.json
# → Result: [{id: okay_nabu, model: okay_nabu}, {id: hey_rick, model: ...}]

# ── LIST without id: CONCATENATION ──
# Lists without id fields are concatenated (your items appended after package items).
# This can cause duplicates if you're not careful.

# ── !extend — MERGE into a specific list item by id ──
# Use !extend to ADD keys to an existing package list item without replacing it.
# Package defines: sensor: [{platform: adc, pin: GPIO34, id: soil_sensor, update_interval: 60s}]
sensor:
  - id: !extend soil_sensor
    filters:
      - median:
          window_size: 5
# → Result: the soil_sensor item now has both the original config AND filters added.
# Without !extend, you'd have to repeat all the package's keys.

# ── !remove — DELETE a specific list item by id ──
# Use !remove to suppress a package-defined component entirely.
# Package defines a debug sensor you don't want:
sensor:
  - id: !remove debug_heap
# → Result: the debug_heap sensor is removed from the compiled config.
```

> **Common gotcha:** `!extend` and `!remove` require the list item to have a stable `id` in the package. If the package doesn't assign `id` fields to its components, you can't target them — you'll need to override the entire list. The Voice PE package (`home-assistant-voice.yaml`) generally assigns `id` fields to its components, making it `!extend`/`!remove` friendly.

**When overriding is intentional**, add a comment explaining why:

```yaml
# Override package default — we need a faster update cycle for this sensor
sensor:
  - platform: adc
    pin: GPIO34
    update_interval: 5s  # Package default is 60s
```

### 6.4 Secrets in ESPHome (MANDATORY)

> ⚠️ **API password REMOVED (ESPHome 2026.1.0):** The `api: password:` option was deprecated in May 2022 and has been **fully removed** in ESPHome 2026.1.0. Configs that include `password:` under `api:` will **fail to build**. All API authentication must use `api: encryption: key:` with a base64 key generated via `openssl rand -base64 32`. If migrating old devices, remove the `password:` line, add an `encryption: key:`, and re-adopt the device in HA with the new key.

ESPHome has its own `secrets.yaml` at `/config/esphome/secrets.yaml`, separate from HA's root `secrets.yaml`. Use `!secret` for ALL sensitive values:

```yaml
# ── In the device config ──
api:
  encryption:
    key: !secret api_key_workshop

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

# OTA MD5 password auth deprecated in 2025.10.0, removed in 2026.1.0 (SHA256 still works) — see §6.6
# ota:
#   password: !secret ota_password

# ── In /config/esphome/secrets.yaml ──
wifi_ssid: "MyNetwork"
wifi_password: "MyPassword123"
api_key_workshop: "YOUR_BASE64_ENCRYPTION_KEY_HERE"
api_key_living_room: "YOUR_BASE64_ENCRYPTION_KEY_HERE"
# ota_password: "supersecret"  # Legacy — only needed for pre-encryption setups
```

**What MUST be in secrets:**
- `api.encryption.key` — API encryption keys are basically passwords. Inline keys get exposed when sharing configs, screenshots, or asking for help on forums.
- `wifi.ssid` and `wifi.password`
- `ota.password` (legacy only — deprecated in 2025.10.0, removed in 2026.1.0; prefer API encryption key)
- Any external API keys, tokens, or URLs with embedded credentials

**Naming convention for per-device secrets:** `<secret_type>_<device_location>` (e.g., `api_key_workshop`, `api_key_living_room`). This keeps them identifiable without being device-hostname-specific.

### 6.5 Custom wake word models

> **Version notes:** The `micro_wake_word` component was introduced in ESPHome 2024.2.0 (single model only). Multiple models per device arrived with Version 2 in ESPHome 2024.7.0 — just add entries to the `models:` list. That release also added the VAD (Voice Activity Detection) model for reducing false triggers. Since ESPHome 2025.5.0, HA can enable/disable individual wake word models remotely and switch the active wake word from the UI. The microphone source refactor in 2025.5.0 also made `microphone:` a required field for standalone configs (package-based devices like Voice PE already include it).

When adding custom micro_wake_word models (e.g., persona-specific wake words), follow this pattern:

```yaml
micro_wake_word:
  models:
    - id: hey_rick
      model: http://homeassistant.local:8123/local/microwake/hey_rick.json
    - id: hey_quark
      model: http://homeassistant.local:8123/local/microwake/hey_quark.json
  vad:                      # Voice Activity Detection — reduces false wake word triggers from non-speech sounds
```

**Model reference formats:**
ESPHome supports three formats for wake word model references:

```yaml
# 1. Shorthand — for official built-in models (preferred for stock wake words)
- model: okay_nabu

# 2. GitHub URL — for community/official models hosted on GitHub
- model: github://esphome/micro-wake-word-models/models/v2/okay_nabu.json

# 3. HTTP URL — for custom/self-trained models served from your HA instance
- model: http://homeassistant.local:8123/local/microwake/hey_rick.json
```

Use shorthand or GitHub format for official models. Use HTTP URLs only for custom/self-trained models hosted locally.

**Rules:**
- Every custom model MUST have a descriptive `id` matching the wake phrase: `hey_rick`, `hey_quark`, etc.
- Model files are served from HA's `/config/www/microwake/` directory (accessible via `http://homeassistant.local:8123/local/microwake/`).
- Keep wake word assignments **per-room/persona** — the Workshop satellite gets Rick's wake words, the Living Room gets Quark's. Don't dump every wake word on every device.
- If adding wake words to a package-based device, you're extending the package's model list (see §6.3).
- The `micro_wake_word` component requires a `microphone` source configuration (mandatory since ESPHome 2025.5.0). Package-based devices like Voice PE already include this — only relevant if building a custom voice satellite from scratch.
- Comment the wake word section with the persona assignment:

```yaml
# 🔽 Device 1 wake words — Workshop satellite (Rick + Quark)
micro_wake_word:
  models:
    - id: hey_rick
      model: http://homeassistant.local:8123/local/microwake/hey_rick.json
    - id: hey_quark
      model: http://homeassistant.local:8123/local/microwake/hey_quark.json
  vad:                      # Recommended — reduces false positives from ambient noise
```

**Voice Activity Detection (VAD):** Adding `vad:` under `micro_wake_word` enables a model that filters out non-speech audio before wake word detection runs. This significantly reduces false triggers from TV audio, music, and ambient noise. Enabled by default in newer packages but worth setting explicitly in custom configs.

**`on_wake_word_detected` automation trigger:** This trigger fires when a specific wake word is detected, allowing persona-based routing — e.g., "Hey Rick" triggers the Rick conversation agent while "Hey Quark" triggers Quark. Useful for multi-persona setups where different wake words should route to different HA assist pipelines. See the [micro_wake_word documentation](https://esphome.io/components/micro_wake_word.html) for syntax.

### 6.6 Common component patterns

**WiFi with fallback AP:**

```yaml
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  min_auth_mode: WPA2     # ESP8266 defaults to WPA (insecure) — always set explicitly
  # Fallback hotspot for initial setup or network issues
  ap:
    ssid: "${friendly_name} Fallback"
    password: !secret fallback_ap_password  # ⚠️ ALWAYS set a password — an open AP is a security hole
```

> ⚠️ **Fallback AP security:** ALWAYS set a password on the fallback AP. An open fallback hotspot lets anyone on your local network connect to the ESP, access the web UI, and push firmware. This is not theoretical — it's trivially exploitable.

**OTA updates:**

```yaml
ota:
  - platform: esphome
    # MD5 password auth deprecated in 2025.10.0, removed in 2026.1.0; passwords now require SHA256.
    # Prefer encryption-based auth via the API encryption key for new configs.
    # Only use password if you have a specific reason:
    # password: !secret ota_password
```

> ⚠️ **OTA auth changes (ESPHome 2025.10.0 → 2026.1.0):** OTA **MD5** password authentication was deprecated in ESPHome 2025.10.0 (when SHA256 became the default) and removed in ESPHome 2026.1.0. OTA passwords still work but now require **SHA256**. The `api.encryption.key` already secures OTA uploads, so for new configs prefer encryption-based auth and skip the OTA password entirely. Only set `ota.password` if you have a specific reason (e.g., OTA from a device without the API key).

**If using `web_server` for debugging**, you MUST add its OTA platform separately — since ESPHome 2025.7.0, the web_server's OTA functionality was extracted into its own platform:

```yaml
ota:
  - platform: esphome
  - platform: web_server    # Required if web_server is enabled

# Enable during development, comment out for production
web_server:
  port: 80
```

**Why this is required:** The web_server component's "Update" button (the firmware upload form in the web UI at `http://<device>:80/`) routes the uploaded firmware through the OTA subsystem. Before 2025.7.0, web_server implicitly used the main OTA handler. After the extraction, `platform: web_server` explicitly registers the `/update` HTTP endpoint that web_server needs for its firmware upload form. Without it, the web UI renders normally but the Update button silently fails — no error message, no log entry, just nothing happens. The `platform: esphome` entry is still needed for ESPHome Dashboard and `esphome run` OTA pushes. You need both if you want both OTA pathways to work.

**Note:** The `platform: esphome` syntax is required for ESPHome 2024.6+. Older devices may still use the legacy `ota:` block without a platform key. When updating old configs, migrate to the new syntax.

**Web server (for local debugging — disable in production):**

```yaml
# Enable during development, comment out for production
web_server:
  port: 80
```

**Captive portal (for fallback AP):**

```yaml
captive_portal:
```

**Logger level control:**

```yaml
# Development:
logger:
  level: DEBUG

# Production — use INFO baseline with component-level filtering:
logger:
  level: INFO
  logs:
    wifi: WARN              # Suppress routine connection logs
    api: WARN               # Suppress API heartbeat noise
    component: ERROR        # Only errors from generic components
    mqtt: WARN              # If using MQTT
    sensor: WARN            # Suppress per-reading sensor logs
```

**Rules:**
- Development: `DEBUG` is fine for troubleshooting.
- Production: Use `INFO` as baseline, not `WARN` or `ERROR` globally — you'll miss useful state transition logs. Instead, silence noisy components individually via the `logs:` map.
- Never log sensitive data (API keys, passwords) at any level. If a custom component logs secrets, override its level to `NONE`.

### 6.7 Debug and diagnostic sensors
Debug sensors are useful during development but consume resources. Gate them behind a clear comment and consider removing for production.

**Preferred: use a substitution toggle instead of manual removal.** Define a substitution that directly controls `disabled_by_default` on each debug entity. Toggling between development and production is a one-line change instead of commenting/uncommenting blocks:

```yaml
substitutions:
  debug_disabled_by_default: "false"    # Set to "true" for production

# Debug sensors — hidden in HA when debug_disabled_by_default is "true"
sensor:
  - platform: debug
    free:
      name: "${friendly_name} Heap Free"
      disabled_by_default: ${debug_disabled_by_default}
    block:
      name: "${friendly_name} Largest Free Block"
      disabled_by_default: ${debug_disabled_by_default}
    loop_time:
      name: "${friendly_name} Loop Time"
      disabled_by_default: ${debug_disabled_by_default}
```

**Alternative approach:** Keep debug sensors in a separate package file (`debug_sensors.yaml`) and include/exclude it via the `packages:` block. Comment out the package import line for production:

```yaml
# ── Debug / diagnostics (remove for production) ──────
debug:
  update_interval: 5s

sensor:
  - platform: debug
    free:
      name: "Heap Free"
    block:
      name: "Largest Free Block"
    loop_time:
      name: "Loop Time"

  - platform: wifi_signal
    name: "${friendly_name} WiFi Signal"
    update_interval: 60s

  - platform: uptime
    name: "${friendly_name} Uptime"
```

**Rules:**
- Always use `${friendly_name}` prefix in sensor names so they're identifiable in HA.
- Set concrete `update_interval` values by sensor type — don't poll every second unless actively debugging:
  - **WiFi/BLE sensors (signal strength, connected clients):** 30–60s
  - **Environmental (temperature, humidity, pressure):** 60–300s
  - **Power/energy (voltage, current, wattage):** 10–30s
  - **Debug/diagnostic (heap size, uptime, loop time):** 10–15s in debug builds, disabled or 300s+ in production
- `debug` component with `update_interval: 5s` is aggressive — fine for troubleshooting, wasteful for everyday use.

### 6.8 ESPHome device naming conventions
- **Hostname** (`name`): Use the ESPHome-generated MAC-based name (e.g., `home-assistant-voice-0905c5`) or a descriptive slug (e.g., `workshop-multisensor`). Must be DNS-safe.
- **Friendly name**: Human-readable, prefixed with `HA` for HA-specific devices: `HA Workshop`, `HA Living Room`. *(House convention — not an ESPHome standard. AI generators should not universalize this prefix to other setups.)*
- **Config filename**: Match the hostname: `home-assistant-voice-0905c5.yaml` or `workshop-multisensor.yaml`.
- **Sensor/entity names**: Always prefix with `${friendly_name}` so entities are identifiable in HA: `"${friendly_name} Temperature"`, `"${friendly_name} Heap Free"`.

### 6.9 Archiving old configs
When a device config is superseded or a device is retired:
- Move the old config to `/config/esphome/archive/`.
- Do NOT delete it — the config may be needed to re-flash or reference pin mappings.
- The `archive/` directory may already be gitignored depending on your setup — verify your `.gitignore` includes it if you want to exclude archived configs from version control.

**Recommended: git for config version control.**

Git is the primary method for ESPHome config archiving — it gives you full history, diff capability, and rollback without cluttering your active config directory.

```bash
# One-time setup in the ESPHome config directory:
cd /config/esphome
git init

# Create a .gitignore to exclude secrets and build artifacts:
cat > .gitignore << 'EOF'
secrets.yaml
.esphome/
archive/
*.pyc
__pycache__/
EOF

git add .
git commit -m "Initial ESPHome config snapshot"
```

**Commit discipline:** Commit before and after every significant change (new device, package version bump, wake word addition). Use descriptive messages: `"Add hey_quark wake word to living room satellite"`, not `"update config"`.

**Optional: push to a private remote** (GitHub/GitLab/Gitea) for off-device backup. Never push `secrets.yaml` — the `.gitignore` above handles this, but double-check before your first push.

**Alternative for non-git setups:** The ESPHome Add-on creates automatic backups via HA's backup system. These are full snapshots (not incremental), so they don't give you diff history, but they do provide rollback. For most users, HA backups + the `archive/` directory pattern is sufficient.

### 6.10 Multi-device consistency
When managing multiple devices of the same type (e.g., multiple Voice PE satellites), keep configs structurally identical except for:
- `substitutions` (name, friendly_name)
- `api.encryption.key` (unique per device, in secrets)
- Device-specific extensions (different wake words per room)

**Pattern:** When creating a new device of the same type, copy an existing config and change only the substitutions and device-specific sections. This makes it trivial to diff configs and spot unintentional drift.

### 6.11 ESPHome and HA automation interaction
ESPHome devices expose entities to HA (sensors, switches, buttons, etc.). When building automations that interact with ESPHome devices:
- Use `entity_id` — never `device_id`. ESPHome devices get new device IDs if re-adopted. (Note: ESPHome 2025.4.0+ handles device replacement more gracefully via Name Conflict Resolution, but `entity_id` remains the safest reference for automations.)
- ESPHome entities follow the naming pattern `<domain>.<hostname>_<component_name>` (e.g., `sensor.home_assistant_voice_0905c5_heap_free`).
- If the auto-generated entity IDs are ugly, rename them in the HA entity registry rather than fighting ESPHome's naming. The ESPHome name only affects the default — HA's registry override persists across re-adoptions.
- For ESPHome `on_*` automations (device-side), prefer HA automations for anything that needs coordination with other devices. ESPHome automations run locally on the device and can't see HA state.

### 6.12 Sub-devices (multi-function boards)
Since ESPHome 2025.7.0, the `devices` key allows a single ESP board to register multiple logical devices in HA. This is useful for multi-function boards (e.g., an ESP32 running a temperature sensor AND a relay that control unrelated things in different rooms).

```yaml
esphome:
  name: ${name}
  friendly_name: ${friendly_name}
  area: Workshop
  min_version: 2025.7.0
  devices:
    - id: workshop_climate
      name: Workshop Climate Sensor
      area: Workshop
    - id: hallway_relay
      name: Hallway Relay
      area: Hallway
```

> **⚠️ Required field:** Each sub-device entry MUST include an `id:` field. Without it, entities cannot reference their parent sub-device via `device_id:`, making the sub-device registration pointless. The `id` is a short internal identifier (e.g., `workshop_climate`), not the display name.

**When to use sub-devices:**
- A single board serves multiple HA areas (sensor in one room, relay in another).
- You want distinct device cards in HA for logically separate functions on the same hardware.

**When NOT to use sub-devices:**
- Single-purpose devices like Voice PE satellites — one board, one function, one area. Don't overcomplicate it.
- If all components belong to the same area — just use the top-level `area` field.

Entities are assigned to sub-devices via the `device` property on individual components. See the [ESPHome sub-devices documentation](https://esphome.io/components/esphome.html#sub-devices) for full syntax.

> 📋 **QA Check INT-2:** ESPHome pattern completeness — verify web_server→OTA dependency, packages merge modes, config archiving, debug sensor toggle, and sub-devices version are all documented. See `09_qa_audit_checklist.md`.
