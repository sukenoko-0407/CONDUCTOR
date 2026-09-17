from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Canonical identifiers do not accept non-finite numbers")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Canonical JSON object keys must be strings")
            _reject_non_finite(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_non_finite(item)


def canonical_json(value: Any) -> str:
    """Return the deterministic JSON representation used by 0.2.1 IDs.

    Python's encoder is used with the RFC 8785 properties needed by the
    current schemas: UTF-8 strings, lexical key ordering, no insignificant
    whitespace, and rejection of NaN/Infinity. Identifier inputs must not
    contain values requiring implementation-specific numeric rounding.
    """

    _reject_non_finite(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: Any, *, width: int = 16) -> str:
    if not prefix or "|" in prefix:
        raise ValueError("ID prefix must be non-empty and must not contain '|'")
    if width < 8 or width > 64:
        raise ValueError("ID hash width must be between 8 and 64")
    return f"{prefix}|{content_hash(value)[:width]}"
