"""Repository URL handling for optional commit and tag links.

Links are only produced when a repository URL is configured explicitly or derived from a remote
with ``repository_url = "auto"``. Derived URLs are restricted to http(s), stripped of credentials,
and every substituted component is percent-encoded.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

_SCP_RE = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[A-Za-z0-9.\-]+):(?P<path>[^\s]+)$")


def normalize_repository_url(raw: str) -> str | None:
    """Turn a clone URL into a browsable ``https://host/path`` URL, or return ``None``."""
    raw = raw.strip()
    if not raw:
        return None
    host: str
    path: str
    if "://" in raw:
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https", "ssh", "git") or not parts.hostname:
            return None
        host, path = parts.hostname, parts.path
        scheme = "http" if parts.scheme == "http" else "https"
    else:
        match = _SCP_RE.match(raw)
        if match is None:
            return None
        host, path = match.group("host"), "/" + match.group("path").lstrip("/")
        scheme = "https"
    path = path.removesuffix("/").removesuffix(".git")
    if not path or path == "/" or ".." in path.split("/"):
        return None
    return f"{scheme}://{host}{quote(path, safe='/@:+-._~')}"


def format_link(template: str, repository_url: str, **values: str) -> str:
    """Fill ``template``; ``{repo}`` is inserted verbatim, other values are percent-encoded."""
    encoded = {k: quote(v, safe="/" if k == "tag" else "") for k, v in values.items()}
    return template.format(repo=repository_url.rstrip("/"), **encoded)


def is_safe_http_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)
