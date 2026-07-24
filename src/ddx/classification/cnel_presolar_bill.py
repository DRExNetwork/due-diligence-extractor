#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNEL EP PRE-SOLAR bill extraction (DREX Admin IET Console — Epic PD-236,
PD-312 / V1-2033 ST-03).

The one-time extraction that feeds the Initial Energy Tariff registry:
``IET = total_amount_usd ÷ total_kwh``, where BOTH operands come from the
'Energía activa' rows ONLY (= the bill's 'Valor Consumo'). USER-CONFIRMED
2026-07-22: "we only care about what is paid for energía activa total" —
Demanda facturable, reactiva, comercialización, alumbrado público, IVA and
VALOR TOTAL are all EXCLUDED. The division itself happens in NestJS (TA2.5);
this module only produces faithful operands + band detail rows.

Clones the ``cnel_energy_bill`` capture-and-reduce architecture and REUSES its
helpers (``_norm``/``_to_float``/``parse_tariff_code``/``_bucket_rows``/
grounding synthesis) — the LLM only transcribes; every interpretation happens
here, fails closed, and hard-nulls the reducer-owned fields at entry (T8.12
discipline: no model guess can survive a refusal path).

Deltas vs the monthly module (build contract:
app-drex-projects/docs/energy-monitoring-tickets/admin-iet-feature.md §5):

- **No solar fields.** A pre-solar bill has no 'Energía inyectada'/'Energía
  facturable' net-metering rows; their presence logs a WRONG-DOCUMENT warning
  (someone uploaded a post-solar bill) and the reduction refuses via the
  Valor-Consumo/positivity invariants.
- **All four CNEL codes have reducers** — BTCGSD01, BTCGCD01, MTCGCD01, and
  the MTCGCD02 time-of-use bands (summed over 'Energía act. hor. A/B/C').
  Human admin review is the safety net here (all values are confirmed in the
  console before publish), unlike the monthly pipeline's MTCGCD01-only gate.
- **Comma decimals are first-class** — the real samples print '6.624,29' /
  '125,77'; ``_to_float`` handles both separators and the fixtures lock it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from ddx.classification.cnel_energy_bill import (
    MONEY_TOLERANCE_USD,
    RATE_BAND_MAX,
    RATE_BAND_MIN,
    BillDetailRow,
    _bucket_rows,
    _reattach_tariff_grounding,
    _sum_over,
    _synthesize_grounding,
    _to_float,
    parse_tariff_code,
)

log = logging.getLogger("ddx.cnel_presolar_bill")

_DO_NOT_EXTRACT = "Computed server-side from detail_rows. Do not extract; leave null."


# =============================================================================
# Capture schema — transcription only (same discipline as cnel_energy_bill)
# =============================================================================


class CnelPresolarBillData(BaseModel):
    """
    One CNEL EP electricity bill from BEFORE the solar plant was operational —
    one subscriber, one billing period. CAPTURE ONLY: every extracted field is
    a copy task; ``normalize_cnel_presolar_bill`` computes the IET operands.
    """

    model_config = ConfigDict(extra="forbid")

    # ---- header: identity ----
    contract_account: Optional[str] = Field(
        default=None,
        description=(
            "The contract account number printed as 'CUENTA CONTRATO' in the "
            "'Información del Consumidor' block (e.g. '200016919595'). Digits only."
        ),
        json_schema_extra={"x-alternativeNames": ["Cuenta Contrato", "Account Number"]},
    )
    barcode_text: Optional[str] = Field(
        default=None,
        description=(
            "The alphanumeric text printed directly beneath the barcode near the top "
            "of the page (e.g. 'K200016919595'). Copy verbatim including the leading letter."
        ),
        json_schema_extra={"x-alternativeNames": ["Barcode Text", "Barcode Number"]},
    )
    company_name: Optional[str] = Field(
        default=None,
        description="Legal name of the account holder, printed as 'Razón Social' or 'Razón social'.",
        json_schema_extra={"x-alternativeNames": ["Razón Social", "Razón social", "Company Name"]},
    )
    ruc: Optional[str] = Field(
        default=None,
        description="The RUC (Ecuador tax ID) of the account holder as printed on the bill.",
        json_schema_extra={"x-alternativeNames": ["RUC", "Tax ID"]},
    )
    service_address: Optional[str] = Field(
        default=None,
        description="Service address printed as 'Dirección del servicio'. Return the full line verbatim.",
        json_schema_extra={"x-alternativeNames": ["Dirección del servicio", "Service Address"]},
    )
    tariff_raw: Optional[str] = Field(
        default=None,
        description=(
            "The FULL 'Tipo de tarifa Arconel' / 'Tipo de tarifa ARCONEL' line, copied "
            "verbatim — code and label together, e.g. 'BTCGCD01 - BT Comercial con "
            "Demanda'. Do not shorten it."
        ),
        json_schema_extra={
            "x-alternativeNames": ["Tipo de tarifa Arconel", "Tipo de tarifa ARCONEL", "Tariff Type"]
        },
    )

    # ---- header: period ----
    issue_date: Optional[str] = Field(
        default=None,
        description=(
            "'Fecha de emisión' from the top-right header block, exactly as printed "
            "(DD-MM-YYYY)."
        ),
        json_schema_extra={"x-alternativeNames": ["Fecha de emisión", "Issue Date"]},
    )
    billing_period_from: Optional[str] = Field(
        default=None,
        description=(
            "'Fecha desde' in section '1. Información Servicio Eléctrico y Alumbrado "
            "Público', exactly as printed (DD-MM-YYYY). NOT 'Fecha de emisión'."
        ),
        json_schema_extra={"x-alternativeNames": ["Fecha desde", "Billing Period Start"]},
    )
    billing_period_to: Optional[str] = Field(
        default=None,
        description="'Fecha hasta' in the same section, exactly as printed (DD-MM-YYYY).",
        json_schema_extra={"x-alternativeNames": ["Fecha hasta", "Billing Period End"]},
    )
    days_billed: Optional[int] = Field(
        default=None,
        description="'Días facturados' in section 1, as an integer. Null if not printed.",
        json_schema_extra={"x-alternativeNames": ["Días facturados", "Billed Days"]},
    )
    multiplication_factor: Optional[float] = Field(
        default=None,
        description=(
            "'Factor de multiplicación' in section 1, as a number. Null if the bill "
            "does not print it (BT tariffs omit it)."
        ),
        json_schema_extra={"x-alternativeNames": ["Factor de multiplicación", "Multiplier"]},
    )

    # ---- money boxes (independent cross-check sources) ----
    valor_total: Optional[float] = Field(
        default=None,
        description=(
            "'VALOR TOTAL' from the header area — the grand total including demand "
            "charges, taxes and public lighting. Copy the number as printed."
        ),
        json_schema_extra={"x-alternativeNames": ["VALOR TOTAL", "Total Amount Due"]},
    )
    valor_consumo: Optional[float] = Field(
        default=None,
        description=(
            "'Valor Consumo' from the 'Servicio Eléctrico y Alumbrado Público' box "
            "(usually bottom-right), as a number. Null if the box is not present."
        ),
        json_schema_extra={"x-alternativeNames": ["Valor Consumo", "Consumption Value"]},
    )
    valor_demanda: Optional[float] = Field(
        default=None,
        description=(
            "'Valor Demanda' from the same box, as a number. Null if the bill has no "
            "demand charge."
        ),
        json_schema_extra={"x-alternativeNames": ["Valor Demanda", "Demand Value"]},
    )

    # ---- the payload ----
    detail_rows: List[BillDetailRow] = Field(
        default_factory=list,
        description=(
            "EVERY row of the detail table under the 'Descripción / … / Consumo Total / "
            "Unidad Medida / Monto ($)' header, in printed order, transcribed verbatim. "
            "Include rows whose Monto is 0.00 or blank, reactive-energy rows and demand "
            "rows alike. Do NOT sum, filter, merge, reorder or skip any row. Do NOT "
            "include the 'VALOR TOTAL' figure — it is not a row of this table."
        ),
        json_schema_extra={"x-alternativeNames": ["Detail Rows", "Itemized Charges"]},
    )

    # ---- derived (schema members for target_fields plumbing; LLM leaves null) ----
    total_kwh: Optional[float] = Field(default=None, description=_DO_NOT_EXTRACT)
    total_amount_usd: Optional[float] = Field(default=None, description=_DO_NOT_EXTRACT)
    tariff_code: Optional[str] = Field(
        default=None,
        description="Computed server-side from tariff_raw. Do not extract; leave null.",
    )


# =============================================================================
# The reducer — energía-activa rows only, all four codes, fails closed
# =============================================================================


def reduce_presolar_rows(
    rows: List[Dict[str, Any]], extracted: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, List[int]], List[str]]:
    """
    Reduce verbatim detail rows into the two IET operands.

    ``total_amount_usd`` = Σ Monto of the 'Energía activa' rows (single
    'Energía activa total' row on standard tariffs; the three 'Energía act.
    hor. A/B/C' bands on MTCGCD02 — ``_bucket_rows`` matches both shapes, so
    the band sum is the same code path). ``total_kwh`` = Σ Consumo Total of
    the same rows. Everything else (demanda, reactiva) is excluded by
    construction. A non-empty ``violations`` list means REFUSE.
    """
    buckets = _bucket_rows(rows)
    violations: List[str] = []

    # Wrong-document signal: net-metering rows do not exist pre-solar.
    solar_era_rows = buckets["inyectada"] + buckets["facturable"]
    if solar_era_rows:
        labels = [
            rows[i].get("descripcion")
            for i in solar_era_rows
            if isinstance(rows[i], dict)
        ]
        log.warning(
            "cnel_presolar_bill: net-metering rows present %s — this looks like a "
            "POST-solar bill uploaded to the pre-solar console (wrong document)",
            labels,
        )

    if not buckets["activa"]:
        violations.append("no 'Energía activa' rows found in detail_rows")
        return {}, {}, violations

    total_kwh = _sum_over(rows, buckets["activa"], "consumo_total")
    total_amount = _sum_over(rows, buckets["activa"], "monto")

    # --- invariants (all must hold or the operands stay null) ---
    if total_kwh <= 0:
        violations.append("no consumed energy (total_kwh <= 0)")
    if total_amount <= 0:
        violations.append(
            "no energy payment found (sum of 'Energía activa' Montos <= 0) — "
            "on a net-metered bill the Monto lives on 'Energía facturable' rows, "
            "which this pre-solar pipeline deliberately does not read"
        )

    valor_consumo = _to_float(extracted.get("valor_consumo"))
    if valor_consumo is not None and abs(total_amount - valor_consumo) > MONEY_TOLERANCE_USD:
        violations.append(
            f"sum of energy Montos {total_amount:.2f} != Valor Consumo {valor_consumo:.2f}"
        )

    valor_demanda = _to_float(extracted.get("valor_demanda"))
    if valor_demanda is not None and buckets["demanda_facturable"]:
        demanda_monto = _sum_over(rows, buckets["demanda_facturable"], "monto")
        if abs(demanda_monto - valor_demanda) > MONEY_TOLERANCE_USD:
            violations.append(
                f"sum of Demanda facturable Montos {demanda_monto:.2f} != "
                f"Valor Demanda {valor_demanda:.2f}"
            )

    valor_total = _to_float(extracted.get("valor_total"))
    if valor_total is not None and total_amount > valor_total + MONEY_TOLERANCE_USD:
        violations.append(
            f"energy amount {total_amount:.2f} exceeds VALOR TOTAL {valor_total:.2f}"
        )

    if total_kwh > 0 and total_amount > 0:
        rate = total_amount / total_kwh
        if not (RATE_BAND_MIN <= rate <= RATE_BAND_MAX):
            violations.append(
                f"effective tariff {rate:.4f} USD/kWh outside plausible band "
                f"[{RATE_BAND_MIN}, {RATE_BAND_MAX}] — possible scale or "
                f"decimal-separator error"
            )

    derived = {
        "total_kwh": round(total_kwh, 2),
        "total_amount_usd": round(total_amount, 2),
    }
    provenance = {
        "total_kwh": list(buckets["activa"]),
        "total_amount_usd": list(buckets["activa"]),
    }

    if buckets["unmatched"]:
        labels = [
            rows[i].get("descripcion")
            for i in buckets["unmatched"]
            if isinstance(rows[i], dict)
        ]
        log.info("cnel_presolar_bill: unmatched detail rows (telemetry): %s", labels)

    return derived, provenance, violations


