"""Query, status, and corpus health verification (`doctor`) helpers for `rtx`."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rtx.config import MAX_LINE_LENGTH, RepoPaths, discover_sources, get_paths
from rtx.index import build_index
from rtx.models import SourceManifest, parse_page_frontmatter

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def ensure_index(paths: RepoPaths) -> Path:
    """Ensure `.corpus/index.db` exists, building it on demand if missing."""
    if not paths.index_db.is_file():
        build_index(paths)
    return paths.index_db


def _fts_query(raw: str, *, use_or: bool = False) -> str:
    tokens = _TOKEN_RE.findall(raw)
    if not tokens:
        return ""
    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low not in seen:
            seen.add(low)
            uniq.append(tok)
    joiner = " OR " if use_or else " AND "
    return joiner.join(f'"{t}"*' for t in uniq)


def _find_best_line(content: str, start_line: int, terms: list[str]) -> int:
    if not terms:
        return start_line
    lower_terms = [t.lower() for t in terms]
    for offset, line in enumerate(content.splitlines()):
        low = line.lower()
        if any(t in low for t in lower_terms):
            return start_line + offset
    return start_line


def _make_snippet(content: str, terms: list[str], max_chars: int = 240) -> str:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    chosen = ""
    lower_terms = [t.lower() for t in terms]
    for ln in lines:
        low = ln.lower()
        if any(t in low for t in lower_terms):
            chosen = ln
            break
    if not chosen and lines:
        chosen = lines[0]
    if len(chosen) > max_chars:
        return chosen[: max_chars - 3].rstrip() + "..."
    return chosen


@dataclass(slots=True)
class SearchHit:
    """Single BM25 or structured search hit."""

    layer: str
    source_id: str
    path: str
    line: int
    end_line: int
    title: str
    heading: str
    url: str
    score: float
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_corpus(
    paths: RepoPaths,
    query: str,
    *,
    source: str | None = None,
    layer: str | None = None,
    limit: int = 15,
) -> list[SearchHit]:
    """Run BM25 FTS5 search across `knowledge`, `mirror`, `api`, and/or `tokens`."""
    db_path = ensure_index(paths)
    terms = _TOKEN_RE.findall(query)
    fts_and = _fts_query(query, use_or=False)
    fts_or = _fts_query(query, use_or=True)

    hits: list[SearchHit] = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if layer in (None, "knowledge", "mirror"):
            hits.extend(_search_docs(conn, fts_and, terms, source=source, layer=layer, limit=limit))
            if not hits and fts_or and fts_or != fts_and:
                hits.extend(_search_docs(conn, fts_or, terms, source=source, layer=layer, limit=limit))

        if layer in (None, "api") and source is None:
            api_limit = limit if layer == "api" else max(3, limit // 3)
            api_hits = _search_api_as_hits(conn, fts_and or fts_or, query, limit=api_limit)
            hits.extend(api_hits)

        if layer in (None, "tokens") and source is None:
            tok_limit = limit if layer == "tokens" else max(3, limit // 3)
            tok_hits = _search_tokens_as_hits(conn, fts_and or fts_or, query, limit=tok_limit)
            hits.extend(tok_hits)
    finally:
        conn.close()

    # Sort by score ascending (SQLite bm25() is more negative = better match);
    # slightly prioritize curated knowledge over raw mirror on near ties when layer is None.
    def sort_key(h: SearchHit) -> tuple[float, int]:
        bias = -0.25 if (layer is None and h.layer == "knowledge") else 0.0
        return (h.score + bias, h.line)

    hits.sort(key=sort_key)
    return hits[:limit]


def _search_docs(
    conn: sqlite3.Connection,
    fts_expr: str,
    terms: list[str],
    *,
    source: str | None,
    layer: str | None,
    limit: int,
) -> list[SearchHit]:
    if not fts_expr:
        return []
    clauses = ["docs_fts MATCH ?"]
    params: list[Any] = [fts_expr]
    if source:
        clauses.append("m.source_id = ?")
        params.append(source)
    if layer in ("knowledge", "mirror"):
        clauses.append("m.layer = ?")
        params.append(layer)
    params.append(limit)

    sql = f"""
        SELECT
            m.layer, m.source_id, m.path, m.title, m.heading, m.url,
            m.start_line, m.end_line, m.content,
            bm25(docs_fts, 4.0, 6.0, 2.0, 1.0, 0.5, 0.5) AS rank
        FROM docs_fts
        JOIN docs_meta m ON docs_fts.rowid = m.id
        WHERE {' AND '.join(clauses)}
        ORDER BY rank
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []

    out: list[SearchHit] = []
    for row in rows:
        best_line = _find_best_line(row["content"], int(row["start_line"]), terms)
        out.append(
            SearchHit(
                layer=row["layer"],
                source_id=row["source_id"],
                path=row["path"],
                line=best_line,
                end_line=int(row["end_line"]),
                title=row["title"],
                heading=row["heading"],
                url=row["url"],
                score=float(row["rank"]),
                snippet=_make_snippet(row["content"], terms),
            )
        )
    return out


