from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict

from ..llm.client import LLMClient


@dataclass
class VectorStoreConfig:
    persist_path: Path = Path(".ddx") / "vector_stores.json"


class VectorStoreManager:
    """
    One vector store per project.

    project_key: stable identifier (e.g. project_id, project_slug, folder name)
    """

    def __init__(
        self, llm_client: Optional[LLMClient] = None, config: Optional[VectorStoreConfig] = None
    ):
        self.llm_client = llm_client or LLMClient(provider="openai")
        self.config = config or VectorStoreConfig()

    def _load(self) -> Dict[str, str]:
        self.config.persist_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config.persist_path.exists():
            return {}
        return json.loads(self.config.persist_path.read_text(encoding="utf-8") or "{}")

    def _save(self, mapping: Dict[str, str]) -> None:
        self.config.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.persist_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    def get_or_create_vector_store_id(
        self, *, project_key: str, display_name: Optional[str] = None
    ) -> str:
        mapping = self._load()
        if project_key in mapping and mapping[project_key]:
            return mapping[project_key]

        name = display_name or f"ddx_kb::{project_key}"
        vs_id = self.llm_client.create_vector_store(name=name)
        mapping[project_key] = vs_id
        self._save(mapping)
        return vs_id

    def list_vector_store_files(self, *, vector_store_id: str) -> Dict[str, str]:
        return self.llm_client.list_vector_store_files(vector_store_id=vector_store_id)
