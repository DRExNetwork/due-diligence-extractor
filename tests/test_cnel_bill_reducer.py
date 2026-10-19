from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ddx.classification.categories import normalize_extracted_document
from ddx.classification.cnel_energy_bill import (
    REDUCERS,
    _to_float,
    normalize_cnel_energy_bill,
    parse_tariff_code,
    reduce_detail_rows,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cnel"


def load_fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    payload.pop("_comment", None)
    return payload


@pytest.fixture()
def solar_bill() -> dict:
    return load_fixture("MTCGCD01_sample.json")


@pytest.fixture()
def nonsolar_bill() -> dict:
    return load_fixture("MTCGCD01_nonsolar_sample.json")


# =============================================================================
# Golden fixture — NET-METERED layout (the real solar sample, clean-PDF run)
# =============================================================================


def test_golden_fixture_reduces_to_billfacts(solar_bill):
    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["total_active_energy_kwh"] == 168000.0
    assert extracted["solar_kwh"] == 5600.0
    assert extracted["grid_kwh"] == 162400.0
    assert extracted["billable_amount_usd"] == 19975.2
    assert extracted["tariff_code"] == "MTCGCD01"


def test_f4_negative_guard_valor_total_unreachable(solar_bill):
    # The F4 trap: VALOR TOTAL (24092.06) and VALOR TOTAL + Demanda (22255.24)
    # must be structurally impossible outputs for billable_amount_usd.
    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["billable_amount_usd"] != 24092.06
    assert extracted["billable_amount_usd"] != 22255.24


def test_dispatched_through_normalize_extracted_document(solar_bill):
    extracted, _ = normalize_extracted_document("CNEL Energy Bill", solar_bill, None)
    assert extracted["grid_kwh"] == 162400.0
    assert extracted["tariff_code"] == "MTCGCD01"


def test_accent_and_case_robustness(solar_bill):
    # The bill itself mixes 'Energía'/'Energia'; extraction may vary casing too.
    for row in solar_bill["detail_rows"]:
        row["descripcion"] = row["descripcion"].upper()

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)
    assert extracted["grid_kwh"] == 162400.0
    assert extracted["billable_amount_usd"] == 19975.2


def test_unit_filter_blocks_kw_rows_from_energy_buckets(solar_bill):
    # A KW row whose label collides with the energy prefix must never be summed.
    solar_bill["detail_rows"].append(
        {"descripcion": "Energia facturable demanda", "consumo_total": 99.0, "unidad_medida": "KW", "monto": 111.11}
    )

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)
    assert extracted["grid_kwh"] == 162400.0
    assert extracted["billable_amount_usd"] == 19975.2


# =============================================================================
# NON-SOLAR layout (plan §4.3b — the solar axis is orthogonal to tariff)
# =============================================================================


def test_nonsolar_layout_activa_carries_the_monto(nonsolar_bill):
    extracted, _ = normalize_cnel_energy_bill(nonsolar_bill, None)

    assert extracted["total_active_energy_kwh"] == 53856.0
    assert extracted["solar_kwh"] == 0.0
    assert extracted["grid_kwh"] == 53856.0
    assert extracted["billable_amount_usd"] == 6624.29
    assert extracted["tariff_code"] == "MTCGCD01"


