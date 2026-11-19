"""Data schemas, frontmatter parsing/formatting, and line-length helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rtx.config import MAX_LINE_LENGTH

_FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$")


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    """Compute hex SHA-256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Compute hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


@dataclass(slots=True)
class PageMetadata:
    """Standard metadata header for `.corpus/<source_id>/pages/**/*.md` and `knowledge/**/*.md`."""

    source_id: str
    url: str = ""
    title: str = ""
    section: str = ""
    fetched_at: str = ""
    last_modified: str = ""
    sha256: str = ""
    etag: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source_id": self.source_id,
            "url": self.url,
            "title": self.title,
            "section": self.section,
            "fetched_at": self.fetched_at,
            "last_modified": self.last_modified,
            "sha256": self.sha256,
        }
        if self.etag:
            data["etag"] = self.etag
        for key, value in self.extra.items():
            if key not in data and value not in ("", None):
                data[key] = value
        return data


def _yaml_quote(value: Any) -> str:
    text = str(value)
    if text == "" or any(ch in text for ch in (":", "#", "\"", "'", "\n", "{", "}", "[", "]")) or text.strip() != text:
        return json.dumps(text, ensure_ascii=False)
    return text


def _unquote(raw: str) -> str:
    val = raw.strip()
    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
        if val[0] == '"':
            try:
                loaded = json.loads(val)
                return str(loaded)
            except json.JSONDecodeError:
                pass
        return val[1:-1]
    return val


def format_page_frontmatter(meta: PageMetadata, style: str = "yaml") -> str:
    """Format `PageMetadata` as YAML frontmatter (`yaml`) or HTML comment (`comment`)."""
    items = meta.to_dict()
    lines = [f"{k}: {_yaml_quote(v)}" for k, v in items.items()]
    if style == "comment":
        return "<!--\n" + "\n".join(lines) + "\n-->\n\n"
    return "---\n" + "\n".join(lines) + "\n---\n\n"


def parse_page_frontmatter(text: str) -> tuple[PageMetadata | None, int]:
    """Parse YAML (`---`) or HTML comment (`<!-- ... -->`) metadata at top of a Markdown file.

    Returns `(metadata_or_none, body_start_line_1based)`.
    """
    lines = text.splitlines()
    if not lines:
        return None, 1

    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return None, 1

    first = lines[idx].strip()
    end_idx: int | None = None
    if first == "---":
        for j in range(idx + 1, min(len(lines), idx + 60)):
            if lines[j].strip() in ("---", "..."):
                end_idx = j
                break
    elif first.startswith("<!--"):
        if "-->" in first and len(first) > 7:
            end_idx = idx
        else:
            for j in range(idx + 1, min(len(lines), idx + 60)):
                if lines[j].strip().endswith("-->"):
                    end_idx = j
                    break

    if end_idx is None:
        return None, 1

    kv: dict[str, str] = {}
    if idx == end_idx and first.startswith("<!--"):
        inner = first[4:-3].strip()
        for part in inner.split(";"):
            m = _FRONTMATTER_KV_RE.match(part.strip())
            if m:
                kv[m.group(1)] = _unquote(m.group(2))
    else:
        for line in lines[idx + 1 : end_idx]:
            stripped = line.strip()
            if not stripped or stripped == "-->":
                continue
            m = _FRONTMATTER_KV_RE.match(stripped)
            if m:
                kv[m.group(1)] = _unquote(m.group(2))

    if not kv:
        return None, 1

    known = {"source_id", "url", "title", "section", "fetched_at", "last_modified", "sha256", "etag"}
    extra = {k: v for k, v in kv.items() if k not in known}
    meta = PageMetadata(
        source_id=kv.get("source_id", ""),
        url=kv.get("url", ""),
        title=kv.get("title", ""),
        section=kv.get("section", ""),
        fetched_at=kv.get("fetched_at", ""),
        last_modified=kv.get("last_modified", ""),
        sha256=kv.get("sha256", ""),
        etag=kv.get("etag", ""),
        extra=extra,
    )
    body_line = end_idx + 2
    while body_line - 1 < len(lines) and not lines[body_line - 1].strip():
        body_line += 1
    return meta, body_line


