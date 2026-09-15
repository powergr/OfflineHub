"""
Tests retrieve() against a fake ModuleManager/ZimReader, so the retrieval
fan-out/aggregation/error-isolation logic is verified without needing a
real .zim file or libzim.
"""

from core.retrieval import MAX_RESULTS_PER_MODULE, MAX_TOTAL_RESULTS, retrieve


class FakeReader:
    def __init__(self, has_search=True, hits=None, snippets=None, search_raises=False):
        self.has_search = has_search
        self._hits = hits or []
        self._snippets = snippets or {}
        self._search_raises = search_raises

    def search(self, query, count):
        if self._search_raises:
            raise RuntimeError("search index corrupted")
        return self._hits[:count]

    def get_text_snippet(self, path, max_chars=500):
        return self._snippets.get(path, "")


class FakeModuleManager:
    def __init__(self, readers: dict[str, FakeReader]):
        self._readers = readers

    def get_zim_reader(self, folder):
        if folder not in self._readers:
            raise FileNotFoundError(folder)
        return self._readers[folder]


def test_retrieves_from_a_single_searchable_module():
    reader = FakeReader(hits=[("Photosynthesis", "A/Photosynthesis")],
                         snippets={"A/Photosynthesis": "Photosynthesis is the process..."})
    mgr = FakeModuleManager({"wikipedia_en_mini": reader})
    installed = [("wikipedia_en_mini", {"type": "zim", "name": "Wikipedia (English, Mini)"})]

    results = retrieve("photosynthesis", mgr, installed)

    assert len(results) == 1
    assert results[0]["title"] == "Photosynthesis"
    assert results[0]["module_name"] == "Wikipedia (English, Mini)"
    assert "process" in results[0]["snippet"]


def test_non_zim_modules_are_skipped():
    mgr = FakeModuleManager({})
    installed = [("assistant_phi3_mini", {"type": "llm", "name": "Offline Assistant"}),
                 ("map_uk", {"type": "mbtiles", "name": "Map: UK"})]
    assert retrieve("anything", mgr, installed) == []


def test_modules_without_search_index_are_skipped():
    reader = FakeReader(has_search=False, hits=[("X", "A/X")])
    mgr = FakeModuleManager({"phet": reader})
    installed = [("phet", {"type": "zim", "name": "PhET"})]
    assert retrieve("anything", mgr, installed) == []


def test_fans_out_across_multiple_modules_and_caps_total_results():
    modules = {}
    installed = []
    for i in range(MAX_TOTAL_RESULTS + 2):
        key = f"module_{i}"
        reader = FakeReader(
            hits=[(f"Title {i}", f"A/{i}")],
            snippets={f"A/{i}": f"volcano snippet content {i}"},
        )
        modules[key] = reader
        installed.append((key, {"type": "zim", "name": key}))

    mgr = FakeModuleManager(modules)
    results = retrieve("tell me about volcanoes", mgr, installed)  # plural - exercises prefix matching
    assert len(results) == MAX_TOTAL_RESULTS


def test_caps_results_per_module():
    hits = [(f"Volcano Title {i}", f"A/{i}") for i in range(10)]
    snippets = {f"A/{i}": f"volcano snippet {i}" for i in range(10)}
    reader = FakeReader(hits=hits, snippets=snippets)
    mgr = FakeModuleManager({"wikipedia": reader})
    installed = [("wikipedia", {"type": "zim", "name": "Wikipedia"})]

    results = retrieve("what is a volcano", mgr, installed)
    assert len(results) == MAX_RESULTS_PER_MODULE


def test_hits_with_empty_snippet_are_dropped():
    reader = FakeReader(hits=[("Volcano", "A/Volcano")], snippets={})  # snippet lookup returns ""
    mgr = FakeModuleManager({"wikipedia": reader})
    installed = [("wikipedia", {"type": "zim", "name": "Wikipedia"})]
    assert retrieve("volcano", mgr, installed) == []


def test_module_that_fails_to_open_is_skipped_not_raised():
    installed = [("broken_module", {"type": "zim", "name": "Broken"})]
    mgr = FakeModuleManager({})  # get_zim_reader raises FileNotFoundError for unknown folders
    assert retrieve("volcano", mgr, installed) == []


def test_module_whose_search_raises_is_skipped_not_raised():
    reader = FakeReader(hits=[("Volcano", "A/Volcano")], search_raises=True)
    mgr = FakeModuleManager({"flaky": reader})
    installed = [("flaky", {"type": "zim", "name": "Flaky"})]
    assert retrieve("volcano", mgr, installed) == []


