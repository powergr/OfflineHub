# Offline Knowledge Hub

A self-contained Windows application that serves Wikipedia, Project Gutenberg,
offline maps, and a small offline LLM chat assistant to students over a local
Wi-Fi hotspot or LAN — no internet required after setup, and no vendor
binaries to download and place by hand.

The running version always comes from the [`VERSION`](VERSION) file. See
[Recent Changes](#recent-changes) at the bottom of this file for what changed.

---

## Project Structure

```bash
hub/
├── main.py                  # Entry point — boots the Flask app + tray icon
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
    └── portal/vendor/maplibre-gl/   # Vendored locally — no CDN at runtime
```

There is no `vendor/` folder. Wikipedia/Gutenberg content is read directly
via the `libzim` Python package, and the offline LLM runs via
`onnxruntime-genai` — both are plain pip dependencies with real Windows
wheels, bundled straight into the compiled exe by Nuitka.

---

## Development Setup

```powershell
# 1. Create a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies (including Nuitka for building)
pip install -r requirements.txt
pip install nuitka

# 3. Run from source
python main.py
```

The first launch opens the setup wizard in your browser at
`http://127.0.0.1:8000/admin/setup` — no separate desktop window opens
anymore. A system tray icon (Open Portal / Open Admin / Quit) is the visible
sign the app is running.

---

## How Content Works

| Module type | Engine | Notes |
| ----------- | ------ | ----- |
| `zim`       | `libzim` (in-process) | Wikipedia, Gutenberg, Khan Academy, or any Kiwix ZIM. No subprocess, no port per module. |
| `mbtiles`   | sqlite (in-process) | Offline vector/raster maps, served straight from the `.mbtiles` file. |
| `llm`       | `onnxruntime-genai` (in-process) | A small offline chat model. Model weights download like content, not as a vendor binary. |

ZIM downloads are resolved live against Kiwix's OPDS catalog
(`https://library.kiwix.org/catalog/v2/entries`) instead of a hardcoded
filename — Kiwix rotates dated snapshot names and deletes old ones, so a
hardcoded URL eventually 404s. The Admin panel's "Discover Content" search
box also lets you search the entire live Kiwix library, not just the
curated quick-start list.

Khan Academy is deliberately **not** in the curated quick-start list: the
current Kiwix library only publishes a single ~180GB "all" ZIM for it (no
small subject-specific version exists anymore). Use the search box if you
still want it — the real size is shown before you download.

Once a module is installed, its Quick Start / Offline Assistant button
switches to a disabled "✓ Installed" state instead of offering Download
again — re-downloading over an already-installed module used to fail with a
raw Windows file-in-use error, since the running app holds that module's
file open in memory. Installing is also refused server-side for the same
reason if you ever hit the API directly. Remove the module first (Admin →
Modules → Remove) if you actually want to replace it.

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

| Field         | Required | Values                    | Notes                          |
| ------------- | -------- | ------------------------- | ------------------------------- |
| `name`        | ✅       | Any string                | Card title                      |
| `emoji`       | ✅       | Any single emoji          | Shown next to the title         |
| `type`        | ✅       | `zim` / `mbtiles` / `llm` | Controls how content is read    |
| `format`      | ❌       | `raster` / `vector`       | Maps (`mbtiles`) only           |
| `description` | ❌       | Any string                | Shown in smaller text on the card |

---

## The Offline LLM

Go to **Admin → Modules → Offline Assistant** and click Download — this
pulls a small pre-tested model (Qwen2.5 0.5B Instruct, ~0.8GB, verified
working end-to-end including in the compiled build) straight from Hugging
Face and installs it as a `type: "llm"` module. Chat with it from the
student portal at `/chat/<module-id>`.

Any other small instruction-tuned model exported for `onnxruntime-genai`
works too — e.g. a Phi-3.5-mini ONNX build. Download all of that variant's
files (`genai_config.json`, `*.onnx`, `*.onnx.data`, tokenizer files) into
one `content/` folder and package it as a `type: "llm"` ZIP module the same
way as any other custom module (see above). The curated one-click model is
defined in `core/downloader.py`'s `LLM_CATALOGUE` / `LLM_REPO` /
`LLM_SUBFOLDER` if you want to swap in a different default.

Inference runs on CPU and is serialized one request at a time — it's meant
for a handful of students at once, not a classroom all chatting simultaneously.

---

## Testing the Hotspot on Your Laptop

Your laptop can share its existing Wi-Fi connection as a second hotspot
network simultaneously — Windows calls this **Mobile Hotspot**.

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

| Page     | Purpose                                        |
| -------- | ----------------------------------------------- |
| Modules  | Download content, add files/ZIPs, remove        |
| Hotspot  | Configure SSID / password, toggle hotspot       |
| Services | View loaded modules, unload to free memory      |
| Settings | Portal port, boot autostart, change password    |

---

## Building the Installer

To avoid antivirus false-positives (common with PyInstaller), this project
uses **Nuitka** to compile to standard C executables, and **Inno Setup** to
package everything into a Windows installer.

1. **Nuitka & C Compiler**: `pip install nuitka` (it prompts to download a
   MinGW compiler on first run).
2. **Inno Setup 6**: install from [jrsoftware.org](https://jrsoftware.org/isdl.php)
   to `C:\Program Files (x86)\Inno Setup 6\`.

Run `build.bat`. It compiles `main.py` into `main.dist\`, then packages
`main.dist\`, `assets\`, and `config.json` into `Output\OfflineHub_Setup.exe`.

`libzim` and `onnxruntime-genai` ship compiled native extensions with
backing DLLs — after building, **run `main.dist\main.exe` directly**, open a
ZIM module, and send one chat message before trusting the build. Missing-DLL
failures from Nuitka's standalone packaging only show up in the frozen exe,
never when running `python main.py` from source.

---

## Architecture Notes

- **No vendor binaries.** ZIM content and the LLM both run in-process via
  pip packages with real Windows wheels (`libzim`, `onnxruntime-genai`) —
  no subprocess management, no missing-exe failures, no antivirus flags on
  a bundled third-party server binary.
- **One process.** The student portal and the admin UI are the same Flask
  app; there's no separate desktop GUI framework to compile or crash.
- **Fully offline pages.** MapLibre GL JS is vendored locally
  (`assets/portal/vendor/`) — nothing on the portal fetches from a CDN at
  runtime, so it genuinely works with zero internet once installed.
- **Hotspot** uses the Windows WinRT Mobile Hotspot API first (Win10/11),
  falling back to `netsh wlan hostednetwork` for older hardware.
- **Downloads are resumable** — interrupted downloads pick up from where
  they left off using HTTP Range headers.

---

## Recent Changes

Full history isn't tracked in a separate file — this is a running summary,
newest first. Bump [`VERSION`](VERSION) when the next set of changes ships.

**0.2.1**
- Added the actual way to get the offline LLM: Admin → Modules → Offline
  Assistant now downloads a real, pre-tested Qwen2.5 0.5B model in one click
  (`core/downloader.py`'s `LLM_CATALOGUE`, wired to a new
  `POST /admin/downloads/llm` route). Previously the LLM engine existed in
  code but nothing ever exposed a way to install one.
- Fixed re-downloading an already-installed module (ZIM or LLM) crashing with
  a raw `WinError 32` ("file in use"): the running app holds that module's
  file open in memory (libzim keeps ZIM archives open for the process
  lifetime), so overwriting it mid-process was never going to work. Installed
  modules now show "✓ Installed" instead of a Download button, and
  `ModuleManager.install_from_download` / `install_llm_from_download` refuse
  cleanly with `FileExistsError` if the module folder already exists, instead
  of attempting the overwrite at all.

**0.2.0** — the vendor-binary-free rewrite
- Removed `vendor/kiwix-serve.exe` and `vendor/Kolibri.exe` entirely, and all
  Kolibri support — Kolibri's Windows distribution bundles a full Python
  runtime and can't run as a standalone extracted exe the way the old README
  instructed. Khan Academy works as a plain ZIM instead.
- Removed the whole `ui/` folder (`customtkinter` wizard, admin panel, main
  window) in favor of one Flask app: `/` is the public student portal,
  `/admin` is a password-gated setup/management UI, both reachable from any
  browser on the hotspot. A system tray icon is the visible running/quit
  signal now that there's no desktop window.
- Added `core/zim_reader.py` (Wikipedia/Gutenberg/Khan Academy via `libzim`,
  in-process, no subprocess) and `core/llm_engine.py` (offline chat via
  `onnxruntime-genai`).
- Fixed the Wikipedia catalogue URL being hardcoded to a dated snapshot
  filename Kiwix had already deleted — URLs now resolve live against Kiwix's
  OPDS catalog.
- Fixed a closure-over-loop-variable bug in the old setup wizard where
  selecting several catalogue items at once silently merged/mislabeled all
  of them into one module folder (`core/jobs.py` binds each download's
  `job_id` per request instead of sharing loop state across threads).
- Removed two silent CDN dependencies (a Google-fonts-style import and
  MapLibre GL JS from unpkg.com) that broke the "works with zero internet"
  promise on an actual hotspot with no WAN — MapLibre is now vendored
  locally in `assets/portal/vendor/`.
- Packaging: a real Nuitka build surfaced three frozen-build-only failures
  (an invalid `--include-package-data=libzim` flag, `onnxruntime`'s `capi/`
  extension module being silently dropped, and `onnxruntime-genai.dll`
  failing to load due to a runtime path-lookup that breaks under a
  Nuitka-compiled package) — all three are fixed and commented in
  `build.bat` and `core/llm_engine.py`.
