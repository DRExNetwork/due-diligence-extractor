from __future__ import annotations
import os
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from tavily import TavilyClient
from ddx.llm.client import LLMClient

# os.environ["TAVILY_API_KEY"] = "your-tavily-api-key"
# os.environ["OPENAI_API_KEY"] = "your-openai-api-key"


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
        "web_searches_performed": [],
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

        result["web_searches_performed"].append(
            {
                "standard": iec["code"],
                "query": iec["pdf_query"],
                "search_type": "PDF",
                "results_count": len(pdf_search_results.get("results", [])),
            }
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

            # print(f"    Analyzing PDF: {url}")

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
            
            Return a JSON response with this exact structure:
            {{
                "has_certification": true/false,
                "confidence": 0.0 to 1.0,
                "evidence_type": "certificate"|"datasheet"|"test_report"|"not_found",
                "certificate_number": "certificate number if found, or null",
                "testing_lab": "name of testing laboratory if found, or null",
                "product_models": "models/series covered if found, or null",
                "key_evidence": "specific quote showing certification",
                "issue_date": "YYYY-MM-DD format if found, or null",
                "valid_until": "YYYY-MM-DD format if found, or null",
                "date_source": "exact text where dates were found, or null"
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
                    used_url = url
                    search_type = "PDF"
                    break

            except Exception as e:
                print(f"    Error analyzing PDF {url}: {str(e)}")
                continue

        # STEP 2: If no PDF evidence found, fallback to regular URL search
        if not found_evidence:
            print(f"  Step 2: No PDF evidence found. Searching regular URLs...")

            url_search_results = tavily.search(
                query=iec["url_query"],
                search_depth="advanced",
                max_results=2,
                include_answer="advanced",
                include_raw_content="text",
            )

            result["web_searches_performed"].append(
                {
                    "standard": iec["code"],
                    "query": iec["url_query"],
                    "search_type": "URL",
                    "results_count": len(url_search_results.get("results", [])),
                }
            )

            # Try each URL result
            for sr in url_search_results.get("results", []):
                url = sr.get("url", "")
                if not url or url == "N/A":
                    continue

                # Skip PDFs in URL search
                if url.lower().endswith(".pdf"):
                    continue

                raw_content = sr.get("raw_content", "")
                if not raw_content:
                    raw_content = sr.get("content", "")

                if not raw_content:
                    continue

                print(f"    Analyzing URL: {url}")

                # Analyze URL content with LLM
                analysis_prompt = f"""
                Analyze the following content to determine if {brand_name} has {iec['code']} certification.
                
                Standard: {iec['code']} - {iec['description']}
                
                Source URL: {url}
                
                Content:
                {raw_content}
                
                IMPORTANT Instructions for date extraction:
                1. Look for publication or update dates in ANY format, including:
                   - "Feb 01, 2023 EST" or "February 1, 2023"
                   - "Published: date", "Updated: date", "Posted: date"
                   - Date in headers, footers, or metadata sections
                   - Date formats like MM/DD/YYYY, DD/MM/YYYY, Month DD YYYY, etc.
                2. Convert any found date to YYYY-MM-DD format
                3. Look for certification evidence even if not in certificate form
                
                Return a JSON response with this exact structure:
                {{
                    "has_certification": true/false,
                    "confidence": 0.0 to 1.0,
                    "evidence_type": "certificate"|"datasheet"|"report"|"commitment"|"not_found",
                    "key_evidence": "specific quote or reference from the content",
                    "published_date": "YYYY-MM-DD format if found, or null",
                    "date_source": "exact text where date was found, or null"
                }}
                """

                messages = [
                    {
                        "role": "system",
                        "content": "You are a technical compliance analyst. Analyze certification evidence carefully. Be thorough in extracting dates. Return only valid JSON.",
                    },
                    {"role": "user", "content": analysis_prompt},
                ]

                try:
                    llm_response = llm_client.chat(
                        messages, response_format={"type": "json_object"}
                    )
                    analysis = json.loads(llm_response)

                    if (
                        analysis.get("evidence_type") != "not_found"
                        and analysis.get("confidence", 0) > 0.3
                    ):
                        found_evidence = True
                        final_analysis = analysis
                        used_url = url
                        search_type = "URL"
                        break

                except Exception as e:
                    print(f"    Error analyzing URL {url}: {str(e)}")
                    continue

        # STEP 3: Store results based on what was found
        if found_evidence and final_analysis:
            score = 0.0
            if final_analysis.get("has_certification"):
                score = 1.0
                # Check if certificate is still valid (for PDFs)
                if search_type == "PDF" and final_analysis.get("valid_until"):
                    try:
                        from datetime import datetime

                        expiry_date = datetime.strptime(final_analysis["valid_until"], "%Y-%m-%d")
                        if expiry_date < datetime.now():
                            score = 0.5  # Expired certificate
                            final_analysis["evidence_type"] = "expired_certificate"
                    except:
                        pass
            elif final_analysis.get("evidence_type") == "commitment":
                score = 0.5

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
            }

            # Add PDF-specific fields if from PDF
            if search_type == "PDF":
                result["iec_certificates"][iec["code"]].update(
                    {
                        "certificate_number": final_analysis.get("certificate_number"),
                        "testing_lab": final_analysis.get("testing_lab"),
                        "product_models": final_analysis.get("product_models"),
                        "issue_date": final_analysis.get("issue_date"),
                        "valid_until": final_analysis.get("valid_until"),
                        "date_source": final_analysis.get("date_source"),
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

    result["web_searches_performed"].append(
        {
            "type": "bankability_pdf",
            "query": bankability_pdf_query,
            "results_count": len(bank_pdf_search.get("results", [])),
        }
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

        print(f"  Analyzing PDF content from: {url}")

        bank_prompt = f"""
        Analyze {brand_name}'s bankability and Bloomberg BNEF Tier 1 status from this PDF document.
        
        Source PDF URL: {url}
        
        Content:
        {raw_content}
        
        IMPORTANT: Extract document date and validity period if mentioned.
        
        Return JSON:
        {{
            "tier_1_status": true/false,
            "rating": "AAA"|"AA"|"A"|"BBB"|"BB"|"B"|"CCC"|"not_listed",
            "evidence": "specific quote about tier 1 status or rating",
            "published_date": "YYYY-MM-DD format if found, or null",
            "valid_until": "YYYY-MM-DD format if found, or null",
            "date_source": "exact text where date was found, or null"
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
                }
                found_bank = True
                bank_search_type = "PDF"
                break

        except Exception as e:
            print(f"  Error analyzing PDF {url}: {str(e)}")
            continue

    # If no PDF evidence, try regular URL search
    if not found_bank:
        print("  No PDF evidence found. Searching regular URLs for bankability...")

        bankability_url_query = f"Is {brand_name} listed as a Bloomberg Tier 1 solar manufacturer or equivalent? Provide latest Bloomberg New Energy Finance BNEF report. -filetype:pdf"
        bank_url_search = tavily.search(
            query=bankability_url_query,
            search_depth="advanced",
            max_results=2,
            include_answer="advanced",
            include_raw_content="text",
        )

        result["web_searches_performed"].append(
            {
                "type": "bankability_url",
                "query": bankability_url_query,
                "results_count": len(bank_url_search.get("results", [])),
            }
        )

        for sr in bank_url_search.get("results", []):
            url = sr.get("url", "")
            if not url or url == "N/A" or url.lower().endswith(".pdf"):
                continue

            raw_content = sr.get("raw_content", "")
            if not raw_content:
                raw_content = sr.get("content", "")

            if not raw_content:
                continue

            print(f"  Analyzing URL content from: {url}")

            bank_prompt = f"""
            Analyze {brand_name}'s bankability and Bloomberg BNEF Tier 1 status.
            
            Source URL: {url}
            
            Content:
            {raw_content}
            
            IMPORTANT: Extract publication date in ANY format.
            
            Return JSON:
            {{
                "tier_1_status": true/false,
                "rating": "AAA"|"AA"|"A"|"BBB"|"BB"|"B"|"CCC"|"not_listed",
                "evidence": "specific quote about tier 1 status or rating",
                "published_date": "YYYY-MM-DD format if found, or null",
                "date_source": "exact text where date was found, or null"
            }}
            """

            messages = [
                {
                    "role": "system",
                    "content": "Analyze solar manufacturer bankability. Extract dates in any format. Return only valid JSON.",
                },
                {"role": "user", "content": bank_prompt},
            ]

            try:
                llm_response = llm_client.chat(messages, response_format={"type": "json_object"})
                bank_analysis = json.loads(llm_response)

                if (
                    bank_analysis.get("tier_1_status")
                    or bank_analysis.get("rating") != "not_listed"
                ):
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
                        "search_type": "URL",
                        "published_date": bank_analysis.get("published_date"),
                        "date_source": bank_analysis.get("date_source"),
                        "weight": 0.10,
                    }
                    found_bank = True
                    bank_search_type = "URL"
                    break

            except Exception as e:
                print(f"  Error analyzing URL {url}: {str(e)}")
                continue

    if not found_bank:
        result["bankability"]["search_type"] = "not_found"
        result["bankability"]["published_date"] = None
        result["bankability"]["date_source"] = None

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
        "web_searches_performed": [],
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

        result["web_searches_performed"].append(
            {
                "standard": iec["code"],
                "query": iec["pdf_query"],
                "search_type": "PDF",
                "results_count": len(pdf_search_results.get("results", [])),
            }
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

            print(f"    Analyzing PDF: {url}")

            # Analyze PDF content with LLM
            analysis_prompt = f"""
            Analyze the following PDF content to determine if {inverter_brand} inverter has {iec['code']} certification/compliance.
            
            Standard: {iec['code']} - {iec['description']}
            
            Source PDF URL: {url}
            
            PDF Content:
            {raw_content}
            
            IMPORTANT Instructions:
            1. Look for certification details including:
               - Certificate number
               - Testing laboratory (TÜV, UL, SGS, Intertek, VDE, etc.)
               - Product model/series covered
               - Validity dates (issue date and expiry date)
            
            2. Extract all dates in YYYY-MM-DD format
            
            Return a JSON response with this exact structure:
            {{
                "has_certification": true/false,
                "confidence": 0.0 to 1.0,
                "evidence_type": "certificate"|"datasheet"|"test_report"|"not_found",
                "certificate_number": "certificate number if found, or null",
                "testing_lab": "name of testing laboratory if found, or null",
                "product_models": "models/series covered if found, or null",
                "key_evidence": "specific quote showing certification",
                "issue_date": "YYYY-MM-DD format if found, or null",
                "valid_until": "YYYY-MM-DD format if found, or null",
                "date_source": "exact text where dates were found, or null"
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
                    search_type = "PDF"
                    break

            except Exception as e:
                print(f"    Error analyzing PDF {url}: {str(e)}")
                continue

        # STEP 2: If no PDF evidence found, fallback to regular URL search
        if not found_evidence:
            print(f"  Step 2: No PDF evidence found. Searching regular URLs...")

            url_search_results = tavily.search(
                query=iec["url_query"],
                search_depth="advanced",
                max_results=2,
                include_answer="advanced",
                include_raw_content="text",
            )

            result["web_searches_performed"].append(
                {
                    "standard": iec["code"],
                    "query": iec["url_query"],
                    "search_type": "URL",
                    "results_count": len(url_search_results.get("results", [])),
                }
            )

            # Try each URL result
            for sr in url_search_results.get("results", []):
                url = sr.get("url", "")
                if not url or url == "N/A":
                    continue

                # Skip PDFs in URL search
                if url.lower().endswith(".pdf"):
                    continue

                raw_content = sr.get("raw_content", "")
                if not raw_content:
                    raw_content = sr.get("content", "")

                if not raw_content:
                    continue

                print(f"    Analyzing URL: {url}")

                # Analyze URL content with LLM
                analysis_prompt = f"""
                Analyze the following content to determine if {inverter_brand} inverter has {iec['code']} certification/compliance.
                
                Standard: {iec['code']} - {iec['description']}
                
                Source URL: {url}
                
                Content:
                {raw_content}
                
                IMPORTANT: Extract publication dates in ANY format and convert to YYYY-MM-DD.
                
                Return a JSON response with this exact structure:
                {{
                    "has_certification": true/false,
                    "confidence": 0.0 to 1.0,
                    "evidence_type": "certificate"|"datasheet"|"report"|"commitment"|"not_found",
                    "key_evidence": "specific quote or reference from the content",
                    "published_date": "YYYY-MM-DD format if found, or null",
                    "date_source": "exact text where date was found, or null"
                }}
                """

                messages = [
                    {
                        "role": "system",
                        "content": "You are a technical compliance analyst specializing in inverter certifications. Return only valid JSON.",
                    },
                    {"role": "user", "content": analysis_prompt},
                ]

                try:
                    llm_response = llm_client.chat(
                        messages, response_format={"type": "json_object"}
                    )
                    analysis = json.loads(llm_response)

                    if (
                        analysis.get("evidence_type") != "not_found"
                        and analysis.get("confidence", 0) > 0.3
                    ):
                        found_evidence = True
                        final_analysis = analysis
                        used_url = url
                        search_type = "URL"
                        break

                except Exception as e:
                    print(f"    Error analyzing URL {url}: {str(e)}")
                    continue

        # STEP 3: Store results based on what was found
        if found_evidence and final_analysis:
            score = 0.0
            if final_analysis.get("has_certification"):
                score = 1.0
                # Check if certificate is still valid (for PDFs)
                if search_type == "PDF" and final_analysis.get("valid_until"):
                    try:
                        from datetime import datetime

                        expiry_date = datetime.strptime(final_analysis["valid_until"], "%Y-%m-%d")
                        if expiry_date < datetime.now():
                            score = 0.5  # Expired certificate
                            final_analysis["evidence_type"] = "expired_certificate"
                    except:
                        pass
            elif final_analysis.get("evidence_type") == "commitment":
                score = 0.5

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
            }

            # Add PDF-specific fields if from PDF
            if search_type == "PDF":
                result["iec_inverter_certificates"][iec["code"]].update(
                    {
                        "certificate_number": final_analysis.get("certificate_number"),
                        "testing_lab": final_analysis.get("testing_lab"),
                        "product_models": final_analysis.get("product_models"),
                        "issue_date": final_analysis.get("issue_date"),
                        "valid_until": final_analysis.get("valid_until"),
                        "date_source": final_analysis.get("date_source"),
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

    # Calculate overall weighted score
    total_score = 0.0
    total_weight = 0.0

    # Add inverter brand score
    total_score += result["inverter_brand"]["score"] * 0.10
    total_weight += 0.10

    # Add IEC certificates scores
    for iec_code, iec_data in result["iec_inverter_certificates"].items():
        total_score += iec_data["score"] * iec_data["weight"]
        total_weight += iec_data["weight"]

    # result["overall_score"] = total_score / total_weight if total_weight > 0 else 0.0
    # result["total_weight"] = total_weight

    return result


def main():
    # Test solar panel compliance
    brand_name = "Trina Solar"
    compliance_result = evaluate_brand_compliance(brand_name)
    print(json.dumps(compliance_result, indent=2))

    print("\n" + "=" * 60 + "\n")

    # Test inverter compliance
    inverter_brand = "Sungrow"
    print(f"Evaluating Inverter Brand: {inverter_brand}")
    print("=" * 60)
    inverter_result = evaluate_inverter_compliance(inverter_brand)
    print(json.dumps(inverter_result, indent=2))


if __name__ == "__main__":
    main()
