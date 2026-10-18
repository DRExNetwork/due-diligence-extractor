"""V1-2273 end-to-end harness — the real extractor API, served locally, without S3.

Runs the real FastAPI app (real LandingAI parse/extract, real OpenAI validation) with
two test-only patches so nothing in AWS is touched:

* ``download_s3_files`` resolves an ``s3_path`` to ``$DDX_E2E_DOCS_DIR/<basename>``
  (a copy in a temp dir, as the real download does);
* the S3 markdown/parse cache is switched off, so every run is a fresh parse and no
  cache object is read or written.

Usage (from the repo root)::

    DDX_E2E_DOCS_DIR=/path/to/pdfs PYTHONPATH=src python tests/e2e/local_server.py --port 8765

Set ``OPENAI_API_KEY=invalid`` in the environment to simulate an AI-provider failure.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import uvicorn

from ddx.api import services
from ddx.classification import extraction_api


async def _local_download(
    s3_paths: List[str],
    bucket: Optional[str] = None,
) -> Tuple[Path, Dict[str, Path]]:
    docs_dir = Path(os.environ["DDX_E2E_DOCS_DIR"])
    temp_dir = Path(tempfile.mkdtemp(prefix="ddx-e2e-"))
    mapping: Dict[str, Path] = {}
    for s3_path in s3_paths:
        source = docs_dir / Path(s3_path).name
        if not source.exists():
            raise RuntimeError(f"E2E document not found: {source}")
        target = temp_dir / source.name
        shutil.copyfile(source, target)
        mapping[s3_path] = target
    return temp_dir, mapping


def _no_cache(markdown_cache, markdown_cache_bucket, markdown_cache_prefix):
    return False, None, markdown_cache_prefix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not os.environ.get("DDX_E2E_DOCS_DIR"):
        raise SystemExit("DDX_E2E_DOCS_DIR is required")

    services.download_s3_files = _local_download
    extraction_api._resolve_cache_config = _no_cache

    from ddx.api.main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
