# Offline Knowledge Hub

A self-contained Windows application. It serves Wikipedia, Project Gutenberg,
offline maps, and a small offline LLM chat assistant. Students access it over
a local Wi-Fi hotspot or LAN. No internet is required after setup. No vendor
binaries need downloading or placing by hand.

The running version always comes from the [`VERSION`](VERSION) file. See
[Recent Changes](#recent-changes) at the bottom of this file for what changed.

---

## Project Structure

```bash
hub/
├── main.py                  # Entry point: boots the Flask app + tray icon
├── requirements.txt
├── build.bat                # 1-click build script (Nuitka + Inno Setup)
├── installer.iss            # Inno Setup configuration script
│
├── core/
│   ├── app_factory.py       # Builds the single Flask app (portal + admin)
│   ├── auth.py               # Admin password hashing
│   ├── registry.py           # Tracks loaded modules' in-process handles
│   ├── module_manager.py     # Install / remove / open content modules
│   ├── downloader.py         # Resumable downloads + live Kiwix catalogue
│   ├── zim_reader.py         # Reads .zim files in-process (libzim)
│   ├── llm_engine.py         # Small offline chat model (onnxruntime-genai)
│   ├── tileserver.py         # SQLite MBTiles tile server
│   ├── hotspot.py            # Windows hotspot (WinRT + netsh fallback)
│   ├── jobs.py                # Background download/install progress tracking
│   └── blueprints/
│       ├── portal.py         # Public, LAN-facing routes (students)
│       └── admin.py          # Password-gated setup/management routes
│
├── templates/
│   ├── portal/               # Student-facing pages (home, ZIM search, chat)
│   └── admin/                # Setup wizard + ongoing admin pages
│
└── assets/
    ├── icons/hub.ico
    └── portal/vendor/maplibre-gl/   # Vendored locally, no CDN at runtime
```

There is no `vendor/` folder. Wikipedia and Gutenberg content is read
directly via the `libzim` Python package. The offline LLM runs via
`onnxruntime-genai`. Both are plain pip dependencies with real Windows
wheels, bundled straight into the compiled exe by Nuitka.

---

## Development Setup

```powershell
# 1. Create a virtual environment
python -m venv .venv
With Bash:
source .venv/Scripts/activate
With PowerShell:
.venv\Scripts\Activate.ps1

# 2. Install dependencies (including Nuitka for building)
pip install -r requirements.txt
pip install nuitka

# 3. Run from source
python main.py
```

The first launch opens the setup wizard in your browser at
`http://127.0.0.1:8000/admin/setup`. No separate desktop window opens
anymore. A system tray icon (Open Portal / Open Admin / Quit) is the visible
sign. It shows the app is running.

### Running the Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

Covers the highest-risk logic: password hashing, the content registry, and
the downloader. The downloader tests include resumable downloads, checksum
verification, and mocked HTTP. No real network calls are made. Also covers
module install and remove. This includes a regression test for a real
zip-slip vulnerability found and fixed in `install_from_zip`. A crafted ZIP
could write files outside the modules folder. That's a real risk, since
Manual Install accepts uploads from any device on the hotspot. GitHub
Actions (`.github/workflows/test.yml`) runs this suite on every push and PR.

---

## How Content Works

| Module type | Engine                           | Notes                                                                                    |
| ----------- | --------------------------------- | ---------------------------------------------------------------------------------------- |
| `zim`       | `libzim` (in-process)            | Wikipedia, Gutenberg, Khan Academy, or any Kiwix ZIM. No subprocess, no port per module. |
| `mbtiles`   | sqlite (in-process)              | Offline vector/raster maps, served straight from the `.mbtiles` file.                    |
| `llm`       | `onnxruntime-genai` (in-process) | A small offline chat model. Model weights download like content, not as a vendor binary. |

ZIM downloads are resolved live against Kiwix's OPDS catalog
(`https://library.kiwix.org/catalog/v2/entries`) instead of a hardcoded
filename. Kiwix rotates dated snapshot names and deletes old ones, so a
hardcoded URL eventually 404s. The Admin panel's "Discover Content" search
box lets you search the entire live Kiwix library. That's not limited to the
curated quick-start list.

The curated quick-start list (`core/downloader.py`'s `CATALOGUE`) covers
grades 1 through high school. **Wikipedia** (mini) and **Gutenberg**
(literature) cover general reference. **Vikidia** (a kids' encyclopedia for
~8-13 year olds) suits younger readers. **Wikipedia Simple English** works
well for ESL readers too. **PhET Simulations** (interactive science/math)
and **Wikibooks** (textbooks/study guides) suit middle and high school. All
were checked against the live Kiwix catalog, not assumed from memory.

Khan Academy is deliberately **not** in the curated quick-start list. The
current Kiwix library only publishes a single ~180GB "all" ZIM for it. No
small subject-specific version exists anymore. Use the search box if you
still want it. The real size is shown before you download.

The Offline Maps tab also has a "Search for a Country" box. Unlike the six
curated regional packs above, this extracts a chosen country's tiles live
from Protomaps' free daily global basemap build, straight into a local
`.mbtiles` file (`core/map_extract.py`). No vendor binary is involved: the
`pmtiles` Python package's `Reader` accepts any byte-range-capable source,
so the extraction is done with plain HTTP Range requests instead of the
`go-pmtiles` CLI a build-time-only dev tool
(`tools/build_map_packs.py`) uses to build the curated packs. Very large
countries automatically get a lower max zoom to keep the download a
reasonable size. The shown size is an estimate, not an exact figure. Real
byte size varies a lot by how much of a country's bounding box is empty
ocean versus dense urban data, unlike Kiwix's own exact reported sizes.

Once a module is installed, its Quick Start / Offline Assistant button
changes. It switches to a disabled "✓ Installed" state instead of offering
Download again. Re-downloading over an already-installed module used to
fail with a raw Windows file-in-use error. That happened because the
running app holds that module's file open in memory. Installing is also
refused server-side for the same reason. This applies even if you hit the
API directly. Remove the module first (Admin → Modules → Remove) if you
actually want to replace it.

---

## Companion Content Pack

A pre-downloaded zip of the quick-start modules, for testing or a first
install without waiting on multiple large downloads:

**[Download OfflineHub_CompanionPack.zip (~1.6GB)](https://www.dropbox.com/scl/fi/m3ef49rm14idr32h0i6mn/OfflineHub_CompanionPack.zip?rlkey=aptcv0ku09rxf5th467gwbh0r&st=o8ymmhgg&dl=0)**

Contains Wikipedia (Simple English) and Vikidia. Also includes Wiktionary
(Simple English), PhET Simulations, and the Qwen2.5 0.5B offline assistant.
Unzip it directly into `C:\OfflineHub\` so it creates
`C:\OfflineHub\modules\<key>\...`. The app picks up any module folder with
a `manifest.json` automatically on next launch. No admin-panel download is
needed. Built with `tools/build_companion_pack.py`.

---

## Adding Custom Modules

Open the **Admin panel** (`/admin`, password-gated) → **Modules**:

- **Raw file**: a `.zim` or `.mbtiles` file already on this PC (type a path)
  or uploaded from another device on the hotspot.
- **ZIP module**: a `manifest.json` + `content/` folder, zipped up, for
  granular control:

```bash
my_module/
├── manifest.json
└── content/
    └── myfile.zim       # or .mbtiles, or ONNX model files for type "llm"
```

```json
{
  "name": "London Map",
  "emoji": "🗺️",
  "type": "mbtiles",
  "format": "vector",
  "description": "A short description shown on the module card."
}
```

| Field         | Required | Values                    | Notes                             |
| ------------- | -------- | ------------------------- | --------------------------------- |
| `name`        | ✅       | Any string                | Card title                        |
| `emoji`       | ✅       | Any single emoji          | Shown next to the title           |
| `type`        | ✅       | `zim` / `mbtiles` / `llm` | Controls how content is read      |
| `format`      | ❌       | `raster` / `vector`       | Maps (`mbtiles`) only             |
| `description` | ❌       | Any string                | Shown in smaller text on the card |

---

## The Offline LLM

Go to **Admin → Modules → Offline Assistant** and click Download. This
pulls a pre-tested model straight from Hugging Face. It installs as a
`type: "llm"` module. **Phi-4-mini** (~4.9GB, Microsoft, MIT license) is the
recommended default. The smaller Qwen2.5 0.5B option that used to be here
was removed. Its answers were too weak to be useful in practice. Chat with
the installed model from the student portal at `/chat/<module-id>`.

A standalone zip of just the Phi-4-mini model is also available, for testing
or a first install without a 4.9GB admin-panel download:

**[Download OfflineHub_LLM_Phi4Mini.zip (~4.6GB)](https://drive.google.com/file/d/1fcf9yW2tl9JQcDXmwDusx8t0jk6uMrdD/view?usp=sharing)**

Unzip it directly into `C:\OfflineHub\` (same drop-in pattern as the
companion pack above). The app picks it up as the `assistant_phi4_mini`
module automatically on next launch. Built with `tools/build_llm_pack.py`.

Any other small instruction-tuned model exported for `onnxruntime-genai`
works too (e.g. a Phi-3.5-mini ONNX build). Download all of that variant's
files (`genai_config.json`, `*.onnx`, `*.onnx.data`, tokenizer files) into
one `content/` folder. Package it as a `type: "llm"` ZIP module. Use the
same approach as any other custom module (see above). The curated one-click
model is defined in `core/downloader.py`'s `LLM_CATALOGUE` / `LLM_REPO` /
`LLM_SUBFOLDER`. Swap in a different default there if you want.

Inference runs on CPU and is serialized one request at a time. It's meant
for a handful of students at once, not a classroom all chatting
simultaneously.

---

## Testing the Hotspot on Your Laptop

Your laptop can share its existing Wi-Fi connection as a second hotspot
network simultaneously. Windows calls this **Mobile Hotspot**.

1. Open **Settings → Network & Internet → Mobile Hotspot**
2. Set a network name and password, toggle it on
3. Connect another device to that network and open `http://<your-laptop-IP>:8000`

Your laptop's IP is shown on the portal home page, or run `ipconfig` and
look for the Wi-Fi adapter address.

**Hardware requirement:** your Wi-Fi adapter must support hosted networks
(virtually all modern adapters do). If the WinRT API fails, the hub falls
back to `netsh wlan hostednetwork`. If both fail, the error appears in the
Hotspot tab of the Admin panel.

---

## Admin Panel

Open `http://<hub-ip>:8000/admin` (password-gated after first-run setup).

| Page     | Purpose                                      |
| -------- | -------------------------------------------- |
| Modules  | Download content, add files/ZIPs, remove     |
| Hotspot  | Configure SSID / password, toggle hotspot    |
| Services | View loaded modules, unload to free memory   |
| Settings | Portal port, boot autostart, change password |

---

## Building the Installer

This project avoids antivirus false-positives (common with PyInstaller) by
using two tools. **Nuitka** compiles the code to standard C executables.
**Inno Setup** then packages everything into a Windows installer.

1. **Nuitka & C Compiler**: `pip install nuitka` (it prompts to download a
   MinGW compiler on first run).
2. **Inno Setup 6**: install from [jrsoftware.org](https://jrsoftware.org/isdl.php)
   to `C:\Program Files (x86)\Inno Setup 6\`.

Run `build.bat`. It compiles `main.py` into `main.dist\`, then packages
`main.dist\`, `assets\`, and `config.json` into `Output\OfflineHub_Setup.exe`.

`libzim` and `onnxruntime-genai` ship compiled native extensions with
backing DLLs. After building, **run `main.dist\OfflineHub.exe` directly**,
open a ZIM module, and send one chat message. Do this before trusting the
build. Missing-DLL failures from Nuitka's standalone packaging only show up
in the frozen exe. They never appear when running `python main.py` from
source.

---

## Architecture Notes

- **No vendor binaries.** ZIM content and the LLM both run in-process via
  pip packages with real Windows wheels. Those packages are `libzim` and
  `onnxruntime-genai`. That means no subprocess management and no
  missing-exe failures. It also avoids antivirus flags on a bundled
  third-party server binary.
- **One process.** The student portal and the admin UI are the same Flask
  app. There's no separate desktop GUI framework to compile or crash.
- **Fully offline pages.** MapLibre GL JS is vendored locally
  (`assets/portal/vendor/`). Nothing on the portal fetches from a CDN at
  runtime. It genuinely works with zero internet once installed.
- **Hotspot** uses the Windows WinRT Mobile Hotspot API first (Win10/11),
  falling back to `netsh wlan hostednetwork` for older hardware.
- **Downloads are resumable.** Interrupted downloads pick up from where
  they left off, using HTTP Range headers.

---

## Recent Changes

Full history isn't tracked in a separate file. This is a running summary,
newest first. Bump [`VERSION`](VERSION) when the next set of changes ships.

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

**0.2.0**: the vendor-binary-free rewrite

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
