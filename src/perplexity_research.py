import os
import json
import re
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from perplexity import Perplexity
import sys
from pydantic import BaseModel

sys.encoding = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
CURRENT_YEAR = datetime.now().year

# ============================================================
# Helper Functions
# ============================================================


def extract_date_from_text(text: str) -> Optional[str]:
    """Extract date from text using common date patterns"""
    if not text:
        return None

    # Pattern 1: YYYY-MM-DD
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return match.group(0)

    # Pattern 2: DD/MM/YYYY or MM/DD/YYYY
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        # Assume DD/MM/YYYY format
        return f"{match.group(3)}-{match.group(2).zfill(2)}-{match.group(1).zfill(2)}"

    # Pattern 3: Month DD, YYYY (e.g., "June 15, 2024")
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

    # Pattern 4: YYYY (just year - use as placeholder for validity year)
    match = re.search(r"\b(20\d{2})\b", text)
    if match:
        return f"{match.group(1)}-01-01"  # Default to Jan 1 of that year

    return None


# ============================================================
# Pydantic Models for Research Response
# ============================================================


class BloombergEvidence(BaseModel):
    rating: str
    source: str

    class Config:
        extra = "forbid"


class CertificateEvidence(BaseModel):
    standard_code: str
    certificate_name: Optional[str] = None
    source: str
    validity_date: Optional[str] = None

    class Config:
        extra = "forbid"


class TestEvidence(BaseModel):
    test_name: Optional[str] = None
    source: str
    test_date: Optional[str] = None

    class Config:
        extra = "forbid"


class ProjectDataMainEquipmentSheetsResearch(BaseModel):
    document_type: str = "Project Data Main Equipment Sheets"
    top_level_category: str = "Technical"
    module_brand: str
    module_bloomberg: BloombergEvidence
    module_certifications: List[str]
    module_certificate_evidence: List[CertificateEvidence]
    module_factory_test_date: Optional[str] = None
    module_test_evidence: List[TestEvidence]
    inverter_brand: str
    inverter_bloomberg: BloombergEvidence
    inverter_certifications: List[str]
    inverter_certificate_evidence: List[CertificateEvidence]
    inverter_anti_island_test_date: Optional[str] = None
    inverter_test_evidence: List[TestEvidence]

    class Config:
        extra = "forbid"


# ============================================================
# Standards Definitions for Solar Modules
# ============================================================

IEC_STANDARDS: List[Dict[str, Any]] = [
    {
        "code": "IEC 61215",
        "description": "Crystalline silicon terrestrial photovoltaic modules - Design qualification and type approval",
        "url_query_template": "latest {current_year} {brand_name} solar module IEC 61215 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC 61730",
        "description": "Photovoltaic module safety qualification",
        "url_query_template": "latest {current_year} {brand_name} solar module IEC 61730 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC TS 62804",
        "description": "Photovoltaic modules - Test for the detection of potential-induced degradation",
        "url_query_template": "latest {current_year} {brand_name} solar module PID test IEC TS 62804 certificate validity date official report pdf",
    },
    {
        "code": "IEC 62716",
        "description": "Salt mist corrosion resistance",
        "url_query_template": "latest {current_year} {brand_name} solar module IEC 62716 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC 61701",
        "description": "Cyclic (dynamic mechanical) load test",
        "url_query_template": "latest {current_year} {brand_name} solar module IEC 61701 certificate validity date official datasheet pdf",
    },
]

# ============================================================
# Standards Definitions for Inverters
# ============================================================

