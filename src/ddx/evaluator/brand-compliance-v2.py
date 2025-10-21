from __future__ import annotations
import os
import json
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, date
from tavily import TavilyClient
from ddx.llm.client import LLMClient
import requests
import hashlib
import tempfile
import aioboto3
import asyncio
from botocore.config import Config
import sys

sys.encoding = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

S3_BUCKET = os.getenv("S3_BUCKET", "drex-network")


# Certification standards for PV modules
PV_MODULE_STANDARDS = [
    {
        "code": "IEC 61215",
        "description": "Outdoor durability & mechanical integrity",
        "mandatory": True,
    },
    {
        "code": "IEC 61730",
        "description": "Electrical safety",
        "mandatory": True,
    },
    {
        "code": "IEC 62804",
        "description": "PID resistance",
        "mandatory": False,
    },
    {
        "code": "IEC 62716",
        "description": "Ammonia corrosion resistance",
        "mandatory": False,
    },
    {
        "code": "IEC 61701",
        "description": "Salt mist corrosion resistance",
        "mandatory": False,
    },
]


# Certification standards for inverters
INVERTER_STANDARDS = [
    {
        "code": "IEC 62109",
        "description": "Safety requirements for power converters",
        "mandatory": True,
    },
    {
        "code": "IEC 61727",
        "description": "Grid interface and grid code compliance",
        "mandatory": True,
    },
    {
        "code": "IEC 62116",
        "description": "Anti-islanding protection measures",
        "mandatory": True,
    },
    {
        "code": "IEC 61000",
        "description": "Electromagnetic compatibility (EMC)",
        "mandatory": True,
    },
]


async def upload_files_to_s3(
    file_pairs: List[Tuple[str, str]], bucket: Optional[str] = None
) -> List[str]:
    """Upload local files to S3."""
    if not file_pairs:
        return []

    bucket_name = bucket or S3_BUCKET
    if not bucket_name:
        raise ValueError("No S3 bucket specified")

    session = aioboto3.Session()
    cfg = Config(max_pool_connections=int(os.getenv("S3_MAX_POOL", "50")))

    print(f"  Uploading {len(file_pairs)} files to S3 bucket {bucket_name}...")
    async with session.client("s3", config=cfg) as s3:

        async def _upload(local_path: str, s3_path: str) -> str:
            if not os.path.isfile(local_path):
                raise FileNotFoundError(f"Local file not found: {local_path}")

            key = s3_path.lstrip("/")
            await s3.upload_file(local_path, bucket_name, key)
            return f"s3://{bucket_name}/{key}"

        return await asyncio.gather(*(_upload(lp, sp) for lp, sp in file_pairs))


def _llm_client(provider: str, model: str):
    """Initialize LLM client."""
    return LLMClient(provider=provider, model=model or None)


def get_standards_for_product_type(product_type: str) -> List[Dict[str, Any]]:
    """Get relevant certification standards based on product type."""
    if product_type == "solar module":
        return PV_MODULE_STANDARDS
    elif product_type == "inverter":
        return INVERTER_STANDARDS
    else:
        raise ValueError(f"Unknown product type: {product_type}")


def calculate_validity_status(
    valid_until_str: Optional[str],
) -> Tuple[Optional[bool], str, Optional[int]]:
    """
    Calculate certificate validity status.

    Returns:
        (is_valid, validity_status, days_until_expiry)
    """
    if not valid_until_str:
        return None, "unknown", None

    try:
        expiry_date = datetime.strptime(valid_until_str, "%Y-%m-%d").date()
        today = date.today()

        is_valid = today <= expiry_date
        days_until_expiry = (expiry_date - today).days

        if is_valid:
            return True, "valid", days_until_expiry
        else:
            return False, "expired", days_until_expiry

    except Exception as e:
        print(f"  Error parsing date {valid_until_str}: {str(e)}")
        return None, "unknown", None


def download_and_upload_pdf(url: str) -> Optional[str]:
    """
    Download PDF from URL and upload to S3.

    Returns:
        S3 path if successful, None otherwise
    """
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        url_hash = hashlib.md5(url.encode()).hexdigest()
        filename = f"{url_hash}.pdf"
        s3_path = f"/projects/due-diligence/{filename}"
        filepath = DOWNLOAD_DIR / filename

        with open(filepath, "wb") as f:
            f.write(response.content)

        asyncio.run(upload_files_to_s3([(str(filepath), s3_path)], bucket=None))
        os.remove(filepath)

        return s3_path

    except Exception as e:
        print(f"    Failed to download/upload PDF {url}: {str(e)}")
        return None