def test_horaria_banded_rows_reduce_via_shared_reducer():
    # MTCGCD02 example bill (non-solar): no 'activa total' row — hourly bands.
    # MTCGCD02 is NOT enabled in REDUCERS yet (hard gate: solar sample), but the
    # shared reducer must already handle the banded layout for that day.
    rows = [
        {"descripcion": "Energía act. hor. A (08h00-18h00)", "consumo_total": 17340.0, "unidad_medida": "kWh", "monto": 1560.60},
        {"descripcion": "Energía act. hor. B (18h00-22h00)", "consumo_total": 2529.60, "unidad_medida": "kWh", "monto": 227.66},
        {"descripcion": "Energía act. hor. C (22h00-08h00)", "consumo_total": 2040.0, "unidad_medida": "kWh", "monto": 148.92},
        {"descripcion": "Energía reactiva total", "consumo_total": 2400.0, "unidad_medida": "kVarh", "monto": None},
        {"descripcion": "Demanda facturable", "consumo_total": 81.60, "unidad_medida": "kW", "monto": 302.15},
    ]
    extracted = {"valor_consumo": 1937.18, "valor_demanda": 302.15, "valor_total": 2333.48}

    derived, provenance, violations, layout = reduce_detail_rows(rows, extracted)

    assert violations == []
    assert layout == "non_solar"
    assert derived["grid_kwh"] == pytest.approx(21909.6)
    assert derived["billable_amount_usd"] == pytest.approx(1937.18)
    assert provenance["billable_amount_usd"] == [0, 1, 2]


# =============================================================================
# Phase-2 layout fixtures (T6.12 "now" work — the three PENDING tariff codes)
#
# These run the SHARED reducer directly (reduce_detail_rows): the codes stay
# OUT of REDUCERS until a net-metered sample of each exists (T6.11 hard gate),
# so normalize_cnel_energy_bill still fail-closes them — locked below.
# =============================================================================


@pytest.fixture()
def btcgsd01_bill() -> dict:
    return load_fixture("BTCGSD01_nonsolar_sample.json")


@pytest.fixture()
def btcgcd01_bill() -> dict:
    return load_fixture("BTCGCD01_nonsolar_sample.json")


@pytest.fixture()
def mtcgcd02_bill() -> dict:
    return load_fixture("MTCGCD02_nonsolar_sample.json")


def test_btcgsd01_single_row_layout_reduces(btcgsd01_bill):
    # Sin Demanda: ONE energy row carrying the Monto; no valor_demanda box.
    derived, provenance, violations, layout = reduce_detail_rows(
        btcgsd01_bill["detail_rows"], btcgsd01_bill
    )

    assert violations == []
    assert layout == "non_solar"
    assert derived["total_active_energy_kwh"] == pytest.approx(1093.0)
    assert derived["grid_kwh"] == pytest.approx(1093.0)
    assert derived["solar_kwh"] == 0.0
    assert derived["billable_amount_usd"] == pytest.approx(111.5)
    assert provenance["billable_amount_usd"] == [0]


def test_btcgcd01_layout_passes_both_money_crosschecks(btcgcd01_bill):
    # Con Demanda: activa carries the Monto; Σ(Demanda facturable) == Valor
    # Demanda (53.12) verified alongside Σ(energy) == Valor Consumo (369.56).
    derived, _, violations, layout = reduce_detail_rows(
        btcgcd01_bill["detail_rows"], btcgcd01_bill
    )

    assert violations == []
    assert layout == "non_solar"
    assert derived["grid_kwh"] == pytest.approx(4017.0)
    assert derived["solar_kwh"] == 0.0
    assert derived["billable_amount_usd"] == pytest.approx(369.56)


def test_btcgcd01_demand_mismatch_refuses(btcgcd01_bill):
    # The 2026-07-13 live failure mode, non-solar edition: a Demanda facturable
    # Monto that disagrees with the printed Valor Demanda box must refuse.
    btcgcd01_bill["valor_demanda"] = 684.01

    _, _, violations, _ = reduce_detail_rows(
        btcgcd01_bill["detail_rows"], btcgcd01_bill
    )

    assert any("Valor Demanda" in violation for violation in violations)


def test_mtcgcd02_fixture_with_banded_demand_reduces(mtcgcd02_bill):
    # Full Horaria fixture: banded energy AND banded demand rows. The banded
    # demand rows ('Demanda máx. hor. A/B/C') match no bucket — telemetry, not
    # failure — while the energy bands still sum to Valor Consumo.
    derived, provenance, violations, layout = reduce_detail_rows(
        mtcgcd02_bill["detail_rows"], mtcgcd02_bill
    )

    assert violations == []
    assert layout == "non_solar"
    assert derived["total_active_energy_kwh"] == pytest.approx(21909.6)
    assert derived["billable_amount_usd"] == pytest.approx(1937.18)
    assert provenance["billable_amount_usd"] == [0, 1, 2]


