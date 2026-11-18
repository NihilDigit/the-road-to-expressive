#!/usr/bin/env python3
"""Mirror Google Design (`design.google`) articles & Material Color Utilities specs.

Discovers relevant `design.google/library/*` articles on Material 3 Expressive,
UX research, adaptive design, typography, motion, color, accessibility, and UX
writing via `sitemap.xml`, parses Next.js `__NEXT_DATA__` losslessly into
Markdown, and mirrors official `material-foundation/material-color-utilities`
HCT / DynamicScheme / ColorSpec2021-2026 concept guides and spec references.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    sha256_text,
    utc_now_iso,
    wrap_long_lines,
)

SOURCE_ID = "google-design"
SOURCE_NAME = "Google Design & Material Color Utilities"
BASE_URL = "https://design.google"
SITEMAP_URL = "https://design.google/sitemap.xml"
MCU_RAW_BASE = "https://raw.githubusercontent.com/material-foundation/material-color-utilities/main"

DESIGN_KEYWORDS = (
    "expressive",
    "material",
    "adaptive",
    "motion",
    "type",
    "typography",
    "color",
    "hct",
    "writing",
    "ux",
    "large-screen",
    "foldable",
    "accessibility",
    "shape",
    "design-system",
    "android",
    "compose",
    "sound-haptic",
    "icons",
    "symbols",
    "variable-font",
    "dark-theme",
    "readability",
)

MCU_MARKDOWN_FILES = (
    ("concepts/color_terms.md", "Color Terms (HCT, Tone, Chroma, Hue)"),
    ("concepts/color_spaces.md", "Color Spaces in Material Color Utilities (HCT & CAM16)"),
    ("concepts/color_extraction.md", "Color Extraction & Quantization"),
    ("concepts/contrast_for_accessibility.md", "Contrast for Accessibility"),
    ("concepts/dynamic_color_scheme.md", "Dynamic Color Scheme Architecture"),
    ("concepts/scheme_generation.md", "Scheme Generation & Variants"),
    ("dev_guide/creating_color_scheme.md", "Developer Guide: Creating a Color Scheme"),
    ("dev_guide/extracting_colors.md", "Developer Guide: Extracting Colors"),
    ("dev_guide/refining_contrast.md", "Developer Guide: Refining Contrast"),
    ("swift/Guides/Hct.md", "HCT Color Space Guide"),
)

MCU_SPEC_SOURCE_FILES = (
    ("kotlin/dynamiccolor/ColorSpec.kt", "ColorSpec Interface (2021 / 2025 / 2026)"),
    ("kotlin/dynamiccolor/ColorSpec2021.kt", "ColorSpec2021 (Material You Baseline Spec)"),
    ("kotlin/dynamiccolor/ColorSpec2025.kt", "ColorSpec2025 (Material 3 Expressive Color Spec)"),
    ("kotlin/dynamiccolor/ColorSpec2026.kt", "ColorSpec2026 (Material Color Spec 2026)"),
    ("kotlin/dynamiccolor/DynamicScheme.kt", "DynamicScheme Core Definition"),
    ("kotlin/scheme/SchemeExpressive.kt", "SchemeExpressive Variant Definition"),
    ("kotlin/scheme/SchemeTonalSpot.kt", "SchemeTonalSpot Variant Definition"),
    ("kotlin/scheme/SchemeCmf.kt", "SchemeCmf Variant Definition"),
)


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
    return value.strip() + "\n"


class SimpleHtmlToMarkdown(HTMLParser):
    """Lightweight HTML-to-Markdown converter for embedded HTML blocks."""

    BLOCK_TAGS = {"article", "blockquote", "div", "figure", "p", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[str] = []
        self.link_stack: list[str] = []
        self.pre_depth = 0

    def block(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n\n"):
            self.parts.append("\n\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = dict(attrs)
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.block()
            self.parts.append("#" * int(tag[1]) + " ")
        elif tag in self.BLOCK_TAGS:
            self.block()
        elif tag in {"ul", "ol"}:
            self.block()
            self.list_stack.append(tag)
        elif tag == "li":
            self.block()
            self.parts.append("1. " if self.list_stack and self.list_stack[-1] == "ol" else "- ")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "code" and self.pre_depth == 0:
            self.parts.append("`")
        elif tag == "pre":
            self.block()
            self.pre_depth += 1
            self.parts.append("```\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "a":
            self.parts.append("[")
            self.link_stack.append(attr.get("href") or "")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"} | self.BLOCK_TAGS:
            self.block()
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self.block()
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "code" and self.pre_depth == 0:
            self.parts.append("`")
        elif tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
            self.parts.append("\n```\n")
            self.block()
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else ""
            self.parts.append(f"]({href})" if href else "]")

    def handle_data(self, data: str) -> None:
        if self.pre_depth:
            self.parts.append(data)
        else:
            self.parts.append(re.sub(r"\s+", " ", data))

    def convert(self, value: str) -> str:
        try:
            self.feed(value)
            self.close()
        except Exception:
            return normalize_text(re.sub(r"<[^>]+>", " ", value))
        return clean_markdown("".join(self.parts))


def discover_design_google_urls(sitemap_xml: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", sitemap_xml):
        loc = match.group(1).strip()
        lastmod = (match.group(2) or "").strip()
        if loc in seen or "/library/" not in loc:
            continue
        lower = loc.lower()
        if any(kw in lower for kw in DESIGN_KEYWORDS):
            seen.add(loc)
            slug = loc.rstrip("/").rsplit("/", 1)[-1]
            entries.append({"url": loc, "slug": slug, "lastmod": lastmod})
    entries.sort(key=lambda e: e["slug"])
    return entries


def _render_block_item(item: Any, asset_notes: list[str]) -> list[str]:
    if not isinstance(item, dict):
        return []
    btype = item.get("type", "")
    val = item.get("value")
    if not isinstance(val, dict):
        return []

    out: list[str] = []
    if btype in {"col_1", "col_2"}:
        for key in ("content", "left_content", "right_content", "columns"):
            children = val.get(key)
            if isinstance(children, list):
                for child in children:
                    out.extend(_render_block_item(child, asset_notes))
        return out

    if btype == "title":
        title = normalize_text(val.get("title"))
        desc = normalize_text(val.get("description"))
        eyebrow = normalize_text(val.get("eyebrow"))
        hsize = str((val.get("format") or {}).get("heading_size", "h2")).lower()
        level = int(hsize[1]) if len(hsize) == 2 and hsize[0] == "h" and hsize[1].isdigit() else 2
        if eyebrow:
            out.append(f"*{eyebrow}*")
        if title:
            out.append(f"{'#' * max(1, min(6, level))} {title}")
        if desc:
            out.append(desc)
        return out

    if btype == "text":
        body = str(val.get("body") or "").strip()
        if body:
            out.append(body.replace("\r\n", "\n"))
        return out

    if btype == "html":
        markup = str(val.get("markup") or "").strip()
        if markup:
            out.append(SimpleHtmlToMarkdown().convert(markup).strip())
        return out

    if btype == "image":
        alt = normalize_text(val.get("alt") or val.get("title") or "image")
        caption = normalize_text(val.get("caption"))
        img_url = (val.get("original") or {}).get("url") or (val.get("renditions") or {}).get("original") or ""
        if img_url:
            asset_notes.append(img_url)
            out.append(f"![{escape_table(alt)}]({img_url})")
        elif alt:
            out.append(f"*Image: {alt}*")
        if caption:
            out.append(f"_{caption}_")
        return out

    if btype == "feature":
        ftitle = normalize_text(val.get("title") or val.get("heading"))
        fbody = str(val.get("body") or val.get("description") or "").strip()
        if ftitle:
            out.append(f"### {ftitle}")
        if fbody:
            out.append(fbody)
        img = val.get("image")
        if isinstance(img, dict):
            out.extend(_render_block_item({"type": "image", "value": img}, asset_notes))
        return out

    if btype == "video":
        vtitle = normalize_text(val.get("title") or "Video")
        vurl = val.get("url") or (
            f"https://www.youtube.com/watch?v={val['embed_id']}"
            if val.get("embed") and val.get("embed_id")
            else ""
        )
        caption = normalize_text(val.get("caption"))
        transcript = str(val.get("transcript") or "").strip()
        if vurl:
            out.append(f"- Video: [{escape_table(vtitle)}]({vurl})")
        if caption:
            out.append(f"_{caption}_")
        if transcript:
            out.append(f"#### Video Transcript\n\n{transcript}")
        return out

    if btype == "audio":
        atitle = normalize_text(val.get("title") or "Audio")
        aurl = val.get("url") or ""
        desc = normalize_text(val.get("description"))
        if aurl:
            out.append(f"- Audio: [{escape_table(atitle)}]({aurl})")
        if desc:
            out.append(desc)
        return out

    return out


def render_design_google_article(html_text: str, url: str) -> tuple[str, str, str, list[str]]:
    """Return `(title, last_modified, markdown_body, image_urls)` from Next.js SSR HTML."""
    nd_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.S)
    asset_urls: list[str] = []
    if nd_match:
        try:
            nd = json.loads(nd_match.group(1))
            page = nd.get("props", {}).get("pageProps", {}).get("page", {})
            title = normalize_text(page.get("title") or page.get("metadata", {}).get("title") or url.rsplit("/", 1)[-1])
            desc = normalize_text(page.get("description") or page.get("metadata", {}).get("description") or "")
            pub = str(page.get("publish_at") or "")
            tags = [str(t) for t in (page.get("tags") or []) if t]
            contributors = [
                f"{c.get('name', '')} ({c.get('role', '')})".strip(" ()")
                for c in (page.get("contributors") or [])
                if isinstance(c, dict) and c.get("name")
            ]
            parts: list[str] = [f"# {title}"]
            if desc:
                parts.append(f"> {desc}")
            meta_lines: list[str] = []
            if pub:
                meta_lines.append(f"- **Published**: `{pub}`")
            if contributors:
                meta_lines.append(f"- **Contributors**: {', '.join(contributors)}")
            if tags:
                meta_lines.append(f"- **Tags**: {', '.join(tags)}")
            if meta_lines:
                parts.append("\n".join(meta_lines))

            body_blocks = (page.get("data") or {}).get("body") or []
            for block in body_blocks:
                parts.extend(_render_block_item(block, asset_urls))

            rendered = wrap_long_lines(clean_markdown("\n\n".join(p for p in parts if p.strip())), MAX_LINE_LENGTH)
            return title, pub, rendered, asset_urls
        except Exception:
            pass

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    title = normalize_text(title_match.group(1) if title_match else url.rsplit("/", 1)[-1])
    main_match = re.search(r"<(?:main|article)[^>]*>(.*?)</(?:main|article)>", html_text, re.S | re.I)
    snippet = main_match.group(1) if main_match else html_text
    snippet = re.sub(r"<script[^>]*>.*?</script>", "", snippet, flags=re.S | re.I)
    snippet = re.sub(r"<style[^>]*>.*?</style>", "", snippet, flags=re.S | re.I)
    body = f"# {title}\n\n" + SimpleHtmlToMarkdown().convert(snippet)
    return title, "", wrap_long_lines(clean_markdown(body), MAX_LINE_LENGTH), asset_urls


def build_index_markdown(records: list[dict[str, Any]], fetched_at: str) -> str:
    lines = [
        "# Google Design & Material Color Utilities Corpus Index",
        "",
        f"- **Source**: {BASE_URL} + `material-foundation/material-color-utilities`",
        f"- **Fetched At**: `{fetched_at}`",
        f"- **Total Pages**: {len(records)}",
        "",
    ]
    by_section: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_section.setdefault(rec["section"], []).append(rec)

    for sec in sorted(by_section):
        items = by_section[sec]
        lines.append(f"## {sec} ({len(items)})")
        lines.append("")
        lines.append("| Page | Title | Upstream URL |")
        lines.append("| --- | --- | --- |")
        for rec in sorted(items, key=lambda x: x["rel_path"]):
            lines.append(f"| [{rec['rel_path']}]({rec['rel_path']}) | {escape_table(rec['title'])} | {rec['url']} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def verify_corpus(out_dir: Path, committed_manifest_path: Path) -> int:
    pages_dir = out_dir / "pages"
    errors: list[str] = []
    if not pages_dir.is_dir():
        errors.append(f"Missing pages directory: {pages_dir}")
    if not (pages_dir / "INDEX.md").is_file():
        errors.append(f"Missing INDEX.md in {pages_dir}")
    if not committed_manifest_path.is_file():
        errors.append(f"Missing committed source manifest: {committed_manifest_path}")

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="Override `.corpus/google-design` output directory")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent HTTP workers")
    parser.add_argument("--no-assets", action="store_true", help="Skip downloading media assets")
    parser.add_argument("--check", action="store_true", help="Check sitemap count & conditional headers only")
    parser.add_argument("--refresh", action="store_true", help="Force re-download ignoring conditional HTTP cache")
    parser.add_argument("--verify", action="store_true", help="Verify corpus pages, frontmatter, and line lengths")
    args = parser.parse_args(argv)

    paths = get_paths(REPO_ROOT)
    out_dir = args.out.resolve() if args.out else paths.source_corpus_dir(SOURCE_ID)
    committed_manifest_path = paths.source_committed_manifest(SOURCE_ID)

    raw_argv = argv if argv is not None else sys.argv[1:]
    if args.verify and set(raw_argv) <= {"--verify"} and (out_dir / "pages").is_dir():
        return verify_corpus(out_dir, committed_manifest_path)

    client = ConditionalHttpClient(
        cache_dir=out_dir / "raw",
        timeout=30.0,
        max_retries=4,
        respect_robots=True,
    )

    sm_res = client.fetch(SITEMAP_URL, force_refresh=args.refresh, headers={"Accept": "application/xml"})
    sm_cache = out_dir / "raw" / "sitemap.xml"
    if sm_res.not_modified and sm_cache.is_file():
        sitemap_text = sm_cache.read_text(encoding="utf-8", errors="replace")
    elif sm_res.ok and sm_res.body is not None:
        sitemap_text = sm_res.body.decode("utf-8", errors="replace")
        write_text(sm_cache, sitemap_text)
    else:
        raise RuntimeError(f"Failed to fetch {SITEMAP_URL}: {sm_res.error}")

    article_jobs = discover_design_google_urls(sitemap_text)
    if args.check:
        client.save_state()
        print(
            json.dumps(
                {
                    "source_id": SOURCE_ID,
                    "sitemap_articles_matched": len(article_jobs),
                    "mcu_docs_configured": len(MCU_MARKDOWN_FILES) + len(MCU_SPEC_SOURCE_FILES),
                    "sitemap_not_modified": sm_res.not_modified,
                },
                indent=2,
            )
        )
        return 0

    fetched_at = utc_now_iso()
    pages_dir = out_dir / "pages"
    page_records: list[dict[str, Any]] = []
    section_counts: dict[str, int] = {}
    failures: list[dict[str, str]] = []

    def fetch_article(job: dict[str, str]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        url = job["url"]
        slug = job["slug"]
        raw_html_path = out_dir / "raw" / "html" / f"{slug}.html"
        res = client.fetch(url, force_refresh=args.refresh, headers={"Accept": "text/html"})
        if res.not_modified and raw_html_path.is_file():
            html_text = raw_html_path.read_text(encoding="utf-8", errors="replace")
        elif res.ok and res.body is not None:
            html_text = res.body.decode("utf-8", errors="replace")
            write_text(raw_html_path, html_text)
        else:
            return None, {"url": url, "error": res.error or f"HTTP {res.status}"}

        title, pub, body, _assets = render_design_google_article(html_text, url)
        if not body.strip():
            return None, {"url": url, "error": "Empty rendered article body"}
        rel = f"articles/{slug}.md"
        md_path = pages_dir / rel
        content_sha = sha256_text(body)
        last_mod = res.last_modified or pub or job.get("lastmod", "")
        meta = PageMetadata(
            source_id=SOURCE_ID,
            url=url,
            title=title,
            section="articles",
            fetched_at=fetched_at,
            last_modified=last_mod,
            sha256=content_sha,
            etag=res.etag,
            extra={"slug": slug},
        )
        write_text(md_path, format_page_frontmatter(meta, style="yaml") + body)
        return {
            "rel_path": rel,
            "url": url,
            "title": title,
            "section": "articles",
            "sha256": content_sha,
        }, None

    def fetch_mcu_doc(item: tuple[str, str, bool]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        rel_repo_path, title, is_code = item
        url = f"{MCU_RAW_BASE}/{rel_repo_path}"
        cache_file = out_dir / "raw" / "mcu" / rel_repo_path
        res = client.fetch(url, force_refresh=args.refresh, headers={"Accept": "text/plain"})
        if res.not_modified and cache_file.is_file():
            raw_text = cache_file.read_text(encoding="utf-8", errors="replace")
        elif res.ok and res.body is not None:
            raw_text = res.body.decode("utf-8", errors="replace")
            write_text(cache_file, raw_text)
        else:
            return None, {"url": url, "error": res.error or f"HTTP {res.status}"}

        if is_code:
            lang = "kotlin" if rel_repo_path.endswith(".kt") else "text"
            body = f"# {title}\n\n- **Source**: `{rel_repo_path}` (`material-foundation/material-color-utilities`)\n\n```{lang}\n{raw_text.rstrip()}\n```\n"
        else:
            stripped = raw_text.lstrip()
            if not re.match(r"^#\s+\S", stripped):
                body = f"# {title}\n\n{stripped}"
            else:
                body = stripped
        body = wrap_long_lines(clean_markdown(body), MAX_LINE_LENGTH)
        safe_name = rel_repo_path.replace("/", "__")
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        rel = f"material-color-utilities/{safe_name}"
        md_path = pages_dir / rel
        content_sha = sha256_text(body)
        meta = PageMetadata(
            source_id=SOURCE_ID,
            url=url,
            title=title,
            section="material-color-utilities",
            fetched_at=fetched_at,
            last_modified=res.last_modified,
            sha256=content_sha,
            etag=res.etag,
            extra={"repo_path": rel_repo_path},
        )
        write_text(md_path, format_page_frontmatter(meta, style="yaml") + body)
        return {
            "rel_path": rel,
            "url": url,
            "title": title,
            "section": "material-color-utilities",
            "sha256": content_sha,
        }, None

    mcu_jobs = [(p, t, False) for p, t in MCU_MARKDOWN_FILES] + [(p, t, True) for p, t in MCU_SPEC_SOURCE_FILES]

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        art_futures = [pool.submit(fetch_article, job) for job in article_jobs]
        mcu_futures = [pool.submit(fetch_mcu_doc, item) for item in mcu_jobs]
        for fut in concurrent.futures.as_completed(art_futures + mcu_futures):
            rec, err = fut.result()
            if rec:
                page_records.append(rec)
                section_counts[rec["section"]] = section_counts.get(rec["section"], 0) + 1
            elif err:
                failures.append(err)

    page_records.sort(key=lambda r: r["rel_path"])
    write_text(pages_dir / "INDEX.md", build_index_markdown(page_records, fetched_at))
    client.save_state()

    if failures:
        write_json(out_dir / "raw" / "failures.json", failures)

    manifest = SourceManifest(
        source_id=SOURCE_ID,
        name=SOURCE_NAME,
        base_url=BASE_URL,
        fetched_at=fetched_at,
        page_count=len(page_records),
        asset_count=0,
        failed_count=len(failures),
        status="ok" if page_records else "failed",
        upstream_version=fetched_at[:10],
        versions={
            "design_google_articles": str(section_counts.get("articles", 0)),
            "material_color_utilities": str(section_counts.get("material-color-utilities", 0)),
        },
        sections=dict(sorted(section_counts.items())),
        notes=(
            f"Mirrored {section_counts.get('articles', 0)} design.google articles on M3 Expressive, adaptive/large-screen UX, "
            f"motion, typography, color, accessibility, and UX writing, plus {section_counts.get('material-color-utilities', 0)} "
            f"material-color-utilities HCT & ColorSpec2021/2025/2026 spec documents."
        ),
    )
    manifest.write_json(out_dir / "manifest.json")
    manifest.write_json(committed_manifest_path)
    print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))

    if args.verify:
        return verify_corpus(out_dir, committed_manifest_path)
    return 0 if page_records else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
