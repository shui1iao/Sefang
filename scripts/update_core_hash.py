"""Refresh only the local, same-version core wheel hash after rebuilding it."""
from pathlib import Path
import hashlib
import re

root = Path(__file__).resolve().parents[1]
wheel = root / "vendor/se_catalog_core-2026.10.24.2-py3-none-any.whl"
lock = root / "uv.lock"
text = lock.read_text()
pattern = r'(filename = "se_catalog_core-2026\.10\.24\.2-py3-none-any\.whl", hash = "sha256:)[a-f0-9]{64}(" )'
updated, count = re.subn(pattern, lambda m: m[1] + hashlib.sha256(wheel.read_bytes()).hexdigest() + m[2], text)
if count != 1:
    raise SystemExit("Expected exactly one pinned local core wheel; lock not changed")
lock.write_text(updated)
