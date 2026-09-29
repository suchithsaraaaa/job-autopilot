import html
import re

_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6])[^>]*>", re.I)
_WS = re.compile(r"[ \t\r\f\v]+")


def html_to_text(raw: str) -> str:
    """Greenhouse returns HTML that is itself HTML-escaped; unescape until stable."""
    prev = None
    while prev != raw:
        prev, raw = raw, html.unescape(raw)
    raw = _BLOCK.sub("\n", raw)
    raw = _TAG.sub(" ", raw)
    raw = _WS.sub(" ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw).strip()
