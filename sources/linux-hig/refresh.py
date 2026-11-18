#!/usr/bin/env python3
"""Mirror the GNOME Human Interface Guidelines and KDE Human Interface Guidelines.

1. GNOME HIG: https://developer.gnome.org/hig/ (Sphinx Furo static HTML, discovered
   via searchindex.js + index links, extracting <article id="furo-main-content">)
2. KDE HIG: https://develop.kde.org/hig/ (Hugo Docsy static HTML, discovered via
   /en/sitemap.xml + internal /hig/ links, extracting <main id="content">)

Supports --check, --refresh, --no-assets, --workers N, --verify, conditional HTTP
caching (ETag / Last-Modified), robots.txt compliance, and INDEX.md generation.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen


SOURCE_ID = "linux-hig"
SOURCE_NAME = "GNOME & KDE Human Interface Guidelines"
GNOME_BASE = "https://developer.gnome.org/hig/"
GNOME_SEARCHINDEX = f"{GNOME_BASE}searchindex.js"
KDE_BASE = "https://develop.kde.org/hig/"
KDE_SITEMAP = "https://develop.kde.org/en/sitemap.xml"
USER_AGENT = "RoadToExpressive-LinuxHIGMirror/0.1 (+local documentation mirror)"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / ".corpus" / SOURCE_ID
COMMITTED_MANIFEST = REPO_ROOT / "manifests" / "sources" / f"{SOURCE_ID}.json"
MAX_LINE_LENGTH = 4000

IMAGE_EXTENSIONS = {".apng", ".avif", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "details", "div", "dl", "dt",
    "figcaption", "figure", "footer", "header", "main", "nav", "p", "section", "summary",
}
SKIP_TAGS = {"script", "style", "template", "noscript", "svg", "button", "form"}
DROP_CLASSES = {
    "headerlink", "td-page-meta", "td-breadcrumbs", "breadcrumb", "feedback",
    "td-heading-self-link", "content-icon-container", "theme-toggle-container",
    "search-results-header", "search-results-body", "nocontent", "visually-hidden",
}


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
    accept: str = "*/*",
    etag: str | None = None,
    last_modified: str | None = None,
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
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=45) as resp:
                raw = resp.read()
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                if resp_headers.get("content-encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                return resp.status, raw, resp_headers
        except HTTPError as err:
            if err.code == 304:
                return 304, b"", {k.lower(): v for k, v in err.headers.items()}
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


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def escape_cell(value: str) -> str:
    return normalize_text(value).replace("|", "\\|")


def wrap_long_line(line: str, limit: int = 3600) -> list[str]:
    if len(line) <= limit:
        return [line]
    words = line.split(" ")
    out: list[str] = []
    cur = ""
    for w in words:
        if len(w) > limit:
            if cur:
                out.append(cur)
                cur = ""
            for i in range(0, len(w), limit):
                out.append(w[i : i + limit])
            continue
        cand = w if not cur else f"{cur} {w}"
        if len(cand) <= limit:
            cur = cand
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def clean_markdown(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"(?m)^([*-]|\d+\.)[ \t]*\n(?:[ \t]*\n)?[ \t]*(?=\S)", r"\1 ", value)
    lines: list[str] = []
    for raw_line in value.split("\n"):
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


class MainBodyExtractor(HTMLParser):
    def __init__(self, mode: str) -> None:
        super().__init__(convert_charrefs=False)
        self.mode = mode  # "gnome" or "kde"
        self.title = ""
        self.body_html = ""
        self._in_title = False
        self._capturing = False
        self._target_tag = ""
        self._stack: list[str] = []
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        if tag == "title" and not self.title:
            self._in_title = True
        if not self._capturing:
            if self.mode == "gnome" and tag == "article" and attrs.get("id") == "furo-main-content":
                self._capturing = True
                self._target_tag = "article"
                self._stack = []
                self._buffer = []
                return
            if self.mode == "kde" and tag == "main" and attrs.get("id") == "content":
                self._capturing = True
                self._target_tag = "main"
                self._stack = []
                self._buffer = []
                return
        if self._capturing:
            self._buffer.append(self.get_starttag_text() or "")
            if tag not in VOID_TAGS:
                self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        if self._capturing:
            self._buffer.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if not self._capturing:
            return
        if tag == self._target_tag and not self._stack:
            self.body_html = "".join(self._buffer)
            self._buffer = []
            self._capturing = False
            return
        self._buffer.append(f"</{tag}>")
        if tag in VOID_TAGS:
            return
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        elif tag in self._stack:
            while self._stack and self._stack[-1] != tag:
                self._stack.pop()
            if self._stack:
                self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._capturing:
            self._buffer.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._capturing:
            self._buffer.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._capturing:
            self._buffer.append(f"&#{name};")


class HtmlToMarkdown(HTMLParser):
    def __init__(self, page_url: str, asset_resolver: Any) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.asset_resolver = asset_resolver
        self.parts: list[str] = []
        self.list_stack: list[str] = []
        self.link_stack: list[str] = []
        self.skip_stack: list[str] = []
        self.pre_depth = 0
        self.cell_parts: list[str] | None = None
        self.row_cells: list[str] | None = None
        self.table_rows: list[list[str]] | None = None
        self.assets: set[str] = set()

    def block(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n\n"):
            if self.parts[-1].endswith("\n"):
                self.parts[-1] += "\n"
            else:
                self.parts.append("\n\n")

    def line(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def text(self, value: str) -> None:
        if self.cell_parts is not None:
            self.cell_parts.append(value)
        else:
            self.parts.append(value)

    def _should_skip(self, tag: str, attrs: dict[str, str]) -> bool:
        if tag in SKIP_TAGS:
            return True
        if tag == "nav":
            return True
        classes = set(attrs.get("class", "").split())
        if classes & DROP_CLASSES:
            return True
        if "hidden" in attrs:
            return True
        return False

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        if self.skip_stack:
            if tag not in VOID_TAGS:
                self.skip_stack.append(tag)
            return
        if self._should_skip(tag, attrs):
            if tag not in VOID_TAGS:
                self.skip_stack.append(tag)
            return

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.block()
            self.parts.append("#" * int(tag[1]) + " ")
        elif tag == "blockquote":
            self.block()
            self.parts.append("> ")
        elif tag in BLOCK_TAGS:
            self.block()
        elif tag == "br":
            self.line()
        elif tag == "hr":
            self.block()
            self.parts.append("---")
            self.block()
        elif tag in {"ul", "ol"}:
            self.block()
            self.list_stack.append(tag)
        elif tag == "li":
            self.line()
            marker = "1. " if (self.list_stack and self.list_stack[-1] == "ol") else "- "
            self.parts.append("  " * max(0, len(self.list_stack) - 1) + marker)
        elif tag == "pre":
            self.block()
            self.pre_depth += 1
            self.parts.append("```\n")
        elif tag == "code" and not self.pre_depth:
            self.text("`")
        elif tag in {"strong", "b"}:
            self.text("**")
        elif tag in {"em", "i"}:
            self.text("*")
        elif tag == "a":
            href = attrs.get("href", "")
            self.link_stack.append(href)
            self.text("[")
        elif tag == "img":
            src = attrs.get("src", "") or attrs.get("data-src", "")
            alt = normalize_text(attrs.get("alt", ""))
            if src and not src.startswith("data:"):
                abs_url = urljoin(self.page_url, src)
                ext = Path(urlparse(abs_url).path).suffix.lower()
                if ext in IMAGE_EXTENSIONS:
                    self.assets.add(abs_url)
                resolved = self.asset_resolver(abs_url)
                if resolved:
                    self.block()
                    self.parts.append(f"![{alt}]({resolved})")
                    self.block()
        elif tag == "table":
            self.block()
            self.table_rows = []
        elif tag == "tr":
            if self.table_rows is not None:
                self.row_cells = []
        elif tag in {"td", "th"}:
            if self.table_rows is not None and self.row_cells is None:
                self.row_cells = []
            if self.row_cells is not None:
                self.cell_parts = []

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        if self.skip_stack:
            return
        if tag in VOID_TAGS:
            self.handle_starttag(tag, attrs_list)
        else:
            self.handle_starttag(tag, attrs_list)
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_stack:
            if self.skip_stack[-1] == tag:
                self.skip_stack.pop()
            elif tag in self.skip_stack:
                while self.skip_stack and self.skip_stack[-1] != tag:
                    self.skip_stack.pop()
                if self.skip_stack:
                    self.skip_stack.pop()
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} or tag in BLOCK_TAGS:
            self.block()
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self.block()
        elif tag == "li":
            self.line()
        elif tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
            self.parts.append("\n```")
            self.block()
        elif tag == "code" and not self.pre_depth:
            self.text("`")
        elif tag in {"strong", "b"}:
            self.text("**")
        elif tag in {"em", "i"}:
            self.text("*")
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else ""
            self.text("]")
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                abs_href = urljoin(self.page_url, html.unescape(href))
                self.text(f"({abs_href})")
        elif tag in {"td", "th"}:
            if self.cell_parts is not None and self.row_cells is not None:
                self.row_cells.append(escape_cell("".join(self.cell_parts)))
            self.cell_parts = None
        elif tag == "tr":
            if self.row_cells is not None and self.table_rows is not None:
                self.table_rows.append(self.row_cells)
            self.row_cells = None
        elif tag == "table":
            if self.table_rows:
                width = max((len(r) for r in self.table_rows), default=0)
                rows = [r + [""] * (width - len(r)) for r in self.table_rows if r]
                if rows:
                    lines = [
                        "| " + " | ".join(rows[0]) + " |",
                        "| " + " | ".join("---" for _ in rows[0]) + " |",
                    ]
                    for r in rows[1:]:
                        lines.append("| " + " | ".join(r) + " |")
                    self.block()
                    self.parts.append("\n".join(lines))
            self.table_rows = None
            self.block()

    def handle_data(self, data: str) -> None:
        if self.skip_stack:
            return
        if self.pre_depth:
            self.text(data)
        else:
            val = normalize_text(data)
            if val:
                self.text(val + " ")

    def markdown(self) -> str:
        return clean_markdown("".join(self.parts))


def discover_gnome_entries(robots: RobotsChecker) -> list[dict[str, str]]:
    slugs: set[str] = {"index"}
    if robots.allowed(GNOME_SEARCHINDEX):
        try:
            _, raw, _ = http_get(GNOME_SEARCHINDEX, accept="application/javascript,text/javascript,*/*")
            text = raw.decode("utf-8", errors="replace")
            m = re.search(r'"docnames"\s*:\s*(\[[^\]]+\])', text)
            if not m:
                m = re.search(r'docnames\s*:\s*(\[[^\]]+\])', text)
            if m:
                for docname in json.loads(m.group(1)):
                    if docname not in {"genindex", "search"}:
                        slugs.add(str(docname))
        except Exception:
            pass
    if robots.allowed(GNOME_BASE):
        _, idx_raw, _ = http_get(GNOME_BASE, accept="text/html,*/*")
        idx_html = idx_raw.decode("utf-8", errors="replace")
        for href in re.findall(r'href="([^"]+\.html)"', idx_html):
            abs_u = urldefrag(urljoin(GNOME_BASE, href))[0]
            if abs_u.startswith(GNOME_BASE):
                rel = abs_u.removeprefix(GNOME_BASE).removesuffix(".html")
                if rel and rel not in {"genindex", "search"}:
                    slugs.add(rel)

    entries: list[dict[str, str]] = []
    for slug in sorted(slugs):
        url = f"{GNOME_BASE}{slug}.html" if slug != "index" else GNOME_BASE
        top = slug.split("/")[0].replace("-", " ").title() if "/" in slug else "Overview"
        entries.append(
            {
                "kind": "gnome",
                "url": url,
                "title": slug.split("/")[-1].replace("-", " ").title(),
                "section": f"GNOME HIG / {top}",
                "relpath": f"gnome/{slug}.md",
            }
        )
    return entries


def discover_kde_entries(robots: RobotsChecker) -> list[dict[str, str]]:
    urls: set[str] = {KDE_BASE}
    if robots.allowed(KDE_SITEMAP):
        _, sm_raw, _ = http_get(KDE_SITEMAP, accept="application/xml,text/xml,*/*")
        sm_text = sm_raw.decode("utf-8", errors="replace")
        for loc in re.findall(r"<loc>([^<]+)</loc>", sm_text):
            u = urldefrag(loc.strip())[0]
            if u.startswith("/"):
                u = urljoin("https://develop.kde.org", u)
            if u.startswith(KDE_BASE):
                urls.add(u if u.endswith("/") else u + "/")

    entries: list[dict[str, str]] = []
    for url in sorted(urls):
        slug = url.removeprefix(KDE_BASE).strip("/") or "index"
        top = slug.split("/")[0].replace("_", " ").replace("-", " ").title() if slug != "index" else "Overview"
        entries.append(
            {
                "kind": "kde",
                "url": url,
                "title": slug.split("/")[-1].replace("_", " ").replace("-", " ").title(),
                "section": f"KDE HIG / {top}",
                "relpath": f"kde/{slug}.md",
            }
        )
    return entries


def local_asset_relpath(url: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower() or ".bin"
    if len(ext) > 6:
        ext = ".bin"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(urlparse(url).path).stem)[:48].strip("-.") or "asset"
    return f"assets/{stem}-{sha256_bytes(url.encode('utf-8'))[:12]}{ext}"


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
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
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
    checks: dict[str, Any] = {}
    for label, url in [("gnome_hig", GNOME_BASE), ("kde_sitemap", KDE_SITEMAP)]:
        if not robots.allowed(url):
            checks[label] = {"status": "blocked"}
            continue
        c = cache.get(url, {})
        st, _, hdrs = http_get(url, etag=c.get("etag"), last_modified=c.get("last_modified"))
        checks[label] = {
            "http_status": st,
            "up_to_date": st == 304,
            "etag": hdrs.get("etag", c.get("etag", "")),
            "last_modified": hdrs.get("last-modified", c.get("last_modified", "")),
        }
    print(json.dumps({"source_id": SOURCE_ID, "checks": checks, "local_manifest_exists": (out_dir / "manifest.json").exists()}, indent=2))
    return 0


def build_index_md(records: list[dict[str, Any]], fetched_at: str) -> str:
    ok_recs = [r for r in records if r.get("status") == "ok"]
    lines = [
        "# GNOME & KDE Human Interface Guidelines — Mirror Index\n",
        f"Total mirrored pages: **{len(ok_recs)}**\n",
        "| Title | Section | Local File | Source URL |",
        "| --- | --- | --- | --- |",
    ]
    for r in ok_recs:
        lines.append(f"| {escape_cell(r['title'])} | {escape_cell(r['section'])} | [{r['relpath']}]({r['relpath']}) | {r['url']} |")
    body = clean_markdown("\n".join(lines))
    fm = build_frontmatter(
        url=GNOME_BASE,
        title="GNOME & KDE Human Interface Guidelines — Index",
        section="Index",
        fetched_at=fetched_at,
        last_modified=fetched_at,
        sha256=sha256_bytes(body.encode("utf-8")),
    )
    return fm + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (default: .corpus/linux-hig)")
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

    entries = discover_gnome_entries(robots) + discover_kde_entries(robots)
    print(f"[{SOURCE_ID}] discovered {len(entries)} pages (GNOME + KDE HIG)", file=sys.stderr)

    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    raw_html_map: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    cache_hits = 0
    cache_lock = threading.Lock()

    def fetch_entry(entry: dict[str, str]) -> tuple[dict[str, str], str | None, str | None, dict[str, str]]:
        nonlocal cache_hits
        url = entry["url"]
        if not robots.allowed(url):
            return entry, None, "blocked by robots.txt", {}
        c = cache.get(url, {})
        raw_rel = sha256_bytes(url.encode("utf-8"))[:20] + ".html"
        raw_path = raw_dir / raw_rel
        use_cache = (not args.refresh) and raw_path.exists()
        try:
            status, data, headers = http_get(
                url,
                accept="text/html,application/xhtml+xml,*/*",
                etag=c.get("etag") if use_cache else None,
                last_modified=c.get("last_modified") if use_cache else None,
            )
            if status == 304 and raw_path.exists():
                data = raw_path.read_bytes()
                with cache_lock:
                    cache_hits += 1
            else:
                write_bytes(raw_path, data)
            meta = {
                "etag": headers.get("etag", c.get("etag", "")),
                "last_modified": headers.get("last-modified", c.get("last_modified", "")),
                "sha256": sha256_bytes(data),
                "raw_file": raw_rel,
            }
            return entry, data.decode("utf-8", errors="replace"), None, meta
        except Exception as err:
            return entry, None, str(err), {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for entry, html_text, err, meta in pool.map(fetch_entry, entries):
            rec = dict(entry)
            if err or html_text is None:
                rec["status"] = "error"
                rec["error"] = err or "empty response"
            else:
                rec["status"] = "ok"
                rec["last_modified"] = meta.get("last_modified") or fetched_at
                cache[entry["url"]] = meta
                raw_html_map[entry["url"]] = html_text
            records.append(rec)

    extracted: dict[str, tuple[str, str]] = {}
    all_assets: set[str] = set()
    for rec in records:
        if rec["status"] != "ok":
            continue
        url = rec["url"]
        extractor = MainBodyExtractor(rec["kind"])
        extractor.feed(raw_html_map[url])
        extractor.close()
        if not extractor.body_html.strip():
            rec["status"] = "skipped"
            rec["error"] = "no main content body found"
            continue
        title = normalize_text(extractor.title)
        for suffix in (" - GNOME Human Interface Guidelines", " | Developer", " — GNOME Human Interface Guidelines"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
        title = title or rec["title"]
        extracted[url] = (title, extractor.body_html)

    asset_map: dict[str, str] = {}
    if not args.no_assets:
        for rec in records:
            if rec["status"] != "ok":
                continue
            conv = HtmlToMarkdown(rec["url"], lambda u: u)
            conv.feed(extracted[rec["url"]][1])
            conv.close()
            all_assets.update(conv.assets)

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
            for aurl, rel in pool.map(fetch_asset, sorted(all_assets)):
                if rel:
                    asset_map[aurl] = rel

    sections: set[str] = set()
    for rec in records:
        if rec["status"] != "ok":
            continue
        url = rec["url"]
        title, body_html = extracted[url]
        page_path = pages_dir / rec["relpath"]

        def resolver(remote: str, _p: Path = page_path) -> str:
            local = asset_map.get(remote)
            if local:
                return Path(os.path.relpath(out_dir / local, _p.parent)).as_posix()
            return remote

        conv = HtmlToMarkdown(url, resolver)
        conv.feed(body_html)
        conv.close()
        body_md = conv.markdown()
        if not body_md.lstrip().startswith("# "):
            body_md = f"# {title}\n\n" + body_md
        body_sha = sha256_bytes(body_md.encode("utf-8"))
        fm = build_frontmatter(
            url=url,
            title=title,
            section=rec["section"],
            fetched_at=fetched_at,
            last_modified=rec["last_modified"],
            sha256=body_sha,
        )
        full_md = fm + body_md
        write_text(page_path, full_md)
        rec["title"] = title
        rec["sha256"] = body_sha
        rec["bytes"] = len(full_md.encode("utf-8"))
        sections.add(rec["section"].split(" / ")[0])

    write_text(pages_dir / "INDEX.md", build_index_md(records, fetched_at))
    write_json(cache_path, cache)

    ok_count = sum(1 for r in records if r["status"] == "ok")
    err_count = sum(1 for r in records if r["status"] == "error")
    skip_count = sum(1 for r in records if r["status"] == "skipped")
    manifest = {
        "source_id": SOURCE_ID,
        "name": SOURCE_NAME,
        "base_url": GNOME_BASE,
        "upstream_urls": [GNOME_BASE, KDE_BASE],
        "fetched_at": fetched_at,
        "version": fetched_at,
        "page_count": len(records),
        "markdown_count": ok_count,
        "page_error_count": err_count,
        "page_skipped_count": skip_count,
        "cache_hits": cache_hits,
        "assets_skipped": bool(args.no_assets),
        "asset_count": len(asset_map),
        "robots_checked": sorted(robots.checked_hosts),
        "sections": sorted(sections),
        "pages": [
            {
                "title": r["title"],
                "section": r["section"],
                "url": r["url"],
                "relpath": r["relpath"],
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
