# Claude Code Prompt: UC3 Custom Charging Display / Matrix Screensaver

## Goal
Replace or overlay the Unfolded Circle Remote 3's boring default charging
clock with something dope — a Matrix-style falling code screensaver, or any
custom visual that runs on the remote's 3.2" touchscreen while it's docked
and charging. This is exploratory — no official path exists for this yet.

## What We Know
- The UC Remote 3 runs **Unfolded OS** — a custom Linux distro on a
  quad-core 64-bit ARM SOC with 4GB RAM and 32GB eMMC
- The display is a high-res 3.2" touchscreen
- The frontend UI is a **Qt application** — open source at
  `github.com/unfoldedcircle/remote-ui`
- The Core API (REST + WebSocket) is documented at
  `unfoldedcircle.github.io/core-api/` — it supports:
  - Custom resource uploads (icons, images)
  - Installing custom remote-ui and web-configurator components
  - Installing custom integration drivers (runs ON the remote since fw 1.9.0)
  - Event subscriptions with async notifications
  - Full REST + WebSocket control of the remote-core service
- The API spec is at `github.com/unfoldedcircle/core-api` (OpenAPI + AsyncAPI)
- The Integration API uses WebSocket with JSON payloads
- Custom integrations can be packaged as `.tar.gz` and uploaded via the
  web configurator under "Install Custom"
- The remote's IP is `192.168.2.204`

## Confirmed Feasibility
The remote-ui README explicitly states: "Custom versions can be built and
installed on the device." The toolchain is Qt 5.15.2 + Qt Creator + Docker
for ARM cross-compilation. A core simulator exists for desktop testing
without the physical remote. This is a real, supported path.

## What We Still Need to Find
- Which QML file in `src/` implements the charging/standby clock screen
- How custom builds are deployed to the remote (the README says it's
  possible but check the docs/ directory for the exact mechanism)
- Whether you can replace JUST the charging screen QML without rebuilding
  the entire app (hot-swap a single QML file vs full rebuild)
- Whether custom integrations can render UI elements beyond standard entity
  types (buttons, media players, sensors, etc.)
- What display states exist (active, standby, charging, sleep) and which
  are programmable
- Whether the remote-ui Qt app can be extended with custom QML components
  without a full fork
- Whether there's an undocumented web view or overlay capability

## Research Plan (Do This First — No Code Until Recon Is Done)

### 1. Fetch and study the Core API spec
```
https://unfoldedcircle.github.io/core-api/
https://github.com/unfoldedcircle/core-api
```
Look specifically for:
- Display/screen-related endpoints or events
- Power state / charging state events (the remote knows when it's docked)
- Any "custom UI" or "custom page" or "widget" capabilities
- The `installing custom remote-ui` feature mentioned in the docs

### 2. Study the remote-ui Qt frontend
```
https://github.com/unfoldedcircle/remote-ui
```
Look for:
- How the charging/standby screen is implemented (QML files?)
- Whether it's a separate view/scene in the Qt app
- Whether custom QML components can be loaded dynamically
- Build system and deployment mechanism

### 3. Study the Integration API
```
https://github.com/unfoldedcircle/core-api (AsyncAPI spec)
```
Look for:
- Whether integrations can push arbitrary UI content
- Whether there's an "overlay" or "notification" display mechanism
- What entity types support visual rendering on the remote's screen

### 4. Check the Unfolded Community / Discord for prior art
Search for anyone who's attempted custom screensavers, clock faces, or
display customization:
```
https://unfolded.community/
https://github.com/unfoldedcircle/feature-and-bug-tracker/issues
```

### 5. Probe the remote's REST API directly
The remote is at `http://192.168.2.204`. The Core API should be accessible.
Try fetching the API docs or exploring endpoints:
```
GET http://192.168.2.204/api/
GET http://192.168.2.204/api/system
GET http://192.168.2.204/api/cfg/display
```
(These are guesses — the actual endpoints need to be discovered from the
API spec. Do NOT brute-force the remote.)

## Possible Approaches (Ranked by Feasibility)

### A — Fork remote-ui, Replace Charging Screen QML (CONFIRMED POSSIBLE)
The remote-ui is open source Qt 5 / QML at github.com/unfoldedcircle/remote-ui.
(Repo title says "Remote Two" but Remote 3 shares the same unfolded OS and
ARM SOC architecture — confirm R3 compatibility before building.)
Custom builds can be installed on the device. The plan:
1. Clone the repo, find the charging/standby QML view in src/
2. Replace or extend it with a Matrix falling-code animation in QML
3. Build for ARM via Docker cross-compilation
4. Deploy to the remote
This is the confirmed path. Start here.

### B — QML Hot-Swap (Lightweight Alternative)
If the remote loads QML files from disk at runtime (common in Qt apps),
it might be possible to replace just the charging screen QML file without
a full rebuild. Check whether the deployed app loads QML from a known
filesystem path that can be modified via SSH or the Core API.

### C — Web Overlay via Core API
If the remote has any web view capability (it runs a web configurator
internally), there might be a way to display a custom web page on the
remote's screen during charging. A Matrix screensaver in HTML/JS/CSS
would be trivial to build — the question is getting it onto the display.

### D — HA Dashboard on the Remote
The remote can display HA entities. If we can get a Lovelace card or
a custom panel to render on the remote's screen, a Matrix-style card
could serve as the visual. This is the most "within the system" approach
but depends on how HA entities render on the UC3 display.

## Deliverables
After recon, produce ONE of:
1. A working proof-of-concept (if any approach pans out)
2. A detailed technical assessment of what's possible and what's blocked,
   with specific API endpoints or code paths that would need to change
3. A feature request draft for UC's GitHub tracker if nothing works today
   but a specific API addition would unlock it

## Constraints
- Do NOT factory reset, brick, or fuck up the remote
- Do NOT brute-force API endpoints — study the spec first
- The remote is at 192.168.2.204 — be gentle with it
- This is exploratory/R&D — it's fine to come back with "not possible yet,
  here's what would need to change"
- If building a custom integration, follow the UC integration packaging
  format (tar.gz, uploaded via web configurator)