def test_comma_string_montos_coerce_through_reducer(btcgsd01_bill):
    # DECIMAL-SEPARATOR: the printed bill uses comma decimals ('111,50'); if
    # ADE ever ships them as strings instead of coerced numbers, the reducer
    # must still land on the same BillFacts.
    btcgsd01_bill["detail_rows"][0]["monto"] = "111,50"
    btcgsd01_bill["detail_rows"][0]["consumo_total"] = "1.093,00"

    derived, _, violations, _ = reduce_detail_rows(
        btcgsd01_bill["detail_rows"], btcgsd01_bill
    )

    assert violations == []
    assert derived["grid_kwh"] == pytest.approx(1093.0)
    assert derived["billable_amount_usd"] == pytest.approx(111.5)


def test_phase2_codes_locked_out_until_solar_samples():
    # T6.11 HARD GATE: layout fixtures above do NOT enable the codes — only a
    # net-metered (solar) sample of each may do that, one at a time (T6.12).
    assert set(REDUCERS) == {"MTCGCD01"}
    for code in ("BTCGSD01", "BTCGCD01", "MTCGCD02"):
        assert code not in REDUCERS


# =============================================================================
# Fail-closed behaviour
# =============================================================================


def test_unknown_tariff_leaves_derived_null(solar_bill):
    assert "BTCGSD01" not in REDUCERS  # enabled only with a net-metered sample
    solar_bill["tariff_raw"] = "BTCGSD01 - BT Comercial"

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["tariff_code"] == "BTCGSD01"  # parsed, reported…
    assert extracted["grid_kwh"] is None           # …but nothing derived
    assert extracted["billable_amount_usd"] is None


def test_unparseable_tariff_leaves_derived_null(solar_bill):
    solar_bill["tariff_raw"] = "MT Comercial con Demanda"  # label only, no code

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["tariff_code"] is None
    assert extracted["grid_kwh"] is None


def test_missing_detail_rows_leaves_derived_null(solar_bill):
    solar_bill["detail_rows"] = []

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["grid_kwh"] is None
    assert extracted["tariff_code"] == "MTCGCD01"


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda b: b.update(valor_consumo=24092.06), "billable != Valor Consumo"),
        (lambda b: b["detail_rows"][2].update(consumo_total=999999.0), "energy identity broken"),
        (lambda b: b["detail_rows"][1].update(monto=688.80), "injected row priced"),
        (lambda b: b.update(valor_total=100.0), "billable exceeds VALOR TOTAL"),
    ],
)
def test_invariant_violations_refuse(solar_bill, mutate, reason):
    mutate(solar_bill)

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["grid_kwh"] is None, reason
    assert extracted["billable_amount_usd"] is None, reason


def test_scale_error_caught_by_rate_band(solar_bill):
    # Un-multiplied meter readings (factor 2800 not applied): energies shrink
    # 2800× but money doesn't. The energy identity still passes (scale-invariant);
    # the effective-tariff band is what must catch it.
    for row in solar_bill["detail_rows"]:
        if row["unidad_medida"] == "KWH" and row["consumo_total"]:
            row["consumo_total"] = row["consumo_total"] / 2800.0

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["grid_kwh"] is None
    assert extracted["billable_amount_usd"] is None


def test_inyectada_without_facturable_is_unknown_layout(solar_bill):
    solar_bill["detail_rows"] = [
        row for row in solar_bill["detail_rows"] if "facturable" not in row["descripcion"].lower()
    ]

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["grid_kwh"] is None


