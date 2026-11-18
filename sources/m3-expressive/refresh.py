#!/usr/bin/env python3
"""Mirror Material Design 3 Expressive (`m3.material.io`) pages and DSDB tokens.

Fetches the live Angular `main.*.js` route manifest, downloads all versioned
Carbon page JSON payloads (including M3 Expressive blog/feature routes,
foundations, styles, components, and develop), resolves DSDB token tables
(`COLOR`, `TYPOGRAPHY`, `ELEVATION`, `MEASUREMENT`, `TOKEN_TYPE_UNSPECIFIED`,
`STATUS_TABLE`, and per-component `TOKEN_TABLE`), renders grep-friendly
Markdown under `.corpus/m3-expressive/pages/`, and exports structured tokens
to `manifests/tokens/m3-expressive-tokens.json`.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rtx.config import MAX_LINE_LENGTH, get_paths  # noqa: E402
from rtx.http import ConditionalHttpClient  # noqa: E402
from rtx.models import (  # noqa: E402
    PageMetadata,
    SourceManifest,
    format_page_frontmatter,
    parse_page_frontmatter,
    sha256_bytes,
    sha256_text,
    utc_now_iso,
    wrap_long_lines,
)

SOURCE_ID = "m3-expressive"
SOURCE_NAME = "Material Design 3 Expressive (m3.material.io)"
BASE_URL = "https://m3.material.io"
ASSET_HOSTS = {
    "firebasestorage.googleapis.com",
    "lh3.googleusercontent.com",
    "storage.googleapis.com",
    "fonts.gstatic.com",
    "fonts.googleapis.com",
}
IMAGE_EXTENSIONS = {".apng", ".avif", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
FONT_EXTENSIONS = {".eot", ".otf", ".ttf", ".woff", ".woff2"}
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mov", ".mp4", ".mkv", ".webm"}
DROP_RESOURCE_KEYS = {
    "author",
    "authors",
    "createTime",
    "email",
    "gaiaId",
    "imageUrl",
    "name",
    "revisionAuthor",
    "revisionCreateTime",
    "revisionId",
    "updatedTimestamp",
}

DSDB_SYSTEM_FILES = (
    ("COLOR", "designSystems/20543ce18892f7d9"),
    ("TYPOGRAPHY", "designSystems/20543ce18892f7d9"),
    ("TOKEN_TYPE_UNSPECIFIED", "designSystems/20543ce18892f7d9"),
    ("ELEVATION", "designSystems/20543ce18892f7d9"),
    ("MEASUREMENT", "designSystems/20543ce18892f7d9"),
)

# Maps M3 typography scale keys to Jetpack Compose Typography property names.
COMPOSE_TYPOGRAPHY_MAP = {
    "display-large": "displayLarge",
    "display-medium": "displayMedium",
    "display-small": "displaySmall",
    "headline-large": "headlineLarge",
    "headline-medium": "headlineMedium",
    "headline-small": "headlineSmall",
    "title-large": "titleLarge",
    "title-medium": "titleMedium",
    "title-small": "titleSmall",
    "body-large": "bodyLarge",
    "body-medium": "bodyMedium",
    "body-small": "bodySmall",
    "label-large": "labelLarge",
    "label-medium": "labelMedium",
    "label-small": "labelSmall",
}

COMPOSE_SHAPE_MAP = {
    "none": "Shapes.none",
    "extra-small": "Shapes.extraSmall",
    "small": "Shapes.small",
    "medium": "Shapes.medium",
    "large": "Shapes.large",
    "large-increased": "Shapes.largeIncreased",
    "extra-large": "Shapes.extraLarge",
    "extra-large-increased": "Shapes.extraLargeIncreased",
    "extra-extra-large": "Shapes.extraExtraLarge",
    "full": "CircleShape",
}


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def escape_table(value: Any) -> str:
    return normalize_text(value).replace("|", "\\|").replace("\n", " ")


def clean_markdown(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"\n[ \t]+\n", "\n\n", value)
    value = re.sub(r"(?m)^([*-]|\d+\.)[ \t]*\n(?:[ \t]*\n)?[ \t]*(?=\S)", r"\1 ", value)
    value = re.sub(r"(?m)^([-*] .+)\n\n(?=^[-*] )", r"\1\n", value)
    value = re.sub(r"(?m)^(\d+\. .+)\n\n(?=^\d+\. )", r"\1\n", value)
    return value.strip() + "\n"


def page_rel_path(slug: str) -> str:
    return "home.md" if not slug else f"{slug}.md"


def page_url(slug: str) -> str:
    return BASE_URL + "/" if not slug else f"{BASE_URL}/{slug}"


def page_section(slug: str) -> str:
    if not slug:
        return "overview"
    top = slug.split("/", 1)[0]
    if top in {"foundations", "styles", "components", "develop"}:
        return top
    return "blog-expressive"


class HtmlToMarkdown(HTMLParser):
    """Dependency-free HTML-to-Markdown converter preserving tables, lists, code, and links."""

    BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "div",
        "figure",
        "footer",
        "header",
        "main",
        "nav",
        "p",
        "section",
    }

    def __init__(self, resolver) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.resolver = resolver
        self.list_stack: list[str] = []
        self.link_stack: list[str] = []
        self.pre_depth = 0
        self.in_table = False
        self.table_rows: list[list[str]] = []
        self.current_row: list[str] | None = None
        self.cell_parts: list[str] | None = None

    def _emit(self, text: str) -> None:
        if self.cell_parts is not None:
            self.cell_parts.append(text)
        else:
            self.parts.append(text)

    def block(self) -> None:
        if self.cell_parts is not None:
            return
        if self.parts and not self.parts[-1].endswith("\n\n"):
            self.parts.append("\n\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = dict(attrs)
        if tag == "table":
            self.block()
            self.in_table = True
            self.table_rows = []
        elif tag == "tr" and self.in_table:
            self.current_row = []
        elif tag in {"td", "th"} and self.in_table:
            self.cell_parts = []
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.block()
            self._emit("#" * int(tag[1]) + " ")
        elif tag in self.BLOCK_TAGS:
            self.block()
        elif tag in {"ul", "ol"}:
            self.block()
            self.list_stack.append(tag)
        elif tag == "li":
            self.block()
            prefix = "1. " if self.list_stack and self.list_stack[-1] == "ol" else "- "
            self._emit(prefix)
        elif tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag == "code" and self.pre_depth == 0:
            self._emit("`")
        elif tag == "pre":
            self.block()
            self.pre_depth += 1
            self._emit("```\n")
        elif tag == "br":
            self._emit(" " if self.cell_parts is not None else "\n")
        elif tag == "a":
            self._emit("[")
            self.link_stack.append(attributes.get("href") or "")
        elif tag == "img":
            src = attributes.get("src") or attributes.get("data-src") or ""
            if src:
                self.block()
                self._emit(f"![{escape_table(attributes.get('alt') or 'image')}]({self.resolver(src)})")
                self.block()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.in_table:
            if self.current_row is not None and self.cell_parts is not None:
                self.current_row.append(escape_table("".join(self.cell_parts)))
            self.cell_parts = None
        elif tag == "tr" and self.in_table:
            if self.current_row is not None and any(cell for cell in self.current_row):
                self.table_rows.append(self.current_row)
            self.current_row = None
        elif tag == "table" and self.in_table:
            self.in_table = False
            if self.table_rows:
                cols = max(len(r) for r in self.table_rows)
                norm_rows = [r + [""] * (cols - len(r)) for r in self.table_rows]
                lines = [
                    "| " + " | ".join(norm_rows[0]) + " |",
                    "| " + " | ".join("---" for _ in range(cols)) + " |",
                ]
                for r in norm_rows[1:]:
                    lines.append("| " + " | ".join(r) + " |")
                self.parts.append("\n".join(lines) + "\n\n")
            self.table_rows = []
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"} | self.BLOCK_TAGS:
            self.block()
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self.block()
        elif tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag == "code" and self.pre_depth == 0:
            self._emit("`")
        elif tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
            self._emit("\n```\n")
            self.block()
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else ""
            self._emit(f"]({self.resolver(href)})" if href else "]")

    def handle_data(self, data: str) -> None:
        if self.pre_depth:
            self._emit(data)
        else:
            self._emit(re.sub(r"\s+", " ", data))

    def convert(self, value: str) -> str:
        try:
            self.feed(value)
            self.close()
        except Exception:
            return normalize_text(re.sub(r"<[^>]+>", " ", value))
        return clean_markdown("".join(self.parts))


def extract_main_script(home_html: str) -> str:
    match = re.search(r'<script[^>]+src=["\']([^"\']*?/main\.[^"\']+?\.js)["\']', home_html, re.I)
    if not match:
        raise RuntimeError("Could not find Angular main.*.js bundle in m3.material.io homepage")
    src = match.group(1)
    return src if src.startswith("http") else BASE_URL + src


def discover_routes(bundle: str, version: str) -> list[dict[str, str]]:
    version_match = re.search(r'carbonVersion:"([^"]+)"', bundle)
    if version_match and version_match.group(1) != version:
        raise RuntimeError(f"Bundle version mismatch: expected {version}, got {version_match.group(1)}")

    pairs = re.findall(r'"slug":"([^"]*)","exportedCarbonFileId":"([^"]+?\.json)"', bundle)
    seen: set[str] = set()
    routes: list[dict[str, str]] = []
    for slug, file_id in pairs:
        if slug in seen:
            continue
        seen.add(slug)
        routes.append(
            {
                "slug": slug,
                "section": page_section(slug),
                "content_id": file_id,
                "content_url": f"{BASE_URL}/_dsm/content/m3/{version}/{file_id}",
                "page_url": page_url(slug),
            }
        )
    if not routes:
        raise RuntimeError("No M3 routes discovered in Angular main bundle")
    return sorted(routes, key=lambda r: r["slug"])


def extract_urls(raw: bytes) -> set[str]:
    text = html.unescape(raw.decode("utf-8", errors="ignore")).replace("\\/", "/")
    urls = set()
    for match in re.findall(r"https?://[^\"'<>\\\s]+", text):
        urls.add(match.rstrip(".,;)]}"))
    return urls


def asset_kind(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname not in ASSET_HOSTS:
        return None
    suffix = Path(unquote(parsed.path)).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in FONT_EXTENSIONS or parsed.hostname in {"fonts.gstatic.com", "fonts.googleapis.com"}:
        return "font"
    if suffix in IMAGE_EXTENSIONS or parsed.hostname in {"firebasestorage.googleapis.com", "lh3.googleusercontent.com"}:
        return "image"
    return "other"


def asset_rel_path(url: str, kind: str, content_type: str | None = None) -> str:
    parsed = urlparse(url)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    if not suffix:
        guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
        suffix = guessed or ".bin"
    digest = sha256_text(url)[:16]
    return f"assets/{kind}/{digest}{suffix}"


def markdown_resolver(url: str, asset_map: dict[str, str], out_dir: Path, markdown_path: Path) -> str:
    url = html.unescape(url or "")
    if not url:
        return url
    local = asset_map.get(url)
    if not local:
        parsed = urlparse(url)
        if parsed.hostname not in ASSET_HOSTS:
            query = [
                (k, v)
                for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                if k != "cachebust" and not k.startswith("utm_")
            ]
            return urlunparse(parsed._replace(query=urlencode(query)))
        return url
    return Path(os.path.relpath(out_dir / local, markdown_path.parent)).as_posix()


def resource_references(value: Any) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = node.get("resourceName")
            module_type = node.get("libraryModuleType")
            if name and module_type:
                found[(str(name), str(module_type))] = {
                    "resource_name": str(name),
                    "module_type": str(module_type),
                }
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return sorted(found.values(), key=lambda item: (item["module_type"], item["resource_name"]))


def resource_url(version: str, reference: dict[str, str]) -> str:
    """Resolve DSDB endpoint URL matching Angular `main.*.js` logic."""
    name = reference["resource_name"]
    mtype = reference["module_type"]
    if mtype == "TOKEN_TABLE":
        comp_id = name.split("components/", 1)[-1]
        filename = f"TOKEN_TABLE.{comp_id}"
    elif mtype == "STATUS_TABLE":
        comp_id = name.split("components/", 1)[-1]
        filename = f"STATUS_TABLE.{comp_id}"
    else:
        sys_id = name.split("/", 1)[-1].split("/", 1)[0]
        filename = f"{mtype}.{sys_id}"
    return f"{BASE_URL}/_dsm/data/dsdb-m3/{version}/{filename}.json"


# ---------------------------------------------------------------------------
# DSDB Token Indexing & Resolution
# ---------------------------------------------------------------------------

def _unit_suffix(unit: str | None) -> str:
    mapping = {
        "DIPS": "dp",
        "SP": "sp",
        "POINTS": "pt",
        "PIXELS": "px",
        "PERCENT": "%",
        "MILLISECONDS": "ms",
        "SECONDS": "s",
    }
    return mapping.get((unit or "").upper(), (unit or "").lower())


def _format_length(obj: dict[str, Any]) -> str:
    val = obj.get("value", 0)
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    return f"{val}{_unit_suffix(obj.get('unit'))}"


def _format_color(obj: dict[str, Any]) -> str:
    r = round(float(obj.get("red", 0.0)) * 255)
    g = round(float(obj.get("green", 0.0)) * 255)
    b = round(float(obj.get("blue", 0.0)) * 255)
    a = float(obj.get("alpha", 1.0))
    if a < 0.999:
        aa = round(a * 255)
        return f"#{aa:02X}{r:02X}{g:02X}{b:02X}"
    return f"#{r:02X}{g:02X}{b:02X}"


def format_dsdb_value(val_obj: dict[str, Any]) -> tuple[str, str | None]:
    """Return `(formatted_value, referenced_token_name_or_none)` for a DSDB value entry."""
    if val_obj.get("undefined"):
        return "", None
    if "tokenName" in val_obj:
        ref = str(val_obj["tokenName"])
        return ref, ref
    if "color" in val_obj and isinstance(val_obj["color"], dict):
        return _format_color(val_obj["color"]), None
    if "length" in val_obj and isinstance(val_obj["length"], dict):
        return _format_length(val_obj["length"]), None
    if "elevation" in val_obj and isinstance(val_obj["elevation"], dict):
        return _format_length(val_obj["elevation"]), None
    if "fontSize" in val_obj and isinstance(val_obj["fontSize"], dict):
        return _format_length(val_obj["fontSize"]), None
    if "lineHeight" in val_obj and isinstance(val_obj["lineHeight"], dict):
        return _format_length(val_obj["lineHeight"]), None
    if "tracking" in val_obj and isinstance(val_obj["tracking"], dict):
        return _format_length(val_obj["tracking"]), None
    if "fontTracking" in val_obj and isinstance(val_obj["fontTracking"], dict):
        return _format_length(val_obj["fontTracking"]), None
    if "durationMs" in val_obj:
        return f"{val_obj['durationMs']}ms", None
    if "duration" in val_obj:
        dur = val_obj["duration"]
        if isinstance(dur, dict):
            return _format_length(dur), None
        return f"{dur}ms", None
    if "opacity" in val_obj:
        return str(val_obj["opacity"]), None
    if "numeric" in val_obj:
        return str(val_obj["numeric"]), None
    if "fontWeight" in val_obj:
        return str(val_obj["fontWeight"]), None
    if "textTransform" in val_obj:
        return str(val_obj["textTransform"]), None
    if "fontNames" in val_obj and isinstance(val_obj["fontNames"], dict):
        return ", ".join(str(x) for x in val_obj["fontNames"].get("values", [])), None
    if "axisValue" in val_obj and isinstance(val_obj["axisValue"], dict):
        ax = val_obj["axisValue"]
        tag = ax.get("tag", "")
        v = ax.get("value")
        return (f"{tag}={v}" if v is not None else str(tag)), None
    if "cubicBezier" in val_obj and isinstance(val_obj["cubicBezier"], dict):
        cb = val_obj["cubicBezier"]
        return f"cubic-bezier({cb.get('x0', 0)}, {cb.get('y0', 0)}, {cb.get('x1', 0)}, {cb.get('y1', 0)})", None
    if "shape" in val_obj and isinstance(val_obj["shape"], dict):
        sh = val_obj["shape"]
        fam = sh.get("family", "")
        if fam == "SHAPE_FAMILY_CIRCULAR":
            return "Circular (Full)", None
        corners = [
            f"{k}={_format_length(sh[k])}"
            for k in ("topLeft", "topRight", "bottomRight", "bottomLeft")
            if isinstance(sh.get(k), dict)
        ]
        if corners:
            return "Rounded(" + ", ".join(corners) + ")", None
        if isinstance(sh.get("defaultSize"), dict):
            return f"Rounded({_format_length(sh['defaultSize'])})", None
        return fam or json.dumps(sh, ensure_ascii=False), None
    if "customComposite" in val_obj and isinstance(val_obj["customComposite"], dict):
        props = val_obj["customComposite"].get("properties", {})
        parts = [f"{k}={v.get('tokenName', v)}" for k, v in props.items() if isinstance(v, dict)]
        return ", ".join(parts), None
    for tkey in ("typography", "type"):
        if tkey in val_obj and isinstance(val_obj[tkey], dict):
            props = val_obj[tkey]
            parts = [
                f"{k}={v.get('tokenName', v) if isinstance(v, dict) else v}"
                for k, v in props.items()
            ]
            return ", ".join(parts), None
    if "motionPath" in val_obj and isinstance(val_obj["motionPath"], dict):
        return json.dumps(val_obj["motionPath"], ensure_ascii=False), None
    if "svgPath" in val_obj:
        return str(val_obj["svgPath"]), None
    if "string" in val_obj:
        return str(val_obj["string"]), None
    return "", None


@dataclass(slots=True)
class DsdbIndex:
    """In-memory resolved DSDB token index across all downloaded DSDB JSONs."""

    dsdb_version: str
    revision_create_time: str
    tags: dict[str, str]
    token_sets: dict[str, str]
    tokens_by_name: dict[str, dict[str, Any]]
    values_by_token_path: dict[str, list[dict[str, Any]]]
    components: dict[str, dict[str, Any]]

    @classmethod
    def from_payloads(cls, payloads: list[dict[str, Any]]) -> DsdbIndex:
        dsdb_version = ""
        rev_time = ""
        tags: dict[str, str] = {}
        token_sets: dict[str, str] = {}
        tokens_by_name: dict[str, dict[str, Any]] = {}
        values_by_token_path: dict[str, list[dict[str, Any]]] = {}
        components: dict[str, dict[str, Any]] = {}

        for payload in payloads:
            sys_obj = payload.get("system")
            if not isinstance(sys_obj, dict):
                continue
            dsdb_version = dsdb_version or str(sys_obj.get("dsdbVersion", ""))
            rev_time = max(rev_time, str(sys_obj.get("revisionCreateTime", "")))
            for tag in sys_obj.get("tags", []) or []:
                if isinstance(tag, dict) and tag.get("name"):
                    tags[tag["name"]] = str(tag.get("displayName", tag["name"]))
            for ts in sys_obj.get("tokenSets", []) or []:
                if isinstance(ts, dict) and ts.get("name"):
                    token_sets[ts["name"]] = str(ts.get("displayName", ts["name"])).strip()
            for tok in sys_obj.get("tokens", []) or []:
                tname = tok.get("tokenName")
                if tname:
                    tokens_by_name[tname] = tok
            for val in sys_obj.get("values", []) or []:
                vname = str(val.get("name", ""))
                if "/values/" in vname:
                    tpath = vname.split("/values/", 1)[0]
                    bucket = values_by_token_path.setdefault(tpath, [])
                    if val not in bucket:
                        bucket.append(val)
            for comp in sys_obj.get("components", []) or []:
                if isinstance(comp, dict) and comp.get("name"):
                    comp_id = comp["name"].split("components/", 1)[-1]
                    components[comp_id] = comp

        return cls(
            dsdb_version=dsdb_version,
            revision_create_time=rev_time,
            tags=tags,
            token_sets=token_sets,
            tokens_by_name=tokens_by_name,
            values_by_token_path=values_by_token_path,
            components=components,
        )

    def context_labels(self, val_obj: dict[str, Any]) -> list[str]:
        return [self.tags.get(ct, ct.rsplit("/", 1)[-1]) for ct in (val_obj.get("contextTags") or [])]

    def resolve_token_values(self, token_name: str) -> list[dict[str, Any]]:
        tok = self.tokens_by_name.get(token_name)
        if not tok:
            return []
        raw_vals = self.values_by_token_path.get(tok["name"], [])
        out: list[dict[str, Any]] = []
        for v in raw_vals:
            if v.get("undefined"):
                continue
            formatted, ref = format_dsdb_value(v)
            if not formatted:
                continue
            resolved = formatted
            if ref and ref in self.tokens_by_name:
                resolved = self._resolve_scalar(ref, self.context_labels(v)) or formatted
            out.append(
                {
                    "context": self.context_labels(v),
                    "raw_value": formatted,
                    "resolved_value": resolved,
                    "ref": ref,
                }
            )
        return out

    def _resolve_scalar(self, token_name: str, preferred_ctx: list[str], depth: int = 0) -> str:
        if depth > 6:
            return token_name
        tok = self.tokens_by_name.get(token_name)
        if not tok:
            return ""
        vals = [v for v in self.values_by_token_path.get(tok["name"], []) if not v.get("undefined")]
        if not vals:
            return ""
        # Pick best matching context (default empty context if no better match)
        pref_set = set(preferred_ctx)
        scored: list[tuple[int, dict[str, Any]]] = []
        for v in vals:
            ctx = set(self.context_labels(v))
            if ctx <= pref_set:
                scored.append((len(ctx), v))
        chosen = max(scored, key=lambda x: x[0])[1] if scored else vals[0]
        formatted, ref = format_dsdb_value(chosen)
        if ref and ref != token_name:
            deeper = self._resolve_scalar(ref, preferred_ctx, depth + 1)
            return deeper or formatted
        return formatted


def build_m3e_tokens_manifest(
    index: DsdbIndex,
    carbon_version: str,
    component_pages: dict[str, list[str]],
) -> dict[str, Any]:
    """Build `manifests/tokens/m3-expressive-tokens.json` from resolved DSDB data."""
    # 1. Color palettes & roles
    palettes: dict[str, dict[str, str]] = {}
    color_roles: dict[str, dict[str, str]] = {}
    for tname, tok in sorted(index.tokens_by_name.items()):
        if tname.startswith("md.ref.palette."):
            entry: dict[str, str] = {}
            for rv in index.resolve_token_values(tname):
                ctx_key = "+".join(rv["context"]) or "baseline_1p"
                entry[ctx_key] = rv["resolved_value"]
            if entry:
                palettes[tname] = entry
        elif tname.startswith("md.sys.color."):
            entry = {}
            for rv in index.resolve_token_values(tname):
                if "iOS" in rv["context"]:
                    continue
                ctx_key = "+".join(rv["context"]) or "default"
                entry[ctx_key] = f"{rv['raw_value']} ({rv['resolved_value']})" if rv["ref"] else rv["resolved_value"]
            if entry:
                color_roles[tname] = entry

    # 2. Typography (15 baseline + 15 emphasized + variable axes)
    def collect_type_scale(prefix: str) -> dict[str, dict[str, str]]:
        scales: dict[str, dict[str, str]] = {}
        for role_slug, compose_name in COMPOSE_TYPOGRAPHY_MAP.items():
            role_prefix = f"{prefix}.{role_slug}."
            props: dict[str, str] = {"compose_token": compose_name}
            for tname in sorted(index.tokens_by_name):
                if tname.startswith(role_prefix):
                    prop = tname[len(role_prefix) :]
                    rvs = index.resolve_token_values(tname)
                    non_ios = [r for r in rvs if not (set(r["context"]) & {"iOS", "Web"})]
                    chosen = next((r for r in non_ios if not r["context"]), non_ios[0] if non_ios else (rvs[0] if rvs else None))
                    if chosen:
                        props[prop] = chosen["resolved_value"]
            if len(props) > 1:
                scales[role_slug] = props
        return scales

    typo_baseline = collect_type_scale("md.sys.typescale")
    typo_emphasized = collect_type_scale("md.sys.typescale.emphasized")
    typo_var_baseline = collect_type_scale("md.sys.typescale.variable")
    typo_var_emphasized = collect_type_scale("md.sys.typescale.variable.emphasized")

    # 3. 10-tier Shapes scale
    shapes_scale: dict[str, dict[str, str]] = {}
    shape_directional: dict[str, str] = {}
    for tname in sorted(index.tokens_by_name):
        if tname.startswith("md.sys.shape.corner-value."):
            tier = tname.removeprefix("md.sys.shape.corner-value.")
            rvs = index.resolve_token_values(tname)
            if rvs:
                shapes_scale[tier] = {
                    "token": tname,
                    "compose_token": COMPOSE_SHAPE_MAP.get(tier, ""),
                    "value": rvs[0]["resolved_value"],
                }
        elif tname.startswith("md.sys.shape.corner."):
            tier = tname.removeprefix("md.sys.shape.corner.")
            rvs = index.resolve_token_values(tname)
            if rvs:
                if tier == "full":
                    shapes_scale["full"] = {
                        "token": tname,
                        "compose_token": "CircleShape",
                        "value": rvs[0]["resolved_value"],
                    }
                elif "." in tier:
                    shape_directional[tname] = rvs[0]["resolved_value"]

    # 4. MotionScheme (Expressive vs Standard spatial/effects fast/default/slow + easing/duration)
    motion_scheme: dict[str, Any] = {"expressive": {"spatial": {}, "effects": {}}, "standard": {"spatial": {}, "effects": {}}}
    for scheme in ("expressive", "standard"):
        scheme_tag = scheme.capitalize()
        for kind in ("spatial", "effects"):
            for speed in ("fast", "default", "slow"):
                d_tok = f"md.sys.motion.spring.{speed}.{kind}.damping"
                s_tok = f"md.sys.motion.spring.{speed}.{kind}.stiffness"
                d_val = next((r["resolved_value"] for r in index.resolve_token_values(d_tok) if r["context"] == [scheme_tag]), None)
                s_val = next((r["resolved_value"] for r in index.resolve_token_values(s_tok) if r["context"] == [scheme_tag]), None)
                if d_val is not None or s_val is not None:
                    motion_scheme[scheme][kind][speed] = {
                        "damping_token": d_tok,
                        "damping": float(d_val) if d_val is not None else None,
                        "stiffness_token": s_tok,
                        "stiffness": float(s_val) if s_val is not None else None,
                        "compose_api": f"MotionScheme.{scheme}().{speed}{kind.capitalize()}Spec()",
                    }

    easing_tokens: dict[str, str] = {}
    duration_tokens: dict[str, str] = {}
    for tname in sorted(index.tokens_by_name):
        if tname.startswith("md.sys.motion.easing."):
            rvs = index.resolve_token_values(tname)
            if rvs:
                easing_tokens[tname] = rvs[0]["resolved_value"]
        elif tname.startswith("md.sys.motion.duration."):
            rvs = index.resolve_token_values(tname)
            if rvs:
                duration_tokens[tname] = rvs[0]["resolved_value"]

    # 5. Elevation, State opacities, Spacing
    elevation: dict[str, str] = {}
    state_opacities: dict[str, str] = {}
    spacing: dict[str, str] = {}
    for tname in sorted(index.tokens_by_name):
        rvs = index.resolve_token_values(tname)
        if not rvs:
            continue
        if tname.startswith("md.sys.elevation."):
            elevation[tname] = rvs[0]["resolved_value"]
        elif tname.startswith("md.sys.state."):
            state_opacities[tname] = rvs[0]["resolved_value"]
        elif tname.startswith("md.sys.spacing.") or tname.startswith("md.sys.measurement."):
            spacing[tname] = rvs[0]["resolved_value"]

    # 6. Component tokens grouped by component slug
    comp_tokens: dict[str, Any] = {}
    for slug, comp_ids in sorted(component_pages.items()):
        rows: list[dict[str, Any]] = []
        seen_tname: set[tuple[str, str]] = set()
        comp_names: list[str] = []
        for cid in comp_ids:
            comp = index.components.get(cid)
            if not comp:
                continue
            comp_names.append(str(comp.get("displayName", cid)))
            for ts_path in comp.get("tokenSets", []) or []:
                ts_label = index.token_sets.get(ts_path, ts_path.rsplit("/", 1)[-1])
                for tname, tok in index.tokens_by_name.items():
                    if not tok.get("name", "").startswith(ts_path + "/"):
                        continue
                    rvs = index.resolve_token_values(tname)
                    if not rvs:
                        continue
                    for rv in rvs:
                        ctx_str = ", ".join(rv["context"])
                        dedup_key = (tname, ctx_str)
                        if dedup_key in seen_tname:
                            continue
                        seen_tname.add(dedup_key)
                        rows.append(
                            {
                                "token": tname,
                                "display_name": tok.get("displayName", ""),
                                "type": tok.get("tokenValueType", ""),
                                "token_set": ts_label,
                                "context": ctx_str or "default",
                                "value": rv["raw_value"],
                                "resolved_value": rv["resolved_value"],
                            }
                        )
        if rows:
            rows.sort(key=lambda r: (r["token_set"], r["token"], r["context"]))
            comp_tokens[slug] = {
                "display_names": comp_names,
                "token_count": len(rows),
                "tokens": rows,
            }

    # 7. Flat `DesignToken` list for `rtx` indexing
    flat_tokens: list[dict[str, str]] = []
    for tname, ctx_map in color_roles.items():
        short = tname.removeprefix("md.sys.color.")
        flat_tokens.append(
            {
                "name": tname,
                "category": "color",
                "value": f"Light: {ctx_map.get('Light', ctx_map.get('default', ''))} | Dark: {ctx_map.get('Dark', '')}".strip(" |"),
                "role": short,
                "compose_token": "MaterialTheme.colorScheme." + re.sub(r"-([a-z])", lambda m: m.group(1).upper(), short),
                "spec_version": "M3 Expressive (2025/2026)",
                "notes": "Material 3 dynamic color role; contrast variants in color.roles",
            }
        )
    for role_slug, props in typo_baseline.items():
        flat_tokens.append(
            {
                "name": f"md.sys.typescale.{role_slug}",
                "category": "typography",
                "value": f"font={props.get('font', '')}, size={props.get('size', '')}, lineHeight={props.get('line-height', '')}, weight={props.get('weight', '')}, tracking={props.get('tracking', '')}",
                "role": role_slug,
                "compose_token": f"MaterialTheme.typography.{props['compose_token']}",
                "spec_version": "M3 Baseline",
                "notes": "Baseline typography token",
            }
        )
    for role_slug, props in typo_emphasized.items():
        flat_tokens.append(
            {
                "name": f"md.sys.typescale.emphasized.{role_slug}",
                "category": "typography-emphasized",
                "value": f"font={props.get('font', '')}, size={props.get('size', '')}, lineHeight={props.get('line-height', '')}, weight={props.get('weight', '')}, tracking={props.get('tracking', '')}",
                "role": f"{role_slug}-emphasized",
                "compose_token": f"MaterialTheme.typography.{props['compose_token']}Emphasized",
                "spec_version": "M3 Expressive (2025)",
                "notes": "Expressive emphasized typography token",
            }
        )
    for tier, info in shapes_scale.items():
        flat_tokens.append(
            {
                "name": info["token"],
                "category": "shape",
                "value": info["value"],
                "role": tier,
                "compose_token": info["compose_token"],
                "spec_version": "M3 Expressive (10-tier Shapes)",
                "notes": "10-tier M3 Expressive corner shape scale",
            }
        )
    for scheme in ("expressive", "standard"):
        for kind in ("spatial", "effects"):
            for speed, sdata in motion_scheme[scheme][kind].items():
                flat_tokens.append(
                    {
                        "name": f"md.sys.motion.spring.{scheme}.{speed}.{kind}",
                        "category": "motion-spring",
                        "value": f"dampingRatio={sdata['damping']}, stiffness={sdata['stiffness']}",
                        "role": f"{scheme}-{speed}-{kind}",
                        "compose_token": sdata["compose_api"],
                        "spec_version": "M3 Expressive (MotionScheme)",
                        "notes": f"MotionScheme.{scheme}() {speed} {kind} spring",
                    }
                )
    for tname, val in elevation.items():
        flat_tokens.append(
            {
                "name": tname,
                "category": "elevation",
                "value": val,
                "role": tname.rsplit(".", 1)[-1],
                "compose_token": "",
                "spec_version": "M3",
                "notes": "Tonal & shadow elevation level",
            }
        )
    for tname, val in state_opacities.items():
        flat_tokens.append(
            {
                "name": tname,
                "category": "state",
                "value": val,
                "role": tname.removeprefix("md.sys.state."),
                "compose_token": "",
                "spec_version": "M3",
                "notes": "State layer opacity",
            }
        )

    return {
        "schema_version": "1.0",
        "source": BASE_URL,
        "generated_at": utc_now_iso(),
        "carbon_version": carbon_version,
        "dsdb_version": index.dsdb_version,
        "dsdb_revision_create_time": index.revision_create_time,
        "color": {
            "hct_spec_notes": {
                "2021_spec": "Original Material You HCT dynamic tonal palettes (primary, secondary, tertiary, neutral, neutral-variant, error) with static tone pairings.",
                "2025_expressive_spec": "Updated M3 Expressive ColorSpec2025 / SchemeExpressive & SchemeTonalSpot refinements adding higher-contrast surface containers (surfaceContainerLowest..Highest), fixed accent roles (primaryFixed/FixedDim/onPrimaryFixed/Variant), and expressive chroma/tone curves across light/dark & medium/high contrast.",
            },
            "roles": color_roles,
            "palettes": palettes,
        },
        "typography": {
            "baseline": typo_baseline,
            "emphasized": typo_emphasized,
            "variable_baseline": typo_var_baseline,
            "variable_emphasized": typo_var_emphasized,
        },
        "shapes": {
            "scale": shapes_scale,
            "directional": shape_directional,
        },
        "motion_scheme": motion_scheme,
        "motion_easing": easing_tokens,
        "motion_duration": duration_tokens,
        "elevation": elevation,
        "state_opacities": state_opacities,
        "spacing": spacing,
        "components": comp_tokens,
        "tokens": flat_tokens,
    }


# ---------------------------------------------------------------------------
# Page & Token-Table Markdown Rendering
# ---------------------------------------------------------------------------

def render_dsdb_tables_for_page(
    slug: str,
    tokens_manifest: dict[str, Any],
    index: DsdbIndex,
    component_ids: list[str],
) -> str:
    """Render clean, structured Markdown token tables for system and component pages."""
    sections: list[str] = []

    if slug in {"styles/color/roles", "styles/color/static"}:
        roles = tokens_manifest["color"]["roles"]
        lines = [
            "## System Color Role Tokens",
            "",
            "| Token | Light (Default) | Dark (Default) | Light (High Contrast) | Dark (High Contrast) |",
            "| --- | --- | --- | --- | --- |",
        ]
        for tname, cmap in sorted(roles.items()):
            lines.append(
                f"| `{tname}` | {escape_table(cmap.get('Light', cmap.get('default', '')))} | "
                f"{escape_table(cmap.get('Dark', ''))} | "
                f"{escape_table(cmap.get('Light+High contrast', cmap.get('High contrast+Light', '')))} | "
                f"{escape_table(cmap.get('Dark+High contrast', cmap.get('High contrast+Dark', '')))} |"
            )
        sections.append("\n".join(lines))

    elif slug == "styles/typography":
        for label, key, suffix in (
            ("Baseline Type Scale Tokens (15 roles)", "baseline", ""),
            ("Emphasized Type Scale Tokens (15 `*Emphasized` roles)", "emphasized", "Emphasized"),
        ):
            scale = tokens_manifest["typography"][key]
            lines = [
                f"## {label}",
                "",
                "| Role | Compose Token | Font | Size | Line Height | Weight | Tracking |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
            for rslug, props in scale.items():
                lines.append(
                    f"| `{rslug}` | `MaterialTheme.typography.{props['compose_token']}{suffix}` | "
                    f"{escape_table(props.get('font', ''))} | {escape_table(props.get('size', ''))} | "
                    f"{escape_table(props.get('line-height', ''))} | {escape_table(props.get('weight', ''))} | "
                    f"{escape_table(props.get('tracking', ''))} |"
                )
            sections.append("\n".join(lines))

    elif slug == "styles/shape":
        lines = [
            "## 10-Tier Shape Scale Tokens",
            "",
            "| Tier | Token | Compose `Shapes` Property | Value |",
            "| --- | --- | --- | --- |",
        ]
        order = [
            "none",
            "extra-small",
            "small",
            "medium",
            "large",
            "large-increased",
            "extra-large",
            "extra-large-increased",
            "extra-extra-large",
            "full",
        ]
        for tier in order:
            info = tokens_manifest["shapes"]["scale"].get(tier)
            if info:
                lines.append(
                    f"| `{tier}` | `{info['token']}` | `{info['compose_token']}` | {escape_table(info['value'])} |"
                )
        sections.append("\n".join(lines))

    elif slug in {"styles/motion/overview", "styles/motion/easing-and-duration"}:
        lines = [
            "## MotionScheme Spring Physics (Expressive vs Standard)",
            "",
            "| Scheme | Type | Speed | Damping Ratio | Stiffness | Compose API |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for scheme in ("expressive", "standard"):
            for kind in ("spatial", "effects"):
                for speed in ("fast", "default", "slow"):
                    sdata = tokens_manifest["motion_scheme"][scheme][kind].get(speed)
                    if sdata:
                        lines.append(
                            f"| {scheme} | {kind} | {speed} | `{sdata['damping']}` | `{sdata['stiffness']}` | `{sdata['compose_api']}` |"
                        )
        sections.append("\n".join(lines))

        dur_lines = [
            "## Duration & Easing Tokens",
            "",
            "| Token | Value |",
            "| --- | --- |",
        ]
        for tname, val in sorted(tokens_manifest["motion_duration"].items()):
            dur_lines.append(f"| `{tname}` | {escape_table(val)} |")
        for tname, val in sorted(tokens_manifest["motion_easing"].items()):
            dur_lines.append(f"| `{tname}` | `{escape_table(val)}` |")
        sections.append("\n".join(dur_lines))

    elif slug == "styles/elevation":
        lines = [
            "## Elevation Tokens",
            "",
            "| Token | Value |",
            "| --- | --- |",
        ]
        for tname, val in sorted(tokens_manifest["elevation"].items()):
            lines.append(f"| `{tname}` | {escape_table(val)} |")
        sections.append("\n".join(lines))

    elif slug == "foundations/interaction/states":
        lines = [
            "## State Layer Opacity Tokens",
            "",
            "| Token | Opacity |",
            "| --- | --- |",
        ]
        for tname, val in sorted(tokens_manifest["state_opacities"].items()):
            lines.append(f"| `{tname}` | `{escape_table(val)}` |")
        sections.append("\n".join(lines))

    elif slug == "styles/spacing" and tokens_manifest["spacing"]:
        lines = [
            "## Spacing & Measurement Tokens",
            "",
            "| Token | Value |",
            "| --- | --- |",
        ]
        for tname, val in sorted(tokens_manifest["spacing"].items()):
            lines.append(f"| `{tname}` | {escape_table(val)} |")
        sections.append("\n".join(lines))

    if slug in tokens_manifest["components"]:
        comp_block = tokens_manifest["components"][slug]
        lines = [
            "## Component Design Tokens",
            "",
            "| Token Set | Token | Context | Value | Resolved |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in comp_block["tokens"]:
            lines.append(
                f"| {escape_table(row['token_set'])} | `{row['token']}` | {escape_table(row['context'])} | "
                f"`{escape_table(row['value'])}` | `{escape_table(row['resolved_value'])}` |"
            )
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def render_status_table(value: Any, resolver) -> str:
    if not isinstance(value, dict):
        return ""
    title = normalize_text(value.get("displayName") or "Implementation Status")
    parts = [f"### Implementation Status: {title}"]
    definition = value.get("definition")
    if definition:
        parts.append(normalize_text(definition))
    connections = value.get("connections")
    if isinstance(connections, list) and connections:
        lines = [
            "| Platform / Library | Type | Status | Reference |",
            "| --- | --- | --- | --- |",
        ]
        for conn in connections:
            if not isinstance(conn, dict):
                continue
            rurl = conn.get("resourceUrl") or ""
            link = f"[{escape_table(rurl)}]({resolver(rurl)})" if rurl else ""
            lines.append(
                f"| {escape_table(conn.get('displayName', ''))} | {escape_table(conn.get('resourceType', ''))} | "
                f"{escape_table(conn.get('status', ''))} | {link} |"
            )
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def render_page_body(
    page: dict[str, Any],
    status_resources: list[Any],
    extra_token_md: str,
    asset_map: dict[str, str],
    out_dir: Path,
    markdown_path: Path,
) -> str:
    resolver = lambda u: markdown_resolver(u, asset_map, out_dir, markdown_path)
    title = normalize_text(page.get("headerTitle") or page.get("title") or "Material Design 3")
    parts: list[str] = [f"# {title}"]
    description = page.get("description")
    if description:
        parts.append(normalize_text(description))
    header_image = page.get("headerImageUrl")
    if header_image:
        parts.append(f"![{escape_table(title)}]({resolver(header_image)})")

    for section in page.get("sections") or []:
        section_name = normalize_text(section.get("name"))
        if section_name and section_name.lower() not in {"tab 1", "tab1"}:
            parts.append(f"## {section_name}")
        for block in section.get("contentBlocks") or []:
            block_title = normalize_text(block.get("title"))
            if block_title:
                parts.append(f"### {block_title}")
            for chunk in block.get("contentChunks") or []:
                chunk_parts: list[str] = []
                html_value = chunk.get("htmlValue")
                if html_value:
                    chunk_parts.append(HtmlToMarkdown(resolver).convert(html_value))
                image_url = chunk.get("imageUrl") or chunk.get("imageUrlFife")
                if image_url and not html_value:
                    chunk_parts.append(f"![{escape_table(chunk.get('altText') or 'image')}]({resolver(image_url)})")
                snippet = chunk.get("snippetCode")
                if snippet:
                    language = normalize_text(chunk.get("snippetLanguage"))
                    chunk_parts.append(f"```{language}\n{snippet.rstrip()}\n```")
                for field_name, label in (
                    ("codeUrl", "Code example"),
                    ("prototypeUrl", "Prototype"),
                    ("videoUrl", "Video"),
                    ("linkUrl", "Source"),
                ):
                    link_val = chunk.get(field_name)
                    if link_val:
                        chunk_parts.append(f"[{label}]({resolver(link_val)})")
                footer = chunk.get("footer")
                if footer:
                    footer_text = HtmlToMarkdown(resolver).convert(footer) if "<" in str(footer) else normalize_text(footer)
                    if footer_text:
                        if re.search(r"<(?:ul|ol|li)\b", str(footer), re.I):
                            chunk_parts.append(footer_text.strip())
                        else:
                            chunk_parts.append(f"_{footer_text.strip()}_")
                if chunk_parts:
                    parts.append("\n\n".join(p for p in chunk_parts if p.strip()))

    for st_res in status_resources:
        rendered = render_status_table(st_res, resolver)
        if rendered:
            parts.append(rendered)

    if extra_token_md:
        parts.append(extra_token_md)

    return wrap_long_lines(clean_markdown("\n\n".join(parts)), MAX_LINE_LENGTH)


def build_index_markdown(records: list[dict[str, Any]], carbon_version: str, fetched_at: str) -> str:
    lines = [
        "# Material Design 3 Expressive Corpus Index",
        "",
        f"- **Source**: {BASE_URL}",
        f"- **Carbon Version**: `{carbon_version}`",
        f"- **Fetched At**: `{fetched_at}`",
        f"- **Total Pages**: {len(records)}",
        "",
    ]
    by_section: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_section.setdefault(rec["section"], []).append(rec)

    for sec in ("overview", "blog-expressive", "foundations", "styles", "components", "develop"):
        items = by_section.get(sec, [])
        if not items:
            continue
        lines.append(f"## {sec} ({len(items)})")
        lines.append("")
        lines.append("| Page | Title | Upstream URL |")
        lines.append("| --- | --- | --- |")
        for rec in sorted(items, key=lambda x: x["rel_path"]):
            lines.append(
                f"| [{rec['rel_path']}]({rec['rel_path']}) | {escape_table(rec['title'])} | {rec['url']} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_corpus(out_dir: Path, committed_manifest_path: Path, tokens_path: Path) -> int:
    pages_dir = out_dir / "pages"
    errors: list[str] = []
    if not pages_dir.is_dir():
        errors.append(f"Missing pages directory: {pages_dir}")
    if not (pages_dir / "INDEX.md").is_file():
        errors.append(f"Missing INDEX.md in {pages_dir}")
    if not committed_manifest_path.is_file():
        errors.append(f"Missing committed source manifest: {committed_manifest_path}")
    if not tokens_path.is_file():
        errors.append(f"Missing M3 Expressive token manifest: {tokens_path}")
    else:
        try:
            tok_data = json.loads(tokens_path.read_text(encoding="utf-8"))
            if len(tok_data.get("typography", {}).get("baseline", {})) < 15:
                errors.append("m3-expressive-tokens.json: expected 15 baseline typography roles")
            if len(tok_data.get("typography", {}).get("emphasized", {})) < 15:
                errors.append("m3-expressive-tokens.json: expected 15 emphasized typography roles")
            if len(tok_data.get("shapes", {}).get("scale", {})) < 10:
                errors.append("m3-expressive-tokens.json: expected 10 shape scale tiers")
            if not tok_data.get("motion_scheme", {}).get("expressive", {}).get("spatial"):
                errors.append("m3-expressive-tokens.json: missing expressive spatial springs")
        except Exception as exc:
            errors.append(f"Invalid tokens JSON {tokens_path}: {exc}")

    md_files = sorted(pages_dir.rglob("*.md")) if pages_dir.is_dir() else []
    checked = 0
    for md in md_files:
        if md.name == "INDEX.md":
            continue
        checked += 1
        text = md.read_text(encoding="utf-8", errors="replace")
        meta, body_line = parse_page_frontmatter(text)
        if meta is None:
            errors.append(f"{md.relative_to(out_dir)}: missing frontmatter")
        else:
            for req in ("source_id", "url", "title", "section", "fetched_at", "sha256"):
                if not getattr(meta, req):
                    errors.append(f"{md.relative_to(out_dir)}: missing frontmatter field {req}")
        lines = text.splitlines()
        for lineno, line in enumerate(lines, start=1):
            if len(line) > MAX_LINE_LENGTH:
                errors.append(f"{md.relative_to(out_dir)}:{lineno}: line length {len(line)} > {MAX_LINE_LENGTH}")
        body = "\n".join(lines[body_line - 1 :])
        if not re.search(r"(?m)^#\s+\S", body):
            errors.append(f"{md.relative_to(out_dir)}: missing top-level `#` heading")
        fence_count = len(re.findall(r"(?m)^```", body))
        if fence_count % 2 != 0:
            errors.append(f"{md.relative_to(out_dir)}: unbalanced code fences ({fence_count})")

    report = {
        "source_id": SOURCE_ID,
        "verified_pages": checked,
        "error_count": len(errors),
        "errors": errors[:25],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# Main Sync Orchestration
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="Override `.corpus/m3-expressive` output directory")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent HTTP workers")
    parser.add_argument("--no-assets", action="store_true", help="Skip downloading media/font assets")
    parser.add_argument("--all-assets", action="store_true", help="Download videos in addition to images/fonts")
    parser.add_argument("--keep-json", action="store_true", help="Keep raw Carbon page JSON files under raw/")
    parser.add_argument("--check", action="store_true", help="Check upstream carbonVersion without rewriting corpus")
    parser.add_argument("--refresh", action="store_true", help="Force re-download ignoring conditional HTTP cache")
    parser.add_argument("--verify", action="store_true", help="Verify corpus pages, frontmatter, line lengths, and tokens")
    args = parser.parse_args(argv)

    paths = get_paths(REPO_ROOT)
    out_dir = args.out.resolve() if args.out else paths.source_corpus_dir(SOURCE_ID)
    committed_manifest_path = paths.source_committed_manifest(SOURCE_ID)
    tokens_manifest_path = paths.token_manifests_dir / "m3-expressive-tokens.json"

    raw_argv = argv if argv is not None else sys.argv[1:]
    if args.verify and set(raw_argv) <= {"--verify"} and (out_dir / "pages").is_dir():
        return verify_corpus(out_dir, committed_manifest_path, tokens_manifest_path)

    client = ConditionalHttpClient(
        cache_dir=out_dir / "raw",
        timeout=30.0,
        max_retries=4,
        respect_robots=True,
    )

    home_res = client.fetch(BASE_URL + "/", force_refresh=args.refresh, headers={"Accept": "text/html"})
    if not home_res.ok and not home_res.not_modified:
        raise RuntimeError(f"Failed to fetch {BASE_URL}/: {home_res.error}")
    home_html_path = out_dir / "raw" / "home.html"
    if home_res.body is not None:
        write_bytes(home_html_path, home_res.body)
    home_text = home_html_path.read_text(encoding="utf-8", errors="replace")

    main_url = extract_main_script(home_text)
    main_res = client.fetch(main_url, force_refresh=args.refresh, headers={"Accept": "text/javascript"})
    if not main_res.ok and not main_res.not_modified:
        raise RuntimeError(f"Failed to fetch {main_url}: {main_res.error}")
    main_js_path = out_dir / "raw" / "main.js"
    if main_res.body is not None:
        write_bytes(main_js_path, main_res.body)
    bundle_text = main_js_path.read_text(encoding="utf-8", errors="replace")

    version_match = re.search(r'carbonVersion:"([^"]+)"', bundle_text)
    if not version_match:
        raise RuntimeError("Could not find `carbonVersion` in Angular main.js")
    carbon_version = version_match.group(1)

    if args.check:
        prev_version = ""
        if committed_manifest_path.is_file():
            try:
                prev_version = json.loads(committed_manifest_path.read_text(encoding="utf-8")).get("upstream_version", "")
            except Exception:
                prev_version = ""
        client.save_state()
        print(
            json.dumps(
                {
                    "source_id": SOURCE_ID,
                    "upstream_version": carbon_version,
                    "local_version": prev_version,
                    "up_to_date": bool(prev_version and prev_version == carbon_version),
                },
                indent=2,
            )
        )
        return 0

    routes = discover_routes(bundle_text, carbon_version)
    write_json(out_dir / "raw" / "routes.json", routes)

    # 1. Fetch all 95 Carbon page JSONs
    page_payloads: dict[str, dict[str, Any]] = {}
    page_http_meta: dict[str, dict[str, str]] = {}
    discovered_urls: set[str] = set()
    failed_pages: list[dict[str, str]] = []

    def fetch_page(route: dict[str, str]) -> tuple[dict[str, str], dict[str, Any] | None, dict[str, str], set[str], str]:
        url = route["content_url"]
        cache_file = out_dir / "raw" / "carbon-pages" / f"{route['content_id']}"
        res = client.fetch(url, force_refresh=args.refresh, headers={"Accept": "application/json"})
        if res.not_modified and cache_file.is_file():
            raw = cache_file.read_bytes()
        elif res.ok and res.body is not None:
            raw = res.body
            write_bytes(cache_file, raw)
        else:
            return route, None, {}, set(), res.error or f"HTTP {res.status}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return route, None, {}, set(), str(exc)
        meta = {
            "last_modified": res.last_modified or str(payload.get("updatedTimestamp", "")),
            "etag": res.etag,
        }
        return route, payload, meta, extract_urls(raw), ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for route, payload, meta, urls, err in pool.map(fetch_page, routes):
            if payload is None:
                failed_pages.append({"slug": route["slug"], "url": route["content_url"], "error": err})
            else:
                page_payloads[route["slug"]] = payload
                page_http_meta[route["slug"]] = meta
                discovered_urls.update(urls)

    # 2. Discover & fetch DSDB system & component resources
    resource_refs_by_page: dict[str, list[dict[str, str]]] = {}
    resource_jobs: dict[str, dict[str, str]] = {}
    for mtype, rname in DSDB_SYSTEM_FILES:
        ref = {"resource_name": rname, "module_type": mtype}
        resource_jobs[resource_url(carbon_version, ref)] = ref

    component_ids_by_slug: dict[str, list[str]] = {}
    for slug, payload in page_payloads.items():
        refs = resource_references(payload)
        resource_refs_by_page[slug] = refs
        for ref in refs:
            resource_jobs[resource_url(carbon_version, ref)] = ref
            if ref["module_type"] == "TOKEN_TABLE" and "components/" in ref["resource_name"]:
                cid = ref["resource_name"].split("components/", 1)[-1]
                component_ids_by_slug.setdefault(slug, []).append(cid)

    resource_values: dict[str, Any] = {}
    failed_resources: list[dict[str, str]] = []

    def fetch_resource(item: tuple[str, dict[str, str]]) -> tuple[str, Any, set[str], str]:
        url, _ref = item
        fname = Path(urlparse(url).path).name
        cache_file = out_dir / "raw" / "dsdb" / fname
        res = client.fetch(url, force_refresh=args.refresh, headers={"Accept": "application/json"})
        if res.not_modified and cache_file.is_file():
            raw = cache_file.read_bytes()
        elif res.ok and res.body is not None:
            raw = res.body
            write_bytes(cache_file, raw)
        else:
            return url, None, set(), res.error or f"HTTP {res.status}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return url, None, set(), str(exc)
        return url, payload, extract_urls(raw), ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for url, payload, urls, err in pool.map(fetch_resource, resource_jobs.items()):
            if payload is None:
                failed_resources.append({"url": url, "error": err})
            else:
                resource_values[url] = payload
                discovered_urls.update(urls)

    # 3. Build DSDB index & structured tokens manifest
    dsdb_payloads = [v for v in resource_values.values() if isinstance(v, dict) and "system" in v]
    dsdb_index = DsdbIndex.from_payloads(dsdb_payloads)
    tokens_manifest = build_m3e_tokens_manifest(dsdb_index, carbon_version, component_ids_by_slug)
    write_json(tokens_manifest_path, tokens_manifest)

    # 4. Assets (optional)
    asset_map: dict[str, str] = {}
    asset_count = 0
    if not args.no_assets:
        asset_jobs: list[tuple[str, str]] = []
        for url in sorted(discovered_urls):
            kind = asset_kind(url)
            if kind and (args.all_assets or kind in {"image", "font"}):
                asset_jobs.append((url, kind))

        def fetch_asset(item: tuple[str, str]) -> tuple[str, str | None]:
            url, kind = item
            rel = asset_rel_path(url, kind)
            target = out_dir / rel
            if target.exists() and not args.refresh:
                return url, rel
            res = client.fetch(url, force_refresh=args.refresh)
            if res.ok and res.body is not None:
                rel = asset_rel_path(url, kind, res.content_type)
                write_bytes(out_dir / rel, res.body)
                return url, rel
            return url, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for url, rel in pool.map(fetch_asset, asset_jobs):
                if rel:
                    asset_map[url] = rel
                    asset_count += 1

    # 5. Render Markdown pages with YAML frontmatter + token tables
    fetched_at = utc_now_iso()
    pages_dir = out_dir / "pages"
    page_records: list[dict[str, Any]] = []
    section_counts: dict[str, int] = {}

    for route in routes:
        slug = route["slug"]
        payload = page_payloads.get(slug)
        if not payload:
            continue
        rel = page_rel_path(slug)
        md_path = pages_dir / rel
        status_list = []
        for ref in resource_refs_by_page.get(slug, []):
            if ref["module_type"] == "STATUS_TABLE":
                rurl = resource_url(carbon_version, ref)
                if rurl in resource_values:
                    status_list.append(resource_values[rurl])

        extra_tokens_md = render_dsdb_tables_for_page(
            slug,
            tokens_manifest,
            dsdb_index,
            component_ids_by_slug.get(slug, []),
        )
        body = render_page_body(payload, status_list, extra_tokens_md, asset_map, out_dir, md_path)
        title = normalize_text(payload.get("headerTitle") or payload.get("title") or slug or "Material Design 3")
        http_meta = page_http_meta.get(slug, {})
        content_sha = sha256_text(body)
        meta = PageMetadata(
            source_id=SOURCE_ID,
            url=route["page_url"],
            title=title,
            section=route["section"],
            fetched_at=fetched_at,
            last_modified=http_meta.get("last_modified", ""),
            sha256=content_sha,
            etag=http_meta.get("etag", ""),
            extra={"carbon_version": carbon_version, "slug": slug or "home"},
        )
        full_md = format_page_frontmatter(meta, style="yaml") + body
        write_text(md_path, full_md)

        section_counts[route["section"]] = section_counts.get(route["section"], 0) + 1
        page_records.append(
            {
                "slug": slug,
                "rel_path": rel,
                "url": route["page_url"],
                "title": title,
                "section": route["section"],
                "sha256": content_sha,
            }
        )

    write_text(pages_dir / "INDEX.md", build_index_markdown(page_records, carbon_version, fetched_at))
    client.save_state()

    manifest = SourceManifest(
        source_id=SOURCE_ID,
        name=SOURCE_NAME,
        base_url=BASE_URL,
        fetched_at=fetched_at,
        page_count=len(page_records),
        asset_count=asset_count,
        failed_count=len(failed_pages) + len(failed_resources),
        status="ok" if not failed_pages else "partial",
        upstream_version=carbon_version,
        versions={
            "carbon_version": carbon_version,
            "dsdb_version": dsdb_index.dsdb_version,
            "dsdb_revision_create_time": dsdb_index.revision_create_time,
        },
        sections=dict(sorted(section_counts.items())),
        notes=(
            f"Mirrored all {len(page_records)} M3 Carbon routes including M3 Expressive blog/feature routes, "
            f"foundations, styles, components, and develop; extracted {len(tokens_manifest['tokens'])} flat tokens "
            f"and {len(tokens_manifest['components'])} component token tables into manifests/tokens/m3-expressive-tokens.json."
        ),
    )
    manifest.write_json(out_dir / "manifest.json")
    manifest.write_json(committed_manifest_path)

    if failed_pages or failed_resources:
        write_json(
            out_dir / "raw" / "failures.json",
            {"pages": failed_pages, "resources": failed_resources},
        )

    print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))

    if args.verify:
        return verify_corpus(out_dir, committed_manifest_path, tokens_manifest_path)
    return 0 if not failed_pages else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
