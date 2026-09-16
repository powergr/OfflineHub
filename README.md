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
| ----------- | -------------------------------- | ---------------------------------------------------------------------------------------- |
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

The Offline Maps tab also has a "Search for a Country" box. Unlike the
six curated regional packs above, this extracts a chosen country's
tiles live. The source is Protomaps' free daily global basemap build
(`core/map_extract.py`). It writes straight into a local `.mbtiles`
file. No vendor binary is involved. The `pmtiles` Python package's
`Reader` accepts any byte-range-capable source. So the extraction uses
plain HTTP Range requests instead. It avoids the `go-pmtiles` CLI a
build-time-only dev tool (`tools/build_map_packs.py`) uses for the
curated packs. Very large countries automatically get a lower max
zoom. That keeps the download a reasonable size.

The shown size is an estimate, not an exact figure. Real byte size
varies by how much of a country's box is empty ocean. Dense
urban data pushes it the other way. Kiwix's own reported sizes
are exact, by contrast. The time estimate is more reliable. It comes
from a real throughput measurement against the live source server, not
a guess. A large country can still take 20-30+ minutes, since that
server rate-limits regardless of concurrency. Any download, including
a country map, can be cancelled mid-way from its own progress bar.

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

For all the changes check **[Changelog](https://github.com/powergr/OfflineHub/blob/master/changelog.md)**

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

## LICENCE MIT