# =============================================================================
# tariff_raw → tariff_code parsing (the live-run drift case)
# =============================================================================


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("MTCGCD01 - MT Comercial con Demanda", "MTCGCD01"),  # live-run drift output
        ("MTCGCD01", "MTCGCD01"),
        ("btcgsd01 - BT Comercial", "BTCGSD01"),
        ("MTCGCD02 - MT Comercial con Demanda Horaria", "MTCGCD02"),
        # Capture shapes the old left-of-first-dash parse rejected — each one used
        # to fall back to the LLM's guess instead of being read off the page (T8.12).
        ("TARIFA: MTCGCD01 - MT Comercial con Demanda", "MTCGCD01"),  # label prefix
        ("Tipo de tarifa Arconel\nMTCGCD01 - MT Comercial", "MTCGCD01"),  # wrapped line
        ("MTCGCD01 – MT Comercial con Demanda", "MTCGCD01"),  # en-dash
        ("MT Comercial con Demanda (MTCGCD01)", "MTCGCD01"),  # code after the label
        # Still refused — a code we cannot identify must never pick a reducer.
        ("MT Comercial con Demanda", None),  # label only
        ("MTCGCD01 / BTCGSD01", None),  # ambiguous: two codes, one bill
        ("XMTCGCD01", None),  # inside a longer alphanumeric run — not a code
        ("MTCGCDO1", None),  # letter O where a zero belongs: not a code, refuse
        ("", None),
        (None, None),
    ],
)
def test_parse_tariff_code(raw, expected):
    assert parse_tariff_code(raw) == expected


# =============================================================================
# T8.12 — the tariff code is reducer-owned: no fallback to the LLM's guess
# =============================================================================


def test_llm_tariff_guess_never_selects_a_reducer(solar_bill):
    # THE T8.12 regression. Before the fix this reduced to 168000/5600/162400/
    # 19975.20: the raw line failed to parse, the normalizer fell back to the
    # model's own `tariff_code`, and that guess — landing on the single enabled
    # code — selected the MTCGCD01 reducer. NestJS's whitelist then sees a
    # supported code, the bill classifies `valid`, and it can be committed to the
    # irreversible ledger. A code nobody read off the page must pick nothing.
    solar_bill["tariff_raw"] = None
    solar_bill["tariff_code"] = "MTCGCD01"  # the guess, on the supported code

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["tariff_code"] is None
    assert extracted["total_active_energy_kwh"] is None
    assert extracted["solar_kwh"] is None
    assert extracted["grid_kwh"] is None
    assert extracted["billable_amount_usd"] is None


def test_llm_tariff_guess_ignored_when_raw_line_unparseable(solar_bill):
    # Same authority rule when the model DID read a line but no code is in it.
    solar_bill["tariff_raw"] = "MT Comercial con Demanda"  # label only
    solar_bill["tariff_code"] = "MTCGCD01"

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["tariff_code"] is None
    assert extracted["billable_amount_usd"] is None


def test_unparseable_raw_line_is_logged_for_parser_widening(solar_bill, caplog):
    # The refusal must be loud: a line the model read but we cannot parse is how
    # we learn the scan needs a new shape. Silence is what made T8.12 invisible.
    solar_bill["tariff_raw"] = "TARIFA MT COMERCIAL"

    with caplog.at_level("WARNING", logger="ddx.cnel_energy_bill"):
        normalize_cnel_energy_bill(solar_bill, None)

    assert any("TARIFA MT COMERCIAL" in record.getMessage() for record in caplog.records)


def test_tariff_grounding_points_at_the_raw_line(solar_bill):
    # The FE's tariff bbox comes from this metadata entry. The model grounded its
    # guess; the code is derived, so the honest evidence is the raw line's box.
    solar_bill["tariff_code"] = "MTCGCD01"
    metadata = {
        "tariff_code": {"references": ["0-GUESS"], "value": "MTCGCD01"},
        "tariff_raw": {"references": ["0-RAW"], "confidence": 0.91},
    }

    extracted, out_meta = normalize_cnel_energy_bill(solar_bill, metadata)

    assert extracted["tariff_code"] == "MTCGCD01"  # parsed from tariff_raw
    assert out_meta["tariff_code"]["references"] == ["0-RAW"]
    assert out_meta["tariff_code"]["confidence"] == 0.91