# The LLM is told to leave these null and is not trusted to (T8.12 discipline).
PRESOLAR_DERIVED_FIELDS = ("total_kwh", "total_amount_usd")
PRESOLAR_REDUCER_OWNED_FIELDS = PRESOLAR_DERIVED_FIELDS + ("tariff_code",)

# All four CNEL codes are enabled — the admin reviews every value in the
# console before publish, so human review (not a code whitelist) is the safety
# net here. The band summation for MTCGCD02 falls out of the shared bucketing.
PRESOLAR_SUPPORTED_CODES = ("BTCGSD01", "BTCGCD01", "MTCGCD01", "MTCGCD02")
PRESOLAR_REDUCERS = {code: reduce_presolar_rows for code in PRESOLAR_SUPPORTED_CODES}


# =============================================================================
# Normalizer entry point
# =============================================================================


def normalize_cnel_presolar_bill(
    extracted: Dict[str, Any],
    extraction_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Document-type normalizer hook for ``cnel_presolar_bill`` (called from
    ``normalize_extracted_document``). Parses the tariff code and computes the
    two IET operands from ``detail_rows``; on any refusal the operands stay
    null and the reason is logged (the admin console shows the document as
    failed / needing manual entry).
    """
    extracted = dict(extracted)

    # Hard-null every reducer-owned field FIRST — only this module may fill
    # them, and only on a fully-validated success path.
    for field in PRESOLAR_REDUCER_OWNED_FIELDS:
        extracted[field] = None
    if isinstance(extraction_metadata, dict):
        for field in PRESOLAR_REDUCER_OWNED_FIELDS:
            extraction_metadata.pop(field, None)

    tariff_raw = extracted.get("tariff_raw")
    tariff_code = parse_tariff_code(tariff_raw)
    extracted["tariff_code"] = tariff_code
    if tariff_code is None:
        if tariff_raw:
            log.warning(
                "cnel_presolar_bill: no ARCONEL code found in tariff_raw %r — "
                "operands left null (widen the parser if this shape is legitimate)",
                tariff_raw,
            )
        else:
            log.warning(
                "cnel_presolar_bill: no tariff line captured — operands left null"
            )
    elif isinstance(extraction_metadata, dict):
        _reattach_tariff_grounding(extraction_metadata, tariff_code)

    rows = extracted.get("detail_rows")
    if not isinstance(rows, list) or not rows:
        log.warning(
            "cnel_presolar_bill: no detail_rows captured — operands left null"
        )
        return extracted, extraction_metadata

    rows = [row if isinstance(row, dict) else {} for row in rows]

    if tariff_code is None:
        return extracted, extraction_metadata

    reducer = PRESOLAR_REDUCERS.get(tariff_code)
    if reducer is None:
        log.warning(
            "cnel_presolar_bill: tariff %s has no reducer (fail closed) — operands left null",
            tariff_code,
        )
        return extracted, extraction_metadata

    derived, provenance, violations = reducer(rows, extracted)
    if violations:
        log.warning(
            "cnel_presolar_bill: invariant violation(s), operands left null: %s",
            "; ".join(violations),
        )
        return extracted, extraction_metadata

    log.info(
        "cnel_presolar_bill: reduced %s → amount=%s kwh=%s (IET would be %.6f USD/kWh)",
        tariff_code,
        derived["total_amount_usd"],
        derived["total_kwh"],
        derived["total_amount_usd"] / derived["total_kwh"],
    )
    extracted.update(derived)

    if isinstance(extraction_metadata, dict):
        _synthesize_grounding(extraction_metadata, derived, provenance)

    return extracted, extraction_metadata
