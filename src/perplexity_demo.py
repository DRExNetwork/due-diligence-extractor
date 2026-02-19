import os
import time
from typing import List, Dict, Any
from perplexity import Perplexity
import sys

sys.encoding = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")

# Configure brands to search
BRANDS: List[str] = [
    "Trina Solar",
    "LONGi Solar",
    "JA Solar",
]

INVERTER_BRANDS: List[str] = [
    "Sungrow",
    "Fronius",
    "SolarEdge",
    "Huawei",
]

IEC_INVERTER_STANDARDS: List[Dict[str, Any]] = [
    {
        "code": "IEC 62109",
        "description": "Safety requirements for power converters used in photovoltaic systems",
        "mandatory": True,
        "weight": 0.10,
        "pdf_query_template": "{brand_name} inverter IEC 62109 certificate filetype:pdf",
        "url_query_template": "Does {brand_name} inverter comply with IEC 62109 safety standard? -filetype:pdf",
    },
    {
        "code": "IEC 61727",
        "description": "Photovoltaic systems' interface with the grid (grid code compliance)",
        "mandatory": True,
        "weight": 0.10,
        "pdf_query_template": "{brand_name} inverter IEC 61727 certificate filetype:pdf",
        "url_query_template": "Does {brand_name} inverter comply with IEC 61727 grid code standard? -filetype:pdf",
    },
    {
        "code": "IEC 62116",
        "description": "Test procedure for anti-islanding protection measures",
        "mandatory": True,
        "weight": 0.10,
        "pdf_query_template": "{brand_name} inverter IEC 62116 certificate filetype:pdf",
        "url_query_template": "Is {brand_name} inverter tested for IEC 62116 anti-islanding protection? -filetype:pdf",
    },
    {
        "code": "IEC 61000",
        "description": "Electromagnetic compatibility (EMC)",
        "mandatory": True,
        "weight": 0.10,
        "pdf_query_template": "{brand_name} inverter IEC 61000 certificate filetype:pdf",
        "url_query_template": "Does {brand_name} inverter comply with IEC 61000 EMC requirements? -filetype:pdf",
    },
]


# Store query templates (avoid f-strings; format with brand_name later)
IEC_STANDARDS: List[Dict[str, Any]] = [
    {
        "code": "IEC 61215",
        "description": "Outdoor durability & mechanical integrity",
        "mandatory": True,
        "weight": 0.10,
        "pdf_query_template": "{brand_name} solar module IEC 61215 certificate  filetype:pdf",
        "url_query_template": "Does {brand_name} solar module have IEC 61215 certification? -filetype:pdf",
    },
    {
        "code": "IEC 61730",
        "description": "Electrical safety",
        "mandatory": True,
        "weight": 0.10,
        "pdf_query_template": "{brand_name} solar module IEC 61730 certificate  filetype:pdf",
        "url_query_template": "Does {brand_name} solar module comply with IEC 61730 electrical safety standard? -filetype:pdf",
    },
    {
        "code": "IEC TS 62804",
        "description": "PID resistance",
        "mandatory": False,
        "weight": 0.05,
        "pdf_query_template": "{brand_name} solar module IEC TS 62804 certificate  filetype:pdf",
        "url_query_template": "Is {brand_name} solar module tested for IEC TS 62804 PID resistance? -filetype:pdf",
    },
    {
        "code": "IEC 62716",
        "description": "Ammonia corrosion resistance",
        "mandatory": False,
        "weight": 0.05,
        "pdf_query_template": "{brand_name} solar module IEC 62716 certificate filetype:pdf",
        "url_query_template": "Does {brand_name} solar module comply with IEC 62716 ammonia corrosion resistance? -filetype:pdf",
    },
    {
        "code": "IEC 61701",
        "description": "Salt mist corrosion resistance",
        "mandatory": False,
        "weight": 0.05,
        "pdf_query_template": "{brand_name} solar module IEC 61701 certificate filetype:pdf",
        "url_query_template": "Does {brand_name} solar module comply with IEC 61701 salt mist corrosion resistance? -filetype:pdf",
    },
]


def get_client() -> Perplexity:
    api_key = os.getenv("PPLX_API_KEY")
    if not api_key:
        raise RuntimeError("Missing PPLX_API_KEY environment variable.")
    return Perplexity(api_key=api_key)


def run_search(client: Perplexity, query: str, max_results: int = 3, country: str = "US"):
    try:
        search = client.search.create(
            query=query,
            max_results=max_results,
            max_tokens=8192,
            max_tokens_per_page=2048,
            country=country,
        )
        return getattr(search, "results", []) or []
    except Exception as e:
        print(f"Search error for query='{query}': {e}")
        return []


def search_inverter_standards(client: Perplexity):
    for brand in INVERTER_BRANDS:
        print(f"\n=== Inverter Brand: {brand} ===")

        # Search for technical datasheets
        print(f"\n- Technical Datasheet")
        datasheet_queries = [
            f"{brand} inverter technical datasheet filetype:pdf",
            f"{brand} inverter specifications datasheet filetype:pdf",
        ]
        for query in datasheet_queries:
            print(f"  Query: {query}")
            results = run_search(client, query, max_results=1)
            if results:
                print("  Results:")
                for r in results:
                    title = getattr(r, "title", "") or ""
                    url = getattr(r, "url", "") or ""
                    print(f"    - {title}: {url}")
            else:
                print("  Results: none")
            time.sleep(0.5)

        for std in IEC_INVERTER_STANDARDS:
            print(f"\n- {std['code']} | {std['description']}")
            pdf_query = std["pdf_query_template"].format(brand_name=brand)
            url_query = std["url_query_template"].format(brand_name=brand)

            print(f"  PDF query: {pdf_query}")
            pdf_results = run_search(client, pdf_query, max_results=1)
            if pdf_results:
                print("  PDF results:")
                for r in pdf_results:
                    title = getattr(r, "title", "") or ""
                    url = getattr(r, "url", "") or ""
                    print(f"    - {title}: {url}")
            else:
                print("  PDF results: none")

            time.sleep(0.5)


def main():
    client = get_client()

    for brand in BRANDS:
        print(f"\n=== Brand: {brand} ===")

        # Search for technical datasheets
        print(f"\n- Technical Datasheet")
        datasheet_queries = [
            f"{brand} solar module technical datasheet filetype:pdf",
            f"{brand} solar module specifications datasheet filetype:pdf",
        ]
        for query in datasheet_queries:
            print(f"  Query: {query}")
            results = run_search(client, query, max_results=1)
            if results:
                print("  Results:")
                for r in results:
                    title = getattr(r, "title", "") or ""
                    url = getattr(r, "url", "") or ""
                    print(f"    - {title}: {url}")
            else:
                print("  Results: none")
            time.sleep(0.5)

        for std in IEC_STANDARDS:
            print(f"\n- {std['code']} | {std['description']}")
            pdf_query = std["pdf_query_template"].format(brand_name=brand)
            url_query = std["url_query_template"].format(brand_name=brand)

            print(f"  URL query: {pdf_query}")
            # PDF search
            pdf_results = run_search(client, pdf_query, max_results=1)
            if pdf_results:
                print("  PDF results:")
                for r in pdf_results:
                    title = getattr(r, "title", "") or ""
                    url = getattr(r, "url", "") or ""
                    print(f"    - {title}: {url}")
            else:
                print("  PDF results: none")

            # Small delay to respect rate limits
            time.sleep(0.5)
    # New: run inverter searches
    search_inverter_standards(client)


if __name__ == "__main__":
    main()
