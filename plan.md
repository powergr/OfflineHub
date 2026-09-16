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

19. ✅ **Programming/developer reference ZIMs.** Done. Added five small
    devdocs.io-style references to `CATALOGUE`: Python, JavaScript, C++,
    HTML, CSS. Picked the languages most likely to be taught in a K-12/
    intro CS setting, not the full dozen-plus Kiwix hosts (PHP, Ruby,
    Docker, PostgreSQL, MariaDB, Rust and more are real entries too -
    reachable via Discover Content). Every `name`/`flavour` was confirmed
    live through `resolve_catalogue_entry()`, the exact function the app
    itself calls at runtime, not just that a search found them. Verified
    beyond just resolving a URL: ran a real download, real install, real
    ZIM open, and a real full-text search through `devdocs_python` end to
    end. Searching "list" correctly returned "List Objects" from Python's
    C API docs.
20. ✅ **MedlinePlus.** Done. Added as `medlineplus` (1.85GB, only one
    flavour available). Confirmed live via `resolve_catalogue_entry()`.
21. ✅ **Project Euler.** Done. Added as `project_euler`. The real, live
    catalogue entry is `freecodecamp_en_project-euler` (~7MB) - hosted
    under freeCodeCamp's ZIM, not a standalone one, confirmed by checking
    the actual catalog rather than assuming a name.
22. ✅ **Wikivoyage.** Done. Added as `wikivoyage_en`, the `nopic` flavour
    (~223MB, all 67,558 articles worldwide) instead of `maxi` (~1.1GB),
    matching the light-footprint preference already used for
    wiktionary_en_simple and the Phase 3 subject slices.
23. ✅ **TED talks (topic-sliced ZIMs).** Done - the verification this item
    itself called for turned up a real blocker, and that got fixed first.
    `core/zim_reader.py`'s `resolve()` always returned `bytes(item.content)`
    - the whole item, fully materialized - and `portal.py`'s
    `content_page()` wrapped that in a plain `Response` with no
    `Accept-Ranges`/206 support. Confirmed by reading both, not assumed.
    A video entry could never be seeked, and a multi-minute talk would
    have had to fully download before playback could even start - the
    "not smooth at classroom scale" risk this item flagged, confirmed as
    a real, specific gap rather than a guess.

    Added real HTTP Range support: `ZimReader.entry_info()` gets an
    entry's size/mimetype without reading its content, and
    `resolve_range()` slices libzim's own memoryview for the requested
    byte range instead of copying the whole entry first.
    `content_page()` now handles a `Range` header (normal, open-ended,
    and suffix ranges, plus 416 for an unsatisfiable one) and still
    serves the same full response as before when there's no Range header.

    Verified two ways, not just unit tests: real HTTP Range requests
    against a real installed ZIM through the actual running app,
    confirming byte-for-byte that a ranged response exactly matches
    slicing the equivalent full response; and 24 new tests covering the
    Range-parsing edge cases directly (suffix ranges, clamping past the
    end, malformed headers). Full suite: 183 passing.

    Added `ted_ed` (TED-Ed specifically - TED's curriculum-style short
    lesson format, the clearest fit for a classroom, not general TED
    conference talks) to `CATALOGUE`, confirmed live via
    `resolve_catalogue_entry()` (~5.7GB). Other TED topic slices are
    real catalogue entries too, reachable via Discover Content.
24. **Let a school upload its own material.** Scoped: PDF only, with
    full-text search. Still to build.

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