def analyze_datasheet_with_llm(
    brand_name: str,
    content: str,
    url: str,
    llm_client: LLMClient,
    product_type: str = "solar module",
) -> Dict[str, Any]:
    """
    Analyze technical datasheet for certification information.
    Ensures that certification numbers are present in the key evidence.
    """
    standards = get_standards_for_product_type(product_type)
    standard_codes = [s["code"] for s in standards]
    standard_list = ", ".join(standard_codes)

    prompt = f"""
Analyze this technical datasheet for {brand_name} {product_type}:

Source URL: {url}

Content:
{content}

CRITICAL REQUIREMENTS:
1. This must be a valid technical datasheet/specification document for {brand_name}
2. Look for EXACT mentions of these IEC certification standards: {standard_list}
3. The key_evidence MUST contain the actual IEC standard codes (e.g., "IEC 61215", "IEC 61730")
4. Only mark a certification as found if the EXACT IEC standard code is mentioned (not EN, UL, or other prefixes)
5. IMPORTANT: "EN 61000" is NOT the same as "IEC 61000" - they are different standards!

SPECIFIC SEARCH CRITERIA:
Look for patterns with IEC prefix specifically:
- "IEC 61215" (correct)
- "EN 61215" (wrong - this is EN, not IEC)
- "Certified to IEC 61730" (correct)
- "Complies with IEC 62109" (correct)
- "IEC 62109-1, IEC 62109-2" (correct)
- "EN 61000-6-2" (wrong - this is EN, not IEC)
- "UL 1741" (wrong - this is UL, not IEC)

For {product_type}s, we need to find these EXACT IEC standards:
{chr(10).join([f"- {s['code']}: {s['description']} (MUST have IEC prefix)" for s in standards])}

VALIDATION RULES:
-  Copy the exact text you find - do not modify prefixes
- If the document says "EN 61000-6-2", write "EN 61000-6-2" in key_evidence, NOT "IEC 61000"
- Only accept standards that start with "IEC" prefix
- "EN", "UL", "AS", "JIS" or other prefixes are NOT IEC standards
- For IEC 61000, we need "IEC 61000" not "EN 61000"
- For IEC 62109, both "IEC 62109-1" and "IEC 62109-2" count as IEC 62109

Return a JSON response with this exact structure:
{{
    "is_datasheet": true/false,
    "has_certifications": true/false,
    "brand_match": true/false (does the datasheet match {brand_name}?),
    "certification_numbers": ["IEC 61215", "IEC 61730", ...] (only IEC standards actually found),
    "certificate_numbers": ["cert-123", ...] or [],
    "issue_date": "YYYY-MM-DD format if found, or null",
    "valid_until": "YYYY-MM-DD format if found, or null", 
    "date_source": "exact text where dates were found, or null",
    "key_evidence": "EXACT quotes showing IEC certifications (must include IEC prefix)",
    "certifications_found": {{
        "{standard_codes[0]}": true/false (only true if "IEC" version appears, not EN/UL/etc),
        "{standard_codes[1]}": true/false,
        ...for each standard
    }},
    "confidence": 0.0 to 1.0
}}

Example of VALID key_evidence for inverters:
"IEC 62109-1, IEC 62109-2, IEC 62116, IEC 61727, IEC 61000-6-2"
"Certified to IEC 62109 and IEC 61727 standards"

Example of INVALID key_evidence (wrong prefix):
"EN 61000-6-2, EN 61000-6-3" (These are EN standards, not IEC)
"UL 1741, CSA C22.2" (These are UL/CSA standards, not IEC)
"""

    messages = [
        {
            "role": "system",
            "content": f"You are a technical compliance analyst specializing in {product_type} certifications. You must find EXACT mentions of IEC standard codes in documents. Do not infer or assume certifications - they must be explicitly stated with the standard code. Return only valid JSON.",
        },
        {"role": "user", "content": prompt},
    ]

    try:
        llm_response = llm_client.chat(messages, response_format={"type": "json_object"})
        return json.loads(llm_response)
    except Exception as e:
        print(f"    Error analyzing datasheet: {str(e)}")
        return {
            "is_datasheet": False,
            "has_certifications": False,
            "certification_numbers": [],
            "certifications_found": {},
            "confidence": 0.0,
        }