def _search_api_as_hits(conn: sqlite3.Connection, fts_expr: str, raw_query: str, *, limit: int) -> list[SearchHit]:
    rows: list[sqlite3.Row] = []
    if fts_expr:
        try:
            rows = conn.execute(
                """
                SELECT a.*, bm25(api_fts, 6.0, 2.0, 3.0, 2.0, 1.0, 1.0, 1.0, 1.0) AS rank
                FROM api_fts
                JOIN api_symbols a ON api_fts.rowid = a.id
                WHERE api_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_expr, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    if not rows and raw_query.strip():
        like = f"%{raw_query.strip()}%"
        rows = conn.execute(
            """
            SELECT *, -1.0 AS rank FROM api_symbols
            WHERE name LIKE ? OR signature LIKE ? OR annotations LIKE ?
            LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()

    out: list[SearchHit] = []
    for r in rows:
        ann = ", ".join(json.loads(r["annotations"]))
        snippet = r["signature"] or r["androidx_signature"] or r["cmp_signature"]
        if ann:
            snippet = f"[{ann}] {snippet}"
        out.append(
            SearchHit(
                layer="api",
                source_id="compose-maven-api",
                path=r["source_file"],
                line=1,
                end_line=1,
                title=r["name"],
                heading=f"{r['package']} ({r['artifact']})" if r["package"] else r["artifact"],
                url="",
                score=float(r["rank"]),
                snippet=snippet[:240],
            )
        )
    return out


def _search_tokens_as_hits(conn: sqlite3.Connection, fts_expr: str, raw_query: str, *, limit: int) -> list[SearchHit]:
    rows: list[sqlite3.Row] = []
    if fts_expr:
        try:
            rows = conn.execute(
                """
                SELECT t.*, bm25(tokens_fts, 6.0, 3.0, 2.0, 2.0, 3.0, 1.0, 1.0) AS rank
                FROM tokens_fts
                JOIN design_tokens t ON tokens_fts.rowid = t.id
                WHERE tokens_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_expr, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    if not rows and raw_query.strip():
        like = f"%{raw_query.strip()}%"
        rows = conn.execute(
            """
            SELECT *, -1.0 AS rank FROM design_tokens
            WHERE name LIKE ? OR category LIKE ? OR compose_token LIKE ? OR role LIKE ?
            LIMIT ?
            """,
            (like, like, like, like, limit),
        ).fetchall()

    out: list[SearchHit] = []
    for r in rows:
        snippet_parts = [p for p in (r["value"], r["compose_token"], r["notes"]) if p]
        out.append(
            SearchHit(
                layer="tokens",
                source_id="m3-expressive",
                path=r["source_file"],
                line=1,
                end_line=1,
                title=r["name"],
                heading=r["category"] or r["role"] or "token",
                url="",
                score=float(r["rank"]),
                snippet=" | ".join(snippet_parts)[:240],
            )
        )
    return out


def query_api(
    paths: RepoPaths,
    symbol_or_query: str,
    *,
    target: str | None = None,
    diff_only: bool = False,
    limit: int = 30,
) -> dict[str, Any]:
    """Query API symbols and Maven version pins across AndroidX & JetBrains CMP."""
    db_path = ensure_index(paths)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        fts_expr = _fts_query(symbol_or_query, use_or=False)
        rows: list[sqlite3.Row] = []
        if fts_expr:
            try:
                rows = conn.execute(
                    """
                    SELECT a.*, bm25(api_fts, 6.0, 2.0, 3.0, 2.0, 1.0, 1.0, 1.0, 1.0) AS rank
                    FROM api_fts
                    JOIN api_symbols a ON api_fts.rowid = a.id
                    WHERE api_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_expr, limit * 3),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

        if not rows:
            like = f"%{symbol_or_query.strip()}%"
            rows = conn.execute(
                """
                SELECT *, 0.0 AS rank FROM api_symbols
                WHERE name LIKE ? OR package LIKE ? OR signature LIKE ? OR annotations LIKE ?
                LIMIT ?
                """,
                (like, like, like, like, limit * 3),
            ).fetchall()

        filtered_symbols: list[dict[str, Any]] = []
        for r in rows:
            targets = json.loads(r["targets"])
            if target:
                t_low = target.lower()
                target_strs = [str(t).lower() for t in targets]
                if t_low not in target_strs and not (t_low in ("android", "desktop", "ios") and "common" in target_strs):
                    continue
            parity = r["parity_status"]
            androidx_sig = r["androidx_signature"]
            cmp_sig = r["cmp_signature"]
            has_diff = bool(
                (parity and parity.lower() not in ("parity", "identical", "exact"))
                or (androidx_sig and cmp_sig and androidx_sig != cmp_sig)
                or (bool(androidx_sig) != bool(cmp_sig))
            )
            if diff_only and not has_diff:
                continue
            filtered_symbols.append(
                {
                    "name": r["name"],
                    "package": r["package"],
                    "kind": r["kind"],
                    "signature": r["signature"],
                    "annotations": json.loads(r["annotations"]),
                    "artifact": r["artifact"],
                    "version": r["version"],
                    "targets": targets,
                    "androidx_signature": androidx_sig,
                    "cmp_signature": cmp_sig,
                    "parity_status": parity,
                    "doc": r["doc"],
                    "source_file": r["source_file"],
                }
            )
            if len(filtered_symbols) >= limit:
                break

        like_ver = f"%{symbol_or_query.strip()}%"
        ver_rows = conn.execute(
            """
            SELECT * FROM api_versions
            WHERE coordinate LIKE ? OR artifact_id LIKE ? OR ecosystem LIKE ?
            ORDER BY ecosystem, coordinate
            LIMIT 20
            """,
            (like_ver, like_ver, like_ver),
        ).fetchall()
        versions = [
            {
                "coordinate": v["coordinate"],
                "ecosystem": v["ecosystem"],
                "stable": v["stable"],
                "rc": v["rc"],
                "beta": v["beta"],
                "alpha": v["alpha"],
                "latest": v["latest"],
                "source_file": v["source_file"],
            }
            for v in ver_rows
        ]
    finally:
        conn.close()

    return {
        "query": symbol_or_query,
        "target": target,
        "diff_only": diff_only,
        "symbols": filtered_symbols,
        "versions": versions,
    }


def query_tokens(
    paths: RepoPaths,
    query: str,
    *,
    category: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Query design tokens from `manifests/tokens/*.json` plus related docs."""
    db_path = ensure_index(paths)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tokens: list[dict[str, Any]] = []
    try:
        fts_expr = _fts_query(query, use_or=False)
        rows: list[sqlite3.Row] = []
        cat_clause = " AND lower(t.category) LIKE ?" if category else ""
        cat_params: list[Any] = [f"%{category.lower()}%"] if category else []
        if fts_expr:
            try:
                rows = conn.execute(
                    f"""
                    SELECT t.*, bm25(tokens_fts, 6.0, 3.0, 2.0, 2.0, 3.0, 1.0, 1.0) AS rank
                    FROM tokens_fts
                    JOIN design_tokens t ON tokens_fts.rowid = t.id
                    WHERE tokens_fts MATCH ?{cat_clause}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_expr, *cat_params, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

        if not rows:
            like = f"%{query.strip()}%"
            cat_clause_plain = " AND lower(category) LIKE ?" if category else ""
            rows = conn.execute(
                f"""
                SELECT *, 0.0 AS rank FROM design_tokens
                WHERE (name LIKE ? OR category LIKE ? OR value LIKE ? OR role LIKE ? OR compose_token LIKE ? OR notes LIKE ?)
                {cat_clause_plain}
                LIMIT ?
                """,
                (like, like, like, like, like, like, *cat_params, limit),
            ).fetchall()

        for r in rows:
            tokens.append(
                {
                    "name": r["name"],
                    "category": r["category"],
                    "value": r["value"],
                    "role": r["role"],
                    "compose_token": r["compose_token"],
                    "spec_version": r["spec_version"],
                    "notes": r["notes"],
                    "source_file": r["source_file"],
                }
            )
    finally:
        conn.close()

    doc_hits = [h.to_dict() for h in search_corpus(paths, query, layer="knowledge", limit=6)]
    return {
        "query": query,
        "category": category,
        "tokens": tokens,
        "knowledge_refs": doc_hits,
    }


def query_component(paths: RepoPaths, name: str) -> dict[str, Any]:
    """Unified component view: M3E tokens, Compose APIs, adaptive behavior, and platform HIG notes."""
    api_res = query_api(paths, name, limit=12)
    tok_res = query_tokens(paths, name, limit=15)

    knowledge_hits = [h.to_dict() for h in search_corpus(paths, name, layer="knowledge", limit=8)]
    m3_hits = [h.to_dict() for h in search_corpus(paths, name, source="m3-expressive", layer="mirror", limit=4)]
    compose_hits = [
        h.to_dict()
        for h in (
            search_corpus(paths, name, source="compose-android", layer="mirror", limit=3)
            + search_corpus(paths, name, source="compose-multiplatform", layer="mirror", limit=3)
        )
    ]
    hig_hits = [
        h.to_dict()
        for h in (
            search_corpus(paths, name, source="apple-hig", layer="mirror", limit=3)
            + search_corpus(paths, name, source="windows-fluent", layer="mirror", limit=3)
            + search_corpus(paths, name, source="linux-hig", layer="mirror", limit=3)
        )
    ]

    return {
        "component": name,
        "compose_apis": api_res["symbols"],
        "tokens": tok_res["tokens"],
        "knowledge": knowledge_hits,
        "m3_expressive": m3_hits,
        "compose_docs": compose_hits,
        "platform_hig": hig_hits,
    }


def query_copy(paths: RepoPaths, topic: str, *, limit: int = 15) -> dict[str, Any]:
    """Query UI copywriting & microcopy rules across UX writing and platform style guides."""
    db_path = ensure_index(paths)
    terms = _TOKEN_RE.findall(topic)
    fts_and = _fts_query(topic, use_or=False)
    fts_or = _fts_query(topic, use_or=True)

    copy_sources = ("knowledge", "writing-style", "m3-expressive", "apple-hig", "windows-fluent", "linux-hig")
    hits: list[SearchHit] = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for expr in (fts_and, fts_or):
            if not expr:
                continue
            placeholders = ",".join("?" for _ in copy_sources)
            try:
                rows = conn.execute(
                    f"""
                    SELECT
                        m.layer, m.source_id, m.path, m.title, m.heading, m.url,
                        m.start_line, m.end_line, m.content,
                        bm25(docs_fts, 4.0, 6.0, 2.0, 1.0, 0.5, 0.5) AS rank
                    FROM docs_fts
                    JOIN docs_meta m ON docs_fts.rowid = m.id
                    WHERE docs_fts MATCH ? AND m.source_id IN ({placeholders})
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (expr, *copy_sources, limit * 2),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

            for r in rows:
                # Prioritize 05-ux-writing in knowledge
                if r["layer"] == "knowledge" and "05-ux-writing" not in r["path"] and "writing" not in r["path"].lower():
                    score = float(r["rank"]) + 1.0
                elif r["layer"] == "knowledge":
                    score = float(r["rank"]) - 1.5
                else:
                    score = float(r["rank"])
                hits.append(
                    SearchHit(
                        layer=r["layer"],
                        source_id=r["source_id"],
                        path=r["path"],
                        line=_find_best_line(r["content"], int(r["start_line"]), terms),
                        end_line=int(r["end_line"]),
                        title=r["title"],
                        heading=r["heading"],
                        url=r["url"],
                        score=score,
                        snippet=_make_snippet(r["content"], terms),
                    )
                )
            if hits:
                break
    finally:
        conn.close()

    hits.sort(key=lambda h: (h.score, h.line))
    return {
        "topic": topic,
        "results": [h.to_dict() for h in hits[:limit]],
    }


def get_status(paths: RepoPaths) -> dict[str, Any]:
    """Collect status of all sources, knowledge files, API manifests, tokens, and index DB."""
    sources_info: list[dict[str, Any]] = []
    for adapter in discover_sources(paths):
        committed = SourceManifest.from_json(adapter.committed_manifest) if adapter.committed_manifest.is_file() else None
        corpus = SourceManifest.from_json(adapter.corpus_manifest) if adapter.corpus_manifest.is_file() else None
        active = corpus or committed
        live_pages = len(list(adapter.pages_dir.rglob("*.md"))) if adapter.pages_dir.is_dir() else 0
        sources_info.append(
            {
                "source_id": adapter.source_id,
                "has_adapter": adapter.has_adapter,
                "synced_locally": adapter.pages_dir.is_dir() and live_pages > 0,
                "live_pages": live_pages,
                "manifest_pages": active.page_count if active else 0,
                "status": active.status if active else ("ready" if adapter.has_adapter else "missing"),
                "fetched_at": active.fetched_at if active else "",
                "upstream_version": active.upstream_version if active else "",
                "has_committed_manifest": committed is not None,
            }
        )

    knowledge_files = sorted(
        p.relative_to(paths.root).as_posix() for p in paths.knowledge_dir.rglob("*.md")
    ) if paths.knowledge_dir.is_dir() else []

    api_files = sorted(
        p.relative_to(paths.root).as_posix() for p in paths.api_manifests_dir.glob("*.json")
    ) if paths.api_manifests_dir.is_dir() else []

    token_files = sorted(
        p.relative_to(paths.root).as_posix() for p in paths.token_manifests_dir.glob("*.json")
    ) if paths.token_manifests_dir.is_dir() else []

    index_meta: dict[str, str] = {}
    if paths.index_db.is_file():
        conn = sqlite3.connect(paths.index_db)
        try:
            for k, v in conn.execute("SELECT key, value FROM index_meta").fetchall():
                index_meta[str(k)] = str(v)
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    return {
        "root": str(paths.root),
        "sources": sources_info,
        "knowledge_count": len(knowledge_files),
        "knowledge_files": knowledge_files,
        "api_manifests": api_files,
        "token_manifests": token_files,
        "index_exists": paths.index_db.is_file(),
        "index_meta": index_meta,
    }


def run_doctor(paths: RepoPaths) -> dict[str, Any]:
    """Verify corpus integrity, line lengths <= 4000, internal links, frontmatter, and FTS5 health."""
    errors: list[str] = []
    warnings: list[str] = []
    checked_files = 0
    broken_links: list[dict[str, Any]] = []
    long_lines: list[dict[str, Any]] = []

    # 1. Check .gitignore excludes .corpus/
    gi = paths.root / ".gitignore"
    if not gi.is_file() or ".corpus/" not in gi.read_text(encoding="utf-8", errors="replace"):
        errors.append(".gitignore missing or does not exclude .corpus/")

    # 2. Check skills/expressive-ui/SKILL.md YAML frontmatter
    skill_md = paths.skills_dir / "expressive-ui" / "SKILL.md"
    if not skill_md.is_file():
        warnings.append("skills/expressive-ui/SKILL.md does not exist yet")
    else:
        skill_text = skill_md.read_text(encoding="utf-8", errors="replace")
        if not skill_text.startswith("---"):
            errors.append("skills/expressive-ui/SKILL.md missing YAML frontmatter")
        else:
            fm_end = skill_text.find("\n---", 3)
            fm_block = skill_text[3:fm_end] if fm_end != -1 else ""
            if "name:" not in fm_block or "description:" not in fm_block:
                errors.append("skills/expressive-ui/SKILL.md frontmatter missing 'name' or 'description'")

    # 3. Check markdown files in knowledge/ and .corpus/*/pages/
    md_targets: list[tuple[str, Path]] = []
    if paths.knowledge_dir.is_dir():
        for p in sorted(paths.knowledge_dir.rglob("*.md")):
            md_targets.append(("knowledge", p))
    if paths.corpus_dir.is_dir():
        for sdir in sorted(paths.corpus_dir.iterdir()):
            if sdir.is_dir() and not sdir.name.startswith((".", "_")):
                pdir = sdir / "pages"
                if not pdir.is_dir():
                    errors.append(f".corpus/{sdir.name} is missing pages/ directory (empty mirror)")
                    continue
                md_pages = sorted(pdir.rglob("*.md"))
                non_index_pages = [p for p in md_pages if p.name != "INDEX.md"]
                if not non_index_pages:
                    errors.append(f".corpus/{sdir.name}/pages/ has 0 mirrored pages (empty mirror)")
                if not (pdir / "INDEX.md").is_file():
                    warnings.append(f".corpus/{sdir.name}/pages/INDEX.md is missing")
                for p in md_pages:
                    md_targets.append(("mirror", p))

    for kind, md_path in md_targets:
        checked_files += 1
        rel = md_path.relative_to(paths.root).as_posix()
        text = md_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        if kind == "mirror" and md_path.name != "INDEX.md":
            meta, _ = parse_page_frontmatter(text)
            if meta is None or (not meta.url and not meta.title):
                warnings.append(f"{rel}: missing standard frontmatter metadata")

        in_fence = False
        fence_char = ""
        for idx, line in enumerate(lines, start=1):
            if len(line) > MAX_LINE_LENGTH:
                long_lines.append({"path": rel, "line": idx, "length": len(line)})
            fm = _FENCE_RE.match(line)
            if fm:
                marker = fm.group(1)
                if not in_fence:
                    in_fence = True
                    fence_char = marker[0]
                elif marker[0] == fence_char:
                    in_fence = False
                    fence_char = ""
                continue
            if kind == "knowledge" and not in_fence:
                for m in _MD_LINK_RE.finditer(line):
                    target = m.group(1).strip()
                    if not target or target.startswith(("http://", "https://", "mailto:", "#", "file://")):
                        continue
                    target_no_anchor = target.split("#", 1)[0].strip()
                    if not target_no_anchor:
                        continue
                    resolved = (md_path.parent / target_no_anchor).resolve()
                    if not resolved.exists():
                        broken_links.append({"path": rel, "line": idx, "target": target})

    if long_lines:
        errors.append(f"{len(long_lines)} line(s) exceed {MAX_LINE_LENGTH} chars")
    if broken_links:
        errors.append(f"{len(broken_links)} broken relative link(s) in knowledge/")

    # 4. Audit `knowledge/` citations live against `manifests/api/` and `manifests/tokens/`
    from rtx.diff import analyze_impact

    audit = analyze_impact(paths)
    for adv in audit.live_advisories[:30]:
        warnings.append(f"{adv['knowledge_file']}:{adv['line']} [{adv['type']}] {adv['detail']}")

    # 5. Check FTS5 index health
    fts_ok = False
    if not paths.index_db.is_file():
        build_index(paths)
    try:
        conn = sqlite3.connect(paths.index_db)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                errors.append(f"SQLite integrity_check failed: {integrity}")
            else:
                conn.execute("SELECT count(*) FROM docs_fts").fetchone()
                conn.execute("SELECT count(*) FROM api_fts").fetchone()
                conn.execute("SELECT count(*) FROM tokens_fts").fetchone()
                fts_ok = True
        finally:
            conn.close()
    except sqlite3.Error as exc:
        errors.append(f"SQLite FTS5 error: {exc}")

    return {
        "ok": len(errors) == 0,
        "checked_files": checked_files,
        "fts_ok": fts_ok,
        "errors": errors,
        "warnings": warnings,
        "long_lines": long_lines[:20],
        "broken_links": broken_links[:20],
        "citation_counts": audit.citation_counts,
        "live_advisories": audit.live_advisories[:30],
    }
