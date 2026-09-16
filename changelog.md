# CHANGELOG

## 0.3.1

- Added nine Quick Start items: five programming reference ZIMs, MedlinePlus,
  Project Euler, Wikivoyage, and TED-Ed. The five reference ZIMs cover Python,
  JavaScript, C++, HTML, and CSS. TED-Ed needed real video streaming, not just
  a full download first. Content serving now supports real HTTP Range
  requests for that.
- Added category tabs to Quick Start: General Reference, Languages, Subjects,
  Programming, and more. The list had grown to 23 items and needed real
  grouping.
- Added support for uploading a school's own PDF material. Manual Install now
  accepts `.pdf` files, not just `.zim`/`.mbtiles`/`.zip`. A PDF opens in the
  browser's own built-in viewer. Full-text search works across every page.
- Fixed the whole admin panel freezing while the assistant replied. A real
  admin report showed it, not just the chat page freezing. The model had no
  CPU thread limit, using every core. Inference now leaves one core free for
  the OS and Flask.
- Fixed Quit taking nearly 25 seconds even with the hotspot off.
  `HotspotManager.stop()` used to always run its full PowerShell and netsh
  sequence. It now skips that work when the hotspot was never started.
- Fixed a silent, unattended uninstall being able to hang forever. That mode
  is used by IT staff deploying across many school PCs. The keep-modules
  prompt now only shows up interactively. A silent uninstall now defaults to
  keeping content instead.
- Completed a full security review of the whole codebase, not just a diff.
  Every finding it surfaced got fixed. The most serious: an unauthenticated
  path to full admin takeover. That chained into remote code execution, run
  by this elevated app. Also fixed two path-traversal bugs, one reachable
  with no login. And two XSS holes, plus a missing CSRF layer everywhere.
  Two more unrelated bugs were found and fixed along the way. A removed map
  could leave its file locked on Windows. Two chat models could load into
  memory at once. Every fix has a real regression test; 229 tests pass now.

## 0.3.0

- Added self-serve country map downloads. The Offline Maps tab now has a
  "Search for a Country" box. It covers all 173 countries in a bundled
  dataset, not just the six curated regions. `core/map_extract.py`
  extracts a chosen country's tiles live from Protomaps' free daily
  global basemap build. It writes straight into a local `.mbtiles` file.
  It uses plain HTTP Range requests instead. That avoids the
  `go-pmtiles` Go binary the maintainer-only build script uses. It keeps
  the "no vendor binaries" principle intact.
- Fixed two real bugs in that feature. Both were found from an actual
  admin report of a broken-looking map. A real hole showed up in the
  middle of Cyprus, centered on Nicosia. The frontend's map source never
  declared its own max zoom. MapLibre assumed data existed all the way
  to z22. It rendered nothing once you zoomed past what a module
  actually had. Separately, the extraction zoom ceiling (z12) was too
  shallow for the POI and road-label layers. They could never show
  anything. Both fixed. `/api/modules` now reports each module's real max zoom.
  The ceiling is raised to z15, the live build's own real maximum.
- Fixed the app being able to hang indefinitely on "Quit." That could
  also let an uninstall catch it still running and delete modules
  unevenly. Root-caused from the app's own log file. `TileServer` caches
  one open `.mbtiles` connection per map for the life of the process.
  The function to close them existed but was never called anywhere.
  Fixed. Quitting now has a 25-second watchdog that force-exits the
  process no matter what else hangs. "Quit" is now guaranteed to
  actually end the process.
- Fixed "keep modules" on uninstall not actually keeping everything.
  Two separate, unrelated bugs caused it, found from two separate real
  reports:
  - `manifest.json` is a small file nothing holds open, so it was being
    deleted. A module's much bigger content file survived only because
    it happened to be locked open. A module could have real data on
    disk but be invisible to the app. It used to just skip a folder
    with no manifest. `core/module_manager.py` now reconstructs and
    saves a manifest from whatever content is actually there.
  - Separately, and more fundamentally: Inno Setup evaluates
    `[UninstallDelete]`'s `Check:` function _before_ `InitializeUninstall()`
    even runs. Confirmed with an instrumented test build of the real
    installer. The modules-keep prompt's answer was never actually seen
    in time. The whole folder was deleted regardless of what the admin
    chose. `installer.iss` now deletes modules explicitly at the
    `usPostUninstall` step instead. That step reliably runs after the
    prompt's answer is recorded.
- Fixed a 30-minute country map extraction being able to die on one
  network hiccup. A retry afterward used to fail with a Windows
  "file in use" error. A long extraction fires thousands of individual
  HTTP requests, with no retry logic at all. One transient timeout used
  to kill the whole job. The destination file's connection was also
  only ever closed on the success path. That leaked a lock a retry then
  tripped over. Both fixed, with regression tests that reproduce the
  exact failure-then-retry sequence.
