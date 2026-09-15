# OfflineHub Roadmap

---

## Phase 1: Reliability for real deployments

1. **Handle a disk-full or interrupted download cleanly.** Right now a
   failed download's error message is whatever the underlying exception
   says. Confirm the `.part` file cleanup path in `Downloader.download()`
   behaves correctly when the disk fills up mid-write, and surface a plain-
   English message ("Not enough disk space") instead of a raw traceback.
2. **Add a log file.** Currently everything goes to a console window nobody
   is watching. Write to a rotating log file under `C:\OfflineHub\logs\`.
3. **Add an "Export Diagnostics" button** in Settings. Zips the log file,
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

## Phase 2: Usability for non-technical admins

6. **In-app help/troubleshooting page.** Right now the only documentation is
   [README.md](README.md) on GitHub, which a school librarian will never
   see. Put a plain-language help page in the admin UI itself: what a
   "module" is, what to do if the hotspot won't start, what to do if a
   download fails.
7. **A single "install the recommended starter bundle" button** instead of
   six separate Quick Start downloads. Most admins want "the normal setup,"
   not to evaluate each item individually on day one.
8. **Clearer setup wizard guidance**: minimum hardware expectations, what
   "hotspot" actually means for someone who's never set one up, a sane
   default path when something in setup fails partway through.

## Phase 3: Scale and breadth

9. ✅ **Visible queue feedback for the LLM chat.** Done. A FIFO ticket
   queue in `core/llm_engine.py` reports live position; the chat UI shows
   "N people ahead of you." (The "second, smaller model for simple
   questions" longer-term idea is still open, not done.)
10. ✅ **More content variety.** Done. Added Spanish/French Wikipedia and
    Vikidia, and English History/Mathematics/Chemistry ZIMs. All were
    live-verified against the real Kiwix catalog.
13. ✅ **A content-refresh story.** Done. Installed modules record their
    source URL. The Modules page flags a "🔄 Newer version available"
    badge and offers a one-click re-download-in-place.

### Deferred: later, not now

12. **Move large-file hosting off personal Drive/Dropbox.** This is a
    hosting decision (GitHub Releases vs. Cloudflare R2 vs. Backblaze B2),
    not a coding task. Needs the user to pick a provider and get
    credentials before any code changes here make sense. Picking this up
    later.

## Phase 4: Differentiators (once the basics are solid)

14. ✅ **Ground the LLM's answers in installed content.** Done. Naive RAG
    over each installed ZIM's own full-text search index
    (`core/retrieval.py`), folded into the system prompt with instructions
    to cite the source and ignore excerpts that aren't relevant. Verified
    live against a real model and a real Vikidia install: "What is a
    volcano?" got a grounded answer ending in `[Source: Vikidia: "Volcano"]`.
    Caught and fixed a real bug in the same pass. A plain "Hi! How are you
    today?" pulled in unrelated articles ("Norwegian language") via
    libzim's fuzzy search, and the model echoed that irrelevant context
    straight into its reply. Added a keyword-overlap relevance filter so
    retrieval only fires when the query and the match actually share real
    words.
15. ✅ **Basic usage visibility for the admin.** Done. `core/usage_stats.py`
    tracks a simple per-module open count (aggregate only, no timestamps,
    no per-student identity), shown as a "👁 N opens" badge on each
    installed module's card.

## Phase 5: Polish

16. ✅ **Spinning icon while waiting for an LLM reply.** Done. The chat UI
    shows a small CSS spinner in the assistant's reply bubble as soon as a
    message sends, and clears it the moment the first real token, queue
    message, or error arrives (`templates/portal/chat.html`).
17. ✅ **Remove em dashes and rewrite long sentences project-wide.** Done.
    Every admin/portal screen, all 4 translation files, README.md, and
    plan.md now avoid em dashes and cap sentences at 15 words. Code
    comments and docstrings across `core/`, `main.py`, and `tools/` were
    cleaned up the same way, along with `installer.iss`, `requirements.txt`,
    and `uninstall_stop_hotspot.ps1`. Also fixed one instance that could
    reach a student's screen: the LLM's citation format
    (`core/llm_engine.py`) used an em dash between the module name and the
    article title, and that format could show up verbatim in a chat reply.
18. ✅ **Self-serve country map downloads.** Done. The Offline Maps tab now
    has a "Search for a Country" box covering all 173 countries in a
    bundled dataset, not just the 6 curated regions. `core/map_extract.py`
    extracts a chosen country's tiles live from Protomaps' free daily
    global basemap build, straight into a local `.mbtiles` file, using
    plain HTTP Range requests against the `pmtiles` Python package's
    `Reader` instead of the `go-pmtiles` Go binary
    `tools/build_map_packs.py` uses (a maintainer-only dev tool, never
    shipped) - keeping the "no vendor binaries" principle intact. Verified
    live end-to-end through the real running app, not just in isolation: a
    real Luxembourg extraction (139 tiles) completed in about 10 seconds
    through the actual `/admin/downloads/map_country` route, background
    thread, and job-progress polling, and the resulting module opened
    correctly in the portal's map viewer. A real France-sized extraction
    took much longer than that throughput would predict - directory-node
    cache reuse is far less effective across a large, spread-out area than
    a small one - so the per-country tile budget was calibrated down
    accordingly (`DEFAULT_TILE_BUDGET` in `core/map_extract.py`) rather
    than trusting the optimistic small-country number alone. Large
    countries automatically get a lower max zoom to stay within that
    budget instead of risking a multi-tens-of-minutes wait.

## Phase 6: More knowledge sources

Checked against the live Kiwix catalog before writing these, not assumed
from memory or an old list.

19. **Programming/developer reference ZIMs.** Kiwix's live catalog already
    hosts docs for Python, PHP, Ruby, Rust, C/C++, Docker, PostgreSQL,
    MariaDB, and a dozen-plus web frameworks. Same `CATALOGUE` pipeline as
    the existing entries, so this is mostly new data entries, not new code.
    A good fit for any coding or CS instruction happening on-site.
20. **MedlinePlus.** The US National Library of Medicine's consumer health
    encyclopedia, confirmed available in the catalog. Trustworthy and
    appropriate for a school, and fills a real gap Wikipedia doesn't cover
    well.
21. **Project Euler.** A math problem archive, confirmed available. Good
    for math and CS enrichment beyond the school's normal curriculum.
22. **Wikivoyage.** A geography, culture, and travel guide, confirmed
    available. Pairs naturally with Wikipedia for social studies.
23. **TED talks (topic-sliced ZIMs).** Real educational video content,
    confirmed available as several topic-specific splits (science, tech,
    ideas, etc.). Needs verification before committing to it: whether
    libzim actually streams embedded video smoothly over a school Wi-Fi
    hotspot at classroom scale, not just for one viewer.
24. **Let a school upload its own material.** A teacher's own PDFs,
    worksheets, or slides as a searchable module, not just more curated
    encyclopedias. This is a genuinely new content type (upload plus
    indexing), not another catalogue entry, so it needs real scoping
    first: which file types, how it gets indexed and searched, and
    whether any storage limit makes sense.

## Phase 7: Fixes from real use

25. ✅ **Self-serve country maps had two real bugs, found from an actual
    admin report.** Done. A screenshot of Cyprus centered on Nicosia showed
    a real hole in the middle of the map, with data only at the edges. Two
    separate causes, both confirmed on the actual installed module (its own
    mbtiles metadata really did say `maxzoom: 12`), not guessed:
    - The frontend's vector source (`templates/portal/index.html`) never
      declared a `maxzoom` of its own, so MapLibre assumed data existed all
      the way to z22. Zooming in past whatever a module actually had meant
      requesting tiles that don't exist, getting 404s, and rendering
      nothing there instead of gracefully reusing the deepest real tile.
      `/api/modules` (`core/blueprints/portal.py`) now reports each
      module's real max zoom, straight from its own mbtiles metadata, the
      same way it already does for `bounds`.
    - Separately, `core/map_extract.py`'s extraction ceiling (`z12`, set
      before the POI/road-label style work in item 18's follow-up) was too
      shallow for that later work to ever show anything: the `pois` and
      `road-labels` layers don't start rendering until `z13`, and
      `poi-labels` not until `z15` - a capital city extracted at the old
      ceiling could never show a single POI, independent of the gap issue
      above. Raised to `z15` (the live Protomaps build's own real maximum,
      confirmed via its header), with the per-country tile budget
      recalibrated so small/city-state-sized countries (Cyprus included)
      reach that full ceiling while larger countries still auto-reduce.

    Verified by re-extracting the admin's actual Cyprus module end to end
    through the real code path, not just in isolation: 14,328 tiles, real
    elapsed time 26 minutes, landed correctly at `maxzoom: 15` in both the
    `.mbtiles` metadata and the live `/api/modules` response. That's
    notably slower than the throughput item 18's own numbers assumed
    (`DEFAULT_TILE_BUDGET`'s comment there is now out of date on the exact
    minutes, though the reasoning and the auto-reduction behavior still
    hold) - worth knowing if this ever needs recalibrating again.

26. ✅ **Quit could hang indefinitely, and an uninstall that caught the
    app mid-hang could delete modules unevenly instead of honoring "keep
    modules."** Done. Found from two real admin reports in the same
    session: the tray icon stopped responding to clicks, and afterward an
    uninstall that was supposed to keep all installed content only kept
    the map modules; every ZIM and the LLM model were gone.

    Root-caused from the app's own log file, not guessed. It showed
    "Quit requested" firing four separate times over 4.5 minutes while
    the process kept serving requests in between - proof the shutdown
    path can start but never actually finish, for a reason still not
    fully pinned down (pystray's win32 message loop is the leading
    suspect). Whatever the exact cause, a process that never exits after
    "Quit" is exactly what a stuck tray icon looks like.

    That explains the uneven module loss too: `core/tileserver.py`'s
    `TileServer` caches one open sqlite connection per `.mbtiles` module
    for the life of the process, and `close_all()` existed but was never
    called from anywhere, confirmed by grepping the whole codebase for
    it. So a hung-but-still-alive process kept every map's `.mbtiles`
    file locked open indefinitely, while ZIM/LLM modules' handles get
    closed fine by `registry.unload_all()`. If the app was still alive
    (however that happens) when an uninstall ran, Windows would refuse to
    delete whatever `.mbtiles` files were still locked while deleting
    everything else normally - the opposite of "keep," and just as wrong
    if the admin had chosen to delete everything instead.

    Fixed both causes in `main.py`'s `quit_app()`: it now calls the
    previously-dead `tile_server.close_all()`, and a 25-second watchdog
    thread force-exits the process (`os._exit`) if normal shutdown hasn't
    already finished by then, so "Quit" is now guaranteed to actually end
    the process within a bounded time no matter what hangs underneath.
    `uninstall_stop_hotspot.ps1` already asks the app to quit gracefully
    over a loopback-only `/_internal/quit` route before the uninstaller's
    `taskkill /F` fallback runs (added earlier the same session for a
    separate stale-icon report); it now polls for the process to actually
    be gone for up to 28 seconds instead of a fixed 1.5-second sleep, to
    match the watchdog's worst case.

    Verified live end-to-end, not just read through: installed a real
    `.mbtiles` module, hit `/api/modules` to force `TileServer` to open
    and cache its connection (confirmed via the response actually
    containing the module's real data), called `/_internal/quit`, and
    confirmed both that the process exited immediately (not via the 25s
    watchdog) and that the `.mbtiles` file could be renamed right
    afterward - proof it was no longer locked. Full 151-test suite still
    passes.

    The admin's actual missing wikipedia/wiktionary/vikidia/phet/LLM
    modules from this incident are gone from disk and were not
    recoverable - they need to be redownloaded from the Modules page.

27. ✅ **A reinstall showed "no maps installed" even though both map
    files were still on disk.** Done. Direct fallout from item 26's
    uninstall bug: `manifest.json` is a tiny file nothing ever holds
    open, so it was deleted cleanly for every module, while the two
    `.mbtiles` data files survived only because `TileServer` had them
    locked open. `core/module_manager.py`'s `list_modules()` used to
    silently skip any folder without a readable manifest, so two real,
    intact map files just disappeared from the app.

    Now self-heals: a module folder with real content but no manifest
    gets one reconstructed and persisted automatically, using the real
    country name for a self-serve map or the real catalogue entry's
    name/description for anything else, not a guessed one. Used this
    same logic to recover the admin's actual two modules on the spot
    ("Map: Cyprus", "Map: United Kingdom", both correctly detected as
    vector). Full test suite passes.

28. ✅ **A 30-minute country map download died on one network hiccup,
    then a retry failed with a locked-file error.** Done. A real Cyprus
    extraction hit `HTTPSConnectionPool: Read timed out` after 30
    minutes, and retrying hit `WinError 32: The process cannot access
    the file`. Two real bugs in `core/map_extract.py`: a long extraction
    fires thousands of individual HTTP range requests against a public
    server with no retry at all, so a single transient timeout aborted
    the entire job; and the destination sqlite connection was only ever
    closed on the success path, so that same failed attempt left the
    file locked, and the retry's own cleanup of it failed.

    Fixed both: each HTTP request now retries with backoff, a tile that
    still fails after retries is tracked and skipped rather than killing
    the whole extraction (unless too many fail, which still raises
    instead of silently installing a mostly-blank map), and the
    connection is always closed and the partial file removed on any
    failure, so a retry starts clean. Verified with new tests that
    reproduce the exact failure-then-retry sequence, not just the happy
    path; 156-test suite passes.

29. ✅ **Choosing "keep" on the modules prompt during uninstall deleted
    the whole app folder anyway.** Done. Found from a real report right
    after item 26/27 shipped - the fix for the *previous* uninstall bug
    still didn't actually honor "keep." Root-caused with an instrumented
    test build of the installer script (real Inno Setup, not guessed):
    it proved `[UninstallDelete]`'s `Check:` function is evaluated
    *before* `InitializeUninstall()` even runs, so `ShouldDeleteModules()`
    always read `KeepModules` at its uninitialized default (false) and
    always deleted the modules folder, regardless of what the admin
    actually answered. The prompt itself worked; the answer just came
    too late for Inno to see it.

    Fixed by moving the deletion out of `[UninstallDelete]`'s Check
    mechanism entirely: `installer.iss` now deletes the modules folder
    explicitly from a `CurUninstallStepChanged` handler at the
    `usPostUninstall` step, which reliably runs after
    `InitializeUninstall()` has already recorded the real answer.
    Verified against the actual compiled uninstaller end to end, not
    just read through: an instrumented test install proved the old code
    called `ShouldDeleteModules()` and got a delete decision *before*
    `InitializeUninstall()` ever ran, then confirmed the fix keeps real
    module content and the app folder itself on "keep," and still
    removes everything on "delete" - both against a real install/
    uninstall cycle, not a simulation.

30. ✅ **Country map downloads were needlessly slow, and there was no way
    to cancel one.** Done. An admin asked why a ~168MB Cyprus extraction
    took so long, and pointed out there's no cancel button for any
    download.

    Measured live against the real Protomaps server, not guessed: a real
    680-tile extraction timed at concurrency 4, 8, 16, 48, and 96 showed
    throughput flat at ~9-10 tiles/sec across *all* of them - a server-
    side rate limit, not something more client concurrency can beat -
    while per-request latency got dramatically worse at high concurrency
    (mean 1.08s at 16 threads vs. 5.14s, max 18.1s, at 96 threads) for
    zero throughput benefit. That latency is very likely what actually
    caused item 28's real read-timeout failure: `CONCURRENCY` was 48,
    eating almost all of the request timeout's margin for nothing in
    return. Lowered to 16 (the fastest of everything tested), and the
    per-request timeout padded from 20s to 30s for extra safety margin.
    At the real ~10 tiles/sec ceiling, a large country's 20-30+ minute
    extraction time is a hard limit from the free public source server,
    not something fixable client-side - now shown to the admin as an
    honest ETA (`est_minutes`) before they commit to it, instead of just
    a size estimate.

    Added cancellation throughout, not just for map extraction: every
    background job (`core/jobs.py`'s `JobTracker`) now carries its own
    `threading.Event`, checked periodically by `Downloader.download()`/
    `download_set()` (every 256KB chunk, and between files in a set) and
    by `map_extract.extract_country()` (between tiles, cancelling
    whatever hasn't started yet and cleaning up the partial file - there's
    no resume support for extraction the way a plain HTTP download has).
    A new `/admin/downloads/<job_id>/cancel` route (session-gated like
    every other admin route) marks a job cancelled immediately so the UI
    can reflect that before the background thread catches up. Every
    download card in the admin
    UI (`templates/admin/_download_panel.html`) now has a working Cancel
    button next to its progress bar.

    Verified live end-to-end through the real running app, not just
    unit tests: started a real Luxembourg extraction against the live
    Protomaps server through the actual `/admin/downloads/map_country`
    route, cancelled it mid-flight through the actual cancel route, and
    confirmed through the actual status route that it stopped and left
    no partial `.mbtiles` file behind. 166-test suite passes, including
    new regression tests for cancellation at every layer (JobTracker,
    Downloader, extract_country).

---
