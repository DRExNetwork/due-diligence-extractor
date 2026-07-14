#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNEL EP energy-bill extraction (DREX Energy Monitoring — Epic PD-236, PD-269).

Capture-and-reduce design (build contract:
app-drex-projects/docs/bill-ocr-extraction-implementation-plan.md §4–§6):

- The LLM ONLY TRANSCRIBES: header scalars + the detail table verbatim
  (``detail_rows``) + the ``Servicio Eléctrico y Alumbrado Público`` money box.
  No field description asks for a filter, a sum, or a choice, and no
  description contains tariff-specific row vocabulary.
- All interpretation happens here, in Python: tariff-code parsing, row
  bucketing, summation, invariants, grounding provenance. Evidence base:
  two live Landing.ai runs on the same bill returned byte-identical
  ``detail_rows`` but DRIFTED on interpretation (run #2 returned the full
  tariff label despite a "code only" instruction).

The derived fields (``total_active_energy_kwh``/``solar_kwh``/``grid_kwh``/
``billable_amount_usd``/``tariff_code``) stay schema members so NestJS can
request them via ``target_fields``; the LLM is instructed to leave them null
and ``normalize_cnel_energy_bill`` computes them authoritatively.

Fail-closed: unknown tariff, missing rows, or any invariant violation leaves
the derived fields null — NestJS's ``hasRequiredFields`` then routes the bill
to review instead of silently accepting a wrong number.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("ddx.cnel_energy_bill")

# =============================================================================
# Constants
# =============================================================================

# ARCONEL "consumidores generales" tariff codes: BT/MT + CG + SD/CD + 2 digits.
# Matched ANYWHERE in the raw tariff line, not just at its head: the anchored
# left-of-first-dash parse fails on any capture shape we have not sighted (a
# 'TARIFA:' prefix, a wrapped line, an en-dash), and every such failure used to
# hand code authority back to the LLM's own guess (T8.12). Widening a
# deterministic scan is reviewable; trusting the guess was not. The lookarounds
# keep it from matching inside a longer alphanumeric run.
TARIFF_CODE_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{2}CG[A-Z]{2}\d{2}(?![A-Z0-9])")

# Normalized (accent-stripped, casefolded) Descripción prefixes.
# The bill ITSELF mixes accents ('Energía activa total' vs 'Energia facturable'),
# so all matching happens on _norm()-ed text — never on raw labels.
ACTIVA_PREFIXES = ("energia activa total", "energia act. hor", "energia act hor")
INYECTADA_PREFIX = "energia inyectada"
FACTURABLE_PREFIX = "energia facturable"
DEMANDA_FACTURABLE_PREFIX = "demanda facturable"
REACTIVA_PREFIX = "energia reactiva"
DEMANDA_PREFIX = "demanda"

ENERGY_UNITS = {"kwh"}
DEMAND_UNITS = {"kw"}
REACTIVE_UNITS = {"kvr", "kvar", "kvarh"}

# Invariant tolerances (plan §6).
ENERGY_TOLERANCE_KWH = 0.02   # |total − (grid + solar)|
MONEY_TOLERANCE_USD = 0.01    # Σ(Montos) vs the printed Valor Consumo / Demanda
# Effective-tariff sanity band (USD/kWh). Observed on real bills: 0.092–0.123.
# Catches scale errors the energy identity cannot (it is scale-invariant) and
# comma-decimal mis-parses (2333,48 → 233348).
RATE_BAND_MIN = 0.01
RATE_BAND_MAX = 2.0


# =============================================================================
# Capture schema — transcription only, zero tariff vocabulary
# =============================================================================


class BillDetailRow(BaseModel):
    """One row of the bill's detail table, transcribed VERBATIM. No interpretation."""

    model_config = ConfigDict(extra="forbid")

    descripcion: Optional[str] = Field(
        default=None,
        description=(
            "The row's 'Descripción' cell, copied EXACTLY as printed, including accents "
            "and capitalisation as they appear on the bill. Do not translate, normalise "
            "or correct it."
        ),
    )
    consumo_total: Optional[float] = Field(
        default=None,
        description="This row's 'Consumo Total' cell as a number. Null if the cell is blank.",
    )
    unidad_medida: Optional[str] = Field(
        default=None,
        description="This row's 'Unidad Medida' cell verbatim (e.g. 'KWH', 'kWh', 'KW', 'KVR', 'kVarh').",
    )
    monto: Optional[float] = Field(
        default=None,
        description="This row's 'Monto ($)' cell as a number. Null if the cell is blank.",
    )