def analyze_certificate_with_llm(
    brand_name: str,
    content: str,
    url: str,
    llm_client: LLMClient,
    standard_code: str,
    product_type: str = "solar module",
) -> Dict[str, Any]:
    """
    Analyze official certificate for specific standard validity and details.
    """
    prompt = f"""
Analyze this certificate for {brand_name} {product_type}:

Source URL: {url}

Looking for: {standard_code} certification specifically for {brand_name}

Content:
{content}

CRITICAL REQUIREMENTS:
1. This must be an official certificate from a testing lab (not a standard document or guideline)
2. The certificate MUST be specifically for {brand_name} products
3. The brand name "{brand_name}" must appear in the certificate
4. Confirm this certificate is specifically for {standard_code}
5. Do NOT accept generic IEC standard documents, guidelines, or sample certificates

VALIDATION CHECKLIST:
1. Is this an actual certificate (not a standard document)?
2. Does it mention "{brand_name}" explicitly?
3. Is it for {standard_code}?
4. Is it from a recognized testing lab (TÜV, UL, SGS, Intertek, etc.)?

RED FLAGS TO REJECT:
1. Documents that don't mention {brand_name}    

IMPORTANT Instructions:
1. Extract {standard_code} is present in the certificate
2. Find issue date (convert to YYYY-MM-DD)
3. Find expiry/validity date (convert to YYYY-MM-DD)
4. Identify testing laboratory
5. Confirm the certificate explicitly mentions {brand_name}

Return a JSON response with this exact structure:
{{
    "is_valid_certificate": true/false (false if generic standard document),
    "is_correct_standard": true/false (must be for {standard_code}),
    "brand_match": true/false (MUST mention {brand_name}),
    "brand_mentioned": "exact text where {brand_name} is mentioned" or null,
    "certificate_number": "cert-number or null",
    "certification_standard": "{standard_code}" or other standard found,
    "issue_date": "YYYY-MM-DD format if found, or null",
    "valid_until": "YYYY-MM-DD format if found, or null",
    "date_source": "exact text where dates were found, or null",
    "testing_lab": "lab name or null",
    "key_evidence": "specific quote showing {brand_name} and {standard_code} certification",
    "confidence": 0.0 to 1.0,
    "document_type": "certificate" | "standard_document" | "guideline" | "unknown"
}}

IMPORTANT: If this appears to be a generic IEC standard document (like IEC-TS-62804-1-1-2020.pdf) 
rather than a certificate for {brand_name}, return:
{{
    "is_valid_certificate": false,
    "brand_match": false,
    "document_type": "standard_document",
    "confidence": 0.0
}}
"""

    messages = [
        {
            "role": "system",
            "content": f"You are a technical compliance analyst specializing in {product_type} certifications. You must verify that certificates are specifically for {brand_name}, not generic standard documents. Be very strict about brand matching - the certificate must explicitly mention {brand_name}. Return only valid JSON.",
        },
        {"role": "user", "content": prompt},
    ]

    try:
        llm_response = llm_client.chat(messages, response_format={"type": "json_object"})
        analysis = json.loads(llm_response)

        # Additional validation for suspicious URLs
        suspicious_domains = ["standards.iteh.ai", "iso.org", "iec.ch", "webstore.iec.ch"]
        if any(domain in url.lower() for domain in suspicious_domains):
            print(
                f"      ⚠ Suspicious URL detected (likely a standard document, not a certificate)"
            )
            analysis["is_valid_certificate"] = False
            analysis["document_type"] = "standard_document"
            analysis["brand_match"] = False
            analysis["confidence"] = 0.0

        return analysis
    except Exception as e:
        print(f"    Error analyzing certificate: {str(e)}")
        return {
            "is_valid_certificate": False,
            "is_correct_standard": False,
            "brand_match": False,
            "confidence": 0.0,
        }


def search_and_parse_datasheet(
    brand_name: str, tavily: TavilyClient, llm_client: LLMClient, product_type: str = "solar module"
) -> Dict[str, Any]:
    """
    Search for technical datasheet and parse for certifications.
    """
    print(f"\n{'='*60}")
    print(f"PHASE 1: Searching for {brand_name} {product_type} datasheet")
    print(f"{'='*60}")

    # Search queries for datasheets
    queries = [
        f"{brand_name} {product_type} technical datasheet filetype:pdf",
        f"{brand_name} {product_type} specifications datasheet filetype:pdf",
    ]

    for query in queries:
        print(f"  Query: {query}")
        try:
            search_results = tavily.search(
                query=query,
                search_depth="advanced",
                max_results=3,
                include_answer="advanced",
                include_raw_content="text",
            )

            for result in search_results.get("results", []):
                url = result.get("url", "")
                if not url or not url.lower().endswith(".pdf"):
                    continue

                print(f"  Analyzing: {url}")

                raw_content = result.get("raw_content", "") or result.get("content", "")
                if not raw_content:
                    continue

                # Download and upload PDF
                # s3_path = download_and_upload_pdf(url)
                s3_path = "random_s3_path_for_demo.pdf"  # TODO: Uncomment above line in production
                if not s3_path:
                    continue

                # Analyze with LLM
                analysis = analyze_datasheet_with_llm(
                    brand_name, raw_content, url, llm_client, product_type
                )

                print(analysis)

                # Check if datasheet has certifications
                if (
                    analysis.get("is_datasheet")
                    and analysis.get("has_certifications")
                    and analysis.get("confidence", 0) > 0.6
                ):

                    print(f"  ✓ DATASHEET FOUND with certifications!")
                    return {
                        "found": True,
                        "source_type": "datasheet",
                        "pdf_url": url,
                        "s3_path": s3_path,
                        "certification_numbers": analysis.get("certification_numbers", []),
                        "certifications_found": analysis.get("certifications_found", {}),
                        "certificate_numbers": analysis.get("certificate_numbers", []),
                        "issue_date": analysis.get("issue_date"),
                        "valid_until": analysis.get("valid_until"),
                        "date_source": analysis.get("date_source"),
                        "key_evidence": analysis.get("key_evidence", ""),
                        "confidence": analysis.get("confidence", 0.0),
                    }

        except Exception as e:
            print(f"  Error in datasheet search: {str(e)}")
            continue

    print(f"  ✗ No datasheet with certifications found")
    return {"found": False}