IEC_INVERTER_STANDARDS: List[Dict[str, Any]] = [
    {
        "code": "IEC 62109",
        "description": "Safety requirements for power converters",
        "url_query_template": "latest {current_year} {brand_name} inverter IEC 62109 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC 61727",
        "description": "Photovoltaic systems' interface with the grid (grid code compliance)",
        "url_query_template": "latest {current_year} {brand_name} inverter IEC 61727 certificate validity date official datasheet pdf",
    },
    {
        "code": "IEC 61000",
        "description": "Electromagnetic compatibility (EMC)",
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


def get_client() -> Perplexity:
    api_key = os.getenv("PPLX_API_KEY")
    if not api_key:
        raise RuntimeError("Missing PPLX_API_KEY environment variable.")
    return Perplexity(api_key=api_key)


def run_search(client: Perplexity, query: str, max_results: int = 1):
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
        print(f"Search error for query='{query}': {e}", file=sys.stderr)
        return []


def research_bloomberg(
    client: Perplexity, brand: str, is_inverter: bool = False
) -> Optional[BloombergEvidence]:
    """Research Bloomberg rating/list status for current year."""
    equipment_type = "inverter" if is_inverter else "solar module"
    query = (
        f"latest {CURRENT_YEAR} BloombergNEF Tier 1 list {brand} {equipment_type} "
        "qualification rating AAA AA A source"
    )

    results = run_search(client, query, max_results=1)
    if results:
        r = results[0]
        title = getattr(r, "title", "") or ""
        url = getattr(r, "url", "") or ""
        # Extract rating token from title (e.g., "AA", "AAA", "A")
        rating = "Unknown"
        if "AAA" in title.upper():
            rating = "AAA"
        elif "AA" in title.upper():
            rating = "AA"
        elif "A" in title.upper() and "BBB" not in title.upper():
            rating = "A"
        return BloombergEvidence(rating=rating, source=url)
    return None


def research_certificates(
    client: Perplexity, brand: str, is_inverter: bool = False
) -> List[CertificateEvidence]:
    """Research IEC certificates for brand"""
    standards = IEC_INVERTER_STANDARDS if is_inverter else IEC_STANDARDS
    certificates = []

    for std in standards:
        query = std["url_query_template"].format(
            brand_name=brand,
            current_year=CURRENT_YEAR,
        )
        results = run_search(client, query, max_results=1)

        cert_name = None
        source_url = ""
        validity_date = None

        if results:
            r = results[0]
            cert_name = getattr(r, "title", None) or None
            source_url = getattr(r, "url", "") or ""
            # Parse validity date from snippet if available
            snippet = getattr(r, "snippet", "") or ""
            validity_date = extract_date_from_text(snippet)

        cert = CertificateEvidence(
            standard_code=std["code"],
            certificate_name=cert_name,
            source=source_url,
            validity_date=validity_date,
        )
        certificates.append(cert)
        time.sleep(0.5)  # Rate limiting

    return certificates


def research_tests(client: Perplexity, brand: str, is_inverter: bool = False) -> List[TestEvidence]:
    """Research required tests for solar modules or inverters."""
    test_definitions = INVERTER_TESTS if is_inverter else SOLAR_MODULE_TESTS
    tests: List[TestEvidence] = []

    for test_def in test_definitions:
        query = test_def["query_template"].format(
            brand_name=brand,
            current_year=CURRENT_YEAR,
        )
        results = run_search(client, query, max_results=1)

        source_url = ""
        test_date = None

        if results:
            r = results[0]
            snippet = getattr(r, "snippet", "") or ""
            title = getattr(r, "title", "") or ""
            source_url = getattr(r, "url", "") or ""
            test_date = extract_date_from_text(f"{snippet} {title}")

        tests.append(
            TestEvidence(
                test_name=test_def["test_name"],
                source=source_url,
                test_date=test_date,
            )
        )
        time.sleep(0.5)

    return tests


def research_module(client: Perplexity, module_brand: str) -> Dict[str, Any]:
    """Research module evidence using module_* fields."""
    module_bloomberg = research_bloomberg(client, module_brand, is_inverter=False)
    if not module_bloomberg:
        module_bloomberg = BloombergEvidence(rating="Unknown", source="")

    module_certificate_evidence = research_certificates(client, module_brand, is_inverter=False)
    module_test_evidence = research_tests(client, module_brand, is_inverter=False)
    module_factory_test_date = next(
        (
            test.test_date
            for test in module_test_evidence
            if test.test_name == "Fabric report test" and test.test_date
        ),
        None,
    )

    return {
        "module_brand": module_brand,
        "module_bloomberg": module_bloomberg,
        "module_certifications": [cert.standard_code for cert in module_certificate_evidence],
        "module_certificate_evidence": module_certificate_evidence,
        "module_factory_test_date": module_factory_test_date,
        "module_test_evidence": module_test_evidence,
    }


def research_inverter(client: Perplexity, inverter_brand: str) -> Dict[str, Any]:
    """Research inverter evidence using inverter_* fields."""
    inverter_bloomberg = research_bloomberg(client, inverter_brand, is_inverter=True)
    if not inverter_bloomberg:
        inverter_bloomberg = BloombergEvidence(rating="Unknown", source="")

    inverter_certificate_evidence = research_certificates(client, inverter_brand, is_inverter=True)
    inverter_test_evidence = research_tests(client, inverter_brand, is_inverter=True)
    inverter_anti_island_test_date = next(
        (
            test.test_date
            for test in inverter_test_evidence
            if test.test_name == "Anti-islanding test" and test.test_date
        ),
        None,
    )

    return {
        "inverter_brand": inverter_brand,
        "inverter_bloomberg": inverter_bloomberg,
        "inverter_certifications": [cert.standard_code for cert in inverter_certificate_evidence],
        "inverter_certificate_evidence": inverter_certificate_evidence,
        "inverter_anti_island_test_date": inverter_anti_island_test_date,
        "inverter_test_evidence": inverter_test_evidence,
    }


def main():
    # Accept command-line arguments or prompt user
    if len(sys.argv) >= 3:
        solar_brand = sys.argv[1]
        inverter_brand = sys.argv[2]
    else:
        print("Usage: python perplexity_research.py <solar_brand> <inverter_brand>")
        print("Example: python perplexity_research.py 'Trina Solar' 'Huawei'")
        print()
        solar_brand = input("Enter solar module brand: ").strip()
        inverter_brand = input("Enter inverter brand: ").strip()

    if not solar_brand or not inverter_brand:
        print("Error: Both solar brand and inverter brand required", file=sys.stderr)
        sys.exit(1)

    client = get_client()

    # Research both brands
    print(f"Researching solar module: {solar_brand}", file=sys.stderr)
    module_research = research_module(client, solar_brand)

    time.sleep(1)  # Delay between brand searches

    print(f"Researching inverter: {inverter_brand}", file=sys.stderr)
    inverter_research = research_inverter(client, inverter_brand)

    # Build response
    response = ProjectDataMainEquipmentSheetsResearch(
        **module_research,
        **inverter_research,
    )

    # Output JSON to stdout
    print(json.dumps(response.model_dump(), indent=2))


if __name__ == "__main__":
    main()
