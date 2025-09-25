from __future__ import annotations
import os
import json
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from tavily import TavilyClient
from ddx.llm.client import LLMClient
import requests
import hashlib
import tempfile


DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# os.environ["TAVILY_API_KEY"] = "your-tavily-api-key"
# os.environ["OPENAI_API_KEY"] = "your-openai-api-key"

import aioboto3
import asyncio
from botocore.config import Config
import os

# Set S3 bucket
S3_BUCKET = os.getenv("S3_BUCKET", "drex-network")  # Default or from env


async def upload_files_to_s3(
    file_pairs: List[Tuple[str, str]], bucket: Optional[str] = None
) -> List[str]:
    """
    Upload local files to S3.

    Args:
        file_pairs: List of (local_path, s3_path) tuples. s3_path should be the key within the bucket.
        bucket: Optional override for the S3 bucket. Falls back to S3_BUCKET.

    Returns:
        List of S3 URIs for the uploaded files.
    """
    if not file_pairs:
        return []

    bucket_name = bucket or S3_BUCKET
    if not bucket_name:
        raise ValueError("No S3 bucket specified")

    session = aioboto3.Session()
    cfg = Config(max_pool_connections=int(os.getenv("S3_MAX_POOL", "50")))

    print(f"Uploading {len(file_pairs)} files to S3 bucket {bucket_name}...")
    async with session.client("s3", config=cfg) as s3:

        async def _upload(local_path: str, s3_path: str) -> str:
            if not os.path.isfile(local_path):
                raise FileNotFoundError(f"Local file not found: {local_path}")

            key = s3_path.lstrip("/")
            await s3.upload_file(local_path, bucket_name, key)
            return f"s3://{bucket_name}/{key}"

        return await asyncio.gather(*(_upload(lp, sp) for lp, sp in file_pairs))


def _llm_client(provider: str, model: str):
    return LLMClient(provider=provider, model=model or None)


