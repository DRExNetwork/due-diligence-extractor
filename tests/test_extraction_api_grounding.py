from ddx.classification.extraction_api import _resolve_field_grounding


def test_resolve_field_grounding_with_table_cell_references() -> None:
    parse_response = {
        "chunks": [
            {
                "id": "table-chunk-1",
                "grounding": {
                    "page": 0,
                    "box": {
                        "left": 0.06,
                        "top": 0.33,
                        "right": 0.95,
                        "bottom": 0.43,
                    },
                },
                "type": "table",
            },
            {
                "id": "text-chunk-1",
                "grounding": {
                    "page": 0,
                    "box": {
                        "left": 0.21,
                        "top": 0.44,
                        "right": 0.88,
                        "bottom": 0.47,
                    },
                },
                "type": "text",
            },
        ],
        "grounding": {
            "0-b": {
                "page": 0,
                "box": {
                    "left": 0.26,
                    "top": 0.38,
                    "right": 0.52,
                    "bottom": 0.40,
                },
                "type": "tableCell",
                "position": {
                    "row": 1,
                    "col": 2,
                    "chunk_id": "table-chunk-1",
                },
            },
            "0-e": {
                "page": 0,
                "box": {
                    "left": 0.73,
                    "top": 0.38,
                    "right": 0.85,
                    "bottom": 0.40,
                },
                "type": "tableCell",
                "position": {
                    "row": 1,
                    "col": 5,
                    "chunk_id": "table-chunk-1",
                },
            },
        },
    }

    extraction_metadata = {
        "shareholders": [
            {
                "shareholder_name": {
                    "value": "CHAN TREVOR CHUN HOU",
                    "references": ["0-b"],
                },
                "ownership_percentage": {
                    "value": 40.0,
                    "references": ["0-e", "text-chunk-1"],
                },
            }
        ]
    }

    grounding = _resolve_field_grounding(extraction_metadata, parse_response)

    assert grounding is not None
    shareholder_grounding = grounding["shareholders"][0]

    name_locations = shareholder_grounding["shareholder_name"]
    assert len(name_locations) == 1
    assert name_locations[0]["chunk_id"] == "0-b"
    assert name_locations[0]["chunk_type"] == "tableCell"
    assert name_locations[0]["page"] == 0

    ownership_locations = shareholder_grounding["ownership_percentage"]
    assert [loc["chunk_id"] for loc in ownership_locations] == ["0-e", "text-chunk-1"]
    assert ownership_locations[0]["chunk_type"] == "tableCell"
    assert ownership_locations[1]["chunk_type"] == "text"


# =============================================================================
# T6.14 — grounding observability + cache/grounding interaction (2026-07-13)
# =============================================================================

import asyncio
import logging

from ddx.classification import extraction_api as ea


def test_boxless_locations_are_skipped_not_emitted() -> None:
    # A grounding entry without a box can never render a highlight — it must
    # be skipped (previously it shipped {"bounding_box": {}} and consumers
    # silently dropped it downstream).
    parse_response = {
        "chunks": [
            {"id": "boxless", "grounding": {"page": 0}, "type": "text"},
            {"id": "empty-box", "grounding": {"page": 0, "box": {}}, "type": "text"},
            {
                "id": "good",
                "grounding": {
                    "page": 0,
                    "box": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4},
                },
                "type": "text",
            },
        ]
    }
    extraction_metadata = {
        "field_a": {"value": "x", "references": ["boxless", "empty-box"]},
        "field_b": {"value": "y", "references": ["good"]},
    }

    grounding = _resolve_field_grounding(extraction_metadata, parse_response)

    assert grounding is not None
    assert "field_a" not in grounding  # only box-less locations → unresolved
    assert len(grounding["field_b"]) == 1
    assert grounding["field_b"][0]["bounding_box"]["left"] == 0.1


def test_partial_resolution_logs_a_warning(caplog) -> None:
    parse_response = {
        "chunks": [
            {
                "id": "good",
                "grounding": {
                    "page": 0,
                    "box": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4},
                },
                "type": "text",
            }
        ]
    }
    extraction_metadata = {
        "resolved_field": {"value": "x", "references": ["good"]},
        "unresolved_field": {"value": "y", "references": ["missing-chunk"]},
    }

    with caplog.at_level(logging.WARNING, logger="ddx.grounding"):
        grounding = _resolve_field_grounding(extraction_metadata, parse_response)

    assert grounding is not None and "resolved_field" in grounding
    assert any("resolved 1/2 fields" in r.message for r in caplog.records)
    assert any("unresolved_field" in r.message for r in caplog.records)


def test_empty_chunk_lookup_logs_a_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="ddx.grounding"):
        grounding = _resolve_field_grounding(
            {"field": {"value": "x", "references": ["r1"]}},
            {"cache_hit": True},  # chunk-less parse stand-in
        )

    assert grounding is None
    assert any("chunk lookup is EMPTY" in r.message for r in caplog.records)


