import json

import numpy as np

from app import rag
from app.rag import LegalIndex, _tokenize

DOCS = [
    {
        "id": "doc-a",
        "title": "Punjab Rented Premises Act",
        "section": "8",
        "text": "Security deposit refund landlord tenant Punjab Pakistan tenancy",
        "jurisdiction": "Pakistan",
        "province_or_state": "Punjab",
        "legal_domain": "landlord_tenant",
        "authority_level": "primary",
        "status": "active",
        "year": 2009,
    },
    {
        "id": "doc-b",
        "title": "Payment of Wages Act",
        "section": "15",
        "text": "Unpaid wages claim employer worker compensation",
        "jurisdiction": "Pakistan",
        "province_or_state": None,
        "legal_domain": "employment",
        "authority_level": "primary",
        "status": "active",
        "year": 1936,
    },
    {
        "id": "doc-c",
        "title": "India Punjab Rent Act",
        "section": "13",
        "text": "Eviction tenant India Punjab urban rented building",
        "jurisdiction": "India",
        "province_or_state": "Punjab",
        "legal_domain": "landlord_tenant",
        "authority_level": "primary",
        "status": "active",
        "year": 1949,
    },
]


def make_index(docs):
    idx = LegalIndex()
    idx.docs = docs
    idx._build_keyword_index()
    return idx


def test_keyword_search_finds_relevant_doc():
    idx = make_index(DOCS)
    results = idx.keyword_search("security deposit Punjab")
    assert results
    assert idx.docs[results[0][0]]["id"] == "doc-a"


def test_keyword_search_no_match_returns_empty():
    idx = make_index(DOCS)
    assert idx.keyword_search("quantum physics homework") == []


def test_keyword_search_empty_query_returns_empty():
    idx = make_index(DOCS)
    assert idx.keyword_search("   ") == []


def test_keyword_search_empty_corpus_returns_empty():
    idx = make_index([])
    assert idx.keyword_search("anything") == []


def test_keyword_search_corrects_single_word_typo():
    # "tennant" (typo) has no postings entry; BM25 is exact-match, so
    # without fuzzy correction this returns nothing even though "tenant"
    # is all over doc-a's text.
    idx = make_index(DOCS)
    results = idx.keyword_search("tennant deposit")
    assert results
    assert idx.docs[results[0][0]]["id"] == "doc-a"


def test_keyword_search_does_not_correct_short_tokens():
    # Below the 4-char minimum, fuzzy correction is skipped to avoid
    # risky matches on short words.
    idx = make_index(DOCS)
    assert idx._correct_token("abc") == "abc"


def test_tokenize_expands_ppc_alias():
    # PPC documents' titles/text only ever spell out "Pakistan Penal Code" —
    # a query token "ppc" must still be able to match them.
    assert set(_tokenize("ppc")) >= {"ppc", "pakistan", "penal", "code"}


def test_tokenize_leaves_unrelated_tokens_alone():
    assert _tokenize("tenant deposit") == ["tenant", "deposit"]


def test_metadata_filter_excludes_known_different_jurisdiction():
    idx = make_index(DOCS)
    allowed = idx._metadata_filter("Pakistan", None)
    allowed_ids = {idx.docs[i]["id"] for i in allowed}
    assert allowed_ids == {"doc-a", "doc-b"}


def test_metadata_filter_none_when_no_jurisdiction_given():
    idx = make_index(DOCS)
    assert idx._metadata_filter(None, None) is None


def test_metadata_filter_falls_back_to_unfiltered_when_nothing_matches():
    idx = make_index(DOCS)
    assert idx._metadata_filter("Germany", None) is None


def test_retrieve_empty_corpus_is_not_relevant():
    idx = make_index([])
    result = idx.retrieve("anything")
    assert result["relevant"] is False
    assert result["sources"] == []


def test_retrieve_irrelevant_query_is_below_threshold():
    idx = make_index(DOCS)
    result = idx.retrieve("how do I bake a chocolate cake")
    assert result["relevant"] is False
    assert result["sources"] == []


def test_retrieve_relevant_query_returns_matching_doc_via_bm25(monkeypatch):
    from app import rag

    monkeypatch.setattr(rag, "MIN_BM25", 0.5)
    idx = make_index(DOCS)
    result = idx.retrieve("security deposit Punjab tenancy")
    assert result["relevant"] is True
    ids = [d["id"] for d in result["sources"]]
    assert "doc-a" in ids