- Country map downloads are also faster, and no longer needlessly
  risky. Measured live against the real source server at several
  concurrency levels. Throughput stayed flat at ~9-10 tiles/sec no
  matter how many concurrent connections were used. That's a
  server-side limit, not something more connections can fix. Higher
  concurrency just made every request slower for no benefit. That's
  very likely what caused the timeout above in the first place.
  Concurrency is lowered accordingly. A country's real extraction time
  now shows as an honest estimate first. A large country can still
  legitimately take 20-30+ minutes on a free public server.
- Added the ability to cancel any in-progress download, not just map
  extraction. Every download card in the admin panel now has a working
  Cancel button. That covers Quick Start, Offline Assistant, curated
  maps, Discover search results, and country maps.
- Restyled the Manual Install tab's file picker button. It now matches
  the rest of the app instead of the browser's unstyled native control.
- Added a spinner to the chat UI while waiting for the offline
  assistant's reply. A slow first token no longer looks like a stall.
- Removed em dashes and rewrote long sentences across every admin and
  portal screen. Also across all translation files and this README.
  Every sentence is now capped at 15 words.

## 0.2.5

- Trimmed the installer from ~46MB to ~44MB (main.dist from 185MB to 170MB
  uncompressed). Fixed two real packaging issues to get there. Both were
  confirmed by actually testing the change rather than assuming it was safe:
  - Removed a duplicate of `onnxruntime-genai.dll` (~7.2MB, byte-identical).
    Nuitka was copying it to both `main.dist/` and
    `main.dist/onnxruntime_genai/`. Confirmed only the copy next to
    `onnxruntime_genai.pyd` is ever loaded. Windows checks a DLL's own
    directory first. Verified this by deleting the top-level one and
    re-running a real chat completion.
  - Excluded Pillow's AVIF image codec (`PIL._avif`, ~7.5MB) via
    `--nofollow-import-to=PIL._avif`. Pillow is only used here to load the
    tray icon's `.ico` file. Its plugin system already wraps each format's
    import in try/except. So a missing codec is silently skipped, not a
    crash. Confirmed by deleting `_avif.pyd` from a built copy. Then
    re-tested the full app: tray icon, portal, ZIM content, and LLM chat.
  - Confirmed via `dumpbin /dependents` that the two biggest remaining
    files are genuine requirements, not bloat. `icudt74.dll` (29MB) is a
    real dependency of libzim's Unicode-aware search. The bundled OpenBLAS
    library (19.6MB) is a real dependency of numpy. `onnxruntime-genai`'s
    Python bindings return arrays from numpy.

## 0.2.4