def test_cached_markdown_without_parse_json_reparses(monkeypatch) -> None:
    # A markdown-only cache entry must be treated as a MISS: serving it with a
    # chunk-less parse_response would silently lose ALL grounding (T6.14).
    fresh_parse = {"chunks": [{"id": "c1", "grounding": {"page": 0, "box": {"left": 0.1, "top": 0.1, "right": 0.2, "bottom": 0.2}}}]}
    saved = {}

    async def fake_load_md(s3, bucket, key):
        return "cached markdown"

    async def fake_load_parse(s3, bucket, key):
        return None  # pre-parse.json cache entry

    async def fake_parse_bytes(client, pdf_bytes, file_name, model=None, rate_limiter=None):
        return "fresh markdown", fresh_parse

    async def fake_save_md(s3, bucket, key, markdown, metadata=None):
        saved["markdown"] = markdown

    async def fake_save_parse(s3, bucket, key, parse_response):
        saved["parse"] = parse_response

    monkeypatch.setattr(ea, "_try_load_markdown_from_s3", fake_load_md)
    monkeypatch.setattr(ea, "_try_load_parse_json_from_s3", fake_load_parse)
    monkeypatch.setattr(ea, "_async_parse_from_bytes", fake_parse_bytes)
    monkeypatch.setattr(ea, "_save_markdown_to_s3", fake_save_md)
    monkeypatch.setattr(ea, "_save_parse_json_to_s3", fake_save_parse)

    markdown, parse_response = asyncio.run(
        ea._parse_with_cache(
            client=object(),
            file_path=None,
            pdf_bytes=b"pdf-bytes",
            file_name="bill.pdf",
            parse_model=None,
            cache_enabled=True,
            cache_bucket="drex-network",
            s3_client=object(),
        )
    )

    assert markdown == "fresh markdown"          # re-parsed, not the stale cache
    assert parse_response == fresh_parse          # chunks present → grounding OK
    assert saved.get("parse") == fresh_parse      # self-healed: parse.json saved


def test_cached_markdown_with_parse_json_is_served(monkeypatch) -> None:
    cached_parse = {"chunks": [{"id": "c1", "grounding": {"page": 0, "box": {"left": 0.1, "top": 0.1, "right": 0.2, "bottom": 0.2}}}]}

    async def fake_load_md(s3, bucket, key):
        return "cached markdown"

    async def fake_load_parse(s3, bucket, key):
        return cached_parse

    async def fail_parse(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("cache hit must not re-parse")

    monkeypatch.setattr(ea, "_try_load_markdown_from_s3", fake_load_md)
    monkeypatch.setattr(ea, "_try_load_parse_json_from_s3", fake_load_parse)
    monkeypatch.setattr(ea, "_async_parse_from_bytes", fail_parse)
    monkeypatch.setattr(ea, "_async_parse_document", fail_parse)

    markdown, parse_response = asyncio.run(
        ea._parse_with_cache(
            client=object(),
            file_path=None,
            pdf_bytes=b"pdf-bytes",
            file_name="bill.pdf",
            parse_model=None,
            cache_enabled=True,
            cache_bucket="drex-network",
            s3_client=object(),
        )
    )

    assert markdown == "cached markdown"
    assert parse_response == cached_parse


# =============================================================================
# T8.7 / T8.9 — release-review fixes (2026-07-13)
# =============================================================================


def test_cache_keys_are_scoped_by_parse_model(monkeypatch) -> None:
    # T8.7: markdown parsed by one model must never be served for another.
    monkeypatch.delenv("LANDING_PARSE_MODEL", raising=False)

    default_key = ea._markdown_cache_key("ddx-cache", "abc123")
    explicit_key = ea._markdown_cache_key("ddx-cache", "abc123", "dpt-2-latest")
    other_key = ea._markdown_cache_key("ddx-cache", "abc123", "dpt-3-preview")

    assert default_key == explicit_key == "ddx-cache/dpt-2-latest/abc123.md"
    assert other_key == "ddx-cache/dpt-3-preview/abc123.md"
    assert other_key != default_key

    # The env default participates in the key too.
    monkeypatch.setenv("LANDING_PARSE_MODEL", "dpt-9")
    assert ea._markdown_cache_key("ddx-cache", "abc123") == "ddx-cache/dpt-9/abc123.md"

    # parse.json rides the same scope, and slugs are S3-safe.
    assert (
        ea._parse_json_cache_key("ddx-cache", "abc123", "custom/model:v2")
        == "ddx-cache/custom_model_v2/abc123.parse.json"
    )


def test_composite_fields_with_no_resolved_cells_count_as_unresolved(caplog) -> None:
    # T8.9: detail_rows whose references all miss must not ship [{}, {}] and
    # must appear in the unresolved list of the summary log.
    parse_response = {
        "chunks": [
            {
                "id": "good",
                "grounding": {
                    "page": 0,
                    "box": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4},
                },
                "type": "text",
            }
        ]
    }
    extraction_metadata = {
        "contract_account": {"value": "200", "references": ["good"]},
        "detail_rows": [
            {
                "descripcion": {"value": "Energia activa total", "references": ["missing-1"]},
                "monto": {"value": 0.0, "references": ["missing-2"]},
            }
        ],
    }

    with caplog.at_level(logging.WARNING, logger="ddx.grounding"):
        grounding = _resolve_field_grounding(extraction_metadata, parse_response)

    assert grounding is not None
    assert "contract_account" in grounding
    assert "detail_rows" not in grounding  # pruned, not [{}]
    assert any("detail_rows" in r.message for r in caplog.records)


def test_composite_fields_keep_rows_where_some_cells_resolved() -> None:
    parse_response = {
        "chunks": [
            {
                "id": "cell-1",
                "grounding": {
                    "page": 0,
                    "box": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4},
                },
                "type": "tableCell",
            }
        ]
    }
    extraction_metadata = {
        "detail_rows": [
            {
                "descripcion": {"value": "Energia facturable", "references": ["cell-1"]},
                "monto": {"value": 19975.2, "references": ["missing"]},
            },
            {
                "descripcion": {"value": "Demanda facturable", "references": ["missing"]},
            },
        ]
    }

    grounding = _resolve_field_grounding(extraction_metadata, parse_response)

    assert grounding is not None
    rows = grounding["detail_rows"]
    assert len(rows) == 1                      # the all-miss row is pruned
    assert "descripcion" in rows[0]            # resolved cell kept
    assert "monto" not in rows[0]              # missed cell pruned
