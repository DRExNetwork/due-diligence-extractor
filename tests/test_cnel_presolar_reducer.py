"""Admin IET Console — pre-solar capture tests (V1-2033 ST-03 / TA1.x).

Locks the sample-derived extraction rules (feature doc §5 step 2 +
admin-iet-tasks.md Stage A1): operands come from the 'Energía activa' rows
ONLY (= Valor Consumo; user-confirmed 2026-07-22 — demand/reactiva/APG/IVA
excluded), MTCGCD02 sums its three time bands, comma decimals parse, the
monthly pipeline's MTCGCD01-only gate stays untouched, and every refusal path
leaves the operands null (fail closed).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ddx.classification.categories import DocumentType, normalize_extracted_document
from ddx.classification.cnel_energy_bill import REDUCERS as MONTHLY_REDUCERS
from ddx.classification.cnel_presolar_bill import (
    PRESOLAR_REDUCERS,
    PRESOLAR_SUPPORTED_CODES,
    normalize_cnel_presolar_bill,
    reduce_presolar_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cnel"


def load_fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    payload.pop("_comment", None)
    return payload


# =============================================================================
# Golden fixtures — one per CNEL tariff code (docs/billis samples, 2026-07-22)
# =============================================================================

GOLDEN = [
    ("PRESOLAR_BTCGSD01_sample.json", "BTCGSD01", 111.50, 1090.00),
    ("PRESOLAR_BTCGCD01_sample.json", "BTCGCD01", 369.56, 4017.00),
    ("PRESOLAR_MTCGCD01_sample.json", "MTCGCD01", 6624.29, 53856.00),
    ("PRESOLAR_MTCGCD02_sample.json", "MTCGCD02", 1937.18, 21909.60),
]


@pytest.mark.parametrize("fixture,code,amount,kwh", GOLDEN)
def test_golden_fixture_reduces_to_iet_operands(fixture, code, amount, kwh):
    extracted, _ = normalize_cnel_presolar_bill(load_fixture(fixture), None)

    assert extracted["tariff_code"] == code
    assert extracted["total_amount_usd"] == amount
    assert extracted["total_kwh"] == kwh


def test_all_four_codes_have_reducers_and_the_monthly_gate_is_untouched():
    # Pre-solar: human admin review is the safety net → all 4 codes enabled.
    assert set(PRESOLAR_REDUCERS.keys()) == set(PRESOLAR_SUPPORTED_CODES)
    assert set(PRESOLAR_SUPPORTED_CODES) == {
        "BTCGSD01",
        "BTCGCD01",
        "MTCGCD01",
        "MTCGCD02",
    }
    # The monthly pipeline's hard gate (T6.11) must NOT be widened by this work.
    assert set(MONTHLY_REDUCERS.keys()) == {"MTCGCD01"}


def test_demanda_and_reactiva_are_excluded_from_the_operands():
    """BTCGCD01 sample: 369.56, NOT 422.68 (+demanda) and NOT 452.10 (VALOR TOTAL)."""
    extracted, _ = normalize_cnel_presolar_bill(
        load_fixture("PRESOLAR_BTCGCD01_sample.json"), None
    )

    assert extracted["total_amount_usd"] == 369.56
    assert extracted["total_amount_usd"] != pytest.approx(369.56 + 53.12)
    assert extracted["total_amount_usd"] != 452.10


def test_mtcgcd02_band_sum_and_row_preservation():
    """The three time bands sum on both axes; detail_rows stay verbatim."""
    payload = load_fixture("PRESOLAR_MTCGCD02_sample.json")
    original_rows = copy.deepcopy(payload["detail_rows"])

    extracted, _ = normalize_cnel_presolar_bill(payload, None)

    assert extracted["total_amount_usd"] == pytest.approx(1560.60 + 227.66 + 148.92)
    assert extracted["total_kwh"] == pytest.approx(17340.00 + 2529.60 + 2040.00)
    # Verbatim band rows survive for the console's evidence viewer / audit.
    assert extracted["detail_rows"] == original_rows


def test_comma_decimals_parse_first_class():
    """MTCGCD01 sample carries '6624,29'-style strings end to end."""
    extracted, _ = normalize_cnel_presolar_bill(
        load_fixture("PRESOLAR_MTCGCD01_sample.json"), None
    )

    assert extracted["total_amount_usd"] == 6624.29
    assert extracted["total_kwh"] == 53856.00


# =============================================================================
# Refusal paths — operands must stay null (fail closed)
# =============================================================================


def test_net_metering_rows_warn_as_wrong_document_and_refuse(caplog):
    """A POST-solar bill uploaded to the pre-solar console: warn + null operands.

    On a net-metered bill the Monto lives on 'Energía facturable' rows, so the
    activa Monto sum is 0 → the positivity invariant refuses.
    """
    payload = load_fixture("PRESOLAR_BTCGSD01_sample.json")
    payload["detail_rows"] = [
        {"descripcion": "Energía activa total", "consumo_total": 168000.0, "unidad_medida": "KWH", "monto": 0.0},
        {"descripcion": "Energía Inyectada a la red", "consumo_total": 5600.0, "unidad_medida": "KWH", "monto": 0.0},
        {"descripcion": "Energía facturable", "consumo_total": 162400.0, "unidad_medida": "KWH", "monto": 19975.20},
    ]

    with caplog.at_level("WARNING", logger="ddx.cnel_presolar_bill"):
        extracted, _ = normalize_cnel_presolar_bill(payload, None)

    assert extracted["total_amount_usd"] is None
    assert extracted["total_kwh"] is None
    assert any("POST-solar" in message for message in caplog.messages)


def test_valor_consumo_cross_check_refuses_on_mismatch():
    payload = load_fixture("PRESOLAR_BTCGCD01_sample.json")
    payload["valor_consumo"] = 999.99

    extracted, _ = normalize_cnel_presolar_bill(payload, None)

    assert extracted["total_amount_usd"] is None
    assert extracted["total_kwh"] is None


def test_implausible_rate_refuses_scale_errors():
    """A decimal-separator mis-parse (111.50 for 1.09 kWh → 102 USD/kWh) refuses."""
    payload = load_fixture("PRESOLAR_BTCGSD01_sample.json")
    payload["detail_rows"][0]["consumo_total"] = "1,09"
    payload["valor_consumo"] = None  # isolate the rate-band check

    extracted, _ = normalize_cnel_presolar_bill(payload, None)

    assert extracted["total_amount_usd"] is None
    assert extracted["total_kwh"] is None


def test_unparseable_tariff_raw_leaves_operands_null(caplog):
    payload = load_fixture("PRESOLAR_BTCGSD01_sample.json")
    payload["tariff_raw"] = "Tarifa comercial residencial"

    with caplog.at_level("WARNING", logger="ddx.cnel_presolar_bill"):
        extracted, _ = normalize_cnel_presolar_bill(payload, None)

    assert extracted["tariff_code"] is None
    assert extracted["total_amount_usd"] is None
    assert extracted["total_kwh"] is None
    assert any("no ARCONEL code" in message for message in caplog.messages)


def test_model_guesses_are_hard_nulled_at_entry():
    """LLM-prefilled operand/code values must never survive a refusal path."""
    payload = load_fixture("PRESOLAR_BTCGSD01_sample.json")
    payload["tariff_raw"] = None
    payload["total_amount_usd"] = 123.45  # model guess
    payload["total_kwh"] = 678.90  # model guess
    payload["tariff_code"] = "MTCGCD01"  # model guess

    extracted, _ = normalize_cnel_presolar_bill(payload, None)

    assert extracted["total_amount_usd"] is None
    assert extracted["total_kwh"] is None
    assert extracted["tariff_code"] is None


def test_missing_activa_rows_refuse():
    payload = load_fixture("PRESOLAR_BTCGCD01_sample.json")
    payload["detail_rows"] = [
        {"descripcion": "Demanda facturable", "consumo_total": 13.10, "unidad_medida": "KW", "monto": 53.12},
    ]

    derived, provenance, violations = reduce_presolar_rows(
        payload["detail_rows"], payload
    )

    assert derived == {}
    assert any("no 'Energía activa' rows" in v for v in violations)


# =============================================================================
# Registration + grounding
# =============================================================================


def test_document_type_dispatch_routes_to_the_presolar_normalizer():
    extracted, _ = normalize_extracted_document(
        DocumentType.CNEL_PRESOLAR_BILL.value,
        load_fixture("PRESOLAR_MTCGCD02_sample.json"),
        None,
    )

    assert extracted["total_amount_usd"] == 1937.18
    assert extracted["total_kwh"] == 21909.60


def test_presolar_type_is_not_a_dataroom_classification_candidate():
    from ddx.classification.categories import DOCUMENT_TYPE_TO_TOP_LEVEL

    assert DocumentType.CNEL_PRESOLAR_BILL not in DOCUMENT_TYPE_TO_TOP_LEVEL


def test_grounding_synthesis_points_operands_at_the_activa_rows():
    payload = load_fixture("PRESOLAR_BTCGSD01_sample.json")
    metadata = {
        "tariff_raw": {"references": [{"page": 0, "bbox": [0.1, 0.1, 0.5, 0.12]}], "confidence": 0.97},
        "detail_rows": [
            {
                "descripcion": {"references": [{"page": 0, "bbox": [0.1, 0.5, 0.4, 0.52]}], "confidence": 0.95},
                "monto": {"references": [{"page": 0, "bbox": [0.8, 0.5, 0.9, 0.52]}], "confidence": 0.91},
            }
        ],
        # A model-guessed grounding for a reducer-owned field must be dropped.
        "total_amount_usd": {"references": [{"page": 0, "bbox": [0, 0, 1, 1]}]},
    }

    extracted, out_metadata = normalize_cnel_presolar_bill(payload, metadata)

    assert extracted["total_amount_usd"] == 111.50
    # Operand grounding points at the activa row's cells (union of cell refs).
    assert out_metadata["total_amount_usd"]["references"]
    assert out_metadata["total_kwh"]["references"]
    assert out_metadata["total_amount_usd"]["references"] != [{"page": 0, "bbox": [0, 0, 1, 1]}]
    # tariff_code grounding is reattached to the tariff_raw line it was parsed from.
    assert out_metadata["tariff_code"]["extracted_text"] == "BTCGSD01"
    assert out_metadata["tariff_code"]["references"] == metadata["tariff_raw"]["references"]