_DO_NOT_EXTRACT = "Computed server-side from detail_rows. Do not extract; leave null."


class CnelEnergyBillData(BaseModel):
    """
    One CNEL EP electricity bill, one subscriber, one billing period.

    CAPTURE ONLY — every extracted field is a copy task. All interpretation
    (row bucketing, summation, tariff-code parsing) happens in
    ``normalize_cnel_energy_bill``. Nullability is deliberate: several fields
    are legitimately absent on some tariffs (e.g. 'Factor de multiplicación'
    on BT bills) and a required field forces the model to invent a value.
    """

    model_config = ConfigDict(extra="forbid")

    # ---- header: identity ----
    contract_account: Optional[str] = Field(
        default=None,
        description=(
            "The contract account number printed as 'CUENTA CONTRATO' in the "
            "'Información del Consumidor' block (e.g. '200047515305'). Digits only."
        ),
        json_schema_extra={"x-alternativeNames": ["Cuenta Contrato", "Account Number"]},
    )
    barcode_text: Optional[str] = Field(
        default=None,
        description=(
            "The alphanumeric text printed directly beneath the barcode near the top "
            "of the page (e.g. 'K200047515305'). Copy verbatim including the leading letter."
        ),
        json_schema_extra={"x-alternativeNames": ["Barcode Text", "Barcode Number"]},
    )
    company_name: Optional[str] = Field(
        default=None,
        description="Legal name of the account holder, printed as 'Razón Social'.",
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
            "The FULL 'Tipo de tarifa Arconel' line, copied verbatim — code and label "
            "together, e.g. 'MTCGCD01 - MT Comercial con Demanda'. Do not shorten it."
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
            "(DD-MM-YYYY). This is the date the bill was issued."
        ),
        json_schema_extra={"x-alternativeNames": ["Fecha de emisión", "Issue Date"]},
    )
    billing_period_from: Optional[str] = Field(
        default=None,
        description=(
            "'Fecha desde' in section '1. Información Servicio Eléctrico y Alumbrado "
            "Público', exactly as printed (DD-MM-YYYY). This is the consumption-window "
            "START — it is NOT 'Fecha de emisión'."
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
            "does not print it (some tariffs omit it entirely)."
        ),
        json_schema_extra={"x-alternativeNames": ["Factor de multiplicación", "Multiplier"]},
    )

    # ---- money boxes (independent cross-check sources) ----
    valor_total: Optional[float] = Field(
        default=None,
        description=(
            "'VALOR TOTAL' from the header area — the grand total the customer owes, "
            "including demand charges, taxes and public lighting. Copy the number as printed."
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
            "'Valor Demanda' from the same 'Servicio Eléctrico y Alumbrado Público' box, "
            "as a number. Null if the bill has no demand charge."
        ),
        json_schema_extra={"x-alternativeNames": ["Valor Demanda", "Demand Value"]},
    )

    # ---- the payload ----
    detail_rows: List[BillDetailRow] = Field(
        default_factory=list,
        description=(
            "EVERY row of the detail table under the 'Descripción / … / Consumo Total / "
            "Unidad Medida / Monto ($)' header, in printed order, transcribed verbatim. "
            "Include rows whose Monto is 0.00, reactive-energy rows and demand rows alike. "
            "Do NOT sum, filter, merge, reorder or skip any row. Do NOT include the "
            "'VALOR TOTAL' figure — it is not a row of this table."
        ),
        json_schema_extra={"x-alternativeNames": ["Detail Rows", "Itemized Charges"]},
    )

    # ---- derived (schema members for target_fields plumbing; LLM leaves null) ----
    total_active_energy_kwh: Optional[float] = Field(default=None, description=_DO_NOT_EXTRACT)
    solar_kwh: Optional[float] = Field(default=None, description=_DO_NOT_EXTRACT)
    grid_kwh: Optional[float] = Field(default=None, description=_DO_NOT_EXTRACT)
    billable_amount_usd: Optional[float] = Field(default=None, description=_DO_NOT_EXTRACT)
    tariff_code: Optional[str] = Field(
        default=None,
        description="Computed server-side from tariff_raw. Do not extract; leave null.",
    )


