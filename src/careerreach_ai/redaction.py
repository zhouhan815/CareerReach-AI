from __future__ import annotations

import json
import re
from typing import Any


SENSITIVE_PATTERNS = {
	"session_file": re.compile(r"session\.enc", re.IGNORECASE),
	"cookie_or_token": re.compile(
		r'(?i)("?(cookie|access_token|refresh_token|authorization)"?\s*[:=])'
	),
	"private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
	"realistic_security_id": re.compile(r'"security_id"\s*:\s*"(?!demo-|mock-|example-)[^"]{8,}"'),
}


def find_sensitive_markers(value: Any) -> list[str]:
	text = json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value
	return [name for name, pattern in SENSITIVE_PATTERNS.items() if pattern.search(text)]