def test_retrieve_respects_jurisdiction_filter(monkeypatch):
    from app import rag

    monkeypatch.setattr(rag, "MIN_BM25", 0.5)
    idx = make_index(DOCS)
    result = idx.retrieve(
        "eviction tenant Punjab rented building",
        jurisdiction="India",
        province_or_state="Punjab",
    )
    ids = [d["id"] for d in result["sources"]]
    assert "doc-c" in ids
    assert "doc-a" not in ids


# ---------------------------------------------------------- sharded loading

def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_documents_merges_base_and_shards(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "DATA_DIR", tmp_path)
    _write_json(tmp_path / "documents.json", [DOCS[0]])
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_json(corpus_dir / "extra_act.json", [DOCS[1]])

    idx = LegalIndex()
    idx._load_documents()

    assert {d["id"] for d in idx.docs} == {"doc-a", "doc-b"}


def test_load_documents_duplicate_id_across_shards_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "DATA_DIR", tmp_path)
    _write_json(tmp_path / "documents.json", [DOCS[0]])
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    # Same id as the base doc, different content — must not silently replace it.
    clashing = {**DOCS[1], "id": "doc-a"}
    _write_json(corpus_dir / "extra_act.json", [clashing])

    idx = LegalIndex()
    idx._load_documents()

    assert len(idx.docs) == 1
    assert idx.docs[0]["title"] == DOCS[0]["title"]


def test_load_embeddings_shard_without_matrix_degrades_to_zero_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "DATA_DIR", tmp_path)
    _write_json(tmp_path / "documents.json", [DOCS[0]])
    base_matrix = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    np.save(tmp_path / "embeddings.npy", base_matrix)

    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_json(corpus_dir / "extra_act.json", [DOCS[1]])
    # Deliberately no extra_act.embeddings.npy — this shard has no vectors yet.

    idx = LegalIndex()
    idx._load_documents()
    idx._load_embeddings()

    assert idx.embed_ok is True  # base still works
    assert idx.embeddings.shape == (2, 3)
    assert np.allclose(idx.embeddings[0], [1.0, 0.0, 0.0])  # base doc intact
    assert np.allclose(idx.embeddings[1], [0.0, 0.0, 0.0])  # shard doc zero-filled


def test_load_embeddings_all_missing_disables_vector_search(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "DATA_DIR", tmp_path)
    _write_json(tmp_path / "documents.json", [DOCS[0]])
    # No embeddings.npy anywhere.

    idx = LegalIndex()
    idx._load_documents()
    idx._load_embeddings()

    assert idx.embed_ok is False
    assert idx.embeddings is None


def test_shard_loading_ignores_index_meta_sidecar_files(tmp_path, monkeypatch):
    """Regression test: build_index.py writes <shard>.index_meta.json next
    to each shard's own JSON. A naive glob("*.json") picks that up as if it
    were a document shard too — it isn't a list of docs (so gets logged and
    skipped in _load_documents), but its dict happened to have 4 top-level
    keys, so len() on it silently produced a bogus "4-document" shard that
    corrupted the combined embeddings row count and disabled vector search
    for the whole app. Shard loading must ignore *.index_meta.json files."""
    monkeypatch.setattr(rag, "DATA_DIR", tmp_path)
    _write_json(tmp_path / "documents.json", [DOCS[0]])
    base_matrix = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    np.save(tmp_path / "embeddings.npy", base_matrix)

    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_json(corpus_dir / "extra_act.json", [DOCS[1]])
    shard_matrix = np.array([[0.0, 1.0, 0.0]], dtype=np.float32)
    np.save(corpus_dir / "extra_act.embeddings.npy", shard_matrix)
    # The meta sidecar build_index.py writes — a dict, not a list of docs.
    _write_json(corpus_dir / "extra_act.index_meta.json", {
        "embed_model": "x", "dim": 3, "count": 1, "doc_ids": ["doc-b"],
    })

    idx = LegalIndex()
    idx._load_documents()
    idx._load_embeddings()

    assert {d["id"] for d in idx.docs} == {"doc-a", "doc-b"}
    assert idx.embed_ok is True
    assert idx.embeddings.shape == (2, 3)
    assert np.allclose(idx.embeddings[0], [1.0, 0.0, 0.0])
    assert np.allclose(idx.embeddings[1], [0.0, 1.0, 0.0])