def search_for_specific_certificates(
    brand_name: str,
    tavily: TavilyClient,
    llm_client: LLMClient,
    standard_codes: List[str],
    product_type: str = "solar module",
) -> Dict[str, Any]:
    """
    Search for individual certificates for specific standards.
    Ensures certificates are specifically for the given brand.
    """
    certificates_found = {}

    print(f"\n{'='*60}")
    print(f"PHASE 2: Searching for individual {brand_name} {product_type} certificates")
    print("standard codes: " + ", ".join(standard_codes))

    for standard_code in standard_codes:
        print(f"\n  Searching for {standard_code} certificate...")

        # More specific query to find brand-specific certificates
        query = f"{brand_name} {standard_code} certificate filetype:pdf"
        print(f"    Query: {query}")

        try:
            search_results = tavily.search(
                query=query,
                search_depth="advanced",
                max_results=3,  # Check more results to find brand-specific certificate
                include_raw_content="text",
            )

            found_certificate = False

            print(search_results)

            for result in search_results.get("results", []):
                url = result.get("url", "")
                if not url or not url.lower().endswith(".pdf"):
                    continue

                print(f"    Analyzing: {url}")

                raw_content = result.get("raw_content", "") or result.get("content", "")
                if not raw_content:
                    continue

                # Download and upload PDF
                s3_path = (
                    "demo_s3_path_for_certificate.pdf"  # TODO: Uncomment below line in production
                )
                # s3_path = download_and_upload_pdf(url)
                if not s3_path:
                    continue

                # Analyze with LLM
                analysis = analyze_certificate_with_llm(
                    brand_name, raw_content, url, llm_client, standard_code, product_type
                )

                print(analysis)

                # Check if valid certificate for THIS SPECIFIC brand and standard
                if (
                    analysis.get("is_valid_certificate")
                    and analysis.get("is_correct_standard")
                    and analysis.get("brand_match")
                    and analysis.get("confidence", 0) > 0.6
                ):
                    print(f"      ✓ CERTIFICATE FOUND for {brand_name} {standard_code}")
                    if analysis.get("brand_mentioned"):
                        print(
                            f"        Brand verification: {analysis.get('brand_mentioned')[:100]}..."
                        )

                    # Check validity status if date is present (optional now)
                    valid_until = analysis.get("valid_until")
                    is_valid = None
                    validity_status = "unknown"
                    days_until_expiry = None

                    if valid_until:
                        is_valid, validity_status, days_until_expiry = calculate_validity_status(
                            valid_until
                        )
                        if is_valid:
                            print(f"        Valid for {days_until_expiry} more days")
                        else:
                            print(f"        Expired {abs(days_until_expiry)} days ago")
                    else:
                        print(f"        No validity date provided in certificate")

                    certificates_found[standard_code] = {
                        "found": True,
                        "source": "individual_certificate",
                        "pdf_url": url,
                        "s3_path": s3_path,
                        "certificate_number": analysis.get("certificate_number"),
                        "testing_lab": analysis.get("testing_lab"),
                        "issue_date": analysis.get("issue_date"),
                        "valid_until": valid_until,
                        "date_source": analysis.get("date_source"),
                        "is_valid": is_valid,  # Can be None if no validity date
                        "validity_status": validity_status,
                        "days_until_expiry": days_until_expiry,
                        "key_evidence": analysis.get("key_evidence", ""),
                        "confidence": analysis.get("confidence", 0.0),
                        "brand_mentioned": analysis.get("brand_mentioned"),
                    }
                    found_certificate = True
                    break  # Stop searching for this standard once found
                else:
                    # Log why certificate was rejected
                    doc_type = analysis.get("document_type", "unknown")

                    if doc_type == "standard_document":
                        print(
                            f"      ✗ Generic IEC standard document, not a certificate for {brand_name}"
                        )
                    elif not analysis.get("is_valid_certificate"):
                        print(f"      ✗ Not a valid certificate document (type: {doc_type})")
                    elif not analysis.get("brand_match"):
                        print(
                            f"      ✗ Certificate does not mention {brand_name} - likely for another brand or generic"
                        )
                    elif not analysis.get("is_correct_standard"):
                        cert_std = analysis.get("certification_standard", "unknown")
                        print(
                            f"      ✗ Certificate for different standard: {cert_std} (looking for {standard_code})"
                        )
                    elif analysis.get("confidence", 0) <= 0.6:
                        print(f"      ✗ Low confidence: {analysis.get('confidence', 0):.2f}")

            if not found_certificate:
                print(f"      ✗ No valid certificate found for {brand_name} {standard_code}")

        except Exception as e:
            print(f"    Error in certificate search for {standard_code}: {str(e)}")

    return certificates_found


