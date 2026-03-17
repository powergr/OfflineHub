# Offline School Knowledge Hub

A self-contained Windows application that serves Wikipedia, Khan Academy,
Project Gutenberg, and OpenStreetMap to students over a local Wi-Fi hotspot
or LAN — no internet required after setup.

---

## Project Structure

```bash
hub/
├── main.py                  # Entry point — first-run detection + launch
├── requirements.txt
├── hub.spec                 # PyInstaller build spec → produces OfflineHub.exe
├── config.json              # Default config (copied to C:\OfflineHub on first run)
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
│       └── index.html       # Student-facing browser portal
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

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run from source
python main.py
```

---

## Adding Vendor Binaries

Before building the EXE, download the required binaries into `vendor/`:

| File              | Source                                                                            |
| ----------------- | --------------------------------------------------------------------------------- |
| `kiwix-serve.exe` | [kiwix](https://www.kiwix.org/en/downloads/) → "kiwix-tools" Windows build        |
| `kolibri.exe`     | [kolibri](https://learningequality.org/kolibri/) → Windows installer, extract EXE |

The Kolibri binary is only required if you plan to serve Khan Academy content
through Kolibri's channel system. Khan Academy is also available as a Kiwix ZIM
(served by kiwix-serve) and is the simpler option.

---

## Building the EXE

```powershell
# Install UPX for compression (optional but recommended)
# Download from https://github.com/upx/upx/releases and add to PATH

# Build
pyinstaller hub.spec --clean

# Output: dist\OfflineHub.exe
```

The resulting `OfflineHub.exe` is fully self-contained.
Distribute just that single file — no Python or dependencies needed on target machines.

### First Run on a New Machine

1. Double-click `OfflineHub.exe`.
2. The setup wizard launches automatically.
3. Choose content to download (requires internet on first run only).
4. Set hotspot SSID / password and admin password.
5. Wait for downloads to complete (large files — plan for hours on slow connections).
6. Done. Students connect to the hotspot and open any browser.

---

## Content Catalogue

| Module                   | Format     | Server                     | Approx. Size |
| ------------------------ | ---------- | -------------------------- | ------------ |
| Wikipedia (English Mini) | `.zim`     | kiwix-serve                | ~12 GB       |
| Project Gutenberg        | `.zim`     | kiwix-serve                | ~60 GB       |
| Khan Academy             | `.zim`     | kiwix-serve                | ~18 GB       |
| OpenStreetMap Europe     | `.mbtiles` | Built-in Flask tile server | ~8 GB        |

ZIM download URLs are in `core/downloader.py → CATALOGUE`.
Update them to point to newer Kiwix releases as needed.

---

## Custom Modules

You can package any Kiwix ZIM file, Kolibri channel, or MBTiles map as a custom
module and install it via **Admin Panel → Modules → Add Module from ZIP**.

### Module folder structure

```bash
my_module/
├── manifest.json        ← required
└── content/
    └── myfile.zim       ← or .mbtiles for maps
```

Zip the `my_module/` folder and the result is ready to install.

### manifest.json reference

```json
{
  "name": "My Module",
  "emoji": "📘",
  "type": "kiwix",
  "description": "A short description shown on the module card."
}
```

| Field         | Required | Values                          | Notes                             |
| ------------- | -------- | ------------------------------- | --------------------------------- |
| `name`        | ✅       | Any string                      | Displayed as the card title       |
| `emoji`       | ✅       | Any single emoji                | Displayed next to the title       |
| `type`        | ✅       | `kiwix` / `kolibri` / `mbtiles` | Controls which server is used     |
| `description` | ❌       | Any string                      | Shown in smaller text on the card |

**Type behaviour:**

- `kiwix` — the hub searches the module folder for a `kiwix-serve.exe` and any `.zim` files, then starts kiwix-serve automatically when the module is opened. Place `kiwix-serve.exe` in the module root or any subfolder.
- `kolibri` — the hub looks for a `kolibri.exe` and starts Kolibri with `KOLIBRI_HOME` pointed at the module's `kolibri_home/` subfolder.
- `mbtiles` — no separate process is started. The hub's built-in Flask tile server reads the `.mbtiles` file directly from the `content/` subfolder and serves tiles at `/tiles/<module_name>/{z}/{x}/{y}.png`. The portal page renders the map using Leaflet.

### Example: packaging a custom ZIM

1. Download any `.zim` from [library.kiwix.org](https://library.kiwix.org)
2. Copy `kiwix-serve.exe` from `C:\OfflineHub\bin\` into the module folder
3. Create `manifest.json` as shown above with `"type": "kiwix"`
4. Zip the folder and install via Admin Panel

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
| Modules  | Download content, add from folder, remove    |
| Hotspot  | Configure SSID / password, toggle hotspot    |
| Services | View running processes, stop / restart       |
| Settings | Portal port, boot autostart, change password |

---

## Architecture Notes

- **No Node.js required.** Map tiles are served directly from `.mbtiles`
  (SQLite) files by a Flask route in `core/tileserver.py`.
- **Hotspot** uses the Windows WinRT Mobile Hotspot API first (Win10/11),
  falling back to `netsh wlan hostednetwork` for older hardware.
- **All services** (kiwix-serve, Kolibri) are managed as subprocesses with
  automatic health-check restarts every 30 seconds.
- **Downloads** are resumable — if interrupted, the next attempt picks up
  from where it left off using HTTP Range headers.