def test_tariff_grounding_dropped_on_refusal(solar_bill):
    solar_bill["tariff_raw"] = None
    solar_bill["tariff_code"] = "MTCGCD01"
    metadata = {"tariff_code": {"references": ["0-GUESS"], "value": "MTCGCD01"}}

    _, out_meta = normalize_cnel_energy_bill(solar_bill, metadata)

    assert "tariff_code" not in out_meta  # no code → no highlight


# =============================================================================
# Numeric coercion (DECIMAL-SEPARATOR risk — comma decimals on 3 of 5 samples)
# =============================================================================


@pytest.mark.parametrize(
    "value, expected",
    [
        (19975.2, 19975.2),
        ("19975.20", 19975.2),
        ("$ 19,975.20", 19975.2),
        ("2333,48", 2333.48),
        ("2 529,60", 2529.6),
        ("1.234,56", 1234.56),
        ("2,529", 2529.0),
        (None, None),
        ("", None),
    ],
)
def test_to_float_handles_separator_styles(value, expected):
    assert _to_float(value) == expected


# =============================================================================
# Grounding provenance synthesis (ROW-METAS defensive)
# =============================================================================


def test_grounding_synthesized_from_real_per_cell_row_metas(solar_bill):
    # The REAL shape settled by the live run (2026-07-10): each row's meta is a
    # dict of PER-CELL metas {references, value} — not a flat {references} dict.
    metadata = {
        "detail_rows": [
            {"descripcion": {"references": ["0-w"]}, "consumo_total": {"references": ["0-D"]},
             "unidad_medida": {"references": ["0-E"]}, "monto": {"references": ["0-F"]}},
            {"descripcion": {"references": ["0-G"]}, "consumo_total": {"references": ["0-N"]},
             "unidad_medida": {"references": ["0-O"]}, "monto": {"references": ["0-P"]}},
            {"descripcion": {"references": ["0-Q"]}, "consumo_total": {"references": ["0-X"]},
             "unidad_medida": {"references": ["0-Y"]}, "monto": {"references": ["0-Z"]}},
            {"descripcion": {"references": ["0-10"]}, "consumo_total": {"references": ["0-17"]},
             "unidad_medida": {"references": ["0-18"]}, "monto": {"references": ["0-19"]}},
            {"descripcion": {"references": ["0-1a"]}, "consumo_total": {"references": ["0-1h"]},
             "unidad_medida": {"references": ["0-1i"]}, "monto": {"references": ["0-1j"]}},
            {"descripcion": {"references": ["0-1k"]}, "consumo_total": {"references": ["0-1r"]},
             "unidad_medida": {"references": ["0-1s"]}, "monto": {"references": ["0-1t"]}},
        ]
    }

    extracted, out_meta = normalize_cnel_energy_bill(solar_bill, metadata)

    assert extracted["billable_amount_usd"] == 19975.2
    # Derived fields ground to the facturable / inyectada row cells.
    assert out_meta["billable_amount_usd"]["references"] == ["0-Q", "0-X", "0-Y", "0-Z"]
    assert out_meta["grid_kwh"]["references"] == ["0-Q", "0-X", "0-Y", "0-Z"]
    assert out_meta["solar_kwh"]["references"] == ["0-G", "0-N", "0-O", "0-P"]