def search_for_bankability(
    brand_name: str, tavily: TavilyClient, llm_client: LLMClient, product_type: str = "solar module"
) -> Dict[str, Any]:
    """
    Search for Bloomberg BNEF Tier 1 bankability status.
    """
    print(f"\n{'='*60}")
    print(f"PHASE 3: Searching for {brand_name} Bankability (Bloomberg Tier 1)")
    print(f"{'='*60}")

    # Different queries for solar modules vs inverters
    if product_type == "solar module":
        queries = [
            f"Bloomberg BNEF Tier 1 {brand_name} solar manufacturer list filetype:pdf",
            f"{brand_name} Bloomberg New Energy Finance Tier 1 solar modules filetype:pdf",
            f"BNEF Tier 1 solar manufacturer {brand_name} 2024 2025 filetype:pdf",
        ]
    else:  # inverter
        queries = [
            f"Bloomberg BNEF {brand_name} inverter manufacturer ranking filetype:pdf",
            f"{brand_name} inverter bankability report filetype:pdf",
        ]

    for query in queries:
        print(f"  Query: {query}")
        try:
            search_results = tavily.search(
                query=query,
                search_depth="advanced",
                max_results=3,
                include_answer="advanced",
                include_raw_content="text",
            )

            for result in search_results.get("results", []):
                url = result.get("url", "")
                if not url or not url.lower().endswith(".pdf"):
                    continue

                print(f"  Analyzing: {url}")

                raw_content = result.get("raw_content", "") or result.get("content", "")
                if not raw_content:
                    continue

                # Download and upload PDF
                # s3_path = download_and_upload_pdf(url)
                s3_path = "random_s3_path_for_demo.pdf"  # TODO: Uncomment above line in production
                if not s3_path:
                    continue

                # Analyze with LLM
                bank_prompt = f"""
                Analyze {brand_name}'s bankability and Bloomberg BNEF Tier 1 status from this PDF document.

                Source PDF URL: {url}

                Content:
                {raw_content}

                CRITICAL REQUIREMENTS:
                1. Look for {brand_name} SPECIFICALLY in the document
                2. The evidence MUST mention {brand_name} explicitly with their tier 1 status or rating
                3. Do not infer - {brand_name} must be explicitly listed or mentioned

                IMPORTANT Instructions:
                1. Look for bankability details including:
                - Bloomberg BNEF Tier 1 status for {brand_name} (true/false)
                - Rating for {brand_name} (AAA, AA, A, BBB, BB, B, CCC, or not_listed)
                - SPECIFIC quotes that mention {brand_name} with their tier 1 status or rating
                - Validity dates (published date and expiry date if mentioned)

                2. Extract all dates in YYYY-MM-DD format

                3. For the evidence field:
                - MUST include {brand_name} name explicitly
                - MUST show their tier 1 status or rating
                - Example good evidence: "{brand_name} is listed as Tier 1 manufacturer in Q3 2024"
                - Example good evidence: "{brand_name} achieved AA rating in Bloomberg BNEF rankings"
                - Example bad evidence: "This report contains Tier 1 manufacturers" (no specific mention of {brand_name})

                4. Provide a brief justification for the bankability status.

                Return a JSON response with this exact structure:
                {{
                    "tier_1_status": true/false (true only if {brand_name} is explicitly listed as Tier 1),
                    "rating": "AAA"|"AA"|"A"|"BBB"|"BB"|"B"|"CCC"|"not_listed",
                    "evidence": "EXACT quote mentioning {brand_name} with their tier 1 status/rating",
                    "published_date": "YYYY-MM-DD format if found, or null",
                    "valid_until": "YYYY-MM-DD format if found, or null",
                    "date_source": "exact text where date was found, or null",
                    "confidence": 0.0 to 1.0,
                    "justification": "brief explanation specifically about {brand_name}'s bankability status"
                }}

                Examples of GOOD evidence:
                - "{brand_name} is included in the Bloomberg New Energy Finance Tier 1 list for Q3 2024"
                - "Tier 1 manufacturers include: JinkoSolar, {brand_name}, Trina Solar..."
                - "{brand_name} maintains its AA rating in the latest BNEF bankability assessment"

                Examples of BAD evidence (too generic):
                - "This document lists Tier 1 manufacturers"
                - "Several manufacturers achieved Tier 1 status"
                - "Top solar companies are rated"
                """

                messages = [
                    {
                        "role": "system",
                        "content": "You are a financial analyst specializing in solar manufacturer bankability. Analyze Bloomberg BNEF Tier 1 lists carefully. Return only valid JSON.",
                    },
                    {"role": "user", "content": bank_prompt},
                ]

                try:
                    llm_response = llm_client.chat(
                        messages, response_format={"type": "json_object"}
                    )
                    bank_analysis = json.loads(llm_response)

                    if (
                        bank_analysis.get("tier_1_status")
                        or bank_analysis.get("rating") != "not_listed"
                    ):
                        if bank_analysis.get("confidence", 0) > 0.5:
                            print(f"  ✓ BANKABILITY INFORMATION FOUND!")

                            rating_scores = {
                                "AAA": 1.0,
                                "AA": 1.0,
                                "A": 1.0,
                                "BBB": 0.75,
                                "BB": 0.75,
                                "B": 0.75,
                                "CCC": 0.5,
                                "not_listed": 0.0,
                            }

                            return {
                                "found": True,
                                "score": rating_scores.get(
                                    bank_analysis.get("rating", "not_listed"), 0.0
                                ),
                                "tier_1": bank_analysis.get("tier_1_status", False),
                                "rating": bank_analysis.get("rating", "not_listed"),
                                "evidence": bank_analysis.get("evidence", "No evidence found"),
                                "source": url,
                                "search_type": "PDF",
                                "published_date": bank_analysis.get("published_date"),
                                "valid_until": bank_analysis.get("valid_until"),
                                "date_source": bank_analysis.get("date_source"),
                                "weight": 0.10,
                                "justification": bank_analysis.get("justification", ""),
                                "confidence": bank_analysis.get("confidence", 0.0),
                                "path": s3_path,
                            }

                except Exception as e:
                    print(f"    Error analyzing bankability PDF: {str(e)}")
                    continue

        except Exception as e:
            print(f"  Error in bankability search: {str(e)}")
            continue

    print(f"  ✗ No bankability information found")
    return {"found": False}


