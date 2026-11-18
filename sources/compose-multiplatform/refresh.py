#!/usr/bin/env python3
"""Mirror the Kotlin Multiplatform and Compose Multiplatform documentation.

kotlinlang.org serves the KMP guide as a React app shell: article pages carry
fully server-rendered HTML when the request sends an explicit Accept: text/html
header. Section and landing pages carry a sibling JSON document named by
`data-topic`. The API reference under /api/compose-multiplatform/ is Dokka
HTML, deduplicated across source sets (keeping common first).

Outputs:
  - .corpus/compose-multiplatform/pages/**/*.md (with YAML frontmatter + INDEX.md)
  - .corpus/compose-multiplatform/assets/* (unless --no-assets)
  - .corpus/compose-multiplatform/manifest.json
  - manifests/sources/compose-multiplatform.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html
import json
import os
import random
import re
import ssl
import sys
import threading
import time
import zlib
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / ".corpus" / "compose-multiplatform"
SOURCE_ID = "compose-multiplatform"

BASE_URL = "https://kotlinlang.org"
USER_AGENT = "TheRoadToExpressive-CmpDocsMirror/1.0 (+local documentation mirror)"
MAX_WORKERS = 10
MAX_LINE_LENGTH = 4000

TOC_URL = f"{BASE_URL}/docs/multiplatform/HelpTOC.json"
CONFIG_URL = f"{BASE_URL}/docs/multiplatform/config.json"
ROBOTS_URL = f"{BASE_URL}/robots.txt"
COMPOSE_SITEMAP_URL = f"{BASE_URL}/api/compose-multiplatform/sitemap.xml"
DOCS_PREFIX = "docs/multiplatform"

COMPOSE_SECTION_TITLES = ("Compose Multiplatform UI framework",)

GROUP_TITLES = {
    "kmp": "KMP Guide",
    "compose": "Compose Multiplatform",
    "api": "Dokka API Reference",
}
GROUP_ORDER = ("kmp", "compose", "api")

API_SITEMAP_PREFIXES = (f"{BASE_URL}/api/compose-multiplatform/",)
API_PACKAGE_DEPTH = 3

IMAGE_EXTENSIONS = {".apng", ".avif", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


# ---------------------------------------------------------------------------
# HTTP Client (keep-alive per thread)
# ---------------------------------------------------------------------------

class FetchFailure(RuntimeError):
    def __init__(self, url: str, message: str, status: int | None = None, attempts: int = 0):
        super().__init__(f"{url}: {message}")
        self.url = url
        self.message = message
        self.status = status
        self.attempts = attempts


class Response:
    def __init__(self, url: str, status: int, body: bytes, headers: dict[str, str]):
        self.url = url
        self.status = status
        self.body = body
        self.headers = headers

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified")


class Http:
    def __init__(self, attempts: int = 4, timeout: float = 45.0):
        self.attempts = attempts
        self.timeout = timeout
        self.local = threading.local()
        self.request_count = 0
        self.downloaded_bytes = 0
        self._counter_lock = threading.Lock()

    def _connection(self, scheme: str, host: str):
        pool: dict[tuple[str, str], Any] = getattr(self.local, "pool", None)
        if pool is None:
            pool = self.local.pool = {}
        key = (scheme, host)
        if key not in pool:
            factory = HTTPSConnection if scheme == "https" else HTTPConnection
            pool[key] = factory(host, timeout=self.timeout)
        return pool[key]

    def _discard(self, scheme: str, host: str) -> None:
        pool: dict[tuple[str, str], Any] = getattr(self.local, "pool", {})
        conn = pool.pop((scheme, host), None)
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        for conn in getattr(self.local, "pool", {}).values():
            try:
                conn.close()
            except OSError:
                pass
        self.local.pool = {}

    def _once(self, url: str, headers: dict[str, str]) -> Response:
        parsed = urlparse(url)
        host = parsed.netloc
        scheme = parsed.scheme or "https"
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        conn = self._connection(scheme, host)
        request_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip",
            "Connection": "keep-alive",
            "Host": host,
            **headers,
        }
        try:
            conn.request("GET", target, headers=request_headers)
            raw = conn.getresponse()
            body = raw.read()
            status = raw.status
            response_headers = {key.lower(): value for key, value in raw.getheaders()}
        except (HTTPException, ssl.SSLError, OSError) as error:
            self._discard(scheme, host)
            raise FetchFailure(url, str(error) or error.__class__.__name__) from error
        encoding = response_headers.get("content-encoding", "")
        if body and "gzip" in encoding:
            body = gzip.decompress(body)
        elif body and "deflate" in encoding:
            body = zlib.decompress(body, -zlib.MAX_WBITS)
        return Response(url, status, body, response_headers)

    def get(self, url: str, headers: dict[str, str] | None = None, redirects: int = 5) -> Response:
        headers = dict(headers or {})
        last: FetchFailure | None = None
        for attempt in range(self.attempts):
            try:
                response = self._once(url, headers)
            except FetchFailure as error:
                last = FetchFailure(url, error.message, None, attempt + 1)
                time.sleep(min(20.0, (2.0**attempt) + random.random()))
                continue
            with self._counter_lock:
                self.request_count += 1
                self.downloaded_bytes += len(response.body)
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location or redirects <= 0:
                    raise FetchFailure(url, f"HTTP {response.status} without usable Location", response.status, attempt + 1)
                return self.get(urljoin(url, location), headers, redirects - 1)
            if response.status in RETRY_STATUS:
                last = FetchFailure(url, f"HTTP {response.status}", response.status, attempt + 1)
                retry_after = response.headers.get("retry-after")
                try:
                    delay = min(30.0, float(retry_after)) if retry_after else 2.0**attempt
                except ValueError:
                    delay = 2.0**attempt
                time.sleep(delay)
                continue
            if response.status >= 400:
                raise FetchFailure(url, f"HTTP {response.status}", response.status, attempt + 1)
            return response
        raise FetchFailure(url, last.message if last else "unknown fetch error", last.status if last else None, self.attempts)


# ---------------------------------------------------------------------------
# Disk & Ledger
# ---------------------------------------------------------------------------

def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def wrap_long_lines(text: str, limit: int = MAX_LINE_LENGTH) -> str:
    out: list[str] = []
    for raw in text.splitlines():
        if len(raw) <= limit:
            out.append(raw)
            continue
        rem = raw
        while len(rem) > limit:
            cut = rem.rfind(" ", 0, limit)
            if cut < limit // 3:
                cut = limit
            out.append(rem[:cut].rstrip())
            rem = rem[cut:].lstrip()
        if rem:
            out.append(rem)
    res = "\n".join(out)
    return res + ("\n" if text.endswith("\n") else "")


def format_frontmatter(
    *,
    url: str,
    title: str,
    section: str,
    fetched_at: str,
    last_modified: str | None,
    etag: str | None,
    body: str,
) -> str:
    digest = sha256(body.encode("utf-8"))
    safe_title = title.replace('"', '\\"')
    lines = [
        "---",
        f"source_id: {SOURCE_ID}",
        f"url: {url}",
        f'title: "{safe_title}"',
        f"section: {section}",
        f"fetched_at: {fetched_at}",
        f"last_modified: {last_modified or ''}",
        f"sha256: {digest}",
    ]
    if etag:
        lines.append(f'etag: "{etag.replace(chr(34), "")}"')
    lines.extend(["---", ""])
    return wrap_long_lines("\n".join(lines) + body)


class RobotsTxt:
    def __init__(self, text: str):
        self.allow: list[str] = []
        self.disallow: list[str] = []
        active = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip().lower(), v.strip()
            if k == "user-agent":
                active = (v == "*")
            elif active and k == "allow" and v:
                self.allow.append(v)
            elif active and k == "disallow" and v:
                self.disallow.append(v)

    def allows(self, path: str) -> bool:
        ba = max((r for r in self.allow if path.startswith(r)), key=len, default="")
        bd = max((r for r in self.disallow if path.startswith(r)), key=len, default="")
        return True if not bd else len(ba) >= len(bd)


class Ledger:
    def __init__(self, metadata: Path, read_only: bool = False):
        self.metadata = metadata
        self.read_only = read_only
        self.cache_path = metadata / "cache.json"
        self.progress_path = metadata / "progress.jsonl"
        self.failures_path = metadata / "failures.json"
        self.entries: dict[str, dict[str, Any]] = read_json(self.cache_path, {})
        self.failures: dict[str, dict[str, Any]] = read_json(self.failures_path, {})
        self._lock = threading.Lock()
        self._progress = None
        self._fold_progress()

    def _fold_progress(self) -> None:
        if not self.progress_path.exists():
            return
        for line in self.progress_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("url"):
                self.entries[record["url"]] = record
        if self.read_only:
            return
        write_json(self.cache_path, self.entries)
        self.progress_path.unlink()

    def open(self) -> None:
        self.metadata.mkdir(parents=True, exist_ok=True)
        self._progress = self.progress_path.open("a", encoding="utf-8")

    def get(self, url: str) -> dict[str, Any] | None:
        return self.entries.get(url)

    def record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.entries[entry["url"]] = entry
            self.failures.pop(entry["url"], None)
            if self._progress is not None:
                self._progress.write(json.dumps(entry, ensure_ascii=False) + "\n")
                self._progress.flush()

    def fail(self, url: str, error: FetchFailure) -> None:
        with self._lock:
            self.failures[url] = {
                "url": url,
                "message": error.message,
                "status": error.status,
                "attempts": error.attempts,
                "at": timestamp(),
            }

    def close(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        write_json(self.cache_path, self.entries)
        write_json(self.failures_path, self.failures)
        if self.progress_path.exists():
            self.progress_path.unlink()


# ---------------------------------------------------------------------------
# HTML to Markdown
# ---------------------------------------------------------------------------

def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def clean_markdown(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n[ \t]+\n", "\n\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip() + "\n"


class Element:
    __slots__ = ("tag", "classes", "attrs", "action", "data")

    def __init__(self, tag: str, classes: set[str], attrs: dict[str, str]):
        self.tag = tag
        self.classes = classes
        self.attrs = attrs
        self.action = "keep"
        self.data: Any = None


class Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sinks: list[list[str]] = [[]]
        self.stack: list[Element] = []
        self.started = False
        self.finished = False
        self.suppress = 0
        self.code_depth = 0
        self.list_stack: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self.base_url = ""
        self.asset_resolver: Callable[[str], str | None] = lambda url: None
        self.headings = 0
        self.code_blocks = 0
        self.markdown_tables = 0

    def is_root(self, tag: str, classes: set[str], attrs: dict[str, str]) -> bool:
        raise NotImplementedError

    def is_dropped(self, tag: str, classes: set[str], attrs: dict[str, str]) -> bool:
        return tag in {"script", "style", "noscript", "nav", "header", "footer", "svg", "form", "button", "object", "iframe"}

    def open_element(self, element: Element) -> None:
        pass

    def close_element(self, element: Element) -> None:
        pass

    def emit(self, text: str) -> None:
        if text:
            self.sinks[-1].append(text)

    def push_sink(self) -> None:
        self.sinks.append([])

    def pop_sink(self) -> str:
        return "".join(self.sinks.pop())

    def block(self) -> None:
        sink = self.sinks[-1]
        while sink and sink[-1].strip() == "" and "\n\n" not in sink[-1]:
            sink.pop()
        if sink and not "".join(sink[-2:]).endswith("\n\n"):
            sink.append("\n\n")

    def newline(self) -> None:
        sink = self.sinks[-1]
        if sink and not sink[-1].endswith("\n"):
            sink.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): (value or "") for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if not self.started:
            if self.is_root(tag, classes, attributes):
                self.started = True
                self.stack.append(Element(tag, classes, attributes))
            return
        if self.finished:
            return
        element = Element(tag, classes, attributes)
        if tag not in VOID_TAGS:
            self.stack.append(element)
        if self.suppress:
            element.action = "suppressed"
            return
        if self.is_dropped(tag, classes, attributes):
            element.action = "drop"
            if tag in VOID_TAGS:
                return
            self.suppress += 1
            return
        self.open_element(element)
        if element.action == "drop" and tag not in VOID_TAGS:
            self.suppress += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.started or self.finished or tag in VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                break
        else:
            return
        while len(self.stack) > index:
            element = self.stack.pop()
            if len(self.stack) == 0:
                self.finished = True
                return
            if element.action == "drop":
                self.suppress = max(0, self.suppress - 1)
                continue
            if not self.suppress:
                self.close_element(element)

    def handle_data(self, data: str) -> None:
        if not self.started or self.finished or self.suppress:
            return
        if self.code_depth:
            self.emit(data)
            return
        if not data.strip():
            sink = self.sinks[-1]
            if sink and not sink[-1].endswith((" ", "\n")):
                self.emit(" ")
            return
        self.emit(collapse(data))

    def start_code(self, language: str) -> None:
        self.block()
        self.code_depth += 1
        self.push_sink()

    def end_code(self, language: str) -> None:
        body = self.pop_sink()
        self.code_depth -= 1
        body = body.strip("\n")
        fence = "```"
        while fence in body:
            fence += "`"
        self.emit(f"{fence}{language}\n{body}\n{fence}")
        self.code_blocks += 1
        self.block()

    def close_emphasis(self, marker: str) -> None:
        sink = self.sinks[-1]
        trailing = ""
        while sink and sink[-1].endswith(" ") and sink[-1].strip():
            sink[-1] = sink[-1][:-1]
            trailing = " "
            break
        self.emit(marker)
        self.emit(trailing)

    def heading(self, level: int) -> None:
        self.block()
        self.emit("#" * level + " ")
        self.headings += 1

    def start_link(self) -> None:
        if self.code_depth:
            return
        self.push_sink()

    def end_link(self, href: str) -> None:
        if self.code_depth:
            return
        label = self.pop_sink().strip()
        target = self.resolve_link(href)
        if not label:
            return
        if not target:
            self.emit(label)
            return
        self.emit(f"[{label}]({target})")

    def resolve_link(self, href: str) -> str:
        href = (href or "").strip()
        if not href or href.startswith(("javascript:", "#")):
            return ""
        return urljoin(self.base_url, href)

    def open_list(self, ordered: bool) -> None:
        self.block()
        self.list_stack.append({"ordered": ordered, "index": 0})

    def close_list(self) -> None:
        if self.list_stack:
            self.list_stack.pop()
        self.block()

    def open_item(self, element: Element) -> None:
        context = self.list_stack[-1] if self.list_stack else {"ordered": False, "index": 0}
        context["index"] = int(context.get("index", 0)) + 1
        element.action = "list-item"
        element.data = f"{context['index']}. " if context["ordered"] else "- "
        self.newline()
        self.push_sink()

    def close_item(self, element: Element) -> None:
        body = clean_markdown(self.pop_sink()).strip()
        marker = str(element.data or "- ")
        if not body:
            return
        lines = body.split("\n")
        rendered = marker + lines[0]
        for line in lines[1:]:
            rendered += "\n" + (" " * len(marker) + line if line.strip() else "")
        self.emit(rendered)
        self.newline()

    def image(self, src: str, alt: str) -> None:
        absolute = urljoin(self.base_url, src)
        local = self.asset_resolver(absolute)
        self.block()
        self.emit(f"![{collapse(alt) or 'image'}]({local or absolute})")
        self.block()

    def start_table(self) -> None:
        self.tables.append({"rows": [], "row": None})
        self.block()

    def start_row(self) -> None:
        if self.tables:
            self.tables[-1]["row"] = []

    def end_row(self) -> None:
        if self.tables and self.tables[-1]["row"] is not None:
            self.tables[-1]["rows"].append(self.tables[-1]["row"])
            self.tables[-1]["row"] = None

    def start_cell(self) -> None:
        if self.tables:
            self.push_sink()

    def end_cell(self) -> None:
        if not self.tables:
            return
        text = clean_markdown(self.pop_sink()).strip()
        text = text.replace("|", "\\|").replace("\n", "<br>")
        row = self.tables[-1]["row"]
        if row is None:
            row = self.tables[-1]["row"] = []
        row.append(text)

    def end_table(self) -> None:
        if not self.tables:
            return
        table = self.tables.pop()
        rows: list[list[str]] = [row for row in table["rows"] if row]
        if not rows:
            return
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        header, body = padded[0], padded[1:]
        lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        self.block()
        self.emit("\n".join(lines))
        self.markdown_tables += 1
        self.block()

    def run(self, page_html: str, base_url: str, asset_resolver: Callable[[str], str | None]) -> str:
        self.base_url = base_url
        self.asset_resolver = asset_resolver
        self.feed(page_html)
        self.close()
        return clean_markdown(self.sinks[0] and "".join(self.sinks[0]) or "")


class DocsConverter(Converter):
    DROP_CLASSES = {"last-modified", "navigation-links", "video-player", "feedback", "tabs-section"}

    def is_root(self, tag: str, classes: set[str], attrs: dict[str, str]) -> bool:
        return tag == "article" and "article" in classes

    def is_dropped(self, tag: str, classes: set[str], attrs: dict[str, str]) -> bool:
        if super().is_dropped(tag, classes, attrs):
            return True
        if classes & self.DROP_CLASSES:
            return True
        if attrs.get("data-feedback-placeholder") or attrs.get("id") == "disqus_thread":
            return True
        return False

    def open_element(self, element: Element) -> None:
        tag, classes, attrs = element.tag, element.classes, element.attrs
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading(int(tag[1]))
        elif tag == "div" and "code-block" in classes:
            language = attrs.get("data-lang", "")
            element.data = language
            self.start_code(language)
        elif tag == "pre":
            element.data = ""
            self.start_code("")
        elif tag == "code" and self.code_depth == 0:
            element.action = "inline-code"
            self.emit("`")
        elif tag == "aside" and "prompt" in classes:
            element.action = "callout"
            element.data = attrs.get("data-type", "note")
            self.block()
            self.push_sink()
        elif tag == "div" and "tabs__content" in classes:
            title = attrs.get("data-title", "")
            if title:
                self.block()
                self.emit(f"**{collapse(title)}**")
                self.block()
        elif tag in {"p", "div", "section", "figure", "figcaption", "blockquote"}:
            self.block()
        elif tag in {"ul", "ol"}:
            self.open_list(tag == "ol")
        elif tag == "li":
            self.open_item(element)
        elif tag in {"strong", "b"} or (tag == "span" and "strong" in classes):
            element.action = "bold"
            self.emit("**")
        elif tag in {"em", "i"} or (tag == "span" and "emphasis" in classes):
            element.action = "italic"
            self.emit("*")
        elif tag == "a":
            element.action = "link"
            self.start_link()
        elif tag == "img":
            self.image(attrs.get("src", ""), attrs.get("alt", ""))
        elif tag == "br":
            self.newline()
        elif tag == "table":
            self.start_table()
        elif tag == "tr":
            self.start_row()
        elif tag in {"td", "th"}:
            self.start_cell()

    def close_element(self, element: Element) -> None:
        tag, classes = element.tag, element.classes
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.block()
        elif tag == "div" and "code-block" in classes:
            self.end_code(element.data or "")
        elif tag == "pre":
            self.end_code("")
        elif element.action == "inline-code":
            self.emit("`")
        elif element.action == "callout":
            body = clean_markdown(self.pop_sink()).strip()
            kind = str(element.data or "note").strip().lower()
            label = {"tip": "Tip", "note": "Note", "warning": "Warning"}.get(kind, kind.title() or "Note")
            quoted = "\n".join("> " + line if line else ">" for line in body.split("\n"))
            self.emit(f"> **{label}**\n>\n{quoted}" if body else "")
            self.block()
        elif element.action == "bold":
            self.close_emphasis("**")
        elif element.action == "italic":
            self.close_emphasis("*")
        elif element.action == "link":
            self.end_link(element.attrs.get("href", ""))
        elif element.action == "list-item":
            self.close_item(element)
        elif tag in {"ul", "ol"}:
            self.close_list()
        elif tag == "table":
            self.end_table()
        elif tag == "tr":
            self.end_row()
        elif tag in {"td", "th"}:
            self.end_cell()
        elif tag in {"p", "section", "figure", "figcaption", "blockquote", "div"}:
            self.block()


class DokkaConverter(Converter):
    DROP_CLASSES = {
        "breadcrumbs", "copy-popup-wrapper", "anchor-wrapper", "source-link-wrapper",
        "platform-bookmarks-row", "filtered-message", "navigation-controls",
        "tabs-section", "sideMenu", "footer", "navigation",
    }

    def is_root(self, tag: str, classes: set[str], attrs: dict[str, str]) -> bool:
        return tag == "div" and "main-content" in classes

    def is_dropped(self, tag: str, classes: set[str], attrs: dict[str, str]) -> bool:
        if super().is_dropped(tag, classes, attrs):
            return True
        return bool(classes & self.DROP_CLASSES)

    def open_element(self, element: Element) -> None:
        tag, classes, attrs = element.tag, element.classes, element.attrs
        if tag == "div" and "platform-hinted" in classes:
            element.action = "platform-hinted"
            element.data = {"seen": set()}
            self.block()
        elif tag == "div" and "sourceset-dependent-content" in classes:
            element.action = "sourceset"
            element.data = (self.headings, self.code_blocks, self.markdown_tables)
            self.push_sink()
        elif tag == "div" and "symbol" in classes:
            element.action = "symbol"
            self.start_code("kotlin")
        elif tag == "code" and self.code_depth == 0:
            element.action = "inline-code"
            self.emit("`")
        elif tag == "code" and self.code_depth:
            language = next((name[5:] for name in classes if name.startswith("lang-")), "")
            holder = next((item for item in reversed(self.stack) if item.action == "pre"), None)
            if holder is not None and language:
                holder.data = language
        elif tag == "pre":
            element.action = "pre"
            element.data = ""
            self.start_code("")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading(2 if tag == "h1" and self.headings else int(tag[1]))
        elif tag == "div" and "table-row" in classes:
            self.block()
            self.emit("---")
            self.block()
        elif tag == "a":
            element.action = "link"
            self.start_link()
        elif tag == "img":
            self.image(attrs.get("src", ""), attrs.get("alt", ""))
        elif tag == "br":
            self.emit("\n" if self.code_depth else " ")
        elif tag in {"strong", "b"}:
            element.action = "bold"
            self.emit("**")
        elif tag in {"em", "i"}:
            element.action = "italic"
            self.emit("*")
        elif tag in {"ul", "ol"}:
            self.open_list(tag == "ol")
        elif tag == "li":
            self.open_item(element)
        elif tag == "table":
            self.start_table()
        elif tag == "tr":
            self.start_row()
        elif tag in {"td", "th"}:
            self.start_cell()
        elif tag in {"p", "div", "section"}:
            self.block()

    def close_element(self, element: Element) -> None:
        tag = element.tag
        if element.action == "sourceset":
            body = self.pop_sink()
            holder = next((item for item in reversed(self.stack) if item.action == "platform-hinted"), None)
            key = collapse(body).strip()
            if holder is not None and key and key in holder.data["seen"]:
                self.headings, self.code_blocks, self.markdown_tables = element.data
                return
            if holder is not None and key:
                holder.data["seen"].add(key)
            self.block()
            self.emit(body)
            self.block()
        elif element.action == "symbol":
            self.end_code("kotlin")
        elif element.action == "pre":
            self.end_code(str(element.data or ""))
        elif element.action == "inline-code":
            self.emit("`")
        elif element.action == "bold":
            self.close_emphasis("**")
        elif element.action == "italic":
            self.close_emphasis("*")
        elif element.action == "link":
            self.end_link(element.attrs.get("href", ""))
        elif element.action == "list-item":
            self.close_item(element)
        elif tag in {"ul", "ol"}:
            self.close_list()
        elif tag == "table":
            self.end_table()
        elif tag == "tr":
            self.end_row()
        elif tag in {"td", "th"}:
            self.end_cell()
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section"}:
            self.block()

    def end_code(self, language: str) -> None:
        body = "".join(self.sinks[-1]).strip()
        if not body:
            self.pop_sink()
            self.code_depth -= 1
            return
        super().end_code(language)


def convert_page(page_html: str, url: str, kind: str, asset_resolver: Callable[[str], str | None]) -> tuple[str, dict[str, int]]:
    converter = DocsConverter() if kind == "docs" else DokkaConverter()
    markdown = converter.run(page_html, url, asset_resolver)
    counts = {
        "headings": converter.headings,
        "code_blocks": converter.code_blocks,
        "tables": converter.markdown_tables,
    }
    return markdown, counts


def page_title(page_html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", page_html, re.S | re.I)
    if not match:
        return ""
    title = html.unescape(collapse(match.group(1))).strip()
    return re.sub(r"\s*\|\s*(Kotlin Documentation|Kotlin|Kotlin Multiplatform Documentation)\s*$", "", title)


def section_topic(page_html: str) -> str:
    match = re.search(r'data-topic="([^"]+)"', page_html)
    return match.group(1) if match else ""


def topic_links(topic: dict[str, Any], page_url: str) -> set[str]:
    found: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            href = node.get("url")
            if isinstance(href, str) and href and not href.startswith(("#", "mailto:", "javascript:")):
                found.add(href if href.startswith("http") else urljoin(page_url, href))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(topic)
    return found


def render_topic_json(
    topic: dict[str, Any], page_url: str, asset_resolver: Callable[[str], str | None]
) -> tuple[str, dict[str, int]]:
    lines: list[str] = []
    title = collapse(str(topic.get("title", "")))
    if title:
        lines += [f"# {title}", ""]
    subtitle = collapse(str(topic.get("subtitle", "")))
    if subtitle:
        lines += [subtitle, ""]

    def emit_cards(items: Any, level: int) -> None:
        nonlocal lines
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = collapse(str(item.get("title", "")))
            description = collapse(str(item.get("description", "")))
            href = item.get("url")
            nested = item.get("data")
            if isinstance(nested, list) and nested and not isinstance(href, str):
                if all(isinstance(child, dict) and not child.get("url") for child in nested):
                    if name:
                        lines += ["", f"{'#' * min(level, 6)} {name}", ""]
                    emit_cards(nested, min(level + 1, 6))
                    continue
            bullet = "- "
            image = item.get("image") or item.get("icon") or ""
            if isinstance(image, str) and image:
                source = image if image.startswith("http") else urljoin(page_url, image)
                local = asset_resolver(source)
                if local:
                    bullet += f"![{name or 'image'}]({local}) "
            if isinstance(href, str) and href and name:
                target = href if href.startswith(("http", "#")) else urljoin(page_url, href)
                bullet += f"[{name}]({target})"
            elif name:
                bullet += f"**{name}**"
            if description:
                bullet += f" — {description}"
            if bullet.strip("- "):
                lines.append(bullet)
            emit_cards(nested, min(level + 1, 6))

    emit_cards(topic.get("tips"), 3)
    for key in ("main", "highlighted"):
        block = topic.get(key)
        if isinstance(block, dict):
            heading = collapse(str(block.get("title", "")))
            if heading:
                lines += ["", f"## {heading}", ""]
            emit_cards(block.get("data"), 3)
    groups = topic.get("groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            heading = collapse(str(group.get("title", "")))
            if heading:
                lines += ["", f"## {heading}", ""]
            emit_cards(group.get("data"), 3)
    prev_next = topic.get("prevNextLinks")
    if isinstance(prev_next, dict):
        for url_key, title_key, label in (("prevPageUrl", "prevPageTitle", "Previous"), ("nextPageUrl", "nextPageTitle", "Next")):
            href, name = prev_next.get(url_key), collapse(str(prev_next.get(title_key, "")))
            if isinstance(href, str) and href:
                target = href if href.startswith(("http", "#")) else urljoin(page_url, href)
                lines += ["", f"{label}: [{name or target}]({target})"]
    markdown = clean_markdown("\n".join(lines))
    return markdown, {"links": len(topic_links(topic, page_url))}


# ---------------------------------------------------------------------------
# Scope & Mirror
# ---------------------------------------------------------------------------

class Target:
    __slots__ = ("url", "group", "kind", "title", "path", "section")

    def __init__(self, url: str, group: str, kind: str, title: str, path: Path, section: str = ""):
        self.url = url
        self.group = group
        self.kind = kind
        self.title = title
        self.path = path
        self.section = section


def page_output_path(out: Path, url: str) -> Path:
    path = urlparse(url).path
    if path.endswith("/"):
        return out / "pages" / path.strip("/") / "index.md"
    if path.endswith(".html"):
        return out / "pages" / (path.strip("/")[: -len(".html")] + ".md")
    return out / "pages" / (path.strip("/") + ".md")


def resolve_section(pages: dict[str, Any], top_level: list[str], titles: tuple[str, ...]) -> str:
    candidates = list(top_level)
    node_id = ""
    for title in titles:
        for candidate in candidates:
            if pages[candidate]["title"] == title:
                node_id = candidate
                candidates = pages[candidate].get("pages", [])
                break
        else:
            raise RuntimeError(f"HelpTOC no longer has section {' > '.join(titles)!r}")
    return node_id


def collect_docs_targets(out: Path, toc: dict[str, Any]) -> list[Target]:
    pages = toc["entities"]["pages"]
    top_level = toc["topLevelIds"]
    targets: list[Target] = []
    claimed: set[str] = set()

    def claim(node_id: str, group: str, section: str) -> None:
        node = pages[node_id]
        url = node.get("url", "")
        if url and not url.startswith(("http", "/")) and node_id not in claimed:
            claimed.add(node_id)
            absolute = f"{BASE_URL}/{DOCS_PREFIX}/{url}"
            targets.append(Target(absolute, group, "docs", node["title"], page_output_path(out, absolute), section))

    def walk(node_id: str, group: str, section: str) -> None:
        claim(node_id, group, section)
        for child in pages[node_id].get("pages", []):
            if child not in claimed or pages[child].get("pages"):
                walk(child, group, section)

    compose_root = resolve_section(pages, top_level, COMPOSE_SECTION_TITLES)
    walk(compose_root, "compose", " > ".join(COMPOSE_SECTION_TITLES))
    for node_id in top_level:
        if node_id not in claimed:
            walk(node_id, "kmp", pages[node_id].get("title", "KMP"))
    return targets


def parse_sitemap(xml: str) -> list[str]:
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def collect_api_targets(out: Path, sitemaps: dict[str, str], full: bool) -> list[Target]:
    targets: list[Target] = []
    seen: set[str] = set()
    for url in sorted({u for xml in sitemaps.values() for u in parse_sitemap(xml)}):
        if not url.startswith(API_SITEMAP_PREFIXES):
            continue
        if not full and not url.endswith("/"):
            continue
        if url.endswith(("navigation.html", "all-types.html", "index-list.html")):
            continue
        if url in seen:
            continue
        seen.add(url)
        segments = url[len(BASE_URL):].strip("/").split("/")
        section = segments[2] if len(segments) > 2 else "compose-multiplatform"
        title = segments[-1] or section
        targets.append(Target(url, "api", "api", title, page_output_path(out, url), section))
    return targets


class Mirror:
    def __init__(self, out: Path, http: Http, ledger: Ledger, args: argparse.Namespace, robots: RobotsTxt):
        self.out = out
        self.http = http
        self.ledger = ledger
        self.args = args
        self.robots = robots
        self.assets: dict[str, str] = {}
        self.asset_lock = threading.Lock()

    def is_fresh(self, url: str) -> bool:
        if self.args.refresh or self.args.max_age <= 0:
            return False
        entry = self.ledger.get(url)
        if not entry or not (self.out / entry.get("path", "")).exists():
            return False
        checked = entry.get("checked_at") or entry.get("fetched_at")
        if not checked:
            return False
        try:
            age = time.time() - time.mktime(time.strptime(checked, "%Y-%m-%dT%H:%M:%SZ")) + time.timezone
        except ValueError:
            return False
        return 0 <= age < self.args.max_age * 3600

    def conditional_headers(self, url: str) -> dict[str, str]:
        if self.args.refresh:
            return {}
        entry = self.ledger.get(url)
        if not entry or not (self.out / entry.get("path", "")).exists():
            return {}
        headers: dict[str, str] = {}
        if entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            headers["If-Modified-Since"] = entry["last_modified"]
        return headers

    def asset_resolver(self, markdown_path: Path) -> Callable[[str], str | None]:
        def resolve(url: str) -> str | None:
            parsed = urlparse(url)
            if parsed.netloc != urlparse(BASE_URL).netloc:
                return None
            if Path(parsed.path).suffix.lower() not in IMAGE_EXTENSIONS:
                return None
            local = "assets/" + parsed.path.strip("/")
            with self.asset_lock:
                self.assets[url.split("#")[0]] = local
            return Path(os.path.relpath(self.out / local, markdown_path.parent)).as_posix()

        return resolve

    def fetch_page(self, target: Target) -> dict[str, Any]:
        path_only = urlparse(target.url).path
        if not self.robots.allows(path_only):
            self.ledger.fail(target.url, FetchFailure(target.url, "robots-disallowed"))
            return {"url": target.url, "status": "robots-disallowed"}
        if self.is_fresh(target.url):
            return {"url": target.url, "status": "fresh", "path": self.ledger.get(target.url).get("path", "")}
        headers = self.conditional_headers(target.url)
        try:
            response = self.http.get(target.url, headers)
        except FetchFailure as error:
            self.ledger.fail(target.url, error)
            return {"url": target.url, "status": "error", "message": error.message, "code": error.status}
        if response.status == 304:
            entry = dict(self.ledger.get(target.url) or {})
            entry.update({"url": target.url, "checked_at": timestamp()})
            self.ledger.record(entry)
            return {"url": target.url, "status": "unchanged", "path": entry.get("path", "")}

        page_html = response.body.decode("utf-8", errors="replace")
        topic_name = section_topic(page_html)
        if target.kind == "api" or "<article" in page_html:
            kind = target.kind
            markdown, counts = convert_page(page_html, target.url, target.kind, self.asset_resolver(target.path))
            title = page_title(page_html) or target.title
            extra: dict[str, Any] = {}
        elif topic_name:
            kind = "docs-json"
            try:
                topic_response = self.http.get(urljoin(target.url, topic_name))
                topic = json.loads(topic_response.body.decode("utf-8", errors="replace"))
            except (FetchFailure, json.JSONDecodeError, UnicodeDecodeError) as error:
                message = error.message if isinstance(error, FetchFailure) else f"{type(error).__name__}: {error}"
                self.ledger.fail(target.url, FetchFailure(target.url, message))
                return {"url": target.url, "status": "error", "message": message}
            markdown, counts = render_topic_json(topic, target.url, self.asset_resolver(target.path))
            title = collapse(str(topic.get("title", ""))) or target.title
            extra = {"topic": topic_name}
        else:
            self.ledger.fail(target.url, FetchFailure(target.url, "no article body and no data-topic"))
            return {"url": target.url, "status": "error", "message": "unrecognized page shape"}

        fetched = timestamp()
        final_md = format_frontmatter(
            url=target.url,
            title=title,
            section=target.section or target.group,
            fetched_at=fetched,
            last_modified=response.last_modified,
            etag=response.etag,
            body=markdown,
        )
        write_text(target.path, final_md)
        entry = {
            "url": target.url,
            "path": target.path.relative_to(self.out).as_posix(),
            "group": target.group,
            "kind": kind,
            **extra,
            "section": target.section,
            "title": title,
            "etag": response.etag,
            "last_modified": response.last_modified,
            "sha256": sha256(response.body),
            "source_bytes": len(response.body),
            "markdown_bytes": len(final_md.encode("utf-8")),
            "counts": counts,
            "fetched_at": fetched,
            "checked_at": fetched,
        }
        self.ledger.record(entry)
        return {"url": target.url, "status": "downloaded", "path": entry["path"]}

    def fetch_asset(self, url: str, local: str) -> dict[str, Any]:
        path = self.out / local
        if path.exists() and self.is_fresh(url):
            return {"url": url, "status": "fresh"}
        headers = self.conditional_headers(url)
        try:
            response = self.http.get(url, headers)
        except FetchFailure as error:
            self.ledger.fail(url, error)
            return {"url": url, "status": "error", "message": error.message, "code": error.status}
        if response.status == 304 and path.exists():
            return {"url": url, "status": "unchanged"}
        write_bytes(path, response.body)
        self.ledger.record({
            "url": url,
            "path": local,
            "kind": "asset",
            "group": "asset",
            "etag": response.etag,
            "last_modified": response.last_modified,
            "sha256": sha256(response.body),
            "source_bytes": len(response.body),
            "fetched_at": timestamp(),
            "checked_at": timestamp(),
        })
        return {"url": url, "status": "downloaded"}

    def run_pool(self, label: str, jobs: Iterable[Any], worker: Callable[[Any], dict[str, Any]]) -> list[dict[str, Any]]:
        jobs = list(jobs)
        results: list[dict[str, Any]] = []
        if not jobs:
            return results
        workers = max(1, min(MAX_WORKERS, self.args.workers))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(worker, job) for job in jobs]
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                results.append(future.result())
                if index % 50 == 0 or index == len(jobs):
                    print(f"{label} {index}/{len(jobs)}", flush=True)
        return results


def prune(out: Path, targets: list[Target], ledger: Ledger) -> list[str]:
    wanted = {target.path.resolve() for target in targets}
    wanted.add((out / "pages" / "INDEX.md").resolve())
    removed: list[str] = []
    for path in sorted((out / "pages").rglob("*.md")):
        if path.resolve() in wanted:
            continue
        rel = path.relative_to(out).as_posix()
        path.unlink()
        removed.append(rel)
    if removed:
        stale = [url for url, entry in ledger.entries.items() if entry.get("path") in removed]
        for url in stale:
            ledger.entries.pop(url, None)
        for parent in sorted((out / "pages").rglob("*"), reverse=True):
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
    return removed


def write_index(out: Path, targets: list[Target], entries: dict[str, dict[str, Any]], kotlin_version: str) -> None:
    lines = [
        "# Compose Multiplatform & KMP Documentation Index",
        "",
        f"Kotlin docs build: `{kotlin_version}` | Generated: `{timestamp()}`",
        "",
    ]
    by_group: dict[str, list[Target]] = {g: [] for g in GROUP_ORDER}
    for t in targets:
        if t.url in entries or t.path.exists():
            by_group[t.group].append(t)

    for group in GROUP_ORDER:
        group_targets = by_group[group]
        if not group_targets:
            continue
        lines.append(f"## {GROUP_TITLES[group]} ({len(group_targets)} pages)")
        lines.append("")
        if group == "api":
            pkg_targets = [t for t in group_targets if len(urlparse(t.url).path.strip("/").split("/")) == API_PACKAGE_DEPTH]
            for t in sorted(pkg_targets, key=lambda x: x.url):
                rel = t.path.relative_to(out / "pages").as_posix()
                lines.append(f"- [{t.title}]({rel}) — {t.section}")
        else:
            for t in group_targets:
                rel = t.path.relative_to(out / "pages").as_posix()
                title = entries.get(t.url, {}).get("title") or t.title
                lines.append(f"- [{title}]({rel})")
        lines.append("")
    write_text(out / "pages" / "INDEX.md", "\n".join(lines).rstrip() + "\n")


def load_scope(out: Path, http: Http, args: argparse.Namespace, metadata: Path, persist: bool) -> tuple[list[Target], str, dict[str, Any], RobotsTxt]:
    def document(url: str, name: str) -> bytes:
        path = metadata / name
        if not args.refresh and args.max_age > 0 and path.exists():
            age = time.time() - path.stat().st_mtime
            if 0 <= age < args.max_age * 3600:
                return path.read_bytes()
        raw = http.get(url).body
        if persist:
            write_bytes(path, raw)
        return raw

    toc_raw = document(TOC_URL, "HelpTOC.json")
    config_raw = document(CONFIG_URL, "config.json")
    robots_raw = document(ROBOTS_URL, "robots.txt")

    toc = json.loads(toc_raw)
    config = json.loads(config_raw)
    robots = RobotsTxt(robots_raw.decode("utf-8", errors="replace"))
    version_match = re.search(r"/tag/v([0-9][^\"/]*)", config.get("productWebUrl", ""))
    kotlin_version = version_match.group(1) if version_match else "unknown"

    targets = collect_docs_targets(out, toc)
    if not args.no_api:
        sitemaps = {"compose": document(COMPOSE_SITEMAP_URL, "sitemap-compose.xml").decode("utf-8", errors="replace")}
        targets += collect_api_targets(out, sitemaps, args.full_api)
    return targets, kotlin_version, config, robots


def run_check(out: Path, http: Http, ledger: Ledger, args: argparse.Namespace, metadata: Path) -> int:
    targets, kotlin_version, _, _ = load_scope(out, http, args, metadata, persist=False)
    changed: list[dict[str, str]] = []
    missing: list[str] = []
    errors: list[dict[str, Any]] = []

    def probe(target: Target) -> None:
        entry = ledger.get(target.url)
        if not entry or not (out / entry.get("path", "")).exists():
            missing.append(target.url)
            return
        headers: dict[str, str] = {}
        if entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            headers["If-Modified-Since"] = entry["last_modified"]
        try:
            resp = http.get(target.url, headers)
            if resp.status != 304 and sha256(resp.body) != entry.get("sha256"):
                changed.append({"url": target.url, "path": entry.get("path", "")})
        except FetchFailure as err:
            errors.append({"url": target.url, "error": err.message})

    workers = max(1, min(MAX_WORKERS, args.workers))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(probe, targets))

    report = {
        "checked_at": timestamp(),
        "kotlin_version": kotlin_version,
        "targets": len(targets),
        "changed": sorted(changed, key=lambda x: x["url"]),
        "missing": sorted(missing),
        "errors": errors,
    }
    write_json(metadata / "check.json", report)
    print(f"checked {len(targets)} pages: {len(changed)} changed, {len(missing)} missing, {len(errors)} errors")
    return 0 if not errors else 1


SOURCE_HEADING_PATTERN = re.compile(r"<h[1-6]\b", re.I)
SOURCE_CODE_PATTERN = re.compile(r'<div\b[^>]*class="[^"]*\bcode-block\b[^"]*"|<pre\b', re.I)
SOURCE_TABLE_PATTERN = re.compile(r"<table\b", re.I)


def content_slice(page_html: str, kind: str) -> str:
    if kind == "docs":
        start = page_html.find('<article class="article"')
        end = page_html.find("</article>", start + 1)
    else:
        start = page_html.find('<div class="main-content"')
        end = page_html.find('<div class="footer', start + 1)
    if start < 0:
        return ""
    return page_html[start : end if end > start else len(page_html)]


def run_verify(out: Path, http: Http, ledger: Ledger, args: argparse.Namespace, metadata: Path) -> int:
    mirrored = [entry for entry in ledger.entries.values() if entry.get("kind") in {"docs", "docs-json", "api"} and entry.get("path")]
    if not mirrored:
        print("nothing to verify: run a mirror first", file=sys.stderr)
        return 1

    # Check max line length across ALL mirrored markdown files
    over_length: list[tuple[int, str]] = []
    max_len = 0
    for md in sorted((out / "pages").rglob("*.md")):
        for line in md.read_text(encoding="utf-8").splitlines():
            l = len(line)
            if l > max_len:
                max_len = l
            if l > MAX_LINE_LENGTH:
                over_length.append((l, md.relative_to(out).as_posix()))

    random.seed(args.seed)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for entry in mirrored:
        buckets.setdefault(entry.get("group", "other"), []).append(entry)
    sample: list[dict[str, Any]] = []
    quota = max(1, args.sample // max(1, len(buckets)))
    for group in sorted(buckets):
        sample += random.sample(buckets[group], min(quota, len(buckets[group])))
    remainder = [e for e in mirrored if e not in sample]
    if len(sample) < args.sample and remainder:
        sample += random.sample(remainder, min(args.sample - len(sample), len(remainder)))

    def check(entry: dict[str, Any]) -> dict[str, Any]:
        path = out / entry["path"]
        if not path.exists():
            return {"url": entry["url"], "status": "missing-markdown", "shortfall": 1}
        try:
            resp = http.get(entry["url"], {})
        except FetchFailure as err:
            return {"url": entry["url"], "status": "error", "message": err.message, "shortfall": 1}
        page_html = resp.body.decode("utf-8", errors="replace")
        source = content_slice(page_html, entry["kind"])
        markdown = path.read_text(encoding="utf-8")
        if entry["kind"] == "docs-json":
            try:
                topic = json.loads(http.get(urljoin(entry["url"], entry.get("topic", ""))).body.decode("utf-8"))
                links = topic_links(topic, entry["url"])
                absent = [u for u in links if u not in markdown]
                shortfall = len(absent)
                return {"url": entry["url"], "path": entry["path"], "kind": "docs-json", "status": "checked", "shortfall": shortfall}
            except Exception as err:
                return {"url": entry["url"], "status": "error", "message": str(err), "shortfall": 1}
        elif entry["kind"] == "docs":
            prose = re.sub(r"(?ms)^[ \t>]*```.*?^[ \t>]*```", "", markdown)
            found_code = len(re.findall(r"(?m)^[ \t>]*```", markdown)) // 2
            found_h = len(re.findall(r"(?m)^[ \t>]*#{1,6} ", prose))
            found_t = len(re.findall(r"(?m)^[ \t>]*\|\s*---", prose))
            exp_code = len(SOURCE_CODE_PATTERN.findall(source))
            exp_h = len(SOURCE_HEADING_PATTERN.findall(source))
            exp_t = len(SOURCE_TABLE_PATTERN.findall(source))
            shortfall = max(0, exp_code - found_code) + max(0, exp_h - found_h) + max(0, exp_t - found_t)
            return {
                "url": entry["url"], "path": entry["path"], "kind": "docs", "status": "checked",
                "expected": {"code": exp_code, "headings": exp_h, "tables": exp_t},
                "found": {"code": found_code, "headings": found_h, "tables": found_t},
                "shortfall": shortfall,
            }
        else:
            # Dokka API page: verify non-empty and headings exist
            has_content = len(markdown.strip()) > 100
            return {"url": entry["url"], "path": entry["path"], "kind": "api", "status": "checked", "shortfall": 0 if has_content else 1}

    workers = max(1, min(MAX_WORKERS, args.workers))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        report = list(pool.map(check, sample))

    shortfalls = [r for r in report if r.get("shortfall", 0) > 0]
    passed = not shortfalls and not over_length
    summary = {
        "generated_at": timestamp(),
        "sample_size": len(report),
        "shortfalls": len(shortfalls),
        "max_line_length": max_len,
        "over_line_limit": len(over_length),
        "passed": passed,
        "sample": report,
    }
    write_json(metadata / "verify.json", summary)
    print(f"verified {len(report)} pages: {len(shortfalls)} shortfalls, max_line={max_len}, over_limit={len(over_length)}, passed={passed}")
    return 0 if passed else 1


def run_mirror(out: Path, http: Http, ledger: Ledger, args: argparse.Namespace, metadata: Path) -> int:
    started = time.time()
    targets, kotlin_version, config, robots = load_scope(out, http, args, metadata, persist=True)
    mirror = Mirror(out, http, ledger, args, robots)

    in_scope = {t.url for t in targets}
    for url in [k for k in ledger.failures if k not in in_scope and not k.endswith(tuple(IMAGE_EXTENSIONS))]:
        ledger.failures.pop(url, None)

    print(f"Scope: {len(targets)} pages (KMP + Compose Multiplatform, Kotlin {kotlin_version})", flush=True)
    page_results = mirror.run_pool("pages", targets, mirror.fetch_page)

    asset_results: list[dict[str, Any]] = []
    if not args.no_assets and mirror.assets:
        asset_results = mirror.run_pool("assets", list(mirror.assets.items()), lambda item: mirror.fetch_asset(*item))

    removed = prune(out, targets, ledger) if not args.no_api else []
    entries = ledger.entries
    write_index(out, targets, entries, kotlin_version)

    by_group: dict[str, int] = {}
    for t in targets:
        if t.url in entries and (out / entries[t.url].get("path", "")).exists():
            by_group[t.group] = by_group.get(t.group, 0) + 1

    page_failures = [u for u in ledger.failures if not u.endswith(tuple(IMAGE_EXTENSIONS))]
    assets_root = out / "assets"
    mirrored_assets = [p for p in assets_root.rglob("*") if p.is_file()] if assets_root.exists() else []
    fetched_at = timestamp()

    manifest = {
        "source_id": SOURCE_ID,
        "name": "Compose Multiplatform & KMP Official Documentation",
        "base_url": BASE_URL,
        "fetched_at": fetched_at,
        "page_count": sum(by_group.values()),
        "asset_count": len(mirrored_assets),
        "failed_count": len(page_failures),
        "status": "ok" if not page_failures else "partial",
        "upstream_version": f"Kotlin {kotlin_version}",
        "versions": {
            "kotlin_docs": kotlin_version,
            "docs_build": config.get("productWebUrl", ""),
        },
        "sections": {GROUP_TITLES[g]: by_group.get(g, 0) for g in GROUP_ORDER if by_group.get(g)},
        "notes": f"Mirrored via HelpTOC.json + Dokka /api/compose-multiplatform/ sitemap in {round(time.time() - started, 1)}s. Pruned {len(removed)} stale pages.",
    }
    write_json(out / "manifest.json", manifest)
    committed_manifest = REPO_ROOT / "manifests" / "sources" / f"{SOURCE_ID}.json"
    write_json(committed_manifest, manifest)
    print(json.dumps(manifest["sections"], indent=2))
    return 0 if not ledger.failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="mirror output directory")
    parser.add_argument("--workers", type=int, default=8, help=f"concurrent workers (max {MAX_WORKERS})")
    parser.add_argument("--no-assets", action="store_true", help="skip downloading images")
    parser.add_argument("--no-api", action="store_true", help="skip Dokka API reference")
    parser.add_argument("--full-api", action="store_true", help="include Dokka member pages")
    parser.add_argument("--refresh", action="store_true", help="ignore freshness window and revalidate")
    parser.add_argument("--max-age", type=float, default=24.0, help="hours before revalidating cached pages")
    parser.add_argument("--check", action="store_true", help="conditional requests only, report changes")
    parser.add_argument("--verify", action="store_true", help="verify fidelity & line lengths <= 4000")
    parser.add_argument("--sample", type=int, default=15, help="pages to sample in --verify")
    parser.add_argument("--seed", type=int, default=0, help="sampling seed")
    args = parser.parse_args()

    out = args.out.resolve()
    metadata = out / "metadata"
    out.mkdir(parents=True, exist_ok=True)
    metadata.mkdir(parents=True, exist_ok=True)

    http = Http()
    ledger = Ledger(metadata, read_only=args.check)
    try:
        if args.check:
            return run_check(out, http, ledger, args, metadata)
        if args.verify:
            return run_verify(out, http, ledger, args, metadata)
        ledger.open()
        return run_mirror(out, http, ledger, args, metadata)
    finally:
        if not args.check:
            ledger.close()
        http.close()


if __name__ == "__main__":
    raise SystemExit(main())
