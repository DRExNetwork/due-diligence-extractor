from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..llm.client import LLMClient


def project_filter(project: str) -> Dict[str, Any]:
    return {"type": "eq", "key": "project", "value": project}


@dataclass
class FileSearchQueryOptions:
    max_num_results: int = 6
    include_results: bool = False


class FileSearchService:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient(provider="openai")

    def ask_in_category(
        self,
        *,
        vector_store_id: str,
        category: str,
        question: str,
        options: Optional[FileSearchQueryOptions] = None,
        model: Optional[str] = None,
    ) -> str:
        options = options or FileSearchQueryOptions()
        resp = self.llm_client.responses_file_search(
            query=question,
            vector_store_ids=[vector_store_id],
            filters=project_filter(category),
            max_num_results=options.max_num_results,
            include_results=options.include_results,
            model=model,
        )
        print(resp)
        return self.llm_client.extract_text_from_responses_output(resp)