def verify_brand_certifications(
    brand_name: str, product_type: str = "solar module"
) -> Dict[str, Any]:
    """
    Main function to verify brand certifications.
    Modified to match the output format of brand_compliance.py
    """
    print(f"\n{'#'*60}")
    print(f"# BRAND CERTIFICATION VERIFICATION")
    print(f"# Brand: {brand_name}")
    print(f"# Product Type: {product_type}")
    print(f"{'#'*60}")

    # Initialize clients
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise ValueError("TAVILY_API_KEY environment variable not set")

    tavily = TavilyClient(api_key=tavily_api_key)
    llm_client = _llm_client(provider="openai", model=None)

    # Check if it's a solar module or inverter
    if product_type == "solar module":
        # Use the original evaluate_brand_compliance format
        APPROVED_BRANDS = ["Trina Solar", "LONGi Solar", "JA Solar"]

        result = {
            "brand": {
                "name": brand_name,
                "score": 1.0 if brand_name in APPROVED_BRANDS else 0.5,
                "in_approved_list": brand_name in APPROVED_BRANDS,
                "evidence": (
                    "In approved list" if brand_name in APPROVED_BRANDS else "Manually specified"
                ),
            },
            "iec_certificates": {},
            "bankability": {"score": 0.0, "evidence": "Not found", "weight": 0.10},
            "overall_score": 0.0,
        }

        # Get all required standards for this product type
        standards = get_standards_for_product_type(product_type)

        # Search for datasheet
        datasheet_result = search_and_parse_datasheet(brand_name, tavily, llm_client, product_type)

        # Process each standard
        for standard in standards:
            std_code = standard["code"]
            weight = 0.10 if standard["mandatory"] else 0.05  # Match original weights

            # Check if found in datasheet
            if datasheet_result.get("found") and datasheet_result.get(
                "certifications_found", {}
            ).get(std_code):
                result["iec_certificates"][std_code] = {
                    "score": 1.0,
                    "description": standard["description"],
                    "mandatory": standard["mandatory"],
                    "weight": weight,
                    "evidence": datasheet_result.get("key_evidence", "Found in datasheet"),
                    "source": datasheet_result["pdf_url"],
                    "search_type": "PDF",
                    "confidence": datasheet_result.get("confidence", 0.8),
                    "evidence_type": "pdf",
                    "certificate_number": None,
                    "testing_lab": None,
                    "issue_date": datasheet_result.get("issue_date"),
                    "valid_until": datasheet_result.get("valid_until"),
                    "date_source": datasheet_result.get("date_source"),
                    "path": datasheet_result.get("s3_path"),
                }
            else:
                # Search for individual certificate
                individual_certs = search_for_specific_certificates(
                    brand_name, tavily, llm_client, [std_code], "pv module"
                )

                if std_code in individual_certs and individual_certs[std_code].get("found"):
                    # Certificate found - the IEC standard number is confirmed
                    cert = individual_certs[std_code]

                    result["iec_certificates"][std_code] = {
                        "score": 1.0 if cert.get("is_valid") else 0.5,
                        "description": standard["description"],
                        "mandatory": standard["mandatory"],
                        "weight": weight,
                        "evidence": cert.get("key_evidence", "Certificate found"),
                        "source": cert["pdf_url"],
                        "search_type": "PDF",
                        "confidence": cert.get("confidence", 0.8),
                        "evidence_type": "pdf",
                        "certificate_number": cert.get("certificate_number"),
                        "testing_lab": cert.get("testing_lab"),
                        "issue_date": cert.get("issue_date"),
                        "valid_until": cert.get("valid_until"),
                        "date_source": cert.get("date_source"),
                        "path": cert.get("s3_path"),
                    }

                    # Add validity status if available
                    if cert.get("validity_status"):
                        result["iec_certificates"][std_code]["validity_status"] = cert[
                            "validity_status"
                        ]
                        result["iec_certificates"][std_code]["days_until_expiry"] = cert.get(
                            "days_until_expiry"
                        )
                else:
                    # No certificate found with the IEC standard number
                    print(f"  No certificate found for {std_code}")
                    result["iec_certificates"][std_code] = {
                        "score": 0.0,
                        "description": standard["description"],
                        "mandatory": standard["mandatory"],
                        "weight": weight,
                        "evidence": "No evidence found in PDFs or web pages",
                        "source": "N/A",
                        "search_type": "not_found",
                        "confidence": 0.0,
                        "evidence_type": "not_found",
                    }
        bankability_result = search_for_bankability(brand_name, tavily, llm_client, product_type)

        if bankability_result.get("found"):
            result["bankability"] = {
                "score": bankability_result.get("score", 0.0),
                "tier_1": bankability_result.get("tier_1", False),
                "rating": bankability_result.get("rating", "not_listed"),
                "evidence": bankability_result.get("evidence", "No evidence found"),
                "source": bankability_result.get("source", "N/A"),
                "search_type": bankability_result.get("search_type", "not_found"),
                "published_date": bankability_result.get("published_date"),
                "valid_until": bankability_result.get("valid_until"),
                "date_source": bankability_result.get("date_source"),
                "weight": 0.10,
                "justification": bankability_result.get("justification", ""),
                "confidence": bankability_result.get("confidence", 0.0),
                "path": bankability_result.get("path"),
                "evidence_type": "pdf",
            }
        else:
            result["bankability"] = {
                "score": 0.0,
                "tier_1": False,
                "rating": "not_listed",
                "evidence": "No evidence found in PDFs",
                "source": "N/A",
                "search_type": "not_found",
                "published_date": None,
                "valid_until": None,
                "date_source": None,
                "weight": 0.10,
                "justification": "",
                "confidence": 0.0,
                "evidence_type": "not_found",
            }

        # Calculate overall weighted score (matching original calculation)
        total_score = 0.0
        total_weight = 0.0

        for iec_code, iec_data in result["iec_certificates"].items():
            total_score += iec_data["score"] * iec_data["weight"]
            total_weight += iec_data["weight"]

        total_score += result["bankability"]["score"] * result["bankability"]["weight"]
        total_weight += result["bankability"]["weight"]

        # Don't include these in the final result to match original
        # result["overall_score"] = total_score / total_weight if total_weight > 0 else 0.0
        # result["total_weight"] = total_weight

        return result

    elif product_type == "inverter":
        # Use the original evaluate_inverter_compliance format
        APPROVED_INVERTER_BRANDS = [
            "Sungrow",
            "Fronius",
            "SolarEdge",
            "Victron Energy",
            "Deye",
            "Solis",
            "Huawei",
        ]

        result = {
            "inverter_brand": {
                "name": brand_name,
                "score": 1.0 if brand_name in APPROVED_INVERTER_BRANDS else 0.5,
                "in_approved_list": brand_name in APPROVED_INVERTER_BRANDS,
                "evidence": (
                    "In approved inverter list"
                    if brand_name in APPROVED_INVERTER_BRANDS
                    else "Manually specified"
                ),
            },
            "iec_inverter_certificates": {},
            "overall_score": 0.0,
        }

        # Get all required standards for inverters
        standards = get_standards_for_product_type(product_type)

        # Search for datasheet
        datasheet_result = search_and_parse_datasheet(brand_name, tavily, llm_client, product_type)

        # Process each standard
        for standard in standards:
            std_code = standard["code"]
            weight = 0.10  # All inverter standards have 0.10 weight

            # Check if found in datasheet
            if datasheet_result.get("found") and datasheet_result.get(
                "certifications_found", {}
            ).get(std_code):
                result["iec_inverter_certificates"][std_code] = {
                    "score": 1.0,
                    "description": standard["description"],
                    "mandatory": standard["mandatory"],
                    "weight": weight,
                    "evidence": datasheet_result.get("key_evidence", "Found in datasheet"),
                    "source": datasheet_result["pdf_url"],
                    "search_type": "PDF",
                    "confidence": datasheet_result.get("confidence", 0.8),
                    "evidence_type": "pdf",
                    "certificate_number": None,
                    "testing_lab": None,
                    "issue_date": datasheet_result.get("issue_date"),
                    "valid_until": datasheet_result.get("valid_until"),
                    "date_source": datasheet_result.get("date_source"),
                    "path": datasheet_result.get("s3_path"),
                }
            else:
                # Search for individual certificate
                individual_certs = search_for_specific_certificates(
                    brand_name, tavily, llm_client, [std_code], product_type
                )

                if std_code in individual_certs and individual_certs[std_code].get("found"):
                    cert = individual_certs[std_code]
                    result["iec_inverter_certificates"][std_code] = {
                        "score": 1.0 if cert.get("is_valid") else 0.5,
                        "description": standard["description"],
                        "mandatory": standard["mandatory"],
                        "weight": weight,
                        "evidence": cert.get("key_evidence", "Certificate found"),
                        "source": cert["pdf_url"],
                        "search_type": "PDF",
                        "confidence": cert.get("confidence", 0.8),
                        "evidence_type": "pdf",
                        "certificate_number": cert.get("certificate_number"),
                        "testing_lab": cert.get("testing_lab"),
                        "issue_date": cert.get("issue_date"),
                        "valid_until": cert.get("valid_until"),
                        "date_source": cert.get("date_source"),
                        "path": cert.get("s3_path"),
                    }

                    # Add validity status if available
                    if cert.get("validity_status"):
                        result["iec_inverter_certificates"][std_code]["validity_status"] = cert[
                            "validity_status"
                        ]
                        result["iec_inverter_certificates"][std_code]["days_until_expiry"] = (
                            cert.get("days_until_expiry")
                        )
                else:
                    # Not found
                    result["iec_inverter_certificates"][std_code] = {
                        "score": 0.0,
                        "description": standard["description"],
                        "mandatory": standard["mandatory"],
                        "weight": weight,
                        "evidence": "No evidence found in PDFs or web pages",
                        "source": "N/A",
                        "search_type": "not_found",
                        "confidence": 0.0,
                        "evidence_type": "not_found",
                    }

        # Search for warranty certificate
        # Calculate overall score
        total_score = 0.0
        total_weight = 0.0

        total_score += result["inverter_brand"]["score"] * 0.10
        total_weight += 0.10

        for iec_data in result["iec_inverter_certificates"].values():
            total_score += iec_data["score"] * iec_data["weight"]
            total_weight += iec_data["weight"]

        result["overall_score"] = total_score / total_weight if total_weight > 0 else 0.0
        result["total_weight"] = total_weight

        return result
    else:
        raise ValueError(f"Unknown product type: {product_type}")


def main():
    # Example usage
    brand_name = "LONGi Solar"
    product_type = "solar module"  # or "inverter"
    result = verify_brand_certifications(brand_name, product_type)
    print(json.dumps(result, indent=2))

    brand_name = "Fronius"
    product_type = "inverter"
    result = verify_brand_certifications(brand_name, product_type)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
