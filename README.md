# Offline Knowledge Hub

A self-contained Windows application that serves Wikipedia, Khan Academy,
Project Gutenberg, and OpenStreetMap to students over a local Wi-Fi hotspot
or LAN — no internet required after setup.

The project is **WORK IN PROGRESS**. v0.1.4

---

## Project Structure

```bash
hub/
├── main.py                  # Entry point — first-run detection + launch
├── requirements.txt
├── build.bat                # 1-click build script (Nuitka + Inno Setup)
├── installer.iss            # Inno Setup configuration script
├── config.json              # Default config (installed to C:\OfflineHub)
│
├── ui/
│   ├── app.py               # Main CTk window
│   ├── admin_panel.py       # Tabbed admin panel
│   ├── cards.py             # Module card widgets
│   └── wizard.py            # First-run setup wizard
│
├── core/
│   ├── module_manager.py    # Install / launch / remove modules
│   ├── service_manager.py   # Process lifecycle + health checks
│   ├── downloader.py        # Resumable HTTP downloads + content catalogue
│   ├── hotspot.py           # Windows hotspot (WinRT + netsh fallback)
│   ├── portal.py            # Flask landing portal server
│   └── tileserver.py        # SQLite MBTiles tile server (replaces Node)
│
├── assets/
│   └── portal/
│       └── index.html       # Student-facing browser portal (MapLibre GL JS)
│
└── vendor/                  # Place third-party binaries here before building
    ├── kiwix-serve.exe      # Download from https://www.kiwix.org/en/downloads/
    └── kolibri.exe          # Download from https://learningequality.org/kolibri/
```

---

## Development Setup

```powershell
# 1. Create a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1
# or: source .venv/Scripts/activate

# 2. Install dependencies (including Nuitka for building)
pip install -r requirements.txt
pip install nuitka

# 3. Run from source
python main.py
```

---

## Adding Vendor Binaries

Before building the Setup package, download the required binaries into `vendor/`:

| File              | Source                                                                            |
| ----------------- | --------------------------------------------------------------------------------- |
| `kiwix-serve.exe` | [kiwix](https://www.kiwix.org/en/downloads/) → "kiwix-tools" Windows build        |
| `kolibri.exe`     | [kolibri](https://learningequality.org/kolibri/) → Windows installer, extract EXE |

The Kolibri binary is only required if you plan to serve Khan Academy content
through Kolibri's channel system. Khan Academy is also available as a Kiwix ZIM
(served by kiwix-serve) and is the simpler option.

---

## Building the Installer

To avoid Antivirus false-positives (common with PyInstaller), this project uses **Nuitka** to compile the Python code into standard C executables, and **Inno Setup** to package everything into a professional Windows Installer (`.exe`).

### Prerequisites for Building

1. **Nuitka & C Compiler**: Installed via `pip install nuitka`. (Nuitka will prompt you to download a MinGW compiler the first time it runs).
2. **Inno Setup 6**: Download and install from [jrsoftware.org](https://jrsoftware.org/isdl.php). Ensure it installs to `C:\Program Files (x86)\Inno Setup 6\`.

### Build Process

Simply double-click the **`build.bat`** file in the project root, or run it from the terminal:

```powershell
.\build.bat
```

**What the build script does:**

1. Compiles `main.py` and its dependencies into a native Windows application folder (`main.dist`).
2. Triggers Inno Setup to bundle `main.dist`, your `assets/`, `config.json`, and `vendor/` binaries into a single, compressed installer.
3. Outputs **`OfflineHub_Setup.exe`** into an `Output/` folder.

You only need to distribute `OfflineHub_Setup.exe`. No Python or dependencies are needed on target machines. The uninstaller is programmed to cleanly remove all downloaded content when uninstalled.

---

### Installation & First Run on a New Machine

1. Double-click `OfflineHub_Setup.exe`.
2. Follow the standard Windows installation prompts (Installs safely to `C:\OfflineHub`).
3. Launch "School Hub" from the newly created Desktop or Start Menu shortcut.
4. The setup wizard launches automatically on the first run.
5. Choose content to download (requires internet on first run only).
6. Set hotspot SSID / password and admin password.
7. Wait for downloads to complete (large files — plan for hours on slow connections).
8. Done. Students connect to the hotspot and open any browser.

---

## Content Catalogue

The setup wizard and Admin Panel provide a 1-click installer for automated starter content:

| Module                   | Format | Server      | Approx. Size |
| ------------------------ | ------ | ----------- | ------------ |
| Wikipedia (English Mini) | `.zim` | kiwix-serve | ~12 GB       |
| Project Gutenberg        | `.zim` | kiwix-serve | ~15 GB       |
| Khan Academy (Computing) | `.zim` | kiwix-serve | ~1.8 GB      |

ZIM download URLs are in `core/downloader.py → CATALOGUE`.
Update them to point to newer Kiwix releases as needed.

---

## Adding Custom Modules & Offline Maps

You can easily add new libraries, books, and interactive offline maps directly from the Admin Panel.

### 1. The Easy Way: Raw Files (Magic Installer)

The app features a smart module installer that handles all the complex folder structures for you.

1. Download any `.zim` file from the [Kiwix Library](https://library.kiwix.org).
2. Download any `.mbtiles` map (Raster or Vector) from [BBBike](https://extract.bbbike.org/) or [MapTiler](https://data.maptiler.com/downloads/europe/).
3. Open the **Admin Panel** (Ctrl + Shift + A).
4. Click **📦 Add File (.zim / .mbtiles / .zip)** and select your file.

The app will instantly move the file, generate a readable name, assign an emoji, build the underlying `manifest.json`, and start the background service.

### 2. The Advanced Way: Custom ZIP Modules

If you want granular control over your module (or are deploying Kolibri channels), you can still package files into a ZIP using the standard structure.

**Module folder structure:**

```bash
my_module/
├── manifest.json        ← required
└── content/
    └── myfile.zim       ← or .mbtiles for maps
```

**manifest.json reference:**

```json
{
  "name": "London Map",
  "emoji": "🗺️",
  "type": "mbtiles",
  "format": "vector",
  "description": "A short description shown on the module card."
}
```

| Field         | Required | Values                          | Notes                             |
| ------------- | -------- | ------------------------------- | --------------------------------- |
| `name`        | ✅       | Any string                      | Displayed as the card title       |
| `emoji`       | ✅       | Any single emoji                | Displayed next to the title       |
| `type`        | ✅       | `kiwix` / `kolibri` / `mbtiles` | Controls which server is used     |
| `format`      | ❌       | `raster` / `vector`             | Used for Maps (`mbtiles`) only    |
| `description` | ❌       | Any string                      | Shown in smaller text on the card |

**Type behaviour:**

- `kiwix` — Starts kiwix-serve automatically when the module is opened.
- `kolibri` — Looks for a `kolibri.exe` and starts Kolibri with `KOLIBRI_HOME` pointed at the module's subfolder.
- `mbtiles` — No separate process is started. The Flask server reads the SQLite `.mbtiles` file and streams vector (`.pbf`) or raster (`.png`) tiles directly to the MapLibre GL JS frontend.

---

## Testing the Hotspot on Your Laptop

Your laptop can share its existing Wi-Fi connection as a second hotspot network
simultaneously — Windows calls this **Mobile Hotspot**. Your laptop stays connected
to your router, and other devices connect to the hub's hotspot instead.

**To test manually (without the app):**

1. Open **Settings → Network & Internet → Mobile Hotspot**
2. Set a network name and password
3. Toggle it on
4. Connect a phone or another device to that network
5. On the connected device, open a browser and go to `http://<your-laptop-IP>:8000`

Your laptop IP is shown in the status bar of the hub app, or run `ipconfig` in
a terminal and look for the **Wi-Fi** adapter address.

**Hardware requirement:** your Wi-Fi adapter must support hosted networks (virtually
all modern adapters do). If the WinRT API fails, the hub automatically falls back
to the older `netsh wlan hostednetwork` method. If both fail, the error message
from Windows will appear in the Hotspot tab of the Admin Panel.

---

## Admin Panel

Open with **Ctrl + Shift + A** from the main window.

| Tab      | Purpose                                      |
| -------- | -------------------------------------------- |
| Modules  | Download content, add raw files/ZIPs, remove |
| Hotspot  | Configure SSID / password, toggle hotspot    |
| Services | View running processes, stop / restart       |
| Settings | Portal port, boot autostart, change password |

---

## Architecture Notes

- **Native Map Engine:** The student portal uses MapLibre GL JS, fully supporting both high-definition Raster Maps and compressed Vector Maps without needing Node.js or Mapbox servers.
- **Fast Shutdown:** Windows process management via `taskkill` ensures instant cleanup of Kiwix background threads when closing the app.
- **Hotspot** uses the Windows WinRT Mobile Hotspot API first (Win10/11), falling back to `netsh wlan hostednetwork` for older hardware.
- **Downloads** are resumable — if interrupted, the next attempt picks up from where it left off using HTTP Range headers.
