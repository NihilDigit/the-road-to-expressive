#!/usr/bin/env python3
"""Mirror the Apple Human Interface Guidelines via Apple's structured DocC JSON API.

Fetches the DocC index tree from developer.apple.com, checks robots.txt, uses
conditional HTTP caching (ETag / Last-Modified), renders lossless Markdown with
YAML frontmatter, tables, asides, platform notes, and code listings, and
verifies structural integrity.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.robotparser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen


SOURCE_ID = "apple-hig"
SOURCE_NAME = "Apple Human Interface Guidelines"
BASE_URL = "https://developer.apple.com"
HIG_PATH_PREFIX = "/design/human-interface-guidelines"
INDEX_URL = f"{BASE_URL}/tutorials/data/index/design--human-interface-guidelines"
ROOT_JSON_URL = f"{BASE_URL}/tutorials/data/design/human-interface-guidelines.json"
USER_AGENT = "RoadToExpressive-AppleHIGMirror/0.1 (+local documentation mirror)"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / ".corpus" / SOURCE_ID
COMMITTED_MANIFEST = REPO_ROOT / "manifests" / "sources" / f"{SOURCE_ID}.json"
MAX_LINE_LENGTH = 4000


class FetchFailure(RuntimeError):
    def __init__(self, url: str, message: str):
        super().__init__(f"{url}: {message}")
        self.url = url


class RobotsChecker:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._lock = threading.Lock()
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.checked_hosts: set[str] = set()

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            parser = self._parsers.get(root)
            if parser is None:
                parser = urllib.robotparser.RobotFileParser()
                robots_url = f"{root}/robots.txt"
                parser.set_url(robots_url)
                try:
                    req = Request(robots_url, headers={"User-Agent": self.user_agent})
                    with urlopen(req, timeout=20) as resp:
                        text = resp.read().decode("utf-8", errors="replace")
                    parser.parse(text.splitlines())
                except HTTPError as err:
                    if err.code == 404:
                        parser.allow_all = True
                    else:
                        parser.disallow_all = True
                except Exception:
                    parser.allow_all = True
                self._parsers[root] = parser
                self.checked_hosts.add(root)
        return parser.can_fetch(self.user_agent, url)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def encode_url(url: str) -> str:
    parts = urlparse(url)
    return parts._replace(path=quote(parts.path, safe="/%")).geturl()


def http_get(
    url: str,
    *,
    accept: str = "application/json,*/*",
    etag: str | None = None,
    last_modified: str | None = None,
    method: str = "GET",
    attempts: int = 4,
) -> tuple[int, bytes, dict[str, str]]:
    url = encode_url(url)
    last_error: Exception | None = None
    for attempt in range(attempts):
        headers = {
            "Accept": accept,
            "Accept-Encoding": "gzip",
            "User-Agent": USER_AGENT,
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        req = Request(url, headers=headers, method=method)
        try:
            with urlopen(req, timeout=45) as resp:
                raw = resp.read()
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                if resp_headers.get("content-encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                return resp.status, raw, resp_headers
        except HTTPError as err:
            if err.code == 304:
                resp_headers = {k.lower(): v for k, v in err.headers.items()}
                return 304, b"", resp_headers
            last_error = err
            if err.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise FetchFailure(url, f"HTTP {err.code}") from err
            retry_after = err.headers.get("Retry-After")
            try:
                delay = min(30.0, float(retry_after)) if retry_after else 2.0**attempt
            except ValueError:
                delay = 2.0**attempt
            time.sleep(delay)
        except (URLError, TimeoutError, OSError, http.client.HTTPException) as err:
            last_error = err
            time.sleep(min(30.0, 2.0**attempt))
    raise FetchFailure(url, str(last_error or "unknown fetch error"))


def wrap_long_line(line: str, limit: int = 3600) -> list[str]:
    if len(line) <= limit:
        return [line]
    # Preserve list/blockquote prefix if any when wrapping prose.
    prefix_match = re.match(r"^(\s*(?:[-*]|\d+\.|>+)\s+)", line)
    cont_prefix = "  " if prefix_match else ""
    words = line.split(" ")
    out: list[str] = []
    cur = ""
    for word in words:
        if len(word) > limit:
            if cur:
                out.append(cur)
                cur = ""
            for i in range(0, len(word), limit):
                out.append(word[i : i + limit])
            continue
        candidate = word if not cur else f"{cur} {word}"
        if len(candidate) <= limit:
            cur = candidate
        else:
            out.append(cur)
            cur = cont_prefix + word
    if cur:
        out.append(cur)
    return out


def normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines: list[str] = []
    for raw_line in text.split("\n"):
        if len(raw_line) > MAX_LINE_LENGTH:
            lines.extend(wrap_long_line(raw_line, 3600))
        else:
            lines.append(raw_line)
    return "\n".join(lines).strip() + "\n"


def yaml_escape(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def build_frontmatter(
    *,
    url: str,
    title: str,
    section: str,
    fetched_at: str,
    last_modified: str,
    sha256: str,
) -> str:
    return (
        "---\n"
        f"source_id: {yaml_escape(SOURCE_ID)}\n"
        f"url: {yaml_escape(url)}\n"
        f"title: {yaml_escape(title)}\n"
        f"section: {yaml_escape(section)}\n"
        f"fetched_at: {yaml_escape(fetched_at)}\n"
        f"last_modified: {yaml_escape(last_modified)}\n"
        f"sha256: {yaml_escape(sha256)}\n"
        "---\n\n"
    )


def discover_hig_entries(index_data: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = [
        {
            "slug": "",
            "path": HIG_PATH_PREFIX,
            "title": "Human Interface Guidelines",
            "section": "Overview",
            "web_url": f"{BASE_URL}{HIG_PATH_PREFIX}",
            "json_url": ROOT_JSON_URL,
        }
    ]
    seen_paths = {HIG_PATH_PREFIX}

    def walk(nodes: list[dict[str, Any]], trail: list[str]) -> None:
        for node in nodes:
            title = str(node.get("title") or "").strip()
            path = str(node.get("path") or "").strip()
            node_type = str(node.get("type") or "").strip()
            children = node.get("children") or []
            if path.startswith(HIG_PATH_PREFIX) and path not in seen_paths and node_type != "groupMarker":
                seen_paths.add(path)
                slug = path.removeprefix(HIG_PATH_PREFIX).strip("/")
                json_url = (
                    ROOT_JSON_URL
                    if not slug
                    else f"{BASE_URL}/tutorials/data/design/human-interface-guidelines/{slug}.json"
                )
                section = " / ".join(trail) if trail else "Root"
                entries.append(
                    {
                        "slug": slug,
                        "path": path,
                        "title": title or slug or "Human Interface Guidelines",
                        "section": section,
                        "web_url": f"{BASE_URL}{path}",
                        "json_url": json_url,
                    }
                )
            next_trail = trail + ([title] if title and (children or node_type == "groupMarker") else [])
            if children:
                walk(children, next_trail)

    swift_nodes = index_data.get("interfaceLanguages", {}).get("swift", [])
    walk(swift_nodes, [])
    return entries


def slug_to_relpath(slug: str) -> str:
    if not slug:
        return "index.md"
    clean = re.sub(r"[^A-Za-z0-9/_-]+", "-", slug).strip("/")
    return f"{clean}.md"


def resolve_doc_link(url_or_path: str, current_relpath: str) -> str:
    if url_or_path.startswith(HIG_PATH_PREFIX):
        path_part, _, frag = url_or_path.partition("#")
        target_slug = path_part.removeprefix(HIG_PATH_PREFIX).strip("/")
        target_rel = slug_to_relpath(target_slug)
        rel = Path(os.path.relpath(target_rel, Path(current_relpath).parent)).as_posix()
        return f"{rel}#{frag}" if frag else rel
    if url_or_path.startswith("/"):
        return f"{BASE_URL}{url_or_path}"
    return url_or_path


def render_inline(
    items: list[dict[str, Any]],
    references: dict[str, Any],
    current_relpath: str,
    asset_resolver: Any,
) -> str:
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(item.get("text", ""))
        elif kind == "codeVoice":
            code = str(item.get("code", "")).replace("`", "\\`")
            parts.append(f"`{code}`")
        elif kind == "strong":
            inner = render_inline(item.get("inlineContent", []), references, current_relpath, asset_resolver)
            parts.append(f"**{inner}**" if inner.strip() else inner)
        elif kind in {"emphasis", "newTerm"}:
            inner = render_inline(item.get("inlineContent", []), references, current_relpath, asset_resolver)
            parts.append(f"*{inner}*" if inner.strip() else inner)
        elif kind == "inlineHead":
            inner = render_inline(item.get("inlineContent", []), references, current_relpath, asset_resolver)
            parts.append(f"**{inner}**" if inner.strip() else inner)
        elif kind == "reference":
            ident = item.get("identifier", "")
            ref = references.get(ident, {})
            title = item.get("overridingTitle") or ref.get("title") or ident.rsplit("/", 1)[-1]
            url = ref.get("url") or ""
            is_active = item.get("isActive", True)
            if url and is_active:
                resolved = resolve_doc_link(url, current_relpath)
                parts.append(f"[{title}]({resolved})")
            else:
                parts.append(str(title))
        elif kind == "image":
            ident = item.get("identifier", "")
            ref = references.get(ident, {})
            alt_items = (item.get("metadata") or {}).get("abstract") or []
            alt = render_inline(alt_items, references, current_relpath, asset_resolver).strip()
            if not alt:
                alt = str(ref.get("alt") or ident)
            variants = ref.get("variants") or []
            img_url = variants[0].get("url", "") if variants else ""
            if img_url.startswith("/"):
                img_url = BASE_URL + img_url
            resolved = asset_resolver(img_url) if img_url else ""
            if resolved:
                parts.append(f"![{alt}]({resolved})")
            elif alt:
                parts.append(f"[Image: {alt}]")
        else:
            if "inlineContent" in item:
                parts.append(render_inline(item["inlineContent"], references, current_relpath, asset_resolver))
            elif "text" in item:
                parts.append(str(item["text"]))
    return "".join(parts)


def escape_cell(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def render_blocks(
    blocks: list[dict[str, Any]],
    references: dict[str, Any],
    current_relpath: str,
    asset_resolver: Any,
    *,
    indent: str = "",
) -> str:
    out: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "heading":
            level = min(6, max(1, int(block.get("level", 2))))
            text = str(block.get("text") or "").strip()
            if text:
                out.append(f"{'#' * level} {text}\n")
        elif btype == "paragraph":
            txt = render_inline(block.get("inlineContent", []), references, current_relpath, asset_resolver).strip()
            if txt:
                out.append(f"{indent}{txt}\n")
        elif btype == "small":
            txt = render_inline(block.get("inlineContent", []), references, current_relpath, asset_resolver).strip()
            if txt:
                out.append(f"{indent}*{txt}*\n")
        elif btype in {"unorderedList", "orderedList"}:
            ordered = btype == "orderedList"
            lines: list[str] = []
            for idx, item in enumerate(block.get("items", []), start=1):
                marker = f"{idx}. " if ordered else "- "
                sub_blocks = item.get("content", [])
                rendered_sub = render_blocks(sub_blocks, references, current_relpath, asset_resolver)
                sub_lines = [ln for ln in rendered_sub.strip().splitlines()]
                if sub_lines:
                    lines.append(f"{indent}{marker}{sub_lines[0]}")
                    for extra in sub_lines[1:]:
                        lines.append(f"{indent}  {extra}" if extra else "")
            if lines:
                out.append("\n".join(lines) + "\n")
        elif btype == "aside":
            style = str(block.get("name") or block.get("style") or "Note").strip()
            style_label = style[:1].upper() + style[1:]
            inner = render_blocks(block.get("content", []), references, current_relpath, asset_resolver).strip()
            if inner:
                quoted = "\n".join(f"> {ln}" if ln else ">" for ln in inner.splitlines())
                out.append(f"> **{style_label}:**\n{quoted}\n")
        elif btype == "codeListing":
            syntax = str(block.get("syntax") or "").strip()
            code_lines = block.get("code") or []
            code_body = "\n".join(str(ln) for ln in code_lines)
            out.append(f"```{syntax}\n{code_body}\n```\n")
        elif btype == "table":
            rows_raw = block.get("rows") or []
            header_kind = block.get("header") or "row"
            rendered_rows: list[list[str]] = []
            for row in rows_raw:
                cells = []
                for cell in row:
                    cell_md = render_blocks(cell, references, current_relpath, asset_resolver).strip()
                    cells.append(escape_cell(cell_md))
                rendered_rows.append(cells)
            if rendered_rows:
                width = max(len(r) for r in rendered_rows)
                norm_rows = [r + [""] * (width - len(r)) for r in rendered_rows]
                if header_kind in {"row", "both"}:
                    head = norm_rows[0]
                    body = norm_rows[1:]
                else:
                    head = [f"Column {i + 1}" for i in range(width)]
                    body = norm_rows
                table_lines = [
                    "| " + " | ".join(head) + " |",
                    "| " + " | ".join("---" for _ in head) + " |",
                ]
                for r in body:
                    table_lines.append("| " + " | ".join(r) + " |")
                out.append("\n".join(table_lines) + "\n")
        elif btype == "row":
            for col in block.get("columns", []):
                col_md = render_blocks(col.get("content", []), references, current_relpath, asset_resolver).strip()
                if col_md:
                    out.append(col_md + "\n")
        elif btype == "tabNavigator":
            for tab in block.get("tabs", []):
                t_title = str(tab.get("title") or "Tab").strip()
                t_body = render_blocks(tab.get("content", []), references, current_relpath, asset_resolver).strip()
                out.append(f"#### {t_title}\n")
                if t_body:
                    out.append(t_body + "\n")
        elif btype == "termList":
            term_lines: list[str] = []
            for item in block.get("items", []):
                term = render_inline(
                    (item.get("term") or {}).get("inlineContent", []),
                    references,
                    current_relpath,
                    asset_resolver,
                ).strip()
                defn = render_blocks(
                    (item.get("definition") or {}).get("content", []),
                    references,
                    current_relpath,
                    asset_resolver,
                ).strip()
                defn_flat = re.sub(r"\n+", " ", defn).strip()
                if term or defn_flat:
                    term_lines.append(f"- **{term}**: {defn_flat}")
            if term_lines:
                out.append("\n".join(term_lines) + "\n")
        elif btype == "links":
            link_lines: list[str] = []
            for ident in block.get("items", []):
                ref = references.get(ident, {})
                title = ref.get("title") or ident.rsplit("/", 1)[-1]
                url = ref.get("url") or ""
                abstract = render_inline(ref.get("abstract", []), references, current_relpath, asset_resolver).strip()
                if url:
                    resolved = resolve_doc_link(url, current_relpath)
                    suffix = f" — {abstract}" if abstract else ""
                    link_lines.append(f"- [{title}]({resolved}){suffix}")
            if link_lines:
                out.append("\n".join(link_lines) + "\n")
        elif btype == "video":
            ident = block.get("identifier", "")
            ref = references.get(ident, {})
            alt = str(ref.get("alt") or ident or "Video")
            variants = ref.get("variants") or []
            v_url = variants[0].get("url", "") if variants else ""
            if v_url.startswith("/"):
                v_url = BASE_URL + v_url
            out.append(f"[Video: {alt}]({v_url})\n" if v_url else f"[Video: {alt}]\n")
        elif btype == "thematicBreak":
            out.append("---\n")
        else:
            if "content" in block and isinstance(block["content"], list):
                sub = render_blocks(block["content"], references, current_relpath, asset_resolver).strip()
                if sub:
                    out.append(sub + "\n")
    return "\n".join(out)


def extract_assets_from_doc(doc: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for ref in (doc.get("references") or {}).values():
        if not isinstance(ref, dict):
            continue
        if ref.get("type") == "image":
            for variant in ref.get("variants") or []:
                u = variant.get("url") or ""
                if u:
                    if u.startswith("/"):
                        u = BASE_URL + u
                    urls.append(u)
                    break
    return urls


def render_docc_markdown(
    doc: dict[str, Any],
    entry: dict[str, str],
    current_relpath: str,
    asset_map: dict[str, str],
    out_dir: Path,
) -> tuple[str, str]:
    references = doc.get("references") or {}
    metadata = doc.get("metadata") or {}
    title = str(metadata.get("title") or entry["title"] or "Untitled").strip()

    def asset_resolver(remote_url: str) -> str:
        local = asset_map.get(remote_url)
        if local:
            page_dir = (out_dir / "pages" / current_relpath).parent
            return Path(os.path.relpath(out_dir / local, page_dir)).as_posix()
        return remote_url

    parts: list[str] = [f"# {title}\n"]

    platforms = metadata.get("platforms") or []
    plat_names = [str(p.get("name")) for p in platforms if isinstance(p, dict) and p.get("name")]
    if plat_names:
        parts.append(f"**Platforms:** {', '.join(plat_names)}\n")

    abstract = render_inline(doc.get("abstract") or [], references, current_relpath, asset_resolver).strip()
    if abstract:
        parts.append(f"{abstract}\n")

    for section in doc.get("primaryContentSections") or []:
        if section.get("kind") == "content":
            rendered = render_blocks(section.get("content") or [], references, current_relpath, asset_resolver).strip()
            if rendered:
                parts.append(rendered + "\n")

    for topic_sec in doc.get("topicSections") or []:
        sec_title = str(topic_sec.get("title") or "Topics").strip()
        items = topic_sec.get("identifiers") or []
        if items:
            lines = [f"## {sec_title}\n"]
            for ident in items:
                ref = references.get(ident, {})
                t = ref.get("title") or ident.rsplit("/", 1)[-1]
                u = ref.get("url") or ""
                abs_txt = render_inline(ref.get("abstract") or [], references, current_relpath, asset_resolver).strip()
                if u:
                    resolved = resolve_doc_link(u, current_relpath)
                    suffix = f" — {abs_txt}" if abs_txt else ""
                    lines.append(f"- [{t}]({resolved}){suffix}")
                else:
                    lines.append(f"- {t}")
            parts.append("\n".join(lines) + "\n")

    body = normalize_markdown("\n".join(parts))
    return title, body


def local_asset_relpath(url: str) -> str:
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower() or ".bin"
    if len(ext) > 6:
        ext = ".bin"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(parsed.path).stem)[:48].strip("-.") or "asset"
    digest = sha256_bytes(url.encode("utf-8"))[:12]
    return f"assets/{stem}-{digest}{ext}"


def load_cache(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_frontmatter(text: str) -> dict[str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    block = text[4:end]
    result: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            try:
                v = json.loads(v)
            except Exception:
                pass
        result[k.strip()] = v
    return result


def verify_corpus(out_dir: Path) -> int:
    pages_dir = out_dir / "pages"
    manifest_path = out_dir / "manifest.json"
    index_path = pages_dir / "INDEX.md"
    errors: list[str] = []

    if not manifest_path.exists():
        errors.append(f"missing manifest: {manifest_path}")
    if not index_path.exists():
        errors.append(f"missing INDEX.md: {index_path}")

    md_files = sorted(pages_dir.rglob("*.md")) if pages_dir.exists() else []
    if not md_files:
        errors.append("no markdown files found under pages/")

    required_keys = {"source_id", "url", "title", "section", "fetched_at", "last_modified", "sha256"}
    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        if fm is None:
            errors.append(f"{md_file}: missing YAML frontmatter")
            continue
        missing = required_keys - set(fm.keys())
        if missing:
            errors.append(f"{md_file}: missing frontmatter keys {sorted(missing)}")
        fence_count = 0
        has_heading = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if len(line) > MAX_LINE_LENGTH:
                errors.append(f"{md_file}:{lineno}: line length {len(line)} > {MAX_LINE_LENGTH}")
            if line.startswith("```"):
                fence_count += 1
            if line.startswith("# "):
                has_heading = True
        if fence_count % 2 != 0:
            errors.append(f"{md_file}: unbalanced fenced code blocks")
        if not has_heading:
            errors.append(f"{md_file}: missing H1 heading")

    if index_path.exists():
        idx_text = index_path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#]+\.md)\)", idx_text):
            resolved = (index_path.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"INDEX.md broken link: {target}")

    report = {
        "source_id": SOURCE_ID,
        "verified": len(errors) == 0,
        "markdown_files": len(md_files),
        "error_count": len(errors),
        "errors": errors[:30],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def run_check(robots: RobotsChecker, out_dir: Path) -> int:
    cache = load_cache(out_dir / "raw" / "http-cache.json")
    if not robots.allowed(INDEX_URL):
        print(json.dumps({"source_id": SOURCE_ID, "status": "blocked-by-robots"}))
        return 1
    cached_idx = cache.get(INDEX_URL, {})
    status, raw, headers = http_get(
        INDEX_URL,
        etag=cached_idx.get("etag"),
        last_modified=cached_idx.get("last_modified"),
    )
    entry_count = None
    if status == 200 and raw:
        data = json.loads(raw.decode("utf-8"))
        entry_count = len(discover_hig_entries(data))
    report = {
        "source_id": SOURCE_ID,
        "index_url": INDEX_URL,
        "http_status": status,
        "up_to_date": status == 304,
        "discovered_pages": entry_count,
        "etag": headers.get("etag", cached_idx.get("etag", "")),
        "last_modified": headers.get("last-modified", cached_idx.get("last_modified", "")),
        "local_manifest_exists": (out_dir / "manifest.json").exists(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_index_md(records: list[dict[str, Any]], fetched_at: str) -> str:
    lines = [
        "# Apple Human Interface Guidelines — Mirror Index\n",
        f"Total mirrored pages: **{len(records)}**\n",
        "| Title | Section | Local File | Source URL |",
        "| --- | --- | --- | --- |",
    ]
    for rec in records:
        if rec.get("status") != "ok":
            continue
        title = escape_cell(rec["title"])
        section = escape_cell(rec["section"])
        rel = rec["relpath"]
        url = rec["url"]
        lines.append(f"| {title} | {section} | [{rel}]({rel}) | {url} |")
    body = normalize_markdown("\n".join(lines))
    fm = build_frontmatter(
        url=f"{BASE_URL}{HIG_PATH_PREFIX}",
        title="Apple Human Interface Guidelines — Index",
        section="Index",
        fetched_at=fetched_at,
        last_modified=fetched_at,
        sha256=sha256_bytes(body.encode("utf-8")),
    )
    return fm + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (default: .corpus/apple-hig)")
    parser.add_argument("--workers", type=int, default=10, help="parallel worker count")
    parser.add_argument("--no-assets", action="store_true", help="skip downloading images/assets")
    parser.add_argument("--refresh", action="store_true", help="ignore conditional HTTP cache and re-fetch")
    parser.add_argument("--check", action="store_true", help="check upstream freshness without modifying corpus")
    parser.add_argument("--verify", action="store_true", help="verify mirrored Markdown and manifests")
    args = parser.parse_args()

    out_dir = args.out.resolve()
    robots = RobotsChecker(USER_AGENT)

    if args.verify and not args.refresh and not args.no_assets:
        return verify_corpus(out_dir)

    if args.check:
        return run_check(robots, out_dir)

    pages_dir = out_dir / "pages"
    raw_dir = out_dir / "raw" / "responses"
    cache_path = out_dir / "raw" / "http-cache.json"
    pages_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    cache = {} if args.refresh else load_cache(cache_path)

    if not robots.allowed(INDEX_URL):
        raise RuntimeError(f"robots.txt disallows {INDEX_URL}")

    idx_cache = cache.get(INDEX_URL, {})
    idx_raw_file = out_dir / "raw" / "index.json"
    idx_status, idx_raw, idx_headers = http_get(
        INDEX_URL,
        etag=None if args.refresh else idx_cache.get("etag"),
        last_modified=None if args.refresh else idx_cache.get("last_modified"),
    )
    if idx_status == 304 and idx_raw_file.exists():
        idx_raw = idx_raw_file.read_bytes()
    else:
        write_bytes(idx_raw_file, idx_raw)
    cache[INDEX_URL] = {
        "etag": idx_headers.get("etag", idx_cache.get("etag", "")),
        "last_modified": idx_headers.get("last-modified", idx_cache.get("last_modified", "")),
        "sha256": sha256_bytes(idx_raw),
    }

    index_data = json.loads(idx_raw.decode("utf-8"))
    entries = discover_hig_entries(index_data)
    print(f"[{SOURCE_ID}] discovered {len(entries)} DocC pages", file=sys.stderr)

    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    docs: dict[str, dict[str, Any]] = {}
    page_meta: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    cache_lock = threading.Lock()

    def fetch_entry(entry: dict[str, str]) -> tuple[dict[str, str], dict[str, Any] | None, str | None, dict[str, str]]:
        nonlocal cache_hits
        jurl = entry["json_url"]
        if not robots.allowed(jurl):
            return entry, None, "blocked by robots.txt", {}
        c = cache.get(jurl, {})
        raw_rel = (entry["slug"] or "index").replace("/", "__") + ".json"
        raw_path = raw_dir / raw_rel
        use_cache = (not args.refresh) and raw_path.exists()
        try:
            status, data, headers = http_get(
                jurl,
                etag=c.get("etag") if use_cache else None,
                last_modified=c.get("last_modified") if use_cache else None,
            )
            if status == 304 and raw_path.exists():
                data = raw_path.read_bytes()
                with cache_lock:
                    cache_hits += 1
            else:
                write_bytes(raw_path, data)
            doc = json.loads(data.decode("utf-8"))
            meta = {
                "etag": headers.get("etag", c.get("etag", "")),
                "last_modified": headers.get("last-modified", c.get("last_modified", "")),
                "sha256": sha256_bytes(data),
                "raw_file": raw_rel,
            }
            return entry, doc, None, meta
        except Exception as err:
            return entry, None, str(err), {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for entry, doc, err, meta in pool.map(fetch_entry, entries):
            jurl = entry["json_url"]
            if err or doc is None:
                page_meta[jurl] = {
                    "url": entry["web_url"],
                    "json_url": jurl,
                    "slug": entry["slug"],
                    "title": entry["title"],
                    "section": entry["section"],
                    "status": "error",
                    "error": err or "empty response",
                }
            else:
                docs[jurl] = doc
                cache[jurl] = meta
                page_meta[jurl] = {
                    "url": entry["web_url"],
                    "json_url": jurl,
                    "slug": entry["slug"],
                    "title": entry["title"],
                    "section": entry["section"],
                    "last_modified": meta.get("last_modified") or fetched_at,
                    "raw_sha256": meta["sha256"],
                    "status": "ok",
                }

    # Optional asset download
    asset_map: dict[str, str] = {}
    asset_count = 0
    if not args.no_assets:
        unique_assets: list[str] = []
        seen_a: set[str] = set()
        for doc in docs.values():
            for au in extract_assets_from_doc(doc):
                if au not in seen_a:
                    seen_a.add(au)
                    unique_assets.append(au)

        def fetch_asset(url: str) -> tuple[str, str | None]:
            if not robots.allowed(url):
                return url, None
            rel = local_asset_relpath(url)
            target = out_dir / rel
            if target.exists() and not args.refresh:
                return url, rel
            try:
                _, data, _ = http_get(url, accept="image/*,*/*")
                write_bytes(target, data)
                return url, rel
            except Exception:
                return url, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for aurl, rel in pool.map(fetch_asset, unique_assets):
                if rel:
                    asset_map[aurl] = rel
                    asset_count += 1

    # Render Markdown pages
    records: list[dict[str, Any]] = []
    sections: set[str] = set()
    for entry in entries:
        jurl = entry["json_url"]
        rec = page_meta[jurl]
        if rec["status"] != "ok":
            records.append(rec)
            continue
        doc = docs[jurl]
        relpath = slug_to_relpath(entry["slug"])
        title, body = render_docc_markdown(doc, entry, relpath, asset_map, out_dir)
        body_sha = sha256_bytes(body.encode("utf-8"))
        fm = build_frontmatter(
            url=entry["web_url"],
            title=title,
            section=entry["section"],
            fetched_at=fetched_at,
            last_modified=rec["last_modified"],
            sha256=body_sha,
        )
        full_md = fm + body
        write_text(pages_dir / relpath, full_md)
        rec["title"] = title
        rec["relpath"] = relpath
        rec["sha256"] = body_sha
        rec["bytes"] = len(full_md.encode("utf-8"))
        sections.add(entry["section"].split(" / ")[0])
        records.append(rec)

    index_md = build_index_md(records, fetched_at)
    write_text(pages_dir / "INDEX.md", index_md)
    write_json(cache_path, cache)

    ok_count = sum(1 for r in records if r.get("status") == "ok")
    err_count = sum(1 for r in records if r.get("status") == "error")
    manifest = {
        "source_id": SOURCE_ID,
        "name": SOURCE_NAME,
        "base_url": BASE_URL,
        "upstream_urls": [INDEX_URL, f"{BASE_URL}{HIG_PATH_PREFIX}"],
        "fetched_at": fetched_at,
        "version": cache[INDEX_URL].get("last_modified") or cache[INDEX_URL].get("etag") or fetched_at,
        "page_count": len(records),
        "markdown_count": ok_count,
        "page_error_count": err_count,
        "cache_hits": cache_hits,
        "assets_skipped": bool(args.no_assets),
        "asset_count": asset_count,
        "robots_checked": sorted(robots.checked_hosts),
        "sections": sorted(sections),
        "pages": [
            {
                "title": r["title"],
                "section": r["section"],
                "url": r["url"],
                "relpath": r.get("relpath", ""),
                "status": r["status"],
            }
            for r in records
        ],
    }
    write_json(out_dir / "manifest.json", manifest)
    if out_dir == DEFAULT_OUT.resolve():
        write_json(COMMITTED_MANIFEST, manifest)

    print(json.dumps({k: v for k, v in manifest.items() if k != "pages"}, ensure_ascii=False, indent=2))
    if args.verify:
        return verify_corpus(out_dir)
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
