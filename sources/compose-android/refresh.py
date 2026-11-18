#!/usr/bin/env python3
"""Mirror Jetpack Compose, Navigation 3, and Android Design (Mobile & Large-Screen)
documentation from developer.android.com.

developer.android.com serves SSR devsite HTML. Discovery walks from group seeds
via the book navigation (<nav class="devsite-book-nav">) and in-body links
within fixed path prefixes, checking every path against live robots.txt.

Outputs:
  - .corpus/compose-android/pages/**/*.md (YAML frontmatter + INDEX.md)
  - .corpus/compose-android/assets/* (unless --no-assets)
  - .corpus/compose-android/manifest.json
  - manifests/sources/compose-android.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html
import http.client
import json
import mimetypes
import os
import random
import re
import ssl
import sys
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urldefrag, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / ".corpus" / "compose-android"
SOURCE_ID = "compose-android"

BASE_URL = "https://developer.android.com"
USER_AGENT = "TheRoadToExpressive-AndroidDocsMirror/1.0 (+local documentation mirror)"
MAX_LINE_LENGTH = 4000
MAX_WORKERS = 10

GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "compose": {
        "seeds": ("/develop/ui/compose/documentation",),
        "prefixes": ("/develop/ui/compose/",),
    },
    "navigation-3": {
        "seeds": ("/guide/navigation/navigation-3",),
        "prefixes": ("/guide/navigation/navigation-3/",),
    },
    "design-mobile": {
        "seeds": ("/design/ui/mobile",),
        "prefixes": ("/design/ui/mobile/",),
    },
    "design-large-screens": {
        "seeds": ("/design/ui/large-screens", "/design/ui/desktop"),
        "prefixes": ("/design/ui/large-screens/", "/design/ui/desktop/"),
    },
}

GROUP_TITLES = {
    "compose": "Jetpack Compose",
    "navigation-3": "Navigation 3",
    "design-mobile": "Android Mobile UI Design (HIG)",
    "design-large-screens": "Android Large-Screen Design (HIG)",
}

ASSET_HOSTS = {
    "developer.android.com",
    "developers.google.com",
    "www.gstatic.com",
    "storage.googleapis.com",
    "lh3.googleusercontent.com",
}
IMAGE_EXTENSIONS = {".apng", ".avif", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}
DROP_TAGS = {
    "script", "style", "template", "noscript", "svg", "form", "button", "iframe",
    "devsite-toc", "devsite-feedback", "devsite-page-rating", "devsite-thumb-rating",
    "devsite-bookmark", "devsite-content-footer", "devsite-actions",
    "devsite-feature-tooltip", "devsite-recommendations",
}
DROP_CLASSES = {
    "nocontent", "devsite-article-meta", "devsite-banner", "devsite-page-bookmark",
    "devsite-content-footer", "devsite-article-meta-updated", "devsite-github-link",
}
INLINE_TAGS = {
    "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "del", "dfn", "em",
    "i", "img", "ins", "kbd", "mark", "q", "s", "samp", "small", "span", "strong",
    "sub", "sup", "time", "u", "var", "wbr", "br", "devsite-nowrap",
}
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def request_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=quote(parts.path, safe="/%:@&=+$,~()!*';")))


class FetchFailure(RuntimeError):
    def __init__(self, url: str, message: str, *, status: int | None = None, attempts: int = 1):
        super().__init__(f"{url}: {message}")
        self.url = url
        self.message = message
        self.status = status
        self.attempts = attempts


class Response:
    __slots__ = ("status", "data", "headers", "attempts")

    def __init__(self, status: int, data: bytes, headers: dict[str, str], attempts: int):
        self.status = status
        self.data = data
        self.headers = headers
        self.attempts = attempts

    @property
    def unchanged(self) -> bool:
        return self.status == 304

    def validators(self) -> dict[str, str]:
        return {key: self.headers[key] for key in ("etag", "last-modified") if self.headers.get(key)}


def fetch(
    url: str,
    *,
    accept: str = "*/*",
    attempts: int = 4,
    validators: dict[str, str] | None = None,
) -> Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        headers = {"Accept": accept, "Accept-Encoding": "gzip", "User-Agent": USER_AGENT}
        if validators:
            if validators.get("etag"):
                headers["If-None-Match"] = validators["etag"]
            if validators.get("last-modified"):
                headers["If-Modified-Since"] = validators["last-modified"]
        try:
            with urlopen(Request(request_url(url), headers=headers), timeout=60) as response:
                received = {key.lower(): value for key, value in response.headers.items()}
                data = response.read()
                if received.get("content-encoding", "").lower() == "gzip":
                    data = gzip.decompress(data)
                return Response(response.status, data, received, attempt)
        except HTTPError as error:
            last_error = error
            if error.code == 304:
                received = {key.lower(): value for key, value in error.headers.items()}
                return Response(304, b"", received, attempt)
            if error.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise FetchFailure(url, f"HTTP {error.code}", status=error.code, attempts=attempt) from error
            retry_after = error.headers.get("Retry-After")
            try:
                delay = min(30.0, float(retry_after)) if retry_after else 2.0**attempt
            except (TypeError, ValueError):
                delay = 2.0**attempt
            time.sleep(delay)
        except (URLError, ssl.SSLError, TimeoutError, OSError, http.client.HTTPException) as error:
            last_error = error
            time.sleep(min(30.0, 2.0**attempt))
    status = getattr(last_error, "code", None)
    raise FetchFailure(url, str(last_error or "unknown fetch error"), status=status, attempts=attempts)


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_text(path: Path, value: str) -> None:
    write_bytes(path, value.encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
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


class Robots:
    def __init__(self, text: str):
        self.allow: list[str] = []
        self.disallow: list[str] = []
        applies = False
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, _, value = line.partition(":")
            field, value = field.strip().lower(), value.strip()
            if field == "user-agent":
                applies = (value == "*")
            elif applies and field == "allow" and value:
                self.allow.append(value)
            elif applies and field == "disallow" and value:
                self.disallow.append(value)

    def allows(self, path: str) -> bool:
        best_allow = max((rule for rule in self.allow if path.startswith(rule)), key=len, default="")
        best_deny = max((rule for rule in self.disallow if path.startswith(rule)), key=len, default="")
        if not best_deny:
            return True
        return len(best_allow) >= len(best_deny)


# ---------------------------------------------------------------------------
# DOM & Devsite HTML -> Markdown
# ---------------------------------------------------------------------------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Any] = []
        self.parent = parent

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def find(self, predicate) -> "Node | None":
        for child in self.children:
            if isinstance(child, Node):
                if predicate(child):
                    return child
                found = child.find(predicate)
                if found is not None:
                    return found
        return None

    def iter_nodes(self) -> Iterable["Node"]:
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.iter_nodes()

    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag == "br":
                parts.append("\n")
            else:
                parts.append(child.text())
        return "".join(parts)


class DomBuilder(HTMLParser):
    AUTO_CLOSE = {
        "li": {"li"},
        "td": {"td", "th", "p"},
        "th": {"td", "th", "p"},
        "tr": {"td", "th", "tr", "p"},
        "dt": {"dt", "dd", "p"},
        "dd": {"dt", "dd", "p"},
        "p": {"p"},
    }
    BLOCK_CLOSES_P = {
        "div", "ul", "ol", "table", "pre", "section", "aside", "blockquote",
        "h1", "h2", "h3", "h4", "h5", "h6", "hr", "dl", "figure",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        closing = self.AUTO_CLOSE.get(tag) or ({"p"} if tag in self.BLOCK_CLOSES_P else set())
        while len(self.stack) > 1 and self.stack[-1].tag in closing:
            self.stack.pop()
        node = Node(tag, {key.lower(): (value or "") for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        node = Node(tag, {key.lower(): (value or "") for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


BODY_404 = re.compile(r"<body[^>]*\btemplate=\"404\"", re.I)
HREF = re.compile(r"<a\b[^>]*?\shref=\"([^\"]*)\"", re.I)
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
IMG_SRC = re.compile(r"\s(?:src|data-src)=\"([^\"]*)\"|\ssrcset=\"([^\"]*)\"", re.I)


def nav_and_article(markup: str) -> tuple[str | None, str | None]:
    nav = None
    start = markup.find('<nav class="devsite-book-nav')
    if start != -1:
        end = markup.find("</nav>", start)
        nav = markup[start : end if end != -1 else len(markup)]
    marker = markup.find("devsite-article-body")
    if marker == -1:
        return nav, None
    start = markup.rfind("<div", 0, marker)
    end = markup.find("</article>", marker)
    return nav, markup[start if start != -1 else marker : end if end != -1 else len(markup)]


def page_title(markup: str) -> str:
    start = markup.find("<h1")
    if start == -1:
        return ""
    end = markup.find("</h1>", start)
    fragment = markup[start : end + 5 if end != -1 else len(markup)]
    heading = parse_html(fragment).find(lambda node: node.tag == "h1")
    return collapse(visible_text(heading)).strip() if heading else ""


def image_source(node: Node) -> str:
    source = node.attrs.get("src") or node.attrs.get("data-src") or ""
    if not source and node.attrs.get("srcset"):
        source = node.attrs["srcset"].split(",")[0].strip().split(" ")[0]
    return source


def dropped(node: Node) -> bool:
    if node.tag in DROP_TAGS or node.classes() & DROP_CLASSES:
        return True
    return "data-nosnippet" in node.attrs or "hidden" in node.attrs


def visible_text(node: Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        elif not dropped(child):
            parts.append(visible_text(child))
    return "".join(parts)


def parse_html(markup: str) -> Node:
    builder = DomBuilder()
    builder.feed(markup)
    builder.close()
    return builder.root


def collapse(value: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", value.replace("\u200b", "")).replace("\n", " ")


def escape_inline(value: str) -> str:
    return value.replace("|", "\\|")


def clean_markdown(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip() + "\n"


def code_language(node: Node) -> str:
    syntax = (node.attrs.get("syntax") or "").strip().lower()
    if syntax:
        return {"c++": "cpp", "shell": "shell", "none": ""}.get(syntax, syntax)
    classes = node.classes()
    for name in classes:
        if name.startswith("lang-"):
            return name[5:].lower()
    if "api-signature" in classes:
        return "java"
    return ""


class Renderer:
    def __init__(self, resolve_link, resolve_image):
        self.resolve_link = resolve_link
        self.resolve_image = resolve_image
        self.selector_depth = 0
        self.code_source: tuple[str, str] | None = None

    def inline(self, node: Node) -> str:
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, str):
                parts.append(collapse(child))
                continue
            parts.append(self.inline_node(child))
        return "".join(parts)

    def inline_node(self, node: Node) -> str:
        tag = node.tag
        if dropped(node):
            return ""
        if tag == "br":
            return " "
        if "expand-control" in node.classes():
            inner = self.inline(node).strip()
            return f"**{inner}**" if inner else ""
        if tag == "img":
            return self.image(node)
        if tag in {"code", "kbd", "samp"}:
            text = collapse(visible_text(node)).strip()
            if not text:
                return ""
            fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
            padding = " " if text.startswith("`") or text.endswith("`") else ""
            literal = f"{fence}{padding}{text}{padding}{fence}"
            anchors = [item for item in node.iter_nodes() if item.tag == "a" and item.attrs.get("href")]
            if len(anchors) == 1 and collapse(visible_text(anchors[0])).strip() == text:
                href = self.resolve_link(anchors[0].attrs["href"])
                if href:
                    return f"[{literal}]({href})"
            return literal
        if tag in {"strong", "b"}:
            inner = self.inline(node).strip()
            return f"**{inner}**" if inner else ""
        if tag in {"em", "i", "dfn", "var", "cite"}:
            inner = self.inline(node).strip()
            return f"*{inner}*" if inner else ""
        if tag == "a":
            inner = self.inline(node).strip()
            href = self.resolve_link(node.attrs.get("href", ""))
            if not inner:
                return ""
            if not href:
                return inner
            return f"[{inner}]({href})"
        return self.inline(node)

    def image(self, node: Node) -> str:
        source = image_source(node)
        if not source:
            return ""
        alt = collapse(node.attrs.get("alt") or "").strip() or "image"
        return f"![{alt}]({self.resolve_image(source)})"

    def blocks(self, node: Node) -> str:
        parts: list[str] = []
        buffer: list[str] = []

        def flush() -> None:
            text = "".join(buffer).strip()
            buffer.clear()
            if text:
                parts.append(text)

        for child in node.children:
            if isinstance(child, str):
                buffer.append(collapse(child))
                continue
            if dropped(child):
                continue
            if child.tag in INLINE_TAGS and child.find(lambda item: item.tag in HEADING_TAGS) is None:
                buffer.append(self.inline_node(child))
                continue
            flush()
            rendered = self.block_node(child)
            if rendered.strip():
                parts.append(rendered.strip("\n"))
        flush()
        return "\n\n".join(parts)

    def block_node(self, node: Node) -> str:
        tag = node.tag
        if tag in HEADING_TAGS:
            text = self.inline(node).strip()
            if not text:
                return ""
            if self.selector_depth:
                return f"**{text}**"
            return "#" * HEADING_TAGS[tag] + " " + text
        if tag == "p":
            return self.inline(node).strip()
        if tag == "pre":
            return self.code_block(node)
        if tag in {"ul", "ol"}:
            return self.list_block(node, ordered=tag == "ol", depth=0)
        if tag == "table":
            return self.table_block(node)
        if tag == "hr":
            return "---"
        if tag == "blockquote":
            return self.quote(self.blocks(node))
        if tag == "aside":
            label = next(iter(node.classes() & {"note", "caution", "warning", "tip", "key-point", "special", "objective", "success", "beta", "dogfood"}), "")
            body = self.blocks(node).strip()
            if not body:
                return ""
            if label:
                name = label.replace("-", " ").title()
                if not re.match(rf"\**{re.escape(name)}\b", body, re.I):
                    body = f"{name}: {body}"
            return self.quote(body)
        if tag == "dl":
            return self.definition_list(node)
        if tag in {"devsite-selector", "devsite-code", "tabs"} or "ds-selector-tabs" in node.classes():
            if tag != "devsite-code":
                self.selector_depth += 1
                try:
                    return self.blocks(node)
                finally:
                    self.selector_depth -= 1
            return self.blocks(node)
        if tag == "figcaption":
            inner = self.blocks(node).strip()
            if not inner:
                return ""
            return f"*{inner}*" if "\n" not in inner else inner
        return self.blocks(node)

    def definition_list(self, node: Node) -> str:
        parts: list[str] = []
        for child in node.children:
            if not isinstance(child, Node) or dropped(child):
                continue
            if child.tag == "dt":
                term = self.inline(child).strip()
                if term:
                    parts.append(f"**{term}**")
            elif child.tag == "dd":
                body = self.blocks(child).strip()
                if body:
                    parts.append(body)
        return "\n\n".join(parts)

    def quote(self, body: str) -> str:
        return "\n".join(("> " + line).rstrip() for line in body.strip().split("\n"))

    def code_block(self, node: Node) -> str:
        text = html.unescape(self.code_text(node)).replace("\u00a0", " ")
        text = text.replace("\r\n", "\n").rstrip()
        if not text.strip():
            return ""
        fence = "`" * max(3, max((len(run) for run in re.findall(r"`{3,}", text)), default=0) + 1)
        block = f"{fence}{code_language(node)}\n{text}\n{fence}"
        if self.code_source and self.code_source[1]:
            block += f"\n\n*Source: [{self.code_source[0]}]({self.code_source[1]})*"
        return block

    def code_text(self, node: Node) -> str:
        parts: list[str] = []
        self.code_source = None

        def walk(current: Node) -> None:
            for child in current.children:
                if isinstance(child, str):
                    parts.append(child)
                    continue
                if "devsite-github-link" in child.classes():
                    link = child.find(lambda item: item.tag == "a")
                    if link is not None:
                        self.code_source = (collapse(link.text()).strip(), link.attrs.get("href", ""))
                    continue
                if child.tag in DROP_TAGS:
                    continue
                if child.tag == "br":
                    parts.append("\n")
                    continue
                walk(child)

        walk(node)
        return "".join(parts)

    def list_block(self, node: Node, ordered: bool, depth: int) -> str:
        lines: list[str] = []
        index = 1
        for child in node.children:
            if not isinstance(child, Node) or child.tag != "li":
                continue
            if child.tag in DROP_TAGS:
                continue
            marker = f"{index}. " if ordered else "- "
            index += 1
            body = self.list_item(child, depth)
            if not body.strip():
                continue
            indent = "    " * depth
            first, *rest = body.split("\n")
            lines.append(indent + marker + first)
            padding = indent + " " * len(marker)
            lines.extend((padding + line).rstrip() if line.strip() else "" for line in rest)
        return "\n".join(lines)

    def list_item(self, node: Node, depth: int) -> str:
        parts: list[str] = []
        buffer: list[str] = []

        def flush() -> None:
            text = "".join(buffer).strip()
            buffer.clear()
            if text:
                parts.append(text)

        for child in node.children:
            if isinstance(child, str):
                buffer.append(collapse(child))
                continue
            if dropped(child):
                continue
            if child.tag in INLINE_TAGS:
                buffer.append(self.inline_node(child))
                continue
            if child.tag in {"ul", "ol"}:
                flush()
                nested = self.list_block(child, ordered=child.tag == "ol", depth=depth + 1)
                if nested.strip():
                    parts.append(nested)
                continue
            flush()
            rendered = self.block_node(child)
            if rendered.strip():
                parts.append(rendered.strip("\n"))
        flush()
        return "\n\n".join(parts)

    def table_block(self, node: Node) -> str:
        if flattens_to_sections(node):
            return self.nested_table_sections(node)
        source_rows = own_rows(node)
        lead = ""
        if source_rows:
            cells = [child for child in source_rows[0].children if isinstance(child, Node) and child.tag in {"td", "th"}]
            heading = cells[0].find(lambda child: child.tag in HEADING_TAGS) if len(cells) == 1 else None
            if heading is not None:
                lead = self.block_node(heading)
                source_rows = source_rows[1:]

        rows: list[tuple[bool, list[str]]] = []
        for row in source_rows:
            cells_text: list[str] = []
            header = False
            for cell in row.children:
                if not isinstance(cell, Node) or cell.tag not in {"td", "th"}:
                    continue
                header = header or cell.tag == "th"
                cells_text.append(self.cell_text(cell))
            if cells_text:
                rows.append((header, cells_text))
        if not rows:
            return lead
        if lead:
            lead += "\n\n"
        width = max(len(cells) for _, cells in rows)
        if width == 1:
            return lead + "\n\n".join(cells[0] for _, cells in rows if cells[0].strip())
        header_cells = rows[0][1] if rows[0][0] else [""] * width
        body = rows[1:] if rows[0][0] else rows
        lines = [
            "| " + " | ".join(pad(header_cells, width)) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        for _, cells in body:
            lines.append("| " + " | ".join(pad(cells, width)) + " |")
        return lead + "\n".join(lines)

    def nested_table_sections(self, node: Node) -> str:
        parts: list[str] = []
        for row in own_rows(node):
            for cell in row.children:
                if not isinstance(cell, Node) or cell.tag not in {"td", "th"} or dropped(cell):
                    continue
                rendered = self.blocks(cell).strip()
                if rendered:
                    parts.append(rendered)
        return "\n\n".join(parts)

    def cell_text(self, node: Node) -> str:
        rendered = self.blocks(node)
        rendered = re.sub(r"```[a-z0-9+#-]*\n(.*?)\n```", lambda m: "`" + m.group(1).replace("\n", " ") + "`", rendered, flags=re.S)
        rendered = re.sub(r"\n+", "<br>", rendered.strip())
        return escape_inline(rendered)


def flattens_to_sections(table: Node) -> bool:
    if table.find(lambda child: child.tag == "table") is not None:
        return True
    for node in table.iter_nodes():
        if node.tag == "pre" and "\n" in node.text().strip():
            return True
    return False


def own_rows(table: Node) -> list[Node]:
    rows: list[Node] = []

    def walk(node: Node) -> None:
        for child in node.children:
            if not isinstance(child, Node):
                continue
            if child.tag == "tr":
                rows.append(child)
            elif child.tag in {"thead", "tbody", "tfoot"}:
                walk(child)

    walk(table)
    return rows


def pad(cells: list[str], width: int) -> list[str]:
    return [cells[index] if index < len(cells) else "" for index in range(width)]


def page_relative_path(path: str) -> str:
    return path.strip("/") or "index"


def markdown_path(out: Path, slug: str) -> Path:
    return out / "pages" / (slug + ".md")


def raw_path(out: Path, slug: str) -> Path:
    return out / "raw" / (slug + ".html.gz")


def existing_asset(out: Path, url: str) -> Path | None:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    for candidate in sorted((out / "assets").glob(digest + ".*")):
        if candidate.is_file():
            return candidate
    return None


def asset_path(out: Path, url: str, content_type: str | None = None) -> Path:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
        suffix = guessed if guessed in IMAGE_EXTENSIONS else (suffix or ".bin")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return out / "assets" / (digest + suffix)


def relative_posix(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target, start)).as_posix()


class Mirror:
    def __init__(self, args: argparse.Namespace):
        self.out: Path = args.out.resolve()
        self.args = args
        self.groups = {name: value for name, value in GROUPS.items() if not args.only or name in args.only}
        self.prefixes = {name: value["prefixes"] for name, value in self.groups.items()}
        self.lock = threading.Lock()
        self.seen: set[str] = set()
        self.page_records: dict[str, dict[str, Any]] = {}
        self.image_urls: set[str] = set()
        self.failures: list[dict[str, Any]] = []
        self.asset_records: dict[str, dict[str, Any]] = {}
        self.robots: Robots | None = None
        self.slugs: dict[str, str] = {}
        self.claimed_slugs: set[str] = set()
        self.validators: dict[str, dict[str, str]] = {}
        self.changed: list[dict[str, Any]] = []
        self.queue: list[str] = []
        self.truncated = False

    def group_of(self, path: str) -> str | None:
        for name, prefixes in self.prefixes.items():
            for prefix in prefixes:
                if path == prefix.rstrip("/") or path.startswith(prefix):
                    return name
        return None

    def crawlable(self, path: str) -> bool:
        return bool(self.robots and self.robots.allows(path))

    def slug_for(self, path: str) -> str:
        with self.lock:
            existing = self.slugs.get(path)
            if existing:
                return existing
            base = page_relative_path(path)
            slug = base
            counter = 2
            while slug.lower() in self.claimed_slugs:
                slug = f"{base}~{counter}"
                counter += 1
            self.claimed_slugs.add(slug.lower())
            self.slugs[path] = slug
            return slug

    def load_robots(self) -> str:
        response = fetch(BASE_URL + "/robots.txt", accept="text/plain")
        write_bytes(self.out / "metadata" / "robots.txt", response.data)
        text = response.data.decode("utf-8", errors="replace")
        self.robots = Robots(text)
        return text

    def fetch_page(self, path: str) -> tuple[str, str]:
        slug = self.slug_for(path)
        cache = raw_path(self.out, slug)
        url = BASE_URL + path
        cached = cache.exists()
        revalidate = self.args.refresh or self.args.check
        if cached and not revalidate:
            return gzip.decompress(cache.read_bytes()).decode("utf-8", errors="replace"), "cached"

        stored = self.validators.get(path) if cached else None
        if cached and (stored is None or "article_sha256" not in stored):
            previous_markup = gzip.decompress(cache.read_bytes()).decode("utf-8", errors="replace")
            stored = dict(stored or {})
            stored["article_sha256"] = sha256((nav_and_article(previous_markup)[1] or previous_markup).encode("utf-8"))
            with self.lock:
                self.validators[path] = stored
        response = fetch(url, accept="text/html", validators=stored)
        if response.unchanged and cached:
            with self.lock:
                self.validators.setdefault(path, {}).update(response.validators())
            return gzip.decompress(cache.read_bytes()).decode("utf-8", errors="replace"), "unchanged"

        markup = response.data.decode("utf-8", errors="replace")
        digest = sha256((nav_and_article(markup)[1] or markup).encode("utf-8"))
        current = dict(response.validators())
        current["article_sha256"] = digest
        unchanged = bool(stored) and stored.get("article_sha256") == digest
        with self.lock:
            self.validators[path] = current
            if cached and not unchanged:
                self.changed.append({
                    "path": path,
                    "url": url,
                    "last_modified": response.headers.get("last-modified"),
                })
        if unchanged:
            return markup, "unchanged"
        if not self.args.check:
            write_bytes(cache, gzip.compress(response.data, 6))
        return markup, "downloaded"

    def load_previous(self) -> bool:
        metadata = self.out / "metadata"
        pages = metadata / "pages.json"
        if not pages.exists():
            return False
        state = metadata / "crawl-state.json"
        if state.exists():
            try:
                saved = json.loads(state.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                saved = {}
            self.validators.update(saved.get("validators", {}))
            self.truncated = bool(saved.get("queue"))
        records = json.loads(pages.read_text(encoding="utf-8"))
        for record in records:
            if not self.group_of(record["path"]):
                continue
            self.page_records[record["path"]] = record
            self.slugs[record["path"]] = record["slug"]
            self.claimed_slugs.add(record["slug"].lower())
        assets = metadata / "assets.json"
        if assets.exists():
            self.image_urls.update(record["url"] for record in json.loads(assets.read_text(encoding="utf-8")))
        failures = metadata / "failures.json"
        if failures.exists():
            self.failures.extend(
                record for record in json.loads(failures.read_text(encoding="utf-8")) if record.get("reason") != "render"
            )
        return bool(self.page_records)

    def state_path(self) -> Path:
        return self.out / "metadata" / "crawl-state.json"

    def load_state(self) -> bool:
        path = self.state_path()
        if self.args.refresh:
            return False
        if not path.exists():
            return self.load_previous()
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        for record in state.get("pages", []):
            if not self.group_of(record["path"]):
                continue
            self.page_records[record["path"]] = record
            self.slugs[record["path"]] = record["slug"]
            self.claimed_slugs.add(record["slug"].lower())
        self.seen.update(state.get("seen", []))
        self.queue = [p for p in state.get("queue", []) if self.group_of(p)]
        self.failures.extend(state.get("failures", []))
        self.image_urls.update(state.get("images", []))
        self.validators.update(state.get("validators", {}))
        return True

    def save_state(self, also_queued: Iterable[str] = ()) -> None:
        with self.lock:
            snapshot = {
                "saved_at": utc_now(),
                "queue": list(self.queue) + list(also_queued),
                "seen": sorted(self.seen),
                "pages": [dict(self.page_records[path]) for path in sorted(self.page_records)],
                "failures": [dict(item) for item in self.failures],
                "images": sorted(self.image_urls),
                "validators": {key: dict(value) for key, value in self.validators.items()},
            }
        write_json(self.state_path(), snapshot)

    def crawl(self) -> None:
        resumed = self.load_state()
        if resumed:
            print(f"resumed: {len(self.page_records)} pages done, {len(self.queue)} queued", flush=True)
        if not resumed or self.args.refresh:
            self.queue = []
            self.seen = set()
        for group in self.groups.values():
            for seed in group["seeds"]:
                if seed not in self.seen:
                    self.seen.add(seed)
                    self.queue.append(seed)

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(MAX_WORKERS, self.args.workers)))
        done = 0
        try:
            while self.queue:
                if self.args.max_pages:
                    room = self.args.max_pages - len(self.page_records)
                    if room <= 0:
                        self.truncated = True
                        break
                    batch, self.queue = self.queue[:room], self.queue[room:]
                else:
                    batch, self.queue = self.queue, []
                for index, result in enumerate(pool.map(self.visit, batch), start=1):
                    done += 1
                    if done % 50 == 0:
                        print(f"pages {done} visited", flush=True)
                    if result is None:
                        continue
                    for link in result:
                        if link not in self.seen:
                            self.seen.add(link)
                            self.queue.append(link)
                    if index % 200 == 0:
                        self.save_state(batch[index:])
                print(f"pages {done} visited, {len(self.queue)} queued", flush=True)
                self.save_state()
        finally:
            pool.shutdown()
            self.truncated = bool(self.queue)
            self.save_state()

    def record_failure(self, path: str, group: str, reason: str, *, error: str | None = None, status: int | None = None, attempts: int = 1) -> None:
        entry: dict[str, Any] = {
            "path": path,
            "url": BASE_URL + path,
            "group": group,
            "reason": reason,
            "status": status,
            "attempts": attempts,
            "last_seen": utc_now(),
        }
        if error:
            entry["error"] = error
        with self.lock:
            self.failures = [item for item in self.failures if item.get("path") != path]
            self.failures.append(entry)

    def visit(self, path: str) -> list[str] | None:
        group = self.group_of(path)
        if not group:
            return None
        if not self.crawlable(path):
            self.record_failure(path, group, "robots-disallowed")
            return None
        try:
            markup, status = self.fetch_page(path)
        except FetchFailure as error:
            self.record_failure(path, group, "fetch", error=error.message, status=error.status, attempts=error.attempts)
            return None
        except Exception as error:
            self.record_failure(path, group, "fetch", error=f"{type(error).__name__}: {error}")
            return None
        if BODY_404.search(markup):
            self.record_failure(path, group, "not-found", status=404)
            return None
        nav, article = nav_and_article(markup)
        if article is None:
            self.record_failure(path, group, "no-article-body")
            return None

        links = self.extract_links(nav, article)
        images = self.extract_images(article)
        slug = self.slug_for(path)
        with self.lock:
            self.image_urls.update(images)
            self.page_records[path] = {
                "path": path,
                "group": group,
                "url": BASE_URL + path,
                "status": status,
                "slug": slug,
            }
        return links

    def extract_links(self, nav: str | None, article: str) -> list[str]:
        found: list[str] = []
        for scope in (nav, article):
            if not scope:
                continue
            for href in HREF.findall(scope):
                if not href or href.startswith(("#", "mailto:", "javascript:")):
                    continue
                parsed = urlparse(urljoin(BASE_URL + "/", html.unescape(href)))
                if parsed.hostname != "developer.android.com" or parsed.query:
                    continue
                candidate = parsed.path.rstrip("/") or "/"
                if self.group_of(candidate):
                    found.append(candidate)
        return found

    def extract_images(self, article: str) -> set[str]:
        urls: set[str] = set()
        for tag in IMG_TAG.findall(article):
            match = IMG_SRC.search(tag)
            if not match:
                continue
            source = html.unescape(match.group(1) or "").strip()
            if not source and match.group(2):
                source = html.unescape(match.group(2)).split(",")[0].strip().split(" ")[0]
            if source.startswith("data:") or not source:
                continue
            absolute, _ = urldefrag(urljoin(BASE_URL + "/", source))
            parsed = urlparse(absolute)
            if parsed.scheme in {"http", "https"} and parsed.hostname in ASSET_HOSTS:
                urls.add(absolute)
        return urls

    def collect_assets(self) -> list[str]:
        return sorted(self.image_urls)

    def download_assets(self, urls: list[str]) -> None:
        previous: dict[str, dict[str, Any]] = {}
        manifest = self.out / "metadata" / "assets.json"
        if manifest.exists():
            try:
                previous = {record["url"]: record for record in json.loads(manifest.read_text(encoding="utf-8"))}
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                previous = {}

        if self.args.no_assets:
            for url in urls:
                cached = previous.get(url)
                if cached and cached.get("path") and (self.out / cached["path"]).exists():
                    self.asset_records[url] = {**cached, "status": "cached"}
                    continue
                on_disk = existing_asset(self.out, url)
                if on_disk is not None:
                    self.asset_records[url] = {"url": url, "status": "cached", "path": on_disk.relative_to(self.out).as_posix()}
                else:
                    self.asset_records[url] = {"url": url, "status": "not-downloaded"}
            return

        def download(url: str) -> dict[str, Any]:
            parsed = urlparse(url)
            if parsed.hostname == "developer.android.com" and not self.crawlable(parsed.path):
                return {"url": url, "status": "robots-disallowed"}
            if not self.args.refresh:
                cached = previous.get(url)
                if cached and cached.get("path") and (self.out / cached["path"]).exists():
                    return {**cached, "status": "cached"}
                on_disk = existing_asset(self.out, url)
                if on_disk is not None:
                    data = on_disk.read_bytes()
                    return {
                        "url": url, "status": "cached",
                        "path": on_disk.relative_to(self.out).as_posix(),
                        "bytes": len(data), "sha256": sha256(data),
                    }
            existing = previous.get(url) or {}
            validators = {key: existing[key] for key in ("etag", "last-modified") if existing.get(key)}
            local = existing_asset(self.out, url)
            try:
                response = fetch(url, validators=validators if local is not None else None)
            except FetchFailure as error:
                return {"url": url, "status": "error", "error": error.message, "http_status": error.status, "attempts": error.attempts}
            except Exception as error:
                return {"url": url, "status": "error", "error": f"{type(error).__name__}: {error}"}
            if response.unchanged and local is not None:
                return {**existing, "url": url, "status": "cached", "path": local.relative_to(self.out).as_posix()}
            path = asset_path(self.out, url, response.headers.get("content-type"))
            write_bytes(path, response.data)
            return {
                "url": url, "status": "downloaded",
                "path": path.relative_to(self.out).as_posix(),
                "bytes": len(response.data), "sha256": sha256(response.data),
                "content_type": response.headers.get("content-type"),
                **response.validators(),
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(MAX_WORKERS, self.args.workers))) as pool:
            for index, record in enumerate(pool.map(download, urls), start=1):
                self.asset_records[record["url"]] = record
                if index % 25 == 0 or index == len(urls):
                    print(f"assets {index}/{len(urls)}", flush=True)

    def render_all(self, fetched_at: str) -> None:
        asset_map = {
            url: record["path"]
            for url, record in self.asset_records.items()
            if record.get("path") and record.get("status") in {"downloaded", "cached"}
        }
        for index, path in enumerate(sorted(self.page_records), start=1):
            record = self.page_records[path]
            cache = raw_path(self.out, record["slug"])
            if not cache.exists():
                continue
            markup = gzip.decompress(cache.read_bytes()).decode("utf-8", errors="replace")
            _, slice_ = nav_and_article(markup)
            if slice_ is None:
                continue
            article = parse_html(slice_)
            target = markdown_path(self.out, record["slug"])

            def resolve_link(href: str, target=target) -> str:
                if not href:
                    return ""
                if href.startswith("#"):
                    return href
                if href.startswith(("mailto:", "javascript:")):
                    return href if href.startswith("mailto:") else ""
                absolute = urljoin(BASE_URL + "/", href)
                parsed = urlparse(absolute)
                if parsed.hostname == "developer.android.com" and not parsed.query:
                    other = parsed.path.rstrip("/") or "/"
                    mirrored = self.page_records.get(other)
                    if mirrored:
                        local = markdown_path(self.out, mirrored["slug"])
                        relative = relative_posix(local, target.parent)
                        return relative + (("#" + parsed.fragment) if parsed.fragment else "")
                return absolute

            def resolve_image(source: str, target=target) -> str:
                if source.startswith("data:"):
                    return source
                absolute, _ = urldefrag(urljoin(BASE_URL + "/", source))
                local = asset_map.get(absolute)
                if local:
                    return relative_posix(self.out / local, target.parent)
                return absolute

            title = page_title(markup) or path.rsplit("/", 1)[-1]
            record["title"] = title
            renderer = Renderer(resolve_link, resolve_image)
            try:
                body = clean_markdown(renderer.blocks(article))
            except Exception as error:
                self.failures.append({"path": path, "group": record["group"], "reason": "render", "error": f"{type(error).__name__}: {error}"})
                continue
            if not body.startswith("# "):
                body = f"# {title}\n\n" + body
            val = self.validators.get(path) or {}
            markdown = format_frontmatter(
                url=record["url"],
                title=title,
                section=record["group"],
                fetched_at=fetched_at,
                last_modified=val.get("last-modified"),
                etag=val.get("etag"),
                body=body,
            )
            write_text(target, markdown)
            record["markdown_path"] = target.relative_to(self.out).as_posix()
            record["markdown_bytes"] = len(markdown.encode("utf-8"))
            if index % 100 == 0 or index == len(self.page_records):
                print(f"markdown {index}/{len(self.page_records)}", flush=True)


def build_index(records: list[dict[str, Any]], groups: dict[str, Any], fetched_at: str) -> str:
    lines = [
        "# Android Compose, Navigation 3 & UI Design Index",
        "",
        f"Updated: `{fetched_at}` | Source: {BASE_URL}",
        "",
    ]
    by_group: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_group.setdefault(record["group"], []).append(record)
    for name in groups:
        pages = sorted(by_group.get(name, []), key=lambda item: item["path"])
        if not pages:
            continue
        lines.append(f"## {GROUP_TITLES.get(name, name)} ({len(pages)} pages)")
        lines.append("")
        for record in pages:
            title = record.get("title") or record["path"].rsplit("/", 1)[-1]
            lines.append(f"- [{title}]({record['path'].strip('/')}.md)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def renders_as_table(node: Node) -> bool:
    if flattens_to_sections(node):
        return False
    rows = own_rows(node)
    if rows:
        cells = [child for child in rows[0].children if isinstance(child, Node) and child.tag in {"td", "th"}]
        if len(cells) == 1 and cells[0].find(lambda child: child.tag in HEADING_TAGS) is not None:
            rows = rows[1:]
    widths = [len([child for child in row.children if isinstance(child, Node) and child.tag in {"td", "th"}]) for row in rows]
    widths = [w for w in widths if w]
    return bool(widths) and max(widths) > 1


def count_source_shapes(markup: str) -> dict[str, int]:
    _, article = nav_and_article(markup)
    if article is None:
        return {}
    root = parse_html(article)
    selector_ids = {
        id(node) for node in root.iter_nodes()
        if node.tag in {"devsite-selector", "tabs"} or "ds-selector-tabs" in node.classes()
    }

    def inside_selector(node: Node) -> bool:
        cur = node.parent
        while cur is not None:
            if id(cur) in selector_ids:
                return True
            cur = cur.parent
        return False

    def is_dropped(node: Node) -> bool:
        cur: Node | None = node
        while cur is not None:
            if dropped(cur):
                return True
            cur = cur.parent
        return False

    counts = {"code": 0, "heading": 0, "table": 0, "image": 0}
    for node in root.iter_nodes():
        if is_dropped(node):
            continue
        if node.tag == "pre":
            counts["code"] += 1
        elif node.tag in HEADING_TAGS and not inside_selector(node):
            counts["heading"] += 1
        elif node.tag == "table" and renders_as_table(node):
            counts["table"] += 1
        elif node.tag == "img" and image_source(node):
            counts["image"] += 1
    return counts


def count_markdown_shapes(markdown: str) -> dict[str, int]:
    counts = {"code": 0, "heading": 0, "table": 0, "image": 0}
    fence = ""
    previous_table = False
    for line in markdown.split("\n"):
        stripped = line.lstrip()
        if fence:
            if stripped.rstrip() == fence:
                fence = ""
            continue
        if stripped.startswith("```"):
            fence = stripped[: len(stripped) - len(stripped.lstrip("`"))]
            counts["code"] += 1
            continue
        if re.match(r"#{1,6} ", stripped):
            counts["heading"] += 1
        is_table = stripped.startswith("| ")
        if is_table and not previous_table:
            counts["table"] += 1
        previous_table = is_table
        counts["image"] += line.count("![")
    return counts


def verify(mirror: Mirror, sample: int, seed: int) -> int:
    records = [
        r for r in mirror.page_records.values()
        if raw_path(mirror.out, r["slug"]).exists() and markdown_path(mirror.out, r["slug"]).exists()
    ]
    records.sort(key=lambda item: item["path"])
    chosen = records if sample <= 0 or sample >= len(records) else random.Random(seed).sample(records, sample)

    results: list[dict[str, Any]] = []
    for record in chosen:
        markup = gzip.decompress(raw_path(mirror.out, record["slug"]).read_bytes()).decode("utf-8", errors="replace")
        markdown = markdown_path(mirror.out, record["slug"]).read_text(encoding="utf-8")
        expected = count_source_shapes(markup)
        found = count_markdown_shapes(markdown)
        longest = max((len(line) for line in markdown.split("\n")), default=0)
        problems = [f"{k} {found.get(k, 0)}/{v}" for k, v in expected.items() if found.get(k, 0) < v]
        if longest > MAX_LINE_LENGTH:
            problems.append(f"line {longest} > {MAX_LINE_LENGTH}")
        results.append({"path": record["path"], "expected": expected, "found": found, "longest_line": longest, "problems": problems})

    over_length = [
        (max((len(line) for line in markdown_path(mirror.out, r["slug"]).read_text(encoding="utf-8").split("\n")), default=0), r["path"])
        for r in records
    ]
    breached = [(l, p) for l, p in over_length if l > MAX_LINE_LENGTH]
    failed = [r for r in results if r["problems"]]
    report = {
        "checked_at": utc_now(),
        "sample": len(results),
        "population": len(records),
        "failed_sample": len(failed),
        "longest_line": max((l for l, _ in over_length), default=0),
        "pages_over_max_line": [{"path": p, "longest_line": l} for l, p in breached],
        "passed": not failed and not breached,
        "results": results,
    }
    write_json(mirror.out / "metadata" / "verify.json", report)
    print(f"verified {len(results)}/{len(records)} pages: {len(failed)} sample problems, {len(breached)} over {MAX_LINE_LENGTH} chars, passed={report['passed']}")
    return 0 if report["passed"] else 1


def check(mirror: Mirror) -> int:
    paths = sorted(mirror.page_records)
    workers = max(1, min(MAX_WORKERS, mirror.args.workers))

    def probe(path: str) -> None:
        try:
            mirror.fetch_page(path)
        except FetchFailure as error:
            mirror.record_failure(path, mirror.page_records[path]["group"], "fetch", error=error.message, status=error.status, attempts=error.attempts)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for index, _ in enumerate(pool.map(probe, paths), start=1):
            if index % 100 == 0 or index == len(paths):
                print(f"checked {index}/{len(paths)}", flush=True)

    report = {
        "checked_at": utc_now(),
        "pages_checked": len(paths),
        "changed": sorted(mirror.changed, key=lambda item: item["path"]),
        "failed": mirror.failures,
    }
    write_json(mirror.out / "metadata" / "check.json", report)
    print(f"{len(mirror.changed)} of {len(paths)} pages changed upstream")
    return exit_code(mirror)


def exit_code(mirror: Mirror) -> int:
    gone = {404, 410}
    hard = [f for f in mirror.failures if f.get("reason") not in {"not-found"} and f.get("status") not in gone]
    hard += [r for r in mirror.asset_records.values() if r.get("status") == "error" and r.get("http_status") not in gone]
    if hard:
        print(f"{len(hard)} hard failures", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="mirror output directory")
    parser.add_argument("--workers", type=int, default=8, help=f"concurrent workers (max {MAX_WORKERS})")
    parser.add_argument("--no-assets", action="store_true", help="skip downloading images")
    parser.add_argument("--refresh", action="store_true", help="revalidate everything with conditional requests")
    parser.add_argument("--only", action="append", choices=sorted(GROUPS), help="restrict crawl to one group")
    parser.add_argument("--max-pages", type=int, default=0, help="stop after this many pages")
    parser.add_argument("--drop-html", action="store_true", help="discard raw HTML cache when finished")
    parser.add_argument("--render-only", action="store_true", help="rebuild Markdown from cached HTML")
    parser.add_argument("--check", action="store_true", help="conditional check only, report changes")
    parser.add_argument("--verify", action="store_true", help="verify fidelity & line lengths <= 4000")
    parser.add_argument("--sample", type=int, default=30, help="pages to sample in --verify (0=all)")
    parser.add_argument("--seed", type=int, default=0, help="sampling seed")
    args = parser.parse_args()

    mirror = Mirror(args)
    mirror.out.mkdir(parents=True, exist_ok=True)
    (mirror.out / "metadata").mkdir(parents=True, exist_ok=True)

    if args.verify:
        if not mirror.load_previous():
            print("nothing to verify: run a crawl first", file=sys.stderr)
            return 1
        return verify(mirror, args.sample, args.seed)

    mirror.load_robots()
    fetched_at = utc_now()

    if args.check:
        if not mirror.load_previous():
            print("nothing to check: run a crawl first", file=sys.stderr)
            return 1
        return check(mirror)

    if args.render_only:
        if not mirror.load_previous():
            print("nothing to render: run a crawl first", file=sys.stderr)
            return 1
    else:
        mirror.crawl()

    assets = mirror.collect_assets()
    mirror.download_assets(assets)
    mirror.render_all(fetched_at)

    metadata = mirror.out / "metadata"
    records = [mirror.page_records[path] for path in sorted(mirror.page_records)]
    write_text(mirror.out / "pages" / "INDEX.md", build_index(records, mirror.groups, fetched_at))
    write_json(metadata / "pages.json", records)
    write_json(metadata / "assets.json", [mirror.asset_records[url] for url in sorted(mirror.asset_records)])
    write_json(metadata / "failures.json", sorted(mirror.failures, key=lambda item: (item.get("path", ""), item.get("url", ""))))

    group_counts = {
        GROUP_TITLES[name]: len([r for r in mirror.page_records.values() if r["group"] == name])
        for name in mirror.groups
    }
    downloaded_assets = len([r for r in mirror.asset_records.values() if r.get("status") in {"downloaded", "cached"}])
    gone = {404, 410}
    hard_failures = [f for f in mirror.failures if f.get("reason") != "not-found" and f.get("status") not in gone]

    manifest = {
        "source_id": SOURCE_ID,
        "name": "Android Jetpack Compose, Navigation 3 & UI Design Guidelines",
        "base_url": BASE_URL,
        "fetched_at": fetched_at,
        "page_count": len(mirror.page_records),
        "asset_count": downloaded_assets,
        "failed_count": len(hard_failures),
        "status": "ok" if not hard_failures else "partial",
        "upstream_version": "developer.android.com",
        "versions": {},
        "sections": group_counts,
        "notes": f"Mirrored /develop/ui/compose/, /guide/navigation/navigation-3/, /design/ui/mobile/, /design/ui/large-screens/ (upstream 404s ignored: {len(mirror.failures) - len(hard_failures)}).",
    }
    write_json(mirror.out / "manifest.json", manifest)
    write_json(REPO_ROOT / "manifests" / "sources" / f"{SOURCE_ID}.json", manifest)
    mirror.save_state()

    if args.drop_html:
        for record in mirror.page_records.values():
            cached = raw_path(mirror.out, record["slug"])
            if cached.exists():
                cached.unlink()

    print(json.dumps(group_counts, indent=2))
    return exit_code(mirror)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