- Added four K-12-relevant Quick Start entries to `core/downloader.py`'s
  `CATALOGUE`. Each was checked against Kiwix's live catalog rather than
  assumed. The four: **Vikidia** (kids' encyclopedia, ~8-13yo) and
  **Wikipedia Simple English** (younger/ESL readers). Also **PhET
  Interactive Simulations** (science/math) and **Wikibooks**
  (textbooks/study guides). Verified end-to-end, not just that they
  resolve. Actually downloaded and opened PhET's real content through the
  running app.

## 0.2.3

- Fixed the portal being unreachable from devices connected to the hotspot.
  This happened even though the hotspot itself connects fine. Root cause:
  an internet uplink (Ethernet/Wi-Fi) and an active hotspot are two
  different adapters. They sit on two different subnets. Confirmed live on
  this machine: Ethernet at `172.20.147.29`, the hotspot's own AP at
  `192.168.137.1`. Both `HotspotManager.get_local_ip()` and a
  near-identical duplicate in `core/blueprints/portal.py` used the same
  trick. Connect a UDP socket to 8.8.8.8, then read the source address.
  That trick always returns the internet uplink's address. That's exactly
  the one address a phone on the hotspot can't reach. The admin Hotspot
  page and the portal's IP badge both prefer the hotspot's
  `192.168.137.0/24` address. This applies whenever that address is
  present. The portal route now calls the one corrected `HotspotManager`
  method, instead of duplicating the logic.
- Fixed "Connected Devices" on the Hotspot page always showing empty, even
  with a device connected. Root cause: Windows lists Mobile Hotspot clients
  in `arp -a` as `static`, not `dynamic`. The parser only matched `dynamic`.
- The installer now adds a Windows Firewall rule during install. That rule
  allows the app through, identified by its program path. It also removes
  the rule on uninstall. Confirmed live that no such rule existed
  beforehand. The app runs windowless and elevated. A console app would
  normally trigger an interactive "allow this app through the firewall?"
  prompt. That prompt may never actually surface to the user here. That
  could silently leave the portal unreachable, regardless of the
  IP-address fix above.

## 0.2.2

- Renamed the compiled executable from `main.exe` to `OfflineHub.exe`. This
  is mainly so the uninstaller's `taskkill /IM` (below) can't collide with
  some unrelated process. That other process might happen to also be named
  `main.exe`.
- Fixed the Wi-Fi Hotspot start failing on modern Wi-Fi drivers. It failed
  with "the group or resource is not in the correct state". It was also
  popping open several visible PowerShell windows while trying. Root
  cause: a bug in the WinRT Mobile Hotspot script (tried before the
  `netsh` fallback). It referenced `WindowsRuntimeSystemExtensions` under
  the wrong namespace. It never loaded the assembly that class actually
  lives in. It also never explicitly loaded the WinRT namespaces it needs.
  So it always failed silently and fell through to `netsh`. Many current
  drivers have dropped support for `netsh` entirely. Running `netsh wlan
show drivers` on them returns `Hosted network supported: No`. Fixed and
  confirmed by actually starting and stopping a real hotspot through it.
  Every subprocess call in `core/hotspot.py` also now runs with
  `CREATE_NO_WINDOW`. That flag is what was popping the console windows.
- Fixed uninstalling the app while it's still running. The installer never
  stopped the running process before deleting files. That could make it
  fail partway through and leave the app still running. It gets worse
  (confirmed by testing): killing the process alone doesn't stop an
  active hotspot. Windows manages Mobile Hotspot as a system service,
  independent of the app's lifetime. A force-killed app can leave a Wi-Fi
  network broadcasting indefinitely. Nothing is left to turn it off. The
  uninstaller now runs `uninstall_stop_hotspot.ps1` first (stops both the
  WinRT and legacy hotspot). Only then does it `taskkill` the process,
  before removing any files.
- Redesigned the admin dashboards (Setup, Modules, Hotspot, Services,
  Settings). They moved from a narrow centered column into wide,
  landscape, grid-based layouts. `assets/portal/style.css` is now a shared
  stylesheet across admin and the student portal. The version number
  (`VERSION`) is now shown on every page too. It's rendered via a Flask
  context processor, instead of nowhere.

## 0.2.1

- Added the actual way to get the offline LLM. Admin → Modules → Offline
  Assistant now downloads a real, pre-tested Qwen2.5 0.5B model in one
  click. This uses `core/downloader.py`'s `LLM_CATALOGUE`, wired to a new
  `POST /admin/downloads/llm` route. Previously the LLM engine existed in
  code. But nothing ever exposed a way to install one.
- Fixed a crash when re-downloading an already-installed module (ZIM or
  LLM). It used to crash with a raw `WinError 32` ("file in use"). The
  running app holds that module's file open in memory. That's because
  libzim keeps ZIM archives open for the process lifetime. So overwriting
  it mid-process was never going to work. Installed modules now show "✓
  Installed" instead of a Download button. `ModuleManager.install_from_download`
  and `install_llm_from_download` now refuse cleanly with `FileExistsError`
  if the module folder already exists. They no longer attempt the
  overwrite at all.

## 0.2.0

- Removed `vendor/kiwix-serve.exe` and `vendor/Kolibri.exe` entirely,
  along with all Kolibri support. Kolibri's Windows distribution bundles a
  full Python runtime. It can't run as a standalone extracted exe the way
  the old README instructed. Khan Academy works as a plain ZIM instead.
- Removed the whole `ui/` folder (`customtkinter` wizard, admin panel,
  main window). Replaced it with one Flask app. `/` is the public student
  portal. `/admin` is a password-gated setup/management UI. Both are
  reachable from any browser on the hotspot. A system tray icon is the
  visible running/quit signal, now that there's no desktop window.
- Added `core/zim_reader.py` (Wikipedia/Gutenberg/Khan Academy via `libzim`,
  in-process, no subprocess) and `core/llm_engine.py` (offline chat via
  `onnxruntime-genai`).
- Fixed the Wikipedia catalogue URL being hardcoded to a dated snapshot
  filename Kiwix had deleted. URLs now resolve live against Kiwix's OPDS
  catalog.
- Fixed a closure-over-loop-variable bug in the old setup wizard. Selecting
  several catalogue items at once used to silently merge and mislabel all
  of them. They'd all land in one module folder. `core/jobs.py` now binds
  each download's `job_id` per request, instead of sharing loop state
  across threads.
- Removed two silent CDN dependencies: a Google-fonts-style import, and
  MapLibre GL JS from unpkg.com. Both broke the "works with zero internet"
  promise on an actual hotspot with no WAN. MapLibre is now vendored
  locally in `assets/portal/vendor/`.
- Packaging: a real Nuitka build surfaced three frozen-build-only
  failures. First, an invalid `--include-package-data=libzim` flag.
  Second, `onnxruntime`'s `capi/` extension module being silently dropped.
  Third, `onnxruntime-genai.dll` failing to load. A runtime path-lookup
  breaks under a Nuitka-compiled package. All three are fixed and
  commented in `build.bat` and `core/llm_engine.py`.
