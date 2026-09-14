# OfflineHub Roadmap

---

## Phase 1 — Reliability for real deployments

1. **Handle a disk-full or interrupted download cleanly.** Right now a
   failed download's error message is whatever the underlying exception
   says. Confirm the `.part` file cleanup path in `Downloader.download()`
   behaves correctly when the disk fills up mid-write, and surface a plain-
   English message ("Not enough disk space") instead of a raw traceback.
2. **Add a log file.** Currently everything goes to a console window nobody
   is watching. Write to a rotating log file under `C:\OfflineHub\logs\`.
3. **Add an "Export Diagnostics" button** in Settings — zips the log file,
   config (with the password hash/salt redacted), and installed-module list
   into one file a non-technical admin can email or hand to whoever's
   helping them.
4. **Add an in-app "check for updates" flow.** No update mechanism exists
   today. At minimum: compare the running `VERSION` against the latest
   GitHub release tag and show a banner if newer.
5. **Actually test the installer on a clean machine with Windows Defender
   active.** Nuitka/PyInstaller-style builds are common antivirus false-
   positive targets; this has been assumed safe, never verified against a
   real, unmodified Defender install.

## Phase 2 — Usability for non-technical admins

6. **In-app help/troubleshooting page.** Right now the only documentation is
   [README.md](README.md) on GitHub, which a school librarian will never
   see. Put a plain-language help page in the admin UI itself: what a
   "module" is, what to do if the hotspot won't start, what to do if a
   download fails.
7. **A single "install the recommended starter bundle" button** instead of
   six separate Quick Start downloads. Most admins want "the normal setup,"
   not to evaluate each item individually on day one.
8. **Clearer setup wizard guidance** — minimum hardware expectations,
   what "hotspot" actually means for someone who's never set one up, a
   sane default path when something in setup fails partway through.

## Phase 3 — Scale and breadth

9. **Visible queue feedback for the LLM chat.** Generation is deliberately
   serialized, one request at a time (see `core/llm_engine.py`'s lock) —
   correct for CPU inference, but right now a second student just sees
   nothing happen while they wait. At minimum, show "N people ahead of you."
   Longer-term, consider a second, smaller model dedicated to short/simple
   questions so it doesn't all funnel through one queue.
10. **More content variety.** Everything curated so far is English-only.
    Kiwix has ZIMs in many languages; worth a curated non-English set for
    international deployments, plus more subject-specific content beyond
    PhET (history, civics, art).
11. **Self-serve custom map regions.** The six curated maps
    (`tools/build_map_packs.py`) cover a fixed list. A real "type your
    country/city, get a map" flow needs either running the Protomaps
    extract pipeline live from the admin panel (needs internet at download
    time, which is fine — only the *students* need to be offline) or a
    hosted service that does it for you.
12. **Move large-file hosting off personal Drive/Dropbox.** Works fine for
    one deployment; doesn't scale to many schools, and personal-account
    storage/bandwidth limits are a real risk at any real scale. Candidates:
    GitHub Releases (2GB/file limit, might not fit the USA map or the LLM
    zip) or a cheap object-storage bucket (Cloudflare R2, Backblaze B2) with
    a stable URL structure the app's catalogues point to directly.
13. **A content-refresh story.** ZIM snapshots and the Protomaps map build
    both go stale — right now everything is a one-time download with no way
    to know a newer version exists, let alone fetch it.

## Phase 4 — Differentiators (once the basics are solid)

14. **Ground the LLM's answers in installed content.** Retrieval over the
    Wikipedia/Gutenberg text already on disk, instead of the model
    answering purely from its own training data. This is the one thing that
    would make OfflineHub's assistant meaningfully different from "generic
    offline chatbot" — it could actually cite the encyclopedia sitting right
    next to it.
15. **Basic usage visibility for the admin.** Which modules actually get
    opened, so a school knows what to download more of instead of guessing.
    Needs care: aggregate counts only, no per-student tracking, in a school
    context with minors.

---