def wrap_long_lines(text: str, max_len: int = MAX_LINE_LENGTH) -> str:
    """Wrap any line exceeding `max_len` at word boundaries so every line stays <= `max_len`."""
    out: list[str] = []
    for raw_line in text.splitlines():
        if len(raw_line) <= max_len:
            out.append(raw_line)
            continue
        remaining = raw_line
        while len(remaining) > max_len:
            split_at = remaining.rfind(" ", 0, max_len)
            if split_at <= max_len // 3:
                split_at = max_len
            out.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        if remaining:
            out.append(remaining)
    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result


@dataclass(slots=True)
class SourceManifest:
    """Summary manifest stored in `.corpus/<id>/manifest.json` and `manifests/sources/<id>.json`."""

    source_id: str
    name: str
    base_url: str
    fetched_at: str = ""
    page_count: int = 0
    asset_count: int = 0
    failed_count: int = 0
    status: str = "ok"
    upstream_version: str = ""
    versions: dict[str, str] = field(default_factory=dict)
    sections: dict[str, int] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> SourceManifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw_sections = raw.get("sections")
        sections: dict[str, int] = {}
        if isinstance(raw_sections, dict):
            sections = {str(k): int(v or 0) for k, v in raw_sections.items()}
        elif isinstance(raw_sections, list):
            sections = {str(item): 0 for item in raw_sections}

        raw_versions = raw.get("versions")
        versions = {str(k): str(v) for k, v in raw_versions.items()} if isinstance(raw_versions, dict) else {}

        return cls(
            source_id=str(raw.get("source_id", path.stem)),
            name=str(raw.get("name", raw.get("source_id", path.stem))),
            base_url=str(raw.get("base_url", raw.get("url", ""))),
            fetched_at=str(raw.get("fetched_at", raw.get("synced_at", ""))),
            page_count=int(raw.get("page_count", raw.get("pages", 0)) or 0),
            asset_count=int(raw.get("asset_count", raw.get("assets", 0)) or 0),
            failed_count=int(raw.get("failed_count", raw.get("page_error_count", raw.get("errors", 0))) or 0),
            status=str(raw.get("status", "ok")),
            upstream_version=str(raw.get("upstream_version", raw.get("version", ""))),
            versions=versions,
            sections=sections,
            notes=str(raw.get("notes", "")),
        )


@dataclass(slots=True)
class ApiSymbol:
    """Standard schema for bytecode-verified API symbols in `manifests/api/*.json`."""

    name: str
    package: str = ""
    kind: str = "composable"
    signature: str = ""
    annotations: list[str] = field(default_factory=list)
    artifact: str = ""
    version: str = ""
    targets: list[str] = field(default_factory=list)
    androidx_signature: str = ""
    cmp_signature: str = ""
    parity_status: str = ""
    doc: str = ""
    kotlin_defaults_signature: str = ""


@dataclass(slots=True)
class KotlinSourceSymbol:
    """Indexed Kotlin/Java declaration from Maven `*-sources.jar`."""

    name: str
    owner: str = ""
    qualified_name: str = ""
    fq_package: str = ""
    kind: str = "fun"
    visibility: str = "public"
    is_composable: bool = False
    annotations: list[str] = field(default_factory=list)
    jar_name: str = ""
    artifact_key: str = ""
    coordinate: str = ""
    version: str = ""
    platform: str = ""
    entry_path: str = ""
    kdoc_start_line: int = 0
    start_line: int = 1
    end_line: int = 1
    has_defaults: bool = False
    kotlin_signature: str = ""
    kdoc: str = ""


@dataclass(slots=True)
class DesignToken:
    """Standard schema for design tokens in `manifests/tokens/*.json`."""

    name: str
    category: str = ""
    value: str = ""
    role: str = ""
    compose_token: str = ""
    spec_version: str = ""
    notes: str = ""


@dataclass(slots=True)
class LedgerEntry:
    """Progress/failure ledger record for mirror fetches."""

    url: str
    status: str  # "ok" | "not_modified" | "skipped_robots" | "failed"
    http_status: int = 0
    local_path: str = ""
    error: str = ""
    timestamp: str = field(default_factory=utc_now_iso)
