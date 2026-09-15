"""
retrieval: naive RAG. Before asking the LLM to answer, search installed
ZIM content (Wikipedia, Gutenberg, etc.) for passages relevant to the
student's question. Hand the model real excerpts to ground its answer in,
instead of answering purely from its own training data. This is the one
thing that makes the offline assistant meaningfully different from a
"generic offline chatbot" (plan.md Phase 4, item 14). It can actually cite
the encyclopedia sitting right next to it.

Deliberately simple: no embeddings, no vector index. Each installed ZIM
already ships its own full-text search index (Xapian under libzim). This
just fans the student's question out across every installed ZIM with
has_search=True and keeps the top few hits.

A plain keyword-overlap relevance filter is applied on top of libzim's own
ranking. This was confirmed necessary live, not a theoretical worry:
"Hi! How are you today?" against a real installed Vikidia returned
"Norwegian language" and "Portuguese language" as top hits. Xapian's
fuzzy/stemmed matching on common words like "how"/"you" pulls in genuinely
unrelated articles. The small local model then echoed that irrelevant
context straight into its visible reply, instead of just ignoring it as
the system prompt asked. A weak instruction-following model can't be
trusted alone to filter noise. So this filters at the retrieval layer
instead: a result only survives if at least one non-trivial query word
literally appears in its title or snippet. libzim's Search object doesn't
expose per-result relevance scores to threshold on directly, which is why
this is a word-overlap check rather than a score cutoff.
"""

import logging
import re

logger = logging.getLogger(__name__)

MAX_RESULTS_PER_MODULE = 2
MAX_TOTAL_RESULTS = 4
SNIPPET_CHARS = 500

# Common words that carry no topical meaning on their own - excluded so a
# query like "Hi! How are you today?" doesn't count "how"/"you"/"today" as
# real search terms that could coincidentally appear in an unrelated
# article and pass the relevance filter.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "am", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "yours", "ours", "theirs",
    "what", "who", "whom", "when", "where", "why", "how", "which", "whose",
    "do", "does", "did", "can", "could", "would", "should", "will", "shall", "may", "might",
    "and", "or", "but", "if", "so", "to", "of", "in", "on", "at", "for", "with",
    "about", "as", "by", "from", "this", "that", "these", "those", "there", "here",
    "hi", "hey", "hello", "thanks", "thank", "please", "ok", "okay", "yes", "no",
    "today", "now", "just", "get", "got", "like", "want", "know", "tell", "have", "has", "had",
}
_WORD_RE = re.compile(r"[a-zA-Z]+")


def _significant_terms(query: str) -> set[str]:
    words = _WORD_RE.findall(query.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _is_relevant(query_terms: set[str], title: str, snippet: str) -> bool:
    """
    A result only counts if at least one real query word shares a prefix
    with a word in its title or snippet - see the module docstring for the
    real "Norwegian language" false-positive this was written to catch.
    Prefix matching (not exact-word matching) on purpose: a plain "word in
    haystack" substring check missed "volcano" (content) against a
    "volcanoes" (query) plural during testing - no real stemming library,
    but startswith() in both directions catches plurals and simple
    derived forms (volcano/volcanoes/volcanic) well enough for this.
    """
    if not query_terms:
        return False
    haystack_words = _WORD_RE.findall((title + " " + snippet).lower())
    return any(
        # word.startswith(term) is safe at any haystack-word length (a
        # short word literally can't start with a longer query term). The
        # reverse needs its own length floor, or a short common haystack
        # word like "a"/"in"/"is" would satisfy term.startswith(word) for
        # almost any query term and defeat the filter entirely.
        word.startswith(term) or (len(word) > 2 and term.startswith(word))
        for term in query_terms
        for word in haystack_words
    )


def retrieve(query: str, module_mgr, installed_modules: list[tuple[str, dict]]) -> list[dict]:
    """
    Searches every installed zim-type module with a full-text index for
    `query`. Returns up to MAX_TOTAL_RESULTS {"module_name", "title",
    "snippet"} dicts, best-effort: a module that fails to open or search
    is skipped rather than raised, since retrieval augmenting a chat reply
    must never be able to break the chat reply itself.
    """
    query_terms = _significant_terms(query)
    if not query_terms:
        return []  # a query with no real content words has nothing to ground

    results = []
    for folder, data in installed_modules:
        if data.get("type") != "zim":
            continue
        try:
            reader = module_mgr.get_zim_reader(folder)
        except Exception:
            continue
        if not reader.has_search:
            continue
        try:
            hits = reader.search(query, count=MAX_RESULTS_PER_MODULE)
        except Exception:
            logger.exception("Search failed for module '%s'", folder)
            continue

        for title, path in hits:
            try:
                snippet = reader.get_text_snippet(path, max_chars=SNIPPET_CHARS)
            except Exception:
                logger.exception("Snippet extraction failed for '%s' in '%s'", path, folder)
                continue
            if snippet and _is_relevant(query_terms, title, snippet):
                results.append({
                    "module_name": data.get("name", folder),
                    "title": title,
                    "snippet": snippet,
                })

    return results[:MAX_TOTAL_RESULTS]
