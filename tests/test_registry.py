from core.registry import ContentRegistry


def test_register_and_get_status():
    reg = ContentRegistry()
    reg.register("wikipedia_en_mini", "zim")
    assert reg.get_status("wikipedia_en_mini") == "loaded"


def test_unknown_module_status_is_unloaded():
    reg = ContentRegistry()
    assert reg.get_status("nope") == "unloaded"


def test_mark_error_on_registered_module():
    reg = ContentRegistry()
    reg.register("broken_map", "mbtiles")
    reg.mark_error("broken_map", "No .mbtiles file found in module folder.")
    assert reg.get_status("broken_map") == "error"


def test_mark_error_on_never_registered_module_still_records_it():
    # module_manager calls mark_error() directly when e.g. a mbtiles module
    # folder has no .mbtiles file, without ever calling register() first.
    reg = ContentRegistry()
    reg.mark_error("never_registered", "boom")
    assert reg.get_status("never_registered") == "error"


def test_get_handle_returns_none_for_unregistered():
    reg = ContentRegistry()
    assert reg.get_handle("nope") is None


def test_unload_calls_handle_close():
    closed = []

    class FakeHandle:
        def close(self):
            closed.append(True)

    reg = ContentRegistry()
    reg.register("assistant_phi4_mini", "llm", handle=FakeHandle())
    reg.unload("assistant_phi4_mini")

    assert closed == [True]
    assert reg.get_status("assistant_phi4_mini") == "unloaded"


def test_unload_survives_handle_with_no_close_method():
    reg = ContentRegistry()
    reg.register("map_uk", "mbtiles", handle=object())
    reg.unload("map_uk")  # must not raise
    assert reg.get_status("map_uk") == "unloaded"


def test_unload_survives_handle_close_raising():
    class BrokenHandle:
        def close(self):
            raise RuntimeError("already closed")

    reg = ContentRegistry()
    reg.register("x", "zim", handle=BrokenHandle())
    reg.unload("x")  # must not raise
    assert reg.get_status("x") == "unloaded"


def test_unload_all():
    reg = ContentRegistry()
    reg.register("a", "zim")
    reg.register("b", "mbtiles")
    reg.unload_all()
    assert reg.all_modules() == {}