def test_grounding_flat_row_metas_still_supported(solar_bill):
    metadata = {
        "detail_rows": [
            {"references": ["c_act"], "confidence": 0.99},
            {"references": ["c_iny"], "confidence": 0.97},
            {"references": ["c_fact"], "confidence": 0.95},
            {"references": ["c_react"], "confidence": 0.99},
            {"references": ["c_dmax"], "confidence": 0.99},
            {"references": ["c_dfact"], "confidence": 0.98},
        ]
    }

    extracted, out_meta = normalize_cnel_energy_bill(solar_bill, metadata)

    assert extracted["billable_amount_usd"] == 19975.2
    assert out_meta["billable_amount_usd"]["references"] == ["c_fact"]
    assert out_meta["billable_amount_usd"]["confidence"] == 0.95


def test_grounding_absent_row_metas_is_harmless(solar_bill):
    metadata = {"detail_rows": {"references": ["whole_table"]}}  # not per-row

    extracted, out_meta = normalize_cnel_energy_bill(solar_bill, copy.deepcopy(metadata))

    assert extracted["billable_amount_usd"] == 19975.2
    assert "billable_amount_usd" not in out_meta  # no synthetic entry, no crash


# =============================================================================
# LLM does not honor "leave null" (live-run regression, 2026-07-10)
# =============================================================================


def _fill_llm_garbage(bill: dict) -> None:
    # What the live run actually returned for the reducer-owned fields: 0.0
    # everywhere (grounded to the activa 'Monto 0.00' cell) and the string
    # 'null' for tariff_code — despite explicit "leave null" instructions.
    bill["total_active_energy_kwh"] = 0.0
    bill["solar_kwh"] = 0.0
    bill["grid_kwh"] = 0.0
    bill["billable_amount_usd"] = 0.0
    bill["tariff_code"] = "null"


def test_llm_prefilled_derived_overwritten_on_success(solar_bill):
    _fill_llm_garbage(solar_bill)

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["grid_kwh"] == 162400.0
    assert extracted["billable_amount_usd"] == 19975.2
    assert extracted["tariff_code"] == "MTCGCD01"


def test_llm_prefilled_derived_nulled_on_refusal(solar_bill):
    # THE critical case: on a refusal path the LLM's 0.0s must NOT survive —
    # a 0.0 billable passes NestJS's null-checks (0.0 is non-null), sails
    # through the arithmetic gate (|0 − (0+0)| = 0), and would commit zeros
    # into the irreversible financial ledger.
    _fill_llm_garbage(solar_bill)
    solar_bill["valor_consumo"] = 24092.06  # force an invariant violation

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["grid_kwh"] is None
    assert extracted["billable_amount_usd"] is None
    assert extracted["total_active_energy_kwh"] is None
    assert extracted["solar_kwh"] is None


def test_llm_prefilled_derived_nulled_on_unknown_tariff(solar_bill):
    _fill_llm_garbage(solar_bill)
    solar_bill["tariff_raw"] = "BTCGSD01 - BT Comercial"  # no reducer enabled

    extracted, _ = normalize_cnel_energy_bill(solar_bill, None)

    assert extracted["billable_amount_usd"] is None


def test_llm_stale_derived_grounding_dropped(solar_bill):
    # The live run grounded the LLM's 0.0 guesses to the WRONG cell (the activa
    # 'Monto 0.00'). Those stale metadata entries must be dropped and replaced
    # by synthesis from the actual contributing rows.
    _fill_llm_garbage(solar_bill)
    metadata = {
        "billable_amount_usd": {"references": ["0-F"], "value": 0.0},  # wrong cell
        "grid_kwh": {"references": ["0-F"], "value": 0.0},
        "detail_rows": [
            {"monto": {"references": ["0-F"]}},
            {"monto": {"references": ["0-P"]}},
            {"monto": {"references": ["0-Z"]}},
            {"monto": {"references": ["0-19"]}},
            {"monto": {"references": ["0-1j"]}},
            {"monto": {"references": ["0-1t"]}},
        ],
    }

    extracted, out_meta = normalize_cnel_energy_bill(solar_bill, metadata)

    assert extracted["billable_amount_usd"] == 19975.2
    assert out_meta["billable_amount_usd"]["references"] == ["0-Z"]  # facturable row, not 0-F
