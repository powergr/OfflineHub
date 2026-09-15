"""
portal blueprint: public, LAN-facing routes. No authentication: this is
what students connect to over the hotspot. Serves ZIM content in-process
(no kiwix-serve subprocess), map tiles from mbtiles, and the LLM chat UI.
"""

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request, url_for

from core.retrieval import retrieve

bp = Blueprint("portal", __name__)


def _module_mgr():
    return current_app.config["MODULE_MGR"]


def _registry():
    return current_app.config["REGISTRY"]


def _tile_server():
    return current_app.config["TILE_SERVER"]


def _hotspot_mgr():
    return current_app.config["HOTSPOT_MGR"]


def _usage():
    return current_app.config["USAGE"]


# ── Home page ─────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("portal/index.html")


@bp.route("/api/modules")
def api_modules():
    module_mgr = _module_mgr()
    registry = _registry()
    tile_server = _tile_server()
    result = {}
    for folder, data in module_mgr.list_modules():
        status = registry.get_status(folder)
        entry = {
            "name":        data.get("name", folder),
            "emoji":       data.get("emoji", "📖"),
            "description": data.get("description", ""),
            "type":        data.get("type", "zim"),
            "status":      "error" if status == "error" else "ready",
            "format":      data.get("format", "raster"),
        }
        if entry["type"] == "mbtiles":
            meta = tile_server.metadata(folder)

            # Lets the frontend fitBounds() to wherever this map actually
            # covers, instead of guessing a center from the module name -
            # added after confirming any non-Cyprus/London map rendered as
            # a blank background (the default [10, 50] view sits outside
            # most curated extracts).
            bounds_str = meta.get("bounds", "")
            parts = bounds_str.split(",")
            if len(parts) == 4:
                try:
                    entry["bounds"] = [float(p) for p in parts]
                except ValueError:
                    pass

            # The .mbtiles file's own metadata table always carries a real
            # "format" ("pbf" for vector, "png"/"jpg"/"webp" for raster) per
            # the MBTiles spec - trust that over the manifest's stored value
            # when it's available. Confirmed live to matter: manual "Raw
            # file" installs (ModuleManager.install_from_raw_file) used to
            # guess vector-vs-raster from whether the filename happened to
            # contain the word "vector," which is wrong for most real
            # files, and the frontend then requested the wrong tile URL
            # (e.g. .png for actual vector/pbf data), rendering a
            # completely blank map with no error anywhere.
            mbtiles_format = meta.get("format")
            if mbtiles_format == "pbf":
                entry["format"] = "vector"
            elif mbtiles_format in ("png", "jpg", "jpeg", "webp"):
                entry["format"] = "raster"
        result[folder] = entry
    return jsonify(result)


@bp.route("/api/ip")
def api_ip():
    return jsonify({"ip": _hotspot_mgr().get_local_ip()})


@bp.route("/api/track-open/<module_id>", methods=["POST"])
def track_open(module_id):
    """
    Records one "opened" for aggregate usage visibility (plan.md Phase 4,
    item 15 - "which modules actually get opened, so a school knows what
    to download more of instead of guessing"). Maps have no server-side
    "entry page" route the way ZIM/chat modules do (they open as a client-
    side overlay straight from the home page), so the frontend calls this
    explicitly instead; content_index()/chat_page() below record their own
    opens directly since they ARE real page loads.
    """
    _usage().record_open(module_id)
    return ("", 204)


# ── ZIM content (replaces the old kiwix-serve subprocess) ────────────────────

@bp.route("/content/<module_id>/")
def content_index(module_id):
    try:
        reader = _module_mgr().get_zim_reader(module_id)
    except Exception:
        abort(404)
    main_path = reader.main_path()
    if main_path is None:
        abort(404)
    _usage().record_open(module_id)
    return redirect(url_for("portal.content_page", module_id=module_id, zim_path=main_path))


@bp.route("/content/<module_id>/_search")
def content_search(module_id):
    try:
        reader = _module_mgr().get_zim_reader(module_id)
    except Exception:
        abort(404)
    query = request.args.get("q", "")
    results = reader.search(query) if reader.has_search else []
    return render_template(
        "portal/search.html", module_id=module_id, query=query, results=results,
        has_search=reader.has_search,
    )


@bp.route("/content/<module_id>/<path:zim_path>")
def content_page(module_id, zim_path):
    try:
        reader = _module_mgr().get_zim_reader(module_id)
    except Exception:
        abort(404)

    target = reader.is_redirect(zim_path)
    if target is not None:
        return redirect(url_for("portal.content_page", module_id=module_id, zim_path=target))

    result = reader.resolve(zim_path)
    if result is None:
        abort(404)
    content, mimetype = result
    return Response(content, mimetype=mimetype)


# ── Map tiles (unchanged approach: read straight from the mbtiles sqlite file) ─

@bp.route("/tiles/<module>/<int:z>/<int:x>/<int:y>.png")
def tile_png(module, z, x, y):
    data = _tile_server().get_tile(module, z, x, y)
    if data is None:
        abort(404)
    return Response(data, mimetype="image/png")


@bp.route("/tiles/<module>/<int:z>/<int:x>/<int:y>.pbf")
def tile_pbf(module, z, x, y):
    data = _tile_server().get_tile(module, z, x, y)
    if data is None:
        abort(404)
    response = Response(data, mimetype="application/x-protobuf")
    if len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B:
        response.headers["Content-Encoding"] = "gzip"
    return response


# ── LLM chat ──────────────────────────────────────────────────────────────────

@bp.route("/chat/<module_id>")
def chat_page(module_id):
    manifest = _module_mgr().get_manifest(module_id)
    if manifest is None or manifest.get("type") != "llm":
        abort(404)
    _usage().record_open(module_id)
    return render_template("portal/chat.html", module_id=module_id, module=manifest)


@bp.route("/api/chat/<module_id>/stream", methods=["POST"])
def chat_stream(module_id):
    manifest = _module_mgr().get_manifest(module_id)
    if manifest is None or manifest.get("type") != "llm":
        abort(404)

    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        abort(400)

    # The browser sends back everything said so far in this chat so the
    # model actually has conversation memory (see core/llm_engine.py) -
    # sanitized here rather than trusted as-is, since it's still
    # client-supplied JSON reaching the model prompt.
    history = []
    for turn in (body.get("history") or []):
        if (
            isinstance(turn, dict)
            and turn.get("role") in ("user", "assistant")
            and isinstance(turn.get("content"), str)
            and turn["content"].strip()
        ):
            history.append({"role": turn["role"], "content": turn["content"]})

    try:
        engine = _module_mgr().get_llm_engine(module_id)
    except Exception as e:
        return Response(f"data: [error] {e}\n\n", mimetype="text/event-stream")

    # Retrieval-augmented grounding (plan.md Phase 4, item 14): search the
    # ZIM content already installed on this machine for passages relevant
    # to the question and hand them to the model as optional context, so
    # it can cite the actual encyclopedia instead of answering purely from
    # its own training data. Best-effort by design (retrieve() never
    # raises) - a search hiccup must degrade to "answered without
    # grounding," never break the chat reply outright.
    try:
        context = retrieve(prompt, _module_mgr(), _module_mgr().list_modules())
    except Exception:
        context = []

    def event_stream():
        try:
            for chunk in engine.generate_stream(prompt, history=history, context=context):
                escaped = chunk.replace("\n", "\\n")
                yield f"data: {escaped}\n\n"
        except Exception as e:
            yield f"data: [error] {e}\n\n"
        yield "event: done\ndata: end\n\n"

    return Response(event_stream(), mimetype="text/event-stream")
