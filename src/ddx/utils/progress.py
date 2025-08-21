from __future__ import annotations
import shutil, sys

def _progress_print(index: int, total: int, label: str, item: str, enabled: bool = False):
    if not enabled:
        return
    cols = shutil.get_terminal_size((80, 20)).columns
    prefix = f"{label} [{index}/{total}] "
    msg = f"{prefix}{item}"
    if len(msg) > cols - 1:
        msg = msg[: cols - 4] + "..."
    sys.stderr.write("\r" + msg)
    sys.stderr.flush()
    if index == total:
        sys.stderr.write("\n")
        sys.stderr.flush()
