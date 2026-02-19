#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    def __init__(self, provider: str = "openai", model: Optional[str] = None):
        self.provider = provider
        self.model = model or os.getenv("LLM_MODEL") or "gpt-4.1-2025-04-14"
        self._openai = None
        if provider == "openai":
            self._init_openai()
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    def _init_openai(self):
        from openai import OpenAI

        self._openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # -----------------------------
    # Files
    # -----------------------------
    def upload_file(self, file_path: Union[str, Path], *, purpose: str = "assistants") -> str:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(str(p))
        with p.open("rb") as f:
            created = self._openai.files.create(file=f, purpose=purpose)  # type: ignore[union-attr]
        return created.id

    def get_file_info(self, file_id: str) -> Dict[str, Any]:
        f = self._openai.files.retrieve(file_id)  # type: ignore[union-attr]
        return f.model_dump()

    def list_files(
        self,
        purpose: Optional[str] = None,
        limit: int = 100,
        order: str = "desc",
    ) -> List[Dict[str, Any]]:
        page = self._openai.files.list(purpose=purpose, limit=limit, order=order)  # type: ignore[union-attr]
        return [x.model_dump() for x in page.data]

    # -----------------------------
    # Vector stores
    # -----------------------------
    def create_vector_store(self, name: str) -> str:
        vs = self._openai.vector_stores.create(name=name)  # type: ignore[union-attr]
        return vs.id

    def add_file_to_vector_store(
        self,
        *,
        vector_store_id: str,
        file_id: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        vsf = self._openai.vector_stores.files.create(  # type: ignore[union-attr]
            vector_store_id=vector_store_id,
            file_id=file_id,
            attributes=attributes or {},
        )
        return vsf.model_dump()

    # -----------------------------
    # Vector stores (by name)
    # -----------------------------
    def list_vector_stores(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        page = self._openai.vector_stores.list(limit=limit)  # type: ignore[union-attr]
        return [x.model_dump() for x in page.data]

    def get_or_create_vector_store_id_by_name(self, name: str) -> str:
        for vs in self.list_vector_stores(limit=100):
            if vs.get("name") == name:
                return vs["id"]
        created = self._openai.vector_stores.create(name=name)  # type: ignore[union-attr]
        return created.id

    def list_vector_store_files(
        self, *, vector_store_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        page = self._openai.vector_stores.files.list(vector_store_id=vector_store_id, limit=limit)  # type: ignore[union-attr]
        return [x.model_dump() for x in page.data]

    def vector_store_has_file(
        self, *, vector_store_id: str, file_id: str, limit: int = 100
    ) -> bool:
        for x in self.list_vector_store_files(vector_store_id=vector_store_id, limit=limit):
            if x.get("file_id") == file_id:
                return True
        return False

    def update_vector_store_file_attributes(
        self,
        *,
        vector_store_id: str,
        file_id: str,
        attributes: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        POST /v1/vector_stores/{vector_store_id}/files/{file_id}
        Updates attributes (scalar-only: string/number/bool).
        """
        updated = self._openai.vector_stores.files.update(  # type: ignore[union-attr]
            vector_store_id=vector_store_id,
            file_id=file_id,
            attributes=attributes,
        )
        return updated.model_dump()

    def wait_until_vector_store_file_ready(
        self,
        *,
        vector_store_id: str,
        file_id: str,
        timeout_s: int = 600,
        poll_s: float = 2.0,
    ) -> None:
        start = time.time()
        while True:
            obj = self._openai.vector_stores.files.retrieve(  # type: ignore[union-attr]
                vector_store_id=vector_store_id, file_id=file_id
            )
            status = getattr(obj, "status", None)
            if status == "completed":
                return
            if status in ("failed", "cancelled"):
                raise RuntimeError(f"Vector store file status={status} file_id={file_id}")
            if time.time() - start > timeout_s:
                raise TimeoutError(f"Timed out waiting for indexing. file_id={file_id}")
            time.sleep(poll_s)

    # -----------------------------
    # Responses + file_search
    # -----------------------------
    def responses_file_search(
        self,
        *,
        query: str,
        vector_store_ids: List[str],
        filters: Optional[Dict[str, Any]] = None,
        max_num_results: int = 8,
        include_results: bool = False,
        model: Optional[str] = None,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        tools: List[Dict[str, Any]] = [
            {
                "type": "file_search",
                "vector_store_ids": vector_store_ids,
                "max_num_results": max_num_results,
            }
        ]
        if filters is not None:
            tools[0]["filters"] = filters

        include = ["file_search_call.results"]

        print(
            f"Sending responses_file_search with query='{query}' to model='{model or self.model}'"
        )
        print(f"Using vector_store_ids={vector_store_ids}, filters={filters}")
        print("debugging tools", tools)
        print("filters", filters)

        resp = self._openai.responses.create(  # type: ignore[union-attr]
            model=model or self.model,
            input=query,
            tools=tools,
            include=include,
            temperature=temperature,
        )

        import pprint

        pprint.pprint(resp.model_dump())
        return resp.model_dump()

    def extract_text_from_responses_output(self, resp: Dict[str, Any]) -> str:
        out = resp.get("output") or []
        texts: List[str] = []
        for item in out:
            if item.get("type") != "message":
                continue
            for c in item.get("content") or []:
                if c.get("type") == "output_text" and isinstance(c.get("text"), str):
                    texts.append(c["text"])
        return "\n".join(texts).strip()
