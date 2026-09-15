"""
admin blueprint: password-gated web UI. Replaces both the old tkinter
first-run wizard and the tkinter admin panel with browser pages served from
the same Flask process as the public portal.

Setup and the ongoing "Modules" page share the exact same download
endpoints below (download_quickstart / download_search / download_custom).
Each POST request binds its own key/item/url as local variables scoped to
that single request+thread, which is what makes this safe for concurrent
downloads. That's unlike the old tkinter wizard, where several download
threads closed over one shared `for` loop's variables and clobbered each other.
"""

import json
import os
import tempfile
import threading
import time

from flask import (
    Blueprint, current_app, flash, jsonify, redirect,
    render_template, request, send_file, session, url_for,
)

from core.auth import generate_salt, hash_password, verify_password
from core.downloader import (
    CATALOGUE, LLM_CATALOGUE, MAPS_CATALOGUE, STARTER_BUNDLE_KEYS, CatalogueError,
    llm_download_plan, resolve_catalogue_entry, search_catalogue,
)
from core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, translate
from core.module_manager import MODULES_DIR
from core.version import get_version
from core import hotspot as hotspot_module

bp = Blueprint("admin", __name__)

_ALWAYS_OPEN = {"admin.login", "admin.setup", "admin.setup_finish"}
_SETUP_DOWNLOAD_ENDPOINTS = {
    "admin.download_quickstart", "admin.download_search",
    "admin.download_custom", "admin.download_llm", "admin.download_map",
    "admin.download_bundle", "admin.download_status",
}

_MAX_ATTEMPTS = 5
_LOCKOUT_WINDOW = 300  # seconds
_failed_logins: dict[str, list[float]] = {}
_login_lock = threading.Lock()


# ── Accessors ─────────────────────────────────────────────────────────────────

def _cfg():
    return current_app.config["APP_CONFIG"]


def _save_cfg(cfg):
    current_app.config["SAVE_CONFIG"](cfg)


def _module_mgr():
    return current_app.config["MODULE_MGR"]


def _registry():
    return current_app.config["REGISTRY"]


def _downloader():
    return current_app.config["DOWNLOADER"]


def _jobs():
    return current_app.config["JOBS"]


def _hotspot_mgr():
    return current_app.config["HOTSPOT_MGR"]


def _usage():
    return current_app.config["USAGE"]


def _t(key: str, **kwargs) -> str:
    """Python-side counterpart to the Jinja `t()` context-processor helper
    (core/app_factory.py) - for flash()/jsonify() messages built in route
    code, which never go through template rendering at all."""
    return translate(key, _cfg().get("language", DEFAULT_LANGUAGE), **kwargs)


# ── Session gate ──────────────────────────────────────────────────────────────

@bp.before_request
def _gate():
    if request.endpoint in _ALWAYS_OPEN:
        return None

    if _cfg().get("first_run", True):
        if request.endpoint in _SETUP_DOWNLOAD_ENDPOINTS:
            return None
        return redirect(url_for("admin.setup"))

    if not session.get("admin_authed"):
        return redirect(url_for("admin.login"))
    return None