31. ✅ **A silent/unattended uninstall could hang instead of honoring
    "keep content," risking custom maps and every other module.** Done.
    Asked to check the uninstall logic for a custom-maps bug. Self-serve
    country maps live under `modules\country_<iso>\`, the same tree as
    every other module, so item 29's "keep on uninstall" fix already
    covers them structurally. The real remaining gap was different:
    `InitializeUninstall()` shows the keep/delete choice with a plain
    `MsgBox`, and checked against Inno Setup's own documentation, plain
    `MsgBox` (unlike `SuppressibleMsgBox`) always opens a real window,
    even during a `/SILENT` or `/VERYSILENT` uninstall - it is not
    suppressed automatically the way Inno's own wizard UI is.

    A school running a fleet-wide silent removal (common for IT-managed
    deployments) would hit that box with no one able to click it,
    hanging the uninstall indefinitely rather than cleanly finishing one
    way or the other.

    Fixed by checking Inno's own `UninstallSilent()` function first: a
    silent uninstall now skips the prompt entirely and defaults to
    keeping the modules folder, rather than risking either a hang or an
    unattended wipe of gigabytes of downloaded content (maps, Wikipedia,
    the offline assistant) with nobody there to say no. Verified the
    script still compiles cleanly with the real Inno Setup Compiler
    (`ISCC.exe`, not just read through) after the change.

32. ✅ **Quick Start's 23 cards were one long flat list, hard to scan for
    what an admin actually wants.** Done. Asked directly for category
    tabs to make browsing easier as Phase 6 kept growing the list.

    Added a `category` field to every `CATALOGUE` entry
    (`core/downloader.py`), grouped into five tabs: General Reference (6),
    Other Languages (4), Subject-Specific (5), Programming (5), and
    Health/Travel/More (3) - counts confirmed against the real catalogue,
    not assumed. `refresh_catalogue()` already copies every entry via
    `dict(item)`, so `category` flows through to the template with no
    other backend change needed.

    The tabs (`templates/admin/_download_panel.html`) filter client-side
    with plain `style.display` toggling - all 23 cards are already in the
    DOM, so switching is instant with no extra request, matching how the
    self-serve country map search already filters client-side. The
    chosen category is remembered in `sessionStorage` so it survives the
    Starter Bundle button's `location.reload()`. New i18n keys added to
    all 4 translation files.

    Verified against the real running app, not just read through: an
    isolated instance's actual `/admin/modules` HTML response was
    inspected directly, confirming all 5 category tab buttons render
    with the correct labels and that the real per-category card counts
    (6/4/5/5/3) match the catalogue exactly. New regression tests confirm
    every `CATALOGUE` entry has a valid category and that
    `refresh_catalogue()` preserves it. 200-test suite passes.

33. ✅ **The whole admin panel froze solid while the offline assistant was
    generating a reply, not just the chat page.** Done. Real report:
    reproduced from a phone connected to the hotspot Wi-Fi, confirming it
    wasn't a same-tab/same-browser artifact.

    Root-caused from the real installed model's own config, not guessed:
    `assistant_phi4_mini/content/genai_config.json`'s
    `session_options.provider_options` is empty, so no CPU thread limit
    was ever set, and `core/llm_engine.py`'s `load()` called
    `og.Model(self._model_dir)` with no `Config` at all. ONNX Runtime's
    own documented default for an unset `intra_op_num_threads` is every
    logical core on the machine. The Flask server is already threaded
    (a request per OS thread - `main.py`'s `make_server(..., threaded=True)`),
    but a thread still needs real CPU time to run at all; with every core
    saturated by onnxruntime's own worker pool for the whole length of a
    reply, the OS scheduler had nothing left to give the admin panel's
    threads, whether or not the native call was also holding the GIL.

    Fixed in `core/llm_engine.py`: a new `_build_config()` loads the
    model's `Config`, overlays `intra_op_num_threads` capped to leave one
    core free (`max(1, os.cpu_count() - 1)`, so it scales correctly
    whether the school PC has 2 cores or 16), and `load()` now passes that
    `Config` to `og.Model()` instead of the bare directory path. Confirmed
    the `Config`/`overlay()` call sequence actually works against the real
    installed `onnxruntime_genai` 0.15.2 package and the real model's own
    config file, not just mocked - couldn't go further and load-test the
    full model end to end, since this machine had only ~2.5GB free RAM at
    the time against a 4.6GB model, and forcing that load risked
    destabilizing a machine already low on memory. New regression tests
    cover the thread-count math (including the `os.cpu_count() -> None`
    edge case) and that `load()` passes the `Config` object through to
    `og.Model()`, not the old raw path. 204-test suite passes.

34. ✅ **A full codebase security review found 10 real, confirmed bugs -
    two of them chaining into unauthenticated remote code execution as
    admin.** Done. Asked for a security and bug review of the whole
    codebase, not just a diff; ran 5 independent audits, personally
    re-verified every finding by reading the real current code, then
    fixed all 10.

    The two most serious, chained together: `/admin/setup/finish`
    (`core/blueprints/admin.py`) was permanently exempt from every auth
    check, not just during first-run, so anyone on the hotspot Wi-Fi
    could silently reset the admin password *and* the hotspot password
    with zero credentials - and that hotspot password then got
    f-string-interpolated unescaped into a PowerShell script
    (`core/hotspot.py`'s `_try_winrt`) run by this already-elevated app,
    so a password containing a single quote was PowerShell injection.
    Fixed by moving `setup`/`setup_finish` out of the permanent
    allow-list and into the first-run-only one (so they require a real
    session once setup is complete, exactly like every other admin
    route), and by escaping single quotes the way PowerShell's own
    single-quoted-string rules require (doubling them) before either the
    SSID or password reaches the script.

    Two path-traversal bugs, one of them unauthenticated: `get_pdf_reader`/
    `get_zim_reader`/`get_llm_engine`/`get_manifest`
    (`core/module_manager.py`) joined a URL path segment straight into a
    filesystem path with no check, reachable from the public, no-auth
    portal blueprint - on Windows, a single Flask route segment can
    legally contain literal backslashes (only "/" is a URL separator), so
    `GET /pdf/..\..\..\Users\name\Documents` resolved outside
    MODULES_DIR entirely. `/admin/modules/remove`'s `folder` form field
    had the same shape, admin-session-gated. Fixed with one shared
    `_resolve_module_dir()` helper that resolves the real path and
    refuses anything outside MODULES_DIR, used by all four getters, by
    `remove()` itself (which now takes a module name rather than a
    caller-built path), and backed by `modules_remove()` additionally
    checking `folder` against the real installed-module list before
    calling it.

    Two stored/reflected XSS holes, both from untrusted external text
    reaching `innerHTML` unescaped: a module's name/description
    (`templates/portal/index.html`, sourced from a "custom" Discover
    Content download whose title/summary come from the live Kiwix
    catalog feed) reached every student's browser on the public portal;
    Discover Content's own search results
    (`templates/admin/_download_panel.html`) reached the admin's own
    session the same way. A third, related bug in the same file: search
    results also built an `onclick='startCustom(${i}, ${JSON.stringify(item)})'`
    attribute by hand, and `JSON.stringify` escapes double quotes but not
    single ones, so a title containing `'` broke out of the
    single-quoted attribute independent of the `innerHTML` issue. Fixed
    with a small `escapeHTML()` helper (build a text node, read back its
    escaped `innerHTML` - the standard technique) applied everywhere
    untrusted text reaches the DOM, and by eliminating the two
    hand-built `onclick="..."` attributes entirely: the map-open button
    now carries its data via `data-*` attributes read by one delegated
    click listener, and the search-result download button looks its item
    up by index from an array instead of embedding it as inline JSON.

    No CSRF protection existed anywhere - confirmed by grepping the whole
    repo for `csrf`/`SameSite`/`WTF` and finding nothing. Fixed with a
    small session-bound token (no new dependency): every admin template's
    `<form>` now carries a hidden `csrf_token` field, and a short script
    in `base.html` attaches it as an `X-CSRF-Token` header to every
    non-GET `fetch()` call site-wide, so none of the many individual
    `fetch()` call sites across `_download_panel.html`/`modules.html`
    needed touching by hand. `modules_install`'s upload path also had its
    own independent traversal risk (an uploaded file's own filename
    wasn't sanitized before being joined onto tempdir) - fixed with
    Werkzeug's own `secure_filename()`.

    Two real concurrency/resource bugs, unrelated to auth: removing a map
    module never closed `TileServer`'s separately-cached sqlite
    connection first, so `rmtree()` hit a Windows `PermissionError` on a
    previously-viewed map's still-open file - the same failure class
    item 26/27 already fixed for a different code path, recurring here
    because `TileServer` keeps its own connection cache outside
    `ContentRegistry` entirely. Fixed with a new `TileServer.close()`
    that `modules_remove()` calls before removing. Separately,
    `get_llm_engine`'s check-existing/unload-previous/load-new sequence
    had no lock, so two threads requesting two different chat modules at
    once could both load a full multi-GB model concurrently, defeating
    the documented single-resident-model design. Fixed with a lock around
    the whole sequence.

    Every fix verified for real, not just read through: a genuine Windows
    file-lock test (rename a file immediately after `TileServer.close()`
    to prove nothing still holds it open); a real threaded-concurrency
    test proving `get_llm_engine` never loads two models at once; a real
    `Flask` app built via `core.app_factory.create_app()` and driven
    through `test_client()` (in-process, no real socket/subprocess)
    proving `/admin/setup/finish` is actually blocked post-setup, that a
    POST without the right CSRF token is actually rejected with 403 and
    one with it succeeds, and that `/admin/modules/remove` actually
    refuses a non-installed folder while still deleting a real one; the
    PowerShell escaping tested against the exact script string
    `_try_winrt()` builds; the JS syntax of both edited templates checked
    with `node --check` after stripping Jinja tags. Building this test
    coverage also surfaced and fixed a real, separate latent bug:
    `admin.py` imported `MODULES_DIR` by value at its own import time, so
    patching `core.module_manager.MODULES_DIR` in a test never reached
    `modules_remove()` - fixed by having `remove()` resolve the module
    path itself instead of the caller constructing one. 229-test suite
    passes (25 new tests).

---
