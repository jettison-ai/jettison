"""Prose compression for non-code tool output.

Bash output, build logs, test failures and documentation are a real slice
of what an agent reads, and none of it benefits from the line-oriented
code pruner. Headroom's Kompress (Apache-2.0, `chopratejas/kompress-v2-base`,
ModernBERT-base) is trained for exactly this and measured here at **17.8%
on verbose prose in ~0.4s**, running on CPU via ONNX — no GPU, no server.

Used as a library, credited in NOTICE, never vendored.

Two hard rules, both learned by measuring:

1. **Never send code.** Kompress strips keywords; on source it produces
   text that is no longer valid in its language while reporting a large
   "saving". Every call here goes through `content_type.classify` first
   and code is refused outright.
2. **Optional and fail-open.** `headroom-ai` is an extra, the model is a
   download, and neither may ever break a session: any import error, any
   missing model, any exception returns the original text unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from jettison.hook.content_type import classify

logger = logging.getLogger(__name__)

# Below this the model's fixed overhead outweighs anything it can save.
MIN_PROSE_CHARS = 1_200

_compressor = None
_unavailable = False


@dataclass
class ProseResult:
    text: str
    compressed: bool
    reason: str = ""


def _get_compressor():
    """Load Kompress once, and remember failure so we retry nothing.

    A missing optional dependency is the normal case, not an error — most
    installs will never have it — so this stays quiet at warning level.
    """
    global _compressor, _unavailable
    if _compressor is not None or _unavailable:
        return _compressor
    try:
        from headroom.transforms.kompress_compressor import KompressCompressor

        c = KompressCompressor()
        c.preload(allow_download=True)
        _compressor = c
    except Exception as e:  # ImportError, download failure, ONNX absent…
        logger.debug("prose compression unavailable: %s", e)
        _unavailable = True
    return _compressor


def compress_prose(text: str, tool_name: str = "") -> ProseResult:
    kind = classify(text, tool_name)
    if kind != "prose":
        return ProseResult(text, False, f"content is {kind}; prose compressor refused")
    if len(text) < MIN_PROSE_CHARS:
        return ProseResult(text, False, "below size floor")

    c = _get_compressor()
    if c is None:
        return ProseResult(text, False, "kompress unavailable (install jettison-ai[runtime])")

    try:
        r = c.compress(text)
    except Exception as e:
        logger.debug("prose compression failed: %s", e)
        return ProseResult(text, False, "compressor raised; original kept")

    out = getattr(r, "compressed", None)
    if not isinstance(out, str) or not out.strip() or len(out) >= len(text):
        return ProseResult(text, False, "no reduction")
    return ProseResult(out, True, f"{len(text):,} -> {len(out):,} chars")