def evaluate_brand_compliance(brand_name: str) -> Dict[str, Any]:
    """
    Evaluate solar panel brand compliance through web search and document analysis.
    """

    # Initialize Tavily
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise ValueError("TAVILY_API_KEY environment variable not set")

    tavily = TavilyClient(api_key=tavily_api_key)
    llm_client = _llm_client(provider="openai", model=None)

    APPROVED_BRANDS = ["Trina Solar", "LONGi Solar", "JA Solar"]

    # Initialize result structure
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
        "factory_reports": {"score": 0.0, "evidence": "Not found", "weight": 0.10},
        "bankability": {"score": 0.0, "evidence": "Not found", "weight": 0.10},
        "overall_score": 0.0,
    }

    # Define IEC standards to check
    iec_standards = [
        {
            "code": "IEC 61215",
            "description": "Outdoor durability & mechanical integrity",
            "mandatory": True,
            "weight": 0.10,
            "pdf_query": f"IEC 61215 {brand_name} solar module certification filetype:pdf",
            "url_query": f"Does {brand_name} solar module have IEC 61215 certification? -filetype:pdf",
        },
        {
            "code": "IEC 61730",
            "description": "Electrical safety",
            "mandatory": True,
            "weight": 0.10,
            "pdf_query": f"IEC 61730 {brand_name} solar module electrical safety certification filetype:pdf",
            "url_query": f"Does {brand_name} solar module comply with IEC 61730 electrical safety standard? -filetype:pdf",
        },
        {
            "code": "IEC TS 62804",
            "description": "PID resistance",
            "mandatory": False,
            "weight": 0.05,
            "pdf_query": f"IEC TS 62804 {brand_name} solar module PID resistance test report filetype:pdf",
            "url_query": f"Is {brand_name} solar module tested for IEC TS 62804 PID resistance? -filetype:pdf",
        },
        {
            "code": "IEC 62716",
            "description": "Ammonia corrosion resistance",
            "mandatory": False,
            "weight": 0.05,
            "pdf_query": f"IEC 62716 {brand_name} solar module ammonia corrosion resistance certification filetype:pdf",
            "url_query": f"Does {brand_name} solar module comply with IEC 62716 ammonia corrosion resistance? -filetype:pdf",
        },
        {
            "code": "IEC 61701",
            "description": "Salt mist corrosion resistance",
            "mandatory": False,
            "weight": 0.05,
            "pdf_query": f"IEC 61701 {brand_name} solar module salt mist corrosion resistance certification filetype:pdf",
            "url_query": f"Does {brand_name} solar module comply with IEC 61701 salt mist corrosion resistance? -filetype:pdf",
        },
    ]

    # Search and evaluate each IEC standard with fallback strategy
    for iec in iec_standards:
        print(f"Searching for {iec['code']}...")

        found_evidence = False
        final_analysis = None
        used_url = "N/A"
        search_type = "not_found"

        # STEP 1: First try searching for PDFs
        print(f"  Step 1: Searching for PDF certificates...")
        pdf_search_results = tavily.search(
            query=iec["pdf_query"],
            search_depth="advanced",
            max_results=3,
            include_answer="advanced",
            include_raw_content="text",
        )

        # Try each PDF result
        for sr in pdf_search_results.get("results", []):
            url = sr.get("url", "")
            if not url or url == "N/A":
                continue

            # Check if URL is actually a PDF
            if not url.lower().endswith(".pdf"):
                continue

            raw_content = sr.get("raw_content", "")
            if not raw_content:
                raw_content = sr.get("content", "")

            if not raw_content:
                continue

            path = None
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                url_hash = hashlib.md5(url.encode()).hexdigest()
                filename = f"{url_hash}.pdf"
                path = f"/projects/due-diligence/{filename}"
                filepath = DOWNLOAD_DIR / filename
                with open(filepath, "wb") as f:
                    f.write(response.content)

                s3_path = asyncio.run(upload_files_to_s3([(str(filepath), path)], bucket=None))

                os.remove(filepath)  # Clean up local file after upload
            except Exception as e:
                print(f"    Failed to download PDF {url}: {str(e)}")
                continue  # Skip if cannot download

            # Analyze PDF content with LLM
            analysis_prompt = f"""
            Analyze the following PDF content to determine if {brand_name} has {iec['code']} certification.
            
            Standard: {iec['code']} - {iec['description']}
            
            Source PDF URL: {url}
            
            PDF Content:
            {raw_content}
            
            IMPORTANT Instructions:
            1. Look for certification details including:
               - Certificate number
               - Testing laboratory (TÜV, UL, SGS, Intertek, etc.)
               - Product model/series covered
               - Validity dates (issue date and expiry date)
            
            2. For validity dates, look for:
               - "Valid until", "Validity", "Expiry date", "Valid from... to..."
               - Certificate issue date and duration
               - Any expiration or renewal dates
            
            3. Extract all dates in YYYY-MM-DD format

            4. Provide a brief justification for the certification status based on the content analysis.

            5. Provide a confidence score from 0.0 to 1.0 based on the evidence found.
            
            Return a JSON response with this exact structure:
            {{
                "has_certification": true/false,
                "confidence": 0.0 to 1.0,
                "evidence_type": "certificate"|"datasheet"|"test_report"|"not_found",
                "certificate_number": "certificate number if found, or null",
                "testing_lab": "name of testing laboratory if found, or null",
                "key_evidence": "specific quote showing certification",
                "issue_date": "YYYY-MM-DD format if found, or null",
                "valid_until": "YYYY-MM-DD format if found, or null",
                "date_source": "exact text where dates were found, or null"
                "justification": "brief explanation of why this is the correct certificate based on the content"

            }}
            """

            messages = [
                {
                    "role": "system",
                    "content": "You are a technical compliance analyst specializing in solar panel certifications. Analyze PDF certificates carefully, extract all relevant details including validity dates. Return only valid JSON.",
                },
                {"role": "user", "content": analysis_prompt},
            ]

            try:
                llm_response = llm_client.chat(messages, response_format={"type": "json_object"})
                analysis = json.loads(llm_response)

                if (
                    analysis.get("evidence_type") != "not_found"
                    and analysis.get("confidence", 0) > 0.3
                ):
                    found_evidence = True
                    final_analysis = analysis
                    final_analysis["path"] = path  # Add path
                    used_url = url
                    search_type = "PDF"
                    break

            except Exception as e:
                print(f"    Error analyzing PDF {url}: {str(e)}")
                continue

        # STEP 2: Store results based on what was found
        if found_evidence and final_analysis:
            score = 0.0
            if final_analysis.get("has_certification"):
                score = 1.0
            result["iec_certificates"][iec["code"]] = {
                "score": score,
                "description": iec["description"],
                "mandatory": iec["mandatory"],
                "weight": iec["weight"],
                "evidence": final_analysis.get("key_evidence", "No evidence found"),
                "source": used_url,
                "search_type": search_type,
                "confidence": final_analysis.get("confidence", 0.0),
                "evidence_type": final_analysis.get("evidence_type"),
                "justification": final_analysis.get("justification", ""),
            }

            # Add PDF-specific fields if from PDF
            if search_type == "PDF":
                result["iec_certificates"][iec["code"]].update(
                    {
                        "certificate_number": final_analysis.get("certificate_number"),
                        "testing_lab": final_analysis.get("testing_lab"),
                        "issue_date": final_analysis.get("issue_date"),
                        "valid_until": final_analysis.get("valid_until"),
                        "date_source": final_analysis.get("date_source"),
                        "path": final_analysis.get("path"),  # Add path
                    }
                )
            else:
                # URL search results
                result["iec_certificates"][iec["code"]].update(
                    {
                        "published_date": final_analysis.get("published_date"),
                        "date_source": final_analysis.get("date_source"),
                    }
                )

        else:
            print(f"  No evidence found for {iec['code']} after PDF and URL searches")
            result["iec_certificates"][iec["code"]] = {
                "score": 0.0,
                "description": iec["description"],
                "mandatory": iec["mandatory"],
                "weight": iec["weight"],
                "evidence": "No evidence found in PDFs or web pages",
                "source": "N/A",
                "search_type": "not_found",
                "confidence": 0.0,
                "evidence_type": "not_found",
            }

    # Search for Bankability (Bloomberg Tier 1) with PDF fallback
    print("Searching for Bankability...")

    # First try PDF search for bankability
    bankability_pdf_query = (
        f"Bloomberg BNEF Tier 1 {brand_name} solar manufacturer list filetype:pdf"
    )
    bank_pdf_search = tavily.search(
        query=bankability_pdf_query,
        search_depth="advanced",
        max_results=2,
        include_answer="advanced",
        include_raw_content="text",
    )

    found_bank = False
    bank_search_type = "not_found"

    # Try PDF results first
    for sr in bank_pdf_search.get("results", []):
        url = sr.get("url", "")
        if not url or url == "N/A" or not url.lower().endswith(".pdf"):
            continue

        raw_content = sr.get("raw_content", "")
        if not raw_content:
            raw_content = sr.get("content", "")

        if not raw_content:
            continue
        path = None
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            url_hash = hashlib.md5(url.encode()).hexdigest()
            filename = f"{url_hash}.pdf"
            path = f"/projects/due-diligence/{filename}"
            filepath = DOWNLOAD_DIR / filename
            with open(filepath, "wb") as f:
                f.write(response.content)

            s3_path = asyncio.run(upload_files_to_s3([(str(filepath), path)], bucket=None))

            os.remove(filepath)  # Clean up local file after upload
        except Exception as e:
            print(f"    Failed to download PDF {url}: {str(e)}")
            continue  # Skip if cannot download

        bank_prompt = f"""
        Analyze {brand_name}'s bankability and Bloomberg BNEF Tier 1 status from this PDF document.

        Source PDF URL: {url}

        Content:
        {raw_content}

        IMPORTANT Instructions:
        1. Look for bankability details including:
        - Bloomberg BNEF Tier 1 status (true/false)
        - Rating (AAA, AA, A, BBB, BB, B, CCC, or not_listed)
        - Specific quotes about the brand's tier 1 status or rating
        - Validity dates (published date and expiry date if mentioned)

        2. For validity dates, look for:
        - "Published", "Updated", "Valid until", "Expiry date"
        - Any date formats and convert to YYYY-MM-DD

        3. Extract all dates in YYYY-MM-DD format

        4. Provide a brief justification for the bankability status based on the content analysis.

        5. Provide a confidence score from 0.0 to 1.0 based on the evidence found.

        Return a JSON response with this exact structure:
        {{
            "tier_1_status": true/false,
            "rating": "AAA"|"AA"|"A"|"BBB"|"BB"|"B"|"CCC"|"not_listed",
            "evidence": "specific quote about tier 1 status or rating",
            "published_date": "YYYY-MM-DD format if found, or null",
            "valid_until": "YYYY-MM-DD format if found, or null",
            "date_source": "exact text where date was found, or null",
            "confidence": 0.0 to 1.0,
            "justification": "brief explanation of the bankability status based on the content"
        }}
        """

        messages = [
            {
                "role": "system",
                "content": "Analyze solar manufacturer bankability from PDF documents. Extract dates and validity periods. Return only valid JSON.",
            },
            {"role": "user", "content": bank_prompt},
        ]

        try:
            llm_response = llm_client.chat(messages, response_format={"type": "json_object"})
            bank_analysis = json.loads(llm_response)

            if bank_analysis.get("tier_1_status") or bank_analysis.get("rating") != "not_listed":
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

                result["bankability"] = {
                    "score": rating_scores.get(bank_analysis.get("rating", "not_listed"), 0.0),
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
                    "path": path,  # Add path
                }
                found_bank = True
                bank_search_type = "PDF"
                break

        except Exception as e:
            print(f"  Error analyzing PDF {url}: {str(e)}")
            continue

    if not found_bank:
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
        }

    # Calculate overall weighted score
    total_score = 0.0
    total_weight = 0.0

    for iec_code, iec_data in result["iec_certificates"].items():
        total_score += iec_data["score"] * iec_data["weight"]
        total_weight += iec_data["weight"]

    total_score += result["bankability"]["score"] * result["bankability"]["weight"]
    total_weight += result["bankability"]["weight"]

    # result["overall_score"] = total_score / total_weight if total_weight > 0 else 0.0
    # result["total_weight"] = total_weight

    return result