def test_a_broken_module_does_not_block_results_from_a_working_one():
    good_reader = FakeReader(hits=[("Volcano", "A/Volcano")], snippets={"A/Volcano": "volcano content"})
    installed = [
        ("broken", {"type": "zim", "name": "Broken"}),
        ("good", {"type": "zim", "name": "Good Module"}),
    ]
    mgr = FakeModuleManager({"good": good_reader})  # "broken" intentionally missing
    results = retrieve("volcano", mgr, installed)
    assert len(results) == 1
    assert results[0]["title"] == "Volcano"


def test_empty_installed_list_returns_empty():
    mgr = FakeModuleManager({})
    assert retrieve("volcano", mgr, []) == []


# ── relevance filtering ──────────────────────────────────────────────────────
# Regression tests for a real failure caught live: "Hi! How are you today?"
# returned "Norwegian language" and "Portuguese language" as libzim's top
# search hits (fuzzy/stemmed matching on generic words), and the model then
# echoed that irrelevant context straight into its reply.

def test_irrelevant_hit_with_no_shared_keywords_is_filtered_out():
    reader = FakeReader(
        hits=[("Norwegian language", "A/Norwegian_language")],
        snippets={"A/Norwegian_language": "Norwegian is an official language of Norway."},
    )
    mgr = FakeModuleManager({"vikidia_en": reader})
    installed = [("vikidia_en", {"type": "zim", "name": "Vikidia"})]

    assert retrieve("Hi! How are you today?", mgr, installed) == []


def test_relevant_hit_with_shared_keyword_is_kept():
    reader = FakeReader(
        hits=[("Volcano", "A/Volcano")],
        snippets={"A/Volcano": "A volcano is an opening in the Earth's crust."},
    )
    mgr = FakeModuleManager({"vikidia_en": reader})
    installed = [("vikidia_en", {"type": "zim", "name": "Vikidia"})]

    results = retrieve("What is a volcano?", mgr, installed)
    assert len(results) == 1
    assert results[0]["title"] == "Volcano"


def test_query_with_only_stopwords_retrieves_nothing():
    """A greeting like "Hi! How are you today?" has no real content words
    at all once stopwords are removed - must short-circuit to no
    retrieval rather than searching with an effectively-empty query."""
    reader = FakeReader(hits=[("Anything", "A/Anything")], snippets={"A/Anything": "some content"})
    mgr = FakeModuleManager({"vikidia_en": reader})
    installed = [("vikidia_en", {"type": "zim", "name": "Vikidia"})]

    assert retrieve("Hi! How are you today?", mgr, installed) == []


def test_plural_query_matches_singular_content_via_prefix():
    """No real stemmer - "volcanoes" (query) must still match "volcano"
    (content) via prefix matching, the case that motivated it."""
    reader = FakeReader(
        hits=[("Volcano", "A/Volcano")],
        snippets={"A/Volcano": "A volcano is an opening in the Earth's crust."},
    )
    mgr = FakeModuleManager({"vikidia_en": reader})
    installed = [("vikidia_en", {"type": "zim", "name": "Vikidia"})]

    results = retrieve("tell me about volcanoes", mgr, installed)
    assert len(results) == 1


def test_short_haystack_word_does_not_cause_false_positive_via_prefix():
    """A short common word in the snippet (e.g. "a", "in") must not
    satisfy term.startswith(word) for an unrelated query term just
    because the term happens to start with those same two letters."""
    reader = FakeReader(
        hits=[("Norwegian language", "A/Norwegian_language")],
        # Contains short words "a", "an", "in" but nothing about volcanoes.
        # "volcano" happens to start with "vo", but no 3+ char haystack
        # word here is a prefix of "volcano" or vice versa.
        snippets={"A/Norwegian_language": "Norwegian is an official language of Norway."},
    )
    mgr = FakeModuleManager({"vikidia_en": reader})
    installed = [("vikidia_en", {"type": "zim", "name": "Vikidia"})]

    assert retrieve("what is a volcano", mgr, installed) == []


def test_relevance_checked_against_snippet_too_not_only_title():
    """A generic title (e.g. "Portal:Geology") wouldn't share words with
    most queries, but a real matching term inside the snippet body must
    still count."""
    reader = FakeReader(
        hits=[("Portal:Geology", "A/Portal")],
        snippets={"A/Portal": "This portal covers volcanoes and earthquakes."},
    )
    mgr = FakeModuleManager({"vikidia_en": reader})
    installed = [("vikidia_en", {"type": "zim", "name": "Vikidia"})]

    results = retrieve("what causes volcanoes", mgr, installed)
    assert len(results) == 1
