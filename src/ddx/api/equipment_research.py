"""Internal web-research helpers for Project Data Main Equipment Sheets."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("ddx.api.equipment_research")

CURRENT_YEAR = datetime.now().year

# Solar module standards required by business rules
IEC_STANDARDS: List[Dict[str, str]] = [
    {
        "code": "IEC 61215",
        "url_query_template": "latest {current_year} {brand_name} solar module IEC 61215 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC 61730",
        "url_query_template": "latest {current_year} {brand_name} solar module IEC 61730 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC TS 62804",
        "url_query_template": "latest {current_year} {brand_name} solar module PID test IEC TS 62804 certificate validity date official report pdf",
    },
    {
        "code": "IEC 62716",
        "url_query_template": "latest {current_year} {brand_name} solar module IEC 62716 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC 61701",
        "url_query_template": "latest {current_year} {brand_name} solar module IEC 61701 certificate validity date official datasheet pdf",
    },
]

# Inverter standards required by business rules
IEC_INVERTER_STANDARDS: List[Dict[str, str]] = [
    {
        "code": "IEC 62109",
        "url_query_template": "latest {current_year} {brand_name} inverter IEC 62109 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC 61727",
        "url_query_template": "latest {current_year} {brand_name} inverter IEC 61727 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC 61000",
        "url_query_template": "latest {current_year} {brand_name} inverter IEC 61000 certificate validity date official datasheet pdf",
    },
]

SOLAR_MODULE_TESTS: List[Dict[str, str]] = [
    {
        "test_name": "Fabric report test",
        "query_template": "latest {current_year} {brand_name} solar module factory report OR fabrication report test date official pdf",
    }
]

INVERTER_TESTS: List[Dict[str, str]] = [
    {
        "test_name": "Anti-islanding test",
        "query_template": "latest {current_year} {brand_name} inverter anti-islanding test report date IEC 62116 official pdf",
    }
]


def _default_payload(module_brand: Optional[str], inverter_brand: Optional[str]) -> Dict[str, Any]:
    """Build the starting payload for equipment research.

    Repeated fields are pre-populated with one placeholder row per known
    standard/test so that NestJS always writes a variable row (with a
    variableId) even when research cannot run because a brand is missing.
    When research succeeds it calls payload.update(...) which overwrites these
    placeholders with real data.
    """
    return {
        "module_brand": module_brand or "",
        "module_bloomberg": {"rating": "Unknown", "source": ""},
        "module_certificate_evidence": [
            {"standard_code": std["code"], "certificate_name": None, "source": None, "validity_date": None}
            for std in IEC_STANDARDS
        ],
        "module_factory_test_date": None,
        "module_test_evidence": [
            {"test_name": test["test_name"], "source": None, "test_date": None}
            for test in SOLAR_MODULE_TESTS
        ],
        "inverter_brand": inverter_brand or "",
        "inverter_bloomberg": {"rating": "Unknown", "source": ""},
        "inverter_certificate_evidence": [
            {"standard_code": std["code"], "certificate_name": None, "source": None, "validity_date": None}
            for std in IEC_INVERTER_STANDARDS
        ],
        "inverter_test_evidence": [
            {"test_name": test["test_name"], "source": None, "test_date": None}
            for test in INVERTER_TESTS
        ],
    }


def _extract_date_from_text(text: str) -> Optional[str]:
    if not text:
        return None

    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return match.group(0)

    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        return f"{match.group(3)}-{match.group(2).zfill(2)}-{match.group(1).zfill(2)}"

    match = re.search(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(\d{4})",
        text,
        re.IGNORECASE,
    )
    if match:
        month_map = {
            "jan": "01",
            "feb": "02",
            "mar": "03",
            "apr": "04",
            "may": "05",
            "jun": "06",
            "jul": "07",
            "aug": "08",
            "sep": "09",
            "oct": "10",
            "nov": "11",
            "dec": "12",
        }
        month = month_map.get(match.group(1).lower()[:3], "01")
        return f"{match.group(3)}-{month}-{match.group(2).zfill(2)}"

    match = re.search(r"\b(20\d{2})\b", text)
    if match:
        return f"{match.group(1)}-01-01"

    return None


def _run_search(client: Any, query: str, max_results: int = 1) -> List[Any]:
    try:
        search = client.search.create(
            query=query,
            max_results=max_results,
            max_tokens=8192,
            max_tokens_per_page=2048,
            country="US",
        )
        return getattr(search, "results", []) or []
    except Exception as e:
        log.warning("Equipment research search failed: query='%s' error='%s'", query, e)
        return []


def _research_bloomberg(client: Any, brand: str, is_inverter: bool) -> Dict[str, str]:
    equipment_type = "inverter" if is_inverter else "solar module"
    query = (
        f"latest {CURRENT_YEAR} BloombergNEF Tier 1 list {brand} {equipment_type} "
        "qualification rating AAA AA A source"
    )

    results = _run_search(client, query, max_results=1)
    if not results:
        return {"rating": "Unknown", "source": ""}

    first = results[0]
    title = (getattr(first, "title", "") or "").upper()
    source = getattr(first, "url", "") or ""

    rating = "Unknown"
    if "AAA" in title:
        rating = "AAA"
    elif "AA" in title:
        rating = "AA"
    elif " A" in f" {title}" and "BBB" not in title:
        rating = "A"

    return {"rating": rating, "source": source}


def _research_certificates(client: Any, brand: str, is_inverter: bool) -> List[Dict[str, Any]]:
    standards = IEC_INVERTER_STANDARDS if is_inverter else IEC_STANDARDS
    certificates: List[Dict[str, Any]] = []

    for standard in standards:
        query = standard["url_query_template"].format(
            brand_name=brand,
            current_year=CURRENT_YEAR,
        )
        results = _run_search(client, query, max_results=3)

        certificate_name = None
        source = ""
        validity_date = None

        _generic = {"certificate", "pdf certificate", "certifiacte", "document", "datasheet"}

        for result in results:
            title = (getattr(result, "title", "") or "").strip()
            # Skip spaced-out "[PDF] C E R T I F I C A T E" style titles and plain generic words
            if re.sub(r"\s+", " ", title).lower().strip("[]pdf ") in _generic:
                continue
            certificate_name = title or None
            source = getattr(result, "url", "") or ""
            snippet = getattr(result, "snippet", "") or ""
            validity_date = _extract_date_from_text(snippet)
            break

        certificates.append(
            {
                "standard_code": standard["code"],
                "certificate_name": certificate_name,
                "source": source,
                "validity_date": validity_date,
            }
        )
        time.sleep(0.5)

    return certificates


def _research_tests(client: Any, brand: str, is_inverter: bool) -> List[Dict[str, Any]]:
    definitions = INVERTER_TESTS if is_inverter else SOLAR_MODULE_TESTS
    tests: List[Dict[str, Any]] = []

    for test_def in definitions:
        query = test_def["query_template"].format(
            brand_name=brand,
            current_year=CURRENT_YEAR,
        )
        results = _run_search(client, query, max_results=1)

        source = ""
        test_date = None

        if results:
            first = results[0]
            snippet = getattr(first, "snippet", "") or ""
            title = getattr(first, "title", "") or ""
            source = getattr(first, "url", "") or ""
            test_date = _extract_date_from_text(f"{snippet} {title}")

        tests.append(
            {
                "test_name": test_def["test_name"],
                "source": source,
                "test_date": test_date,
            }
        )
        time.sleep(0.5)

    return tests


def _research_module(client: Any, module_brand: str) -> Dict[str, Any]:
    module_bloomberg = _research_bloomberg(client, module_brand, is_inverter=False)
    module_certificate_evidence = _research_certificates(client, module_brand, is_inverter=False)
    module_test_evidence = _research_tests(client, module_brand, is_inverter=False)
    module_factory_test_date = next(
        (
            test.get("test_date")
            for test in module_test_evidence
            if test.get("test_name") == "Fabric report test" and test.get("test_date")
        ),
        None,
    )

    return {
        "module_brand": module_brand,
        "module_bloomberg": module_bloomberg,
        "module_certifications": [c["standard_code"] for c in module_certificate_evidence],
        "module_certificate_evidence": module_certificate_evidence,
        "module_factory_test_date": module_factory_test_date,
        "module_test_evidence": module_test_evidence,
    }


def _research_inverter(client: Any, inverter_brand: str) -> Dict[str, Any]:
    inverter_bloomberg = _research_bloomberg(client, inverter_brand, is_inverter=True)
    inverter_certificate_evidence = _research_certificates(client, inverter_brand, is_inverter=True)
    inverter_test_evidence = _research_tests(client, inverter_brand, is_inverter=True)
    inverter_anti_island_test_date = next(
        (
            test.get("test_date")
            for test in inverter_test_evidence
            if test.get("test_name") == "Anti-islanding test" and test.get("test_date")
        ),
        None,
    )

    return {
        "inverter_brand": inverter_brand,
        "inverter_bloomberg": inverter_bloomberg,
        "inverter_certifications": [c["standard_code"] for c in inverter_certificate_evidence],
        "inverter_certificate_evidence": inverter_certificate_evidence,
        "inverter_anti_island_test_date": inverter_anti_island_test_date,
        "inverter_test_evidence": inverter_test_evidence,
    }


def run_equipment_research(
    module_brand: Optional[str],
    inverter_brand: Optional[str],
) -> Dict[str, Any]:
    """Run web research for module and inverter brands.

    This function never raises, by design. It returns an empty/default payload
    if credentials are missing or research fails.
    """
    payload = _default_payload(module_brand, inverter_brand)

    if not (module_brand or inverter_brand):
        return payload

    api_key = os.getenv("PPLX_API_KEY")
    if not api_key:
        log.warning("PPLX_API_KEY not configured; skipping equipment research")
        return payload

    try:
        from perplexity import Perplexity
    except Exception as e:
        log.warning("Perplexity dependency unavailable; skipping equipment research: %s", e)
        return payload

    try:
        client = Perplexity(api_key=api_key)

        if module_brand:
            payload.update(_research_module(client, module_brand))

        if inverter_brand:
            payload.update(_research_inverter(client, inverter_brand))

        return payload
    except Exception as e:
        log.warning(
            "Equipment research failed for module='%s' inverter='%s': %s",
            module_brand,
            inverter_brand,
            e,
        )
        return payload


async def run_equipment_research_async(
    module_brand: Optional[str],
    inverter_brand: Optional[str],
) -> Dict[str, Any]:
    """Async wrapper that executes research in a worker thread."""
    return await asyncio.to_thread(run_equipment_research, module_brand, inverter_brand)