# ── Index ─────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    """Bare '/admin' has no page of its own. Send visitors to whatever the
    _gate() before_request would otherwise land them on (setup/login/modules)."""
    return redirect(url_for("admin.modules"))


# ── Login / logout ────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if _is_locked_out(ip):
            return render_template("admin/login.html", error=_t("login.too_many_attempts"))
        password = request.form.get("password", "")
        cfg = _cfg()
        if verify_password(password, cfg.get("admin_password_hash", ""), cfg.get("admin_password_salt", "")):
            _clear_lockout(ip)
            session["admin_authed"] = True
            session.permanent = True
            return redirect(url_for("admin.modules"))
        _record_failure(ip)
        return render_template("admin/login.html", error=_t("login.incorrect_password"))
    return render_template("admin/login.html", error=None)


@bp.route("/logout")
def logout():
    session.pop("admin_authed", None)
    return redirect(url_for("portal.index"))


def _is_locked_out(ip: str) -> bool:
    with _login_lock:
        attempts = [t for t in _failed_logins.get(ip, []) if time.time() - t < _LOCKOUT_WINDOW]
        _failed_logins[ip] = attempts
        return len(attempts) >= _MAX_ATTEMPTS


def _record_failure(ip: str):
    with _login_lock:
        _failed_logins.setdefault(ip, []).append(time.time())


def _clear_lockout(ip: str):
    with _login_lock:
        _failed_logins.pop(ip, None)


# ── First-run setup ───────────────────────────────────────────────────────────

@bp.route("/setup")
def setup():
    from core.downloader import refresh_catalogue

    try:
        quickstart = refresh_catalogue()
    except Exception:
        quickstart = {}
    installed_keys = {folder for folder, _ in _module_mgr().list_modules()}
    bundle_remaining = [k for k in STARTER_BUNDLE_KEYS if k not in installed_keys]
    return render_template(
        "admin/setup.html", config=_cfg(), quickstart=quickstart,
        llm_catalogue=LLM_CATALOGUE, maps_catalogue=MAPS_CATALOGUE,
        installed_keys=installed_keys,
        bundle_remaining=bundle_remaining,
        bundle_total=len(STARTER_BUNDLE_KEYS),
        bundle_size=sum(quickstart.get(k, {}).get("size", 0) or 0 for k in bundle_remaining),
    )


@bp.route("/setup/finish", methods=["POST"])
def setup_finish():
    cfg = _cfg()
    cfg["hotspot"]["ssid"] = request.form.get("ssid", "OfflineHub").strip() or "OfflineHub"
    cfg["hotspot"]["password"] = request.form.get("hotspot_password", "")

    p1 = request.form.get("admin_password", "")
    p2 = request.form.get("admin_password_confirm", "")
    if len(p1) < 6:
        flash(_t("flash.password_too_short"), "error")
        return redirect(url_for("admin.setup"))
    if p1 != p2:
        flash(_t("flash.passwords_dont_match"), "error")
        return redirect(url_for("admin.setup"))
    cfg["admin_password_salt"] = generate_salt()
    cfg["admin_password_hash"] = hash_password(p1, cfg["admin_password_salt"])

    cfg["first_run"] = False
    _save_cfg(cfg)
    session["admin_authed"] = True
    flash(_t("flash.setup_complete"), "success")
    return redirect(url_for("admin.modules"))


# ── Modules ───────────────────────────────────────────────────────────────────

@bp.route("/modules")
def modules():
    from core.downloader import refresh_catalogue

    module_mgr = _module_mgr()
    registry = _registry()
    installed = [
        (folder, data, registry.get_status(folder))
        for folder, data in module_mgr.list_modules()
    ]
    try:
        quickstart = refresh_catalogue()
    except Exception:
        quickstart = {}
    installed_keys = {folder for folder, _ in module_mgr.list_modules()}
    bundle_remaining = [k for k in STARTER_BUNDLE_KEYS if k not in installed_keys]
    return render_template(
        "admin/modules.html", installed=installed, quickstart=quickstart,
        llm_catalogue=LLM_CATALOGUE, maps_catalogue=MAPS_CATALOGUE,
        installed_keys=installed_keys,
        bundle_remaining=bundle_remaining,
        bundle_total=len(STARTER_BUNDLE_KEYS),
        bundle_size=sum(quickstart.get(k, {}).get("size", 0) or 0 for k in bundle_remaining),
        content_updates=_stale_content_keys(installed, quickstart),
        usage_counts=_usage().get_counts(),
    )


def _stale_content_keys(installed, quickstart) -> set[str]:
    """
    Which installed modules have a newer snapshot available at their
    original source, compared against the manifest's own recorded
    "source_url" (see ModuleManager.install_from_download) - a ZIM's
    filename encodes its build date, so a changed URL means Kiwix has
    since published a newer one. Manual/zip installs have no "source_url"
    at all (nothing to compare against) and are silently skipped, not
    flagged. ZIM comparisons only count when `quickstart[folder]["live"]`
    is True - a failed live lookup falling back to the last-known-good
    static URL must never be mistaken for "content is stale," since that
    static URL can differ from what's installed for reasons having nothing
    to do with a real newer release existing.
    """
    stale = set()
    for folder, data, _status in installed:
        source_url = data.get("source_url")
        if not source_url:
            continue
        if data.get("type") == "zim":
            entry = quickstart.get(folder)
            if entry and entry.get("live") and entry.get("url") and entry["url"] != source_url:
                stale.add(folder)
        elif data.get("type") == "mbtiles":
            entry = MAPS_CATALOGUE.get(folder)
            if entry and entry.get("url") and entry["url"] != source_url:
                stale.add(folder)
    return stale


@bp.route("/modules/install", methods=["POST"])
def modules_install():
    module_mgr = _module_mgr()
    filepath = request.form.get("filepath", "").strip()
    upload = request.files.get("file")

    try:
        if upload and upload.filename:
            target = os.path.join(tempfile.gettempdir(), upload.filename)
            upload.save(target)
        elif filepath:
            if not os.path.isfile(filepath):
                raise FileNotFoundError(_t("flash.file_not_found", path=filepath))
            target = filepath
        else:
            raise ValueError(_t("flash.provide_file_or_upload"))

        if target.lower().endswith(".zip"):
            module_mgr.install_from_zip(target)
        else:
            module_mgr.install_from_raw_file(target)
        flash(_t("flash.module_installed"), "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("admin.modules"))


@bp.route("/modules/remove", methods=["POST"])
def modules_remove():
    folder = request.form.get("folder", "")
    path = os.path.join(MODULES_DIR, folder)
    if os.path.isdir(path):
        _module_mgr().remove(path)
        _usage().forget(folder)
        flash(_t("flash.removed", name=folder), "success")
    return redirect(url_for("admin.modules"))


# ── Downloads (shared by /admin/setup and /admin/modules) ───────────────────

@bp.route("/downloads/quickstart", methods=["POST"])
def download_quickstart():
    key = request.form.get("key") or (request.get_json(silent=True) or {}).get("key")
    if key not in CATALOGUE:
        return jsonify({"error": _t("flash.unknown_catalogue_key")}), 404
    if _is_installed(key):
        return jsonify({"error": _t("flash.already_installed", name=key)}), 409

    item = dict(CATALOGUE[key])
    try:
        live = resolve_catalogue_entry(
            item["opds_name"], item.get("opds_flavour"), lang=item.get("lang", "eng")
        )
    except CatalogueError as e:
        return jsonify({"error": str(e)}), 502

    item["url"] = live["url"]
    from core.downloader import DOWNLOAD_DIR
    dest = os.path.join(DOWNLOAD_DIR, f"{key}.zim")

    jobs = _jobs()
    job_id = jobs.new_job()
    module_mgr = _module_mgr()

    def on_success(path):
        module_mgr.install_from_download(key, item, path)

    threading.Thread(
        target=_downloader().download,
        args=(item["url"], dest, jobs.progress_cb(job_id), jobs.done_cb(job_id, on_success)),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@bp.route("/downloads/bundle", methods=["POST"])
def download_bundle():
    """
    Installs STARTER_BUNDLE_KEYS as one action instead of making a new
    admin evaluate all six Quick Start cards individually on day one.
    Downloads/installs each not-already-installed item one at a time
    (reusing Downloader.download() synchronously inside this background
    thread, the same call a single-item download wraps in its own thread)
    so one job tracks combined progress across the whole bundle.
    """
    keys = [k for k in STARTER_BUNDLE_KEYS if not _is_installed(k)]
    if not keys:
        return jsonify({"error": _t("flash.bundle_already_installed")}), 409

    resolved = []
    for key in keys:
        item = dict(CATALOGUE[key])
        try:
            live = resolve_catalogue_entry(
                item["opds_name"], item.get("opds_flavour"), lang=item.get("lang", "eng")
            )
        except CatalogueError as e:
            return jsonify({"error": _t("flash.could_not_resolve", name=item["name"], error=str(e))}), 502
        item["url"] = live["url"]
        resolved.append((key, item))

    from core.downloader import DOWNLOAD_DIR

    jobs = _jobs()
    job_id = jobs.new_job()
    module_mgr = _module_mgr()
    downloader = _downloader()
    # Captured here, in the request's own Flask app context, and passed
    # into the background thread as a plain value - current_app (which
    # _t() reads) isn't available once this request finishes, and the
    # thread easily outlives it (a bundle download can run for minutes).
    lang = _cfg().get("language", DEFAULT_LANGUAGE)

    def run():
        total = len(resolved)
        for i, (key, item) in enumerate(resolved):
            dest = os.path.join(DOWNLOAD_DIR, f"{key}.zim")
            outcome = {}

            def progress_cb(pct, speed, i=i):
                overall = (i + pct / 100) / total * 100
                jobs.progress_cb(job_id)(overall, speed)

            def done_cb(success, path, error=None):
                outcome["success"] = success
                outcome["error"] = error

            downloader.download(item["url"], dest, progress_cb, done_cb)

            if not outcome.get("success"):
                fallback = translate("flash.failed_to_download", lang, name=item["name"])
                jobs.done_cb(job_id)(False, "", outcome.get("error") or fallback)
                return
            try:
                module_mgr.install_from_download(key, item, dest)
            except Exception as e:
                jobs.done_cb(job_id)(False, "", str(e))
                return

        jobs.done_cb(job_id)(True, "")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id, "count": len(keys)})


@bp.route("/downloads/update", methods=["POST"])
def download_update():
    """
    Re-downloads an already-installed CATALOGUE/MAPS_CATALOGUE module from
    its current source and replaces the install in place - the "fetch it"
    half of content-refresh visibility (_stale_content_keys() in modules()
    is the "know a newer version exists" half). Only meaningful for modules
    that were themselves installed from one of those catalogues in the
    first place (manual/zip installs have no catalogue entry to re-fetch
    from), enforced by requiring the manifest's own type to match a real
    catalogue lookup rather than trusting the client-supplied key alone.
    """
    key = request.form.get("key") or (request.get_json(silent=True) or {}).get("key")
    manifest = _module_mgr().get_manifest(key) if key else None
    if manifest is None:
        return jsonify({"error": _t("flash.unknown_module")}), 404

    mod_type = manifest.get("type")
    from core.downloader import DOWNLOAD_DIR
    module_mgr = _module_mgr()

    if mod_type == "zim":
        if key not in CATALOGUE:
            return jsonify({"error": _t("flash.no_quickstart_entry", key=key)}), 400
        item = dict(CATALOGUE[key])
        try:
            live = resolve_catalogue_entry(
                item["opds_name"], item.get("opds_flavour"), lang=item.get("lang", "eng")
            )
        except CatalogueError as e:
            return jsonify({"error": str(e)}), 502
        item["url"] = live["url"]
        dest = os.path.join(DOWNLOAD_DIR, f"{key}.zim")
        install_fn = module_mgr.install_from_download
    elif mod_type == "mbtiles":
        if key not in MAPS_CATALOGUE:
            return jsonify({"error": _t("flash.no_maps_entry", key=key)}), 400
        item = dict(MAPS_CATALOGUE[key])
        dest = os.path.join(DOWNLOAD_DIR, f"{key}.mbtiles")
        install_fn = module_mgr.install_map_from_download
    else:
        return jsonify({"error": _t("flash.cant_update_type", type=mod_type)}), 400

    jobs = _jobs()
    job_id = jobs.new_job()

    def on_success(path):
        install_fn(key, item, path, replace=True)

    threading.Thread(
        target=_downloader().download,
        args=(item["url"], dest, jobs.progress_cb(job_id), jobs.done_cb(job_id, on_success)),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@bp.route("/downloads/search", methods=["POST"])
def download_search():
    body = request.get_json(force=True, silent=True) or {}
    query = (body.get("q") or "").strip()
    if not query:
        return jsonify({"results": []})
    try:
        results = search_catalogue(query, count=20)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"results": results})


@bp.route("/downloads/custom", methods=["POST"])
def download_custom():
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("name") or _t("flash.custom_content_default")).strip()
    url = body.get("url")
    if not url:
        return jsonify({"error": _t("flash.missing_url")}), 400

    key = _slugify(name)
    if _is_installed(key):
        return jsonify({"error": _t("flash.already_installed", name=name)}), 409

    from core.downloader import DOWNLOAD_DIR
    dest = os.path.join(DOWNLOAD_DIR, f"{key}.zim")
    item = {"name": name, "emoji": "📚", "description": body.get("summary", "")}

    jobs = _jobs()
    job_id = jobs.new_job()
    module_mgr = _module_mgr()

    def on_success(path):
        module_mgr.install_from_download(key, item, path)

    threading.Thread(
        target=_downloader().download,
        args=(url, dest, jobs.progress_cb(job_id), jobs.done_cb(job_id, on_success)),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id, "key": key})


@bp.route("/downloads/llm", methods=["POST"])
def download_llm():
    key = request.form.get("key") or (request.get_json(silent=True) or {}).get("key")
    if key not in LLM_CATALOGUE:
        return jsonify({"error": _t("flash.unknown_llm_key")}), 404
    if _is_installed(key):
        return jsonify({"error": _t("flash.already_installed", name=key)}), 409

    item = dict(LLM_CATALOGUE[key])
    files, dest_dir = llm_download_plan(key)

    jobs = _jobs()
    job_id = jobs.new_job()
    module_mgr = _module_mgr()

    def on_success(path):
        module_mgr.install_llm_from_download(key, item, path)

    threading.Thread(
        target=_downloader().download_set,
        args=(files, dest_dir, jobs.progress_cb(job_id), jobs.done_cb(job_id, on_success)),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@bp.route("/downloads/map", methods=["POST"])
def download_map():
    key = request.form.get("key") or (request.get_json(silent=True) or {}).get("key")
    if key not in MAPS_CATALOGUE:
        return jsonify({"error": _t("flash.unknown_map_key")}), 404
    if _is_installed(key):
        return jsonify({"error": _t("flash.already_installed", name=key)}), 409

    item = dict(MAPS_CATALOGUE[key])
    from core.downloader import DOWNLOAD_DIR
    dest = os.path.join(DOWNLOAD_DIR, f"{key}.mbtiles")

    jobs = _jobs()
    job_id = jobs.new_job()
    module_mgr = _module_mgr()

    def on_success(path):
        module_mgr.install_map_from_download(key, item, path)

    threading.Thread(
        target=_downloader().download,
        args=(item["url"], dest, jobs.progress_cb(job_id), jobs.done_cb(job_id, on_success)),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@bp.route("/downloads/countries")
def download_countries():
    """
    The bundled country list (core/data/country_bboxes.json) plus each
    entry's computed maxzoom/tile_count/estimated size - all pure math, no
    network I/O, so this is cheap on every call and needs no caching of its
    own. The frontend fetches this once and filters it client-side (the
    whole list is ~20KB), unlike the ZIM "Discover" search which hits a
    live API per query.
    """
    from core.map_extract import estimate_size_mb, load_countries, pick_maxzoom

    installed = {folder for folder, _ in _module_mgr().list_modules()}
    countries = []
    for iso, (name, bbox) in load_countries().items():
        maxzoom, tile_count = pick_maxzoom(bbox)
        countries.append({
            "iso": iso,
            "name": name,
            "maxzoom": maxzoom,
            "tile_count": tile_count,
            "est_size_mb": round(estimate_size_mb(tile_count)),
            "installed": f"country_{iso.lower()}" in installed,
        })
    return jsonify({"countries": countries})


@bp.route("/downloads/map_country", methods=["POST"])
def download_map_country():
    """
    Self-serve country map download: extracts the requested country's
    tiles live from Protomaps' daily build (core/map_extract.py) straight
    into a local .mbtiles file, in a background thread reporting progress
    through the same JobTracker/pollJob() pattern every other download in
    this file already uses - see download_quickstart above for the
    reference shape this follows.
    """
    from core.map_extract import extract_country, load_countries

    iso = request.form.get("iso") or (request.get_json(silent=True) or {}).get("iso")
    countries = load_countries()
    if iso not in countries:
        return jsonify({"error": _t("flash.unknown_country")}), 404
    key = f"country_{iso.lower()}"
    if _is_installed(key):
        return jsonify({"error": _t("flash.already_installed", name=key)}), 409

    name, _bbox = countries[iso]
    from core.downloader import DOWNLOAD_DIR
    dest = os.path.join(DOWNLOAD_DIR, f"{key}.mbtiles")

    jobs = _jobs()
    job_id = jobs.new_job()
    module_mgr = _module_mgr()

    def on_success(path):
        module_mgr.install_extracted_map(iso, name, path)

    # extract_country() doesn't share Downloader.download()'s (url, dest,
    # progress_cb, done_cb) signature - it returns a result dict on success
    # instead of calling a done_cb - so it's wrapped here rather than
    # passed straight to Thread like the other download routes.
    def run():
        try:
            extract_country(iso, dest, jobs.progress_cb(job_id))
        except Exception as e:
            jobs.done_cb(job_id)(False, "", str(e))
            return
        jobs.done_cb(job_id, on_success)(True, dest)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@bp.route("/downloads/<job_id>/status")
def download_status(job_id):
    job = _jobs().get(job_id)
    if job is None:
        return jsonify({"error": _t("flash.unknown_job")}), 404
    return jsonify(job)


# ── Hotspot ───────────────────────────────────────────────────────────────────

@bp.route("/hotspot", methods=["GET", "POST"])
def hotspot():
    cfg = _cfg()
    if request.method == "POST":
        cfg["hotspot"]["ssid"] = request.form.get("ssid", "")
        cfg["hotspot"]["password"] = request.form.get("password", "")
        _save_cfg(cfg)
        flash(_t("flash.hotspot_saved"), "success")
        return redirect(url_for("admin.hotspot"))

    mgr = _hotspot_mgr()
    return render_template(
        "admin/hotspot.html", config=cfg,
        running=mgr.is_running(), ip=mgr.get_local_ip(),
        is_admin=hotspot_module.is_admin(),
    )


@bp.route("/hotspot/toggle", methods=["POST"])
def hotspot_toggle():
    cfg = _cfg()
    mgr = _hotspot_mgr()
    if mgr.is_running():
        mgr.stop()
        cfg["hotspot"]["enabled"] = False
    else:
        ok, msg = mgr.start()
        cfg["hotspot"]["enabled"] = ok
        if not ok:
            flash(msg, "error")
    _save_cfg(cfg)
    return redirect(url_for("admin.hotspot"))


@bp.route("/hotspot/devices")
def hotspot_devices():
    return jsonify({"devices": _hotspot_mgr().list_connected_devices()})


# ── Services ──────────────────────────────────────────────────────────────────

@bp.route("/services")
def services():
    module_mgr = _module_mgr()
    registry = _registry()
    items = [
        (folder, data, registry.get_status(folder))
        for folder, data in module_mgr.list_modules()
    ]
    return render_template("admin/services.html", modules=items)


@bp.route("/services/unload", methods=["POST"])
def services_unload():
    folder = request.form.get("folder", "")
    _registry().unload(folder)
    flash(_t("flash.unloaded", name=folder), "success")
    return redirect(url_for("admin.services"))


# ── Help ──────────────────────────────────────────────────────────────────────

@bp.route("/help")
def help_page():
    return render_template("admin/help.html")


# ── Settings ──────────────────────────────────────────────────────────────────

@bp.route("/settings", methods=["GET", "POST"])
def settings():
    cfg = _cfg()
    if request.method == "POST":
        try:
            cfg["portal_port"] = int(request.form.get("portal_port", 8000))
        except ValueError:
            flash(_t("flash.port_not_a_number"), "error")
            return redirect(url_for("admin.settings"))

        cfg["autostart"] = "autostart" in request.form
        if cfg["autostart"]:
            _register_autostart()

        language = request.form.get("language")
        if language in SUPPORTED_LANGUAGES:
            cfg["language"] = language

        p1 = request.form.get("new_password", "")
        p2 = request.form.get("confirm_password", "")
        if p1 or p2:
            if p1 != p2:
                flash(_t("flash.passwords_dont_match"), "error")
                return redirect(url_for("admin.settings"))
            if len(p1) < 6:
                flash(_t("flash.password_too_short"), "error")
                return redirect(url_for("admin.settings"))
            cfg["admin_password_salt"] = generate_salt()
            cfg["admin_password_hash"] = hash_password(p1, cfg["admin_password_salt"])

        _save_cfg(cfg)
        flash(_t("flash.settings_saved"), "success")
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", config=cfg)


@bp.route("/diagnostics/export")
def diagnostics_export():
    """Zips the log file(s), config.json (password hash/salt/secret_key
    redacted - nothing else in it is sensitive), and the installed-module
    list into one file a non-technical admin can email or hand to whoever's
    helping them, without needing to find C:\\OfflineHub themselves."""
    import io
    import zipfile
    from datetime import datetime

    from core.logging_setup import LOG_DIR

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.isdir(LOG_DIR):
            for fname in os.listdir(LOG_DIR):
                fpath = os.path.join(LOG_DIR, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, arcname=f"logs/{fname}")

        cfg = dict(_cfg())
        for secret_field in ("admin_password_hash", "admin_password_salt", "secret_key"):
            if secret_field in cfg:
                cfg[secret_field] = "[redacted]"
        if isinstance(cfg.get("hotspot"), dict):
            cfg["hotspot"] = dict(cfg["hotspot"])
            cfg["hotspot"]["password"] = "[redacted]"
        zf.writestr("config.json", json.dumps(cfg, indent=2))

        module_mgr = _module_mgr()
        registry = _registry()
        modules_info = [
            {
                "folder": folder,
                "name": data.get("name", folder),
                "type": data.get("type"),
                "status": registry.get_status(folder),
            }
            for folder, data in module_mgr.list_modules()
        ]
        zf.writestr("installed_modules.json", json.dumps(modules_info, indent=2))
        zf.writestr("app_version.txt", get_version())

    buf.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"offlinehub_diagnostics_{timestamp}.zip",
    )


# ── Update check ──────────────────────────────────────────────────────────────

@bp.route("/updates/check")
def updates_check():
    from core.update_check import check_for_update

    update = check_for_update(get_version())
    if update:
        return jsonify({"available": True, **update})
    return jsonify({"available": False})


def _register_autostart():
    import sys
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "OfflineHub", 0, winreg.REG_SZ, sys.executable)
        winreg.CloseKey(key)
    except Exception as e:
        flash(_t("flash.autostart_failed", error=str(e)), "error")


# ── Utility ───────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in name).strip()
    return safe.replace(" ", "_").lower() or "custom_module"


def _is_installed(key: str) -> bool:
    return os.path.isdir(os.path.join(MODULES_DIR, key))