def evaluate_inverter_compliance(inverter_brand: str) -> Dict[str, Any]:
    """
    Evaluate solar inverter brand compliance through web search and document analysis.
    """

    # Initialize Tavily
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        raise ValueError("TAVILY_API_KEY environment variable not set")

    tavily = TavilyClient(api_key=tavily_api_key)
    llm_client = _llm_client(provider="openai", model=None)

    APPROVED_INVERTER_BRANDS = [
        "Sungrow",
        "Fronius",
        "SolarEdge",
        "Victron Energy",
        "Deye",
        "Solis",
        "Huawei",
    ]

    # Initialize result structure
    result = {
        "inverter_brand": {
            "name": inverter_brand,
            "score": 1.0 if inverter_brand in APPROVED_INVERTER_BRANDS else 0.5,
            "in_approved_list": inverter_brand in APPROVED_INVERTER_BRANDS,
            "evidence": (
                "In approved inverter list"
                if inverter_brand in APPROVED_INVERTER_BRANDS
                else "Manually specified"
            ),
        },
        "iec_inverter_certificates": {},
        "overall_score": 0.0,
    }

    # Define IEC inverter standards with both PDF and URL queries
    iec_inverter_standards = [
        {
            "code": "IEC 62109",
            "description": "Safety requirements for power converters used in photovoltaic systems",
            "mandatory": True,
            "weight": 0.10,
            "pdf_query": f"IEC 62109 {inverter_brand} inverter safety certification filetype:pdf",
            "url_query": f"Does {inverter_brand} inverter comply with IEC 62109 safety standard? -filetype:pdf",
        },
        {
            "code": "IEC 61727",
            "description": "Photovoltaic systems' interface with the grid (grid code compliance)",
            "mandatory": True,
            "weight": 0.10,
            "pdf_query": f"IEC 61727 {inverter_brand} inverter grid code certification filetype:pdf",
            "url_query": f"Does {inverter_brand} inverter comply with IEC 61727 grid code standard? -filetype:pdf",
        },
        {
            "code": "IEC 62116",
            "description": "Test procedure for anti-islanding protection measures",
            "mandatory": True,
            "weight": 0.10,
            "pdf_query": f"IEC 62116 {inverter_brand} inverter anti-islanding test report filetype:pdf",
            "url_query": f"Is {inverter_brand} inverter tested for IEC 62116 anti-islanding protection? -filetype:pdf",
        },
        {
            "code": "IEC 61000",
            "description": "Electromagnetic compatibility (EMC)",
            "mandatory": True,
            "weight": 0.10,
            "pdf_query": f"IEC 61000 {inverter_brand} inverter EMC certification filetype:pdf",
            "url_query": f"Does {inverter_brand} inverter comply with IEC 61000 EMC requirements? -filetype:pdf",
        },
    ]

    # Search and evaluate each IEC inverter standard with fallback
    for iec in iec_inverter_standards:
        print(f"Searching for inverter {iec['code']} compliance...")

        found_evidence = False
        final_analysis = None
        used_url = "N/A"
        search_type = "not_found"

        # STEP 1: First try searching for PDFs
        print(f"  Step 1: Searching for PDF certificates...")
        pdf_search_results = tavily.search(
            query=iec["pdf_query"],
            search_depth="advanced",
            max_results=3,
            include_answer="advanced",
            include_raw_content="text",
        )

        # Try each PDF result
        for sr in pdf_search_results.get("results", []):
            url = sr.get("url", "")
            if not url or url == "N/A":
                continue

            # Check if URL is actually a PDF
            if not url.lower().endswith(".pdf"):
                continue

            raw_content = sr.get("raw_content", "")
            if not raw_content:
                raw_content = sr.get("content", "")

            if not raw_content:
                continue

            path = None
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                url_hash = hashlib.md5(url.encode()).hexdigest()
                filename = f"{url_hash}.pdf"
                path = f"/projects/due-diligence/{filename}"
                filepath = DOWNLOAD_DIR / filename
                with open(filepath, "wb") as f:
                    f.write(response.content)

                s3_path = asyncio.run(upload_files_to_s3([(str(filepath), path)], bucket=None))

                os.remove(filepath)  # Clean up local file after upload
            except Exception as e:
                print(f"    Failed to download PDF {url}: {str(e)}")
                continue  # Skip if cannot download

            print(f"    Analyzing PDF: {url}")

            # Analyze PDF content with LLM
            analysis_prompt = f"""
            Analyze the following PDF content to determine if {inverter_brand} has {iec['code']} certification.
            
            Standard: {iec['code']} - {iec['description']}
            
            Source PDF URL: {url}
            
            PDF Content:
            {raw_content}
            
            IMPORTANT Instructions:
            1. Look for certification details including:
               - Certificate number
               - Testing laboratory (TÜV, UL, SGS, Intertek, etc.)
               - Product model/series covered
               - Validity dates (issue date and expiry date)
            
            2. For validity dates, look for:
               - "Valid until", "Validity", "Expiry date", "Valid from... to..."
               - Certificate issue date and duration
               - Any expiration or renewal dates
            
            3. Extract all dates in YYYY-MM-DD format

            4. Provide a brief justification for the certification status based on the content analysis.

            5. Provide a confidence score from 0.0 to 1.0 based on the evidence found.
            
            Return a JSON response with this exact structure:
            {{
                "has_certification": true/false,
                "confidence": 0.0 to 1.0,
                "evidence_type": "certificate"|"datasheet"|"test_report"|"not_found",
                "certificate_number": "certificate number if found, or null",
                "testing_lab": "name of testing laboratory if found, or null",
                "key_evidence": "specific quote showing certification",
                "issue_date": "YYYY-MM-DD format if found, or null",
                "valid_until": "YYYY-MM-DD format if found, or null",
                "date_source": "exact text where dates were found, or null"
                "justification": "brief explanation of why this is the correct certificate based on the content"

            }}
            """

            messages = [
                {
                    "role": "system",
                    "content": "You are a technical compliance analyst specializing in solar inverter certifications. Analyze PDF certificates carefully. Return only valid JSON.",
                },
                {"role": "user", "content": analysis_prompt},
            ]

            try:
                llm_response = llm_client.chat(messages, response_format={"type": "json_object"})
                analysis = json.loads(llm_response)

                if (
                    analysis.get("evidence_type") != "not_found"
                    and analysis.get("confidence", 0) > 0.3
                ):
                    found_evidence = True
                    final_analysis = analysis
                    used_url = url
                    final_analysis["path"] = path  # Add path
                    search_type = "PDF"
                    break

            except Exception as e:
                print(f"    Error analyzing PDF {url}: {str(e)}")
                continue

        if found_evidence and final_analysis:
            score = 0.0
            if final_analysis.get("has_certification"):
                score = 1.0

            result["iec_inverter_certificates"][iec["code"]] = {
                "score": score,
                "description": iec["description"],
                "mandatory": iec["mandatory"],
                "weight": iec["weight"],
                "evidence": final_analysis.get("key_evidence", "No evidence found"),
                "source": used_url,
                "search_type": search_type,
                "confidence": final_analysis.get("confidence", 0.0),
                "evidence_type": final_analysis.get("evidence_type"),
                "justification": final_analysis.get("justification", ""),
            }

            # Add PDF-specific fields if from PDF
            if search_type == "PDF":
                result["iec_inverter_certificates"][iec["code"]].update(
                    {
                        "certificate_number": final_analysis.get("certificate_number"),
                        "testing_lab": final_analysis.get("testing_lab"),
                        "issue_date": final_analysis.get("issue_date"),
                        "valid_until": final_analysis.get("valid_until"),
                        "date_source": final_analysis.get("date_source"),
                        "path": final_analysis.get("path"),  # Add path
                    }
                )
            else:
                # URL search results
                result["iec_inverter_certificates"][iec["code"]].update(
                    {
                        "published_date": final_analysis.get("published_date"),
                        "date_source": final_analysis.get("date_source"),
                    }
                )

        else:
            print(f"  No evidence found for {iec['code']} after PDF and URL searches")
            result["iec_inverter_certificates"][iec["code"]] = {
                "score": 0.0,
                "description": iec["description"],
                "mandatory": iec["mandatory"],
                "weight": iec["weight"],
                "evidence": "No evidence found in PDFs or web pages",
                "source": "N/A",
                "search_type": "not_found",
                "confidence": 0.0,
                "evidence_type": "not_found",
            }
    print("Searching for inverter warranty certificates...")

    warranty_pdf_query = f"{inverter_brand} inverter warranty certificate filetype:pdf"
    warranty_results = tavily.search(
        query=warranty_pdf_query,
        search_depth="advanced",
        max_results=3,
        include_answer="advanced",
        include_raw_content="text",
    )

    found_warranty = False
    final_warranty: Optional[Dict[str, Any]] = None
    warranty_source = "N/A"
    warranty_path = None

    for sr in warranty_results.get("results", []):
        url = sr.get("url", "")
        if not url or url == "N/A" or not url.lower().endswith(".pdf"):
            continue

        raw_content = sr.get("raw_content", "") or sr.get("content", "")
        if not raw_content:
            continue

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            url_hash = hashlib.md5(url.encode()).hexdigest()
            filename = f"{url_hash}.pdf"
            warranty_path = f"/projects/due-diligence/{filename}"
            filepath = DOWNLOAD_DIR / filename
            with open(filepath, "wb") as f:
                f.write(response.content)

            asyncio.run(upload_files_to_s3([(str(filepath), warranty_path)], bucket=None))
            os.remove(filepath)
        except Exception as e:
            print(f"  Failed to download warranty PDF {url}: {str(e)}")
            continue

        warranty_prompt = f"""
        Analyze the following PDF content to determine the warranty terms for {inverter_brand} inverters.

        Source PDF URL: {url}

        Content:
        {raw_content}

        IMPORTANT Instructions:
        1. Identify the warranty duration (in years) for the inverter.
        2. Look for terms like "Standard warranty", "Product warranty", "Performance warranty".
        3. Confirm if the warranty duration is at least 10 years.
        4. Extract any warranty-related dates (convert to YYYY-MM-DD).
        5. Provide page number(s) where the warranty statement appears.
        6. Provide a brief justification and confidence score (0.0-1.0).

        Return a JSON response with this exact structure:
        {{
            "has_warranty": true/false,
            "confidence": 0.0 to 1.0,
            "warranty_years": number or null,
            "evidence": "specific quote describing the warranty duration",
            "issue_date": "YYYY-MM-DD format if found, or null",
            "valid_until": "YYYY-MM-DD format if found, or null",
            "date_source": "exact text where dates were found, or null",
            "page_number": [1, 2] or null,
            "justification": "brief explanation of the warranty status based on the content"
        }}
        """

        messages = [
            {
                "role": "system",
                "content": "You are a compliance analyst focused on inverter warranty verification. Return only valid JSON.",
            },
            {"role": "user", "content": warranty_prompt},
        ]

        try:
            llm_response = llm_client.chat(messages, response_format={"type": "json_object"})
            analysis = json.loads(llm_response)

            if analysis.get("has_warranty"):
                found_warranty = True
                final_warranty = analysis
                warranty_source = url
                break

        except Exception as e:
            print(f"  Error analyzing warranty PDF {url}: {str(e)}")
            continue

    if found_warranty and final_warranty:
        warranty_years = final_warranty.get("warranty_years") or 0
        score = 1.0 if warranty_years and warranty_years >= 10 else 0.0

        result["warranty_certificate"] = {
            "score": score,
            "requirement": "Warranty ≥ 10 years",
            "weight": 0.05,
            "evidence": final_warranty.get("evidence", "No evidence found"),
            "source": warranty_source,
            "search_type": "PDF",
            "confidence": final_warranty.get("confidence", 0.0),
            "justification": final_warranty.get("justification", ""),
            "warranty_years": warranty_years,
            "issue_date": final_warranty.get("issue_date"),
            "valid_until": final_warranty.get("valid_until"),
            "date_source": final_warranty.get("date_source"),
            "page_number": final_warranty.get("page_number"),
            "path": warranty_path,
        }
    else:
        result["warranty_certificate"] = {
            "score": 0.0,
            "requirement": "Warranty ≥ 10 years",
            "weight": 0.05,
            "evidence": "No evidence found in PDFs",
            "source": "N/A",
            "search_type": "not_found",
            "confidence": 0.0,
            "justification": "",
            "warranty_years": None,
            "issue_date": None,
            "valid_until": None,
            "date_source": None,
            "page_number": None,
            "path": None,
        }

    total_score = 0.0
    total_weight = 0.0

    total_score += result["inverter_brand"]["score"] * 0.10
    total_weight += 0.10

    for iec_data in result["iec_inverter_certificates"].values():
        total_score += iec_data["score"] * iec_data["weight"]
        total_weight += iec_data["weight"]

    total_score += (
        result["warranty_certificate"]["score"] * result["warranty_certificate"]["weight"]
    )
    total_weight += result["warranty_certificate"]["weight"]

    result["overall_score"] = total_score / total_weight if total_weight > 0 else 0.0
    result["total_weight"] = total_weight

    return result


