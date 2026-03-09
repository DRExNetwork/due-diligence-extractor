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