# =============================================================================
# Normalization helpers
# =============================================================================


def _norm(label: Any) -> str:
    """Accent-strip + casefold + trim — the bill itself mixes 'Energía'/'Energia'."""
    text = "" if label is None else str(label)
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return stripped.casefold().strip()


def _to_float(value: Any) -> Optional[float]:
    """Defensive numeric coercion ($ signs, spaces, comma decimals)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace("$", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        # Whichever separator comes first is the thousands separator.
        if text.find(",") < text.find("."):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        if head and len(tail) == 3:
            text = text.replace(",", "")  # 2,529 → thousands
        else:
            text = text.replace(",", ".")  # 2333,48 → decimal comma
    try:
        return float(text)
    except ValueError:
        return None


def parse_tariff_code(tariff_raw: Any) -> Optional[str]:
    """'MTCGCD01 - MT Comercial con Demanda' → 'MTCGCD01'. None if the line has no code.

    Done in Python because the LLM returned the full label on a live run despite
    an explicit "code only" instruction — an instruction is not a guarantee. This
    is now the ONLY source of the code (T8.12): the model's `tariff_code` slot is
    hard-nulled at normalizer entry, because the code selects the reducer that
    turns a PDF into an irreversible financial record, and a code nobody read off
    the page must never make that choice.

    Two distinct codes on one line is not a tariff we can identify — refuse.
    """
    if not tariff_raw:
        return None
    codes = TARIFF_CODE_RE.findall(str(tariff_raw).upper())
    if not codes:
        return None
    if len(set(codes)) > 1:
        log.warning(
            "cnel_energy_bill: ambiguous tariff line %r (codes %s) — refusing",
            tariff_raw,
            sorted(set(codes)),
        )
        return None
    return codes[0]


# =============================================================================
# The reducer — deterministic, per-tariff, fails closed
# =============================================================================

NET_METERED = "net_metered"
NON_SOLAR = "non_solar"


def _bucket_rows(rows: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    """Assign each row index to a label bucket (energy buckets are KWH-filtered)."""
    buckets: Dict[str, List[int]] = {
        "activa": [],
        "inyectada": [],
        "facturable": [],
        "demanda_facturable": [],
        "reactiva": [],
        "demanda_other": [],
        "unmatched": [],
    }

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            buckets["unmatched"].append(index)
            continue
        label = _norm(row.get("descripcion"))
        unit = _norm(row.get("unidad_medida"))

        if label.startswith(ACTIVA_PREFIXES) and unit in ENERGY_UNITS:
            buckets["activa"].append(index)
        elif label.startswith(INYECTADA_PREFIX) and unit in ENERGY_UNITS:
            buckets["inyectada"].append(index)
        elif label.startswith(FACTURABLE_PREFIX) and unit in ENERGY_UNITS:
            buckets["facturable"].append(index)
        elif label.startswith(DEMANDA_FACTURABLE_PREFIX) and unit in DEMAND_UNITS:
            buckets["demanda_facturable"].append(index)
        elif label.startswith(REACTIVA_PREFIX) or unit in REACTIVE_UNITS:
            buckets["reactiva"].append(index)
        elif label.startswith(DEMANDA_PREFIX) or unit in DEMAND_UNITS:
            buckets["demanda_other"].append(index)
        else:
            buckets["unmatched"].append(index)

    return buckets


def _sum_over(rows: List[Dict[str, Any]], indexes: List[int], key: str) -> float:
    total = 0.0
    for index in indexes:
        value = _to_float(rows[index].get(key))
        if value is not None:
            total += value
    return total


def reduce_detail_rows(
    rows: List[Dict[str, Any]], extracted: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, List[int]], List[str], str]:
    """
    Reduce verbatim detail rows into the derived BillFacts fields.

    Returns ``(derived, provenance, violations, layout)``. A non-empty
    ``violations`` list means REFUSE — the caller must leave the derived
    fields null. Handles both layouts (the solar axis is orthogonal to
    tariff — plan §4.3b):

    - NET-METERED: 'Energia facturable' rows carry the Monto;
      grid = Σ facturable, solar = Σ inyectada, total = activa row(s).
    - NON-SOLAR: no facturable/inyectada rows; the activa row(s) —
      'Energía activa total' or the hourly 'Energía act. hor. A/B/C'
      bands — carry the Monto; solar = 0.
    """
    buckets = _bucket_rows(rows)
    violations: List[str] = []

    if not buckets["activa"]:
        violations.append("no 'Energía activa' rows found in detail_rows")
        return {}, {}, violations, "unknown"

    activa_kwh = _sum_over(rows, buckets["activa"], "consumo_total")

    if buckets["facturable"]:
        layout = NET_METERED
        grid = _sum_over(rows, buckets["facturable"], "consumo_total")
        solar = _sum_over(rows, buckets["inyectada"], "consumo_total")
        billable = _sum_over(rows, buckets["facturable"], "monto")
        total = activa_kwh

        if abs(total - (grid + solar)) > ENERGY_TOLERANCE_KWH:
            violations.append(
                f"energy identity failed: activa {total} != facturable {grid} + inyectada {solar}"
            )
        for index in buckets["inyectada"]:
            monto = _to_float(rows[index].get("monto"))
            if monto not in (None, 0.0):
                violations.append(f"injected-energy row {index} has non-zero Monto {monto}")
        provenance = {
            "total_active_energy_kwh": list(buckets["activa"]),
            "solar_kwh": list(buckets["inyectada"]),
            "grid_kwh": list(buckets["facturable"]),
            "billable_amount_usd": list(buckets["facturable"]),
        }
    elif buckets["inyectada"]:
        # Injected rows without a facturable row — a layout we have never seen.
        violations.append("inyectada rows present but no facturable row (unknown layout)")
        return {}, {}, violations, "unknown"
    else:
        # NON-SOLAR layout: the activa row(s) carry the Monto directly (§4.3b).
        # Whether this is acceptable for an SGDA subscriber is NestJS's call
        # (SOLAR-ZERO decision) — we derive faithfully either way.
        layout = NON_SOLAR
        grid = activa_kwh
        solar = 0.0
        billable = _sum_over(rows, buckets["activa"], "monto")
        total = activa_kwh
        provenance = {
            "total_active_energy_kwh": list(buckets["activa"]),
            "solar_kwh": [],
            "grid_kwh": list(buckets["activa"]),
            "billable_amount_usd": list(buckets["activa"]),
        }

    # --- money cross-checks against the independently-printed box (plan §6) ---
    valor_consumo = _to_float(extracted.get("valor_consumo"))
    if valor_consumo is not None and abs(billable - valor_consumo) > MONEY_TOLERANCE_USD:
        violations.append(
            f"sum of energy Montos {billable:.2f} != Valor Consumo {valor_consumo:.2f}"
        )

    valor_demanda = _to_float(extracted.get("valor_demanda"))
    if valor_demanda is not None and buckets["demanda_facturable"]:
        demanda_monto = _sum_over(rows, buckets["demanda_facturable"], "monto")
        if abs(demanda_monto - valor_demanda) > MONEY_TOLERANCE_USD:
            violations.append(
                f"sum of Demanda facturable Montos {demanda_monto:.2f} != Valor Demanda {valor_demanda:.2f}"
            )

    valor_total = _to_float(extracted.get("valor_total"))
    if valor_total is not None and billable > valor_total + MONEY_TOLERANCE_USD:
        violations.append(f"billable {billable:.2f} exceeds VALOR TOTAL {valor_total:.2f}")

    if grid <= 0:
        violations.append("no billable energy (grid <= 0)")
    elif billable > 0:
        rate = billable / grid
        if not (RATE_BAND_MIN <= rate <= RATE_BAND_MAX):
            violations.append(
                f"effective tariff {rate:.4f} USD/kWh outside plausible band "
                f"[{RATE_BAND_MIN}, {RATE_BAND_MAX}] — possible scale or decimal-separator error"
            )

    derived = {
        "total_active_energy_kwh": round(total, 2),
        "solar_kwh": round(solar, 2),
        "grid_kwh": round(grid, 2),
        "billable_amount_usd": round(billable, 2),
    }
    if buckets["unmatched"]:
        # Telemetry, not failure: learn the real label vocabulary from production.
        labels = [rows[i].get("descripcion") for i in buckets["unmatched"] if isinstance(rows[i], dict)]
        log.info("cnel_energy_bill: unmatched detail rows (telemetry): %s", labels)

    return derived, provenance, violations, layout


# The reducer-owned output fields. The LLM is told to leave them null but does
# NOT reliably comply — live run 2026-07-10 returned 0.0 for every one of these
# (grounded to the activa row's 'Monto 0.00' cell) and the literal string
# 'null' for tariff_code. They are hard-nulled at normalizer entry so no LLM
# guess can ever survive a refusal path (a 0.0 billable would sail through
# NestJS's null-checks and commit zeros into the financial ledger).
DERIVED_FIELDS = (
    "total_active_energy_kwh",
    "solar_kwh",
    "grid_kwh",
    "billable_amount_usd",
)

# Everything the LLM is told to leave null and is not trusted to. `tariff_code`
# joins the four money/energy fields here (T8.12): it is derived from
# `tariff_raw` and nothing else. It used to be exempt — the normalizer fell back
# to the model's guess whenever the raw line failed to parse, which meant the
# one input that SELECTS the reducer was the one input the model could still
# choose. A guess landing on the single enabled code (MTCGCD01) reduced the bill
# into real numbers, passed NestJS's whitelist, and could reach the ledger.
REDUCER_OWNED_FIELDS = DERIVED_FIELDS + ("tariff_code",)

# Per-tariff registry — fail-closed: a code absent here leaves derived null.
# All four CNEL layouts route through the shared reducer today (the buckets are
# label-anchored and layout-aware). Codes are enabled one at a time as a
# NET-METERED sample of each is fixtured (hard gate — plan §8 Phase 2);
# NestJS additionally enforces its own SUPPORTED_TARIFF_CODES guard.
REDUCERS = {
    "MTCGCD01": reduce_detail_rows,
}


# =============================================================================
# Grounding provenance + the normalizer entry point
# =============================================================================


def _collect_row_references(row_meta: Any) -> Tuple[List[Any], Optional[float]]:
    """Pull (references, confidence) out of one detail-row meta entry, defensively.

    Live run 2026-07-10 settled the actual shape (ROW-METAS): each row's meta is
    a dict of PER-CELL metas — ``{"descripcion": {"references": [...], "value": …},
    "monto": {…}, …}`` — so when a dict has no top-level ``references`` we recurse
    into its values and union the cell refs. The flat shape stays supported.
    """
    if isinstance(row_meta, dict):
        if "references" in row_meta:
            references = row_meta.get("references") or []
            if not isinstance(references, list):
                references = [references]
            confidence = row_meta.get("confidence")
            return references, confidence if isinstance(confidence, (int, float)) else None
        # Per-cell shape: union the refs of every cell meta.
        references = []
        confidences: List[float] = []
        for cell_meta in row_meta.values():
            refs, conf = _collect_row_references(cell_meta)
            references.extend(refs)
            if conf is not None:
                confidences.append(conf)
        return references, min(confidences) if confidences else None
    if isinstance(row_meta, list):
        references = []
        confidences = []
        for entry in row_meta:
            refs, conf = _collect_row_references(entry)
            references.extend(refs)
            if conf is not None:
                confidences.append(conf)
        return references, min(confidences) if confidences else None
    return [], None


def _synthesize_grounding(
    extraction_metadata: Dict[str, Any],
    derived: Dict[str, Any],
    provenance: Dict[str, List[int]],
) -> None:
    """Point each derived field's metadata at the detail rows that produced it,
    so `_resolve_field_grounding` gives the FE a bbox on the actual table cells."""
    row_metas = extraction_metadata.get("detail_rows")
    if not isinstance(row_metas, list):
        return  # ROW-METAS shape unavailable — derived fields simply carry no grounding.

    for field, row_indexes in provenance.items():
        references: List[Any] = []
        confidences: List[float] = []
        for index in row_indexes:
            if 0 <= index < len(row_metas):
                refs, conf = _collect_row_references(row_metas[index])
                references.extend(refs)
                if conf is not None:
                    confidences.append(conf)
        if references:
            seen = set()
            unique_refs = []
            for ref in references:
                key = str(ref)
                if key not in seen:
                    seen.add(key)
                    unique_refs.append(ref)
            meta: Dict[str, Any] = {
                "extracted_text": str(derived.get(field)),
                "references": unique_refs,
            }
            if confidences:
                meta["confidence"] = min(confidences)
            extraction_metadata[field] = meta


def _reattach_tariff_grounding(
    extraction_metadata: Dict[str, Any], tariff_code: str
) -> None:
    """Point `tariff_code`'s grounding at the raw line it was parsed from.

    NestJS reads the FE's tariff bbox from this field's metadata, and we drop the
    model's own entry at entry (it grounded a guess). The honest evidence for a
    derived code is the `tariff_raw` line on the page.
    """
    raw_meta = extraction_metadata.get("tariff_raw")
    if not isinstance(raw_meta, dict):
        return
    references = raw_meta.get("references")
    if not references:
        return
    meta: Dict[str, Any] = {"extracted_text": tariff_code, "references": references}
    confidence = raw_meta.get("confidence")
    if isinstance(confidence, (int, float)):
        meta["confidence"] = confidence
    extraction_metadata["tariff_code"] = meta


def normalize_cnel_energy_bill(
    extracted: Dict[str, Any],
    extraction_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Document-type normalizer hook for ``cnel_energy_bill`` (called from
    ``normalize_extracted_document``). Parses the tariff code and computes the
    derived BillFacts from ``detail_rows``; on any refusal the derived fields
    stay null and the reason is logged (NestJS decides the incident).
    """
    extracted = dict(extracted)

    # Hard-null every reducer-owned field FIRST (see REDUCER_OWNED_FIELDS): only
    # this module may fill them, and only on a fully-validated success path.
    for field in REDUCER_OWNED_FIELDS:
        extracted[field] = None
    if isinstance(extraction_metadata, dict):
        # Drop the LLM's own (wrong) grounding for these fields too — otherwise
        # a stale ref (e.g. the activa 'Monto 0.00' cell) survives and the FE
        # highlights the wrong cell. Synthesis re-adds correct refs on success.
        for field in REDUCER_OWNED_FIELDS:
            extraction_metadata.pop(field, None)

    tariff_raw = extracted.get("tariff_raw")
    tariff_code = parse_tariff_code(tariff_raw)
    extracted["tariff_code"] = tariff_code
    if tariff_code is None:
        # No fallback to the model's guess — refuse and say so. A raw line that
        # the model DID read but we cannot parse is the signal that the scan
        # needs widening (deterministically, in review), so log the line itself.
        if tariff_raw:
            log.warning(
                "cnel_energy_bill: no ARCONEL code found in tariff_raw %r — "
                "derived fields left null (widen the parser if this shape is legitimate)",
                tariff_raw,
            )
        else:
            log.warning(
                "cnel_energy_bill: no tariff line captured — derived fields left null"
            )
    elif isinstance(extraction_metadata, dict):
        _reattach_tariff_grounding(extraction_metadata, tariff_code)

    rows = extracted.get("detail_rows")
    if not isinstance(rows, list) or not rows:
        log.warning("cnel_energy_bill: no detail_rows captured — derived fields left null")
        return extracted, extraction_metadata

    rows = [row if isinstance(row, dict) else {} for row in rows]

    if tariff_code is None:
        return extracted, extraction_metadata

    reducer = REDUCERS.get(tariff_code)
    if reducer is None:
        log.warning(
            "cnel_energy_bill: tariff %s has no reducer (fail closed) — derived fields left null",
            tariff_code,
        )
        return extracted, extraction_metadata

    derived, provenance, violations, layout = reducer(rows, extracted)
    if violations:
        log.warning(
            "cnel_energy_bill: invariant violation(s), derived fields left null: %s",
            "; ".join(violations),
        )
        return extracted, extraction_metadata

    log.info(
        "cnel_energy_bill: reduced %s/%s → total=%s solar=%s grid=%s billable=%s",
        tariff_code,
        layout,
        derived["total_active_energy_kwh"],
        derived["solar_kwh"],
        derived["grid_kwh"],
        derived["billable_amount_usd"],
    )
    extracted.update(derived)

    if isinstance(extraction_metadata, dict):
        _synthesize_grounding(extraction_metadata, derived, provenance)

    return extracted, extraction_metadata