def main():
    # Test solar panel compliance
    # brands = ["Trina Solar", "LONGi Solar", "JA Solar"]
    # for brand_name in brands:
    #     print(f"Evaluating Brand: {brand_name}")
    #     compliance_result = evaluate_brand_compliance(brand_name)
    #     print(json.dumps(compliance_result, indent=2))
    #     print("\n" + "=" * 60 + "\n")

    # print("\n" + "=" * 60 + "\n")

    # Test inverter compliance
    inverter_brands = [
        "Sungrow",
        # "Fronius",
        # "SolarEdge",
        # "Victron Energy",
        # "Deye",
        # "Solis",
        # "Huawei",
    ]
    for inverter_brand in inverter_brands:
        print(f"Evaluating Inverter Brand: {inverter_brand}")
        print("=" * 60)
        inverter_result = evaluate_inverter_compliance(inverter_brand)
        print(json.dumps(inverter_result, indent=2))
        print("\n" + "=" * 60 + "\n")

    # For "other (Specify Input)"
    other_brand = input("Specify other inverter brand (or press Enter to skip): ").strip()
    if other_brand:
        print(f"Evaluating Inverter Brand: {other_brand}")
        print("=" * 60)
        inverter_result = evaluate_inverter_compliance(other_brand)
        print(json.dumps(inverter_result, indent=2))


if __name__ == "__main__":
    main()
