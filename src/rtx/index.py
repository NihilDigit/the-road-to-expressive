"""SQLite FTS5 + BM25 indexer for knowledge guides, `.corpus/` mirrors, API manifests, and tokens."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rtx.config import RepoPaths, get_paths
from rtx.models import parse_page_frontmatter, utc_now_iso

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


@dataclass(slots=True)
class IndexStats:
    """Summary counts produced by `build_index`."""

    db_path: Path
    doc_chunks: int
    knowledge_files: int
    mirror_files: int
    api_symbols: int
    api_versions: int
    design_tokens: int
    built_at: str


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;

        DROP TABLE IF EXISTS docs_fts;
        DROP TABLE IF EXISTS docs_meta;
        DROP TABLE IF EXISTS api_fts;
        DROP TABLE IF EXISTS api_symbols;
        DROP TABLE IF EXISTS api_versions;
        DROP TABLE IF EXISTS tokens_fts;
        DROP TABLE IF EXISTS design_tokens;
        DROP TABLE IF EXISTS index_meta;

        CREATE TABLE docs_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            layer TEXT NOT NULL,
            source_id TEXT NOT NULL,
            path TEXT NOT NULL,
            title TEXT NOT NULL,
            section TEXT NOT NULL,
            heading TEXT NOT NULL,
            url TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            content TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE docs_fts USING fts5(
            title,
            heading,
            section,
            content,
            source_id,
            layer,
            content='docs_meta',
            content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TABLE api_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            package TEXT NOT NULL,
            kind TEXT NOT NULL,
            signature TEXT NOT NULL,
            annotations TEXT NOT NULL,
            artifact TEXT NOT NULL,
            version TEXT NOT NULL,
            targets TEXT NOT NULL,
            androidx_signature TEXT NOT NULL,
            cmp_signature TEXT NOT NULL,
            parity_status TEXT NOT NULL,
            doc TEXT NOT NULL,
            source_file TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE api_fts USING fts5(
            name,
            package,
            signature,
            annotations,
            artifact,
            targets,
            parity_status,
            doc,
            content='api_symbols',
            content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TABLE api_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coordinate TEXT NOT NULL,
            group_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            ecosystem TEXT NOT NULL,
            stable TEXT NOT NULL,
            rc TEXT NOT NULL,
            beta TEXT NOT NULL,
            alpha TEXT NOT NULL,
            latest TEXT NOT NULL,
            source_file TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );

        CREATE TABLE design_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            value TEXT NOT NULL,
            role TEXT NOT NULL,
            compose_token TEXT NOT NULL,
            spec_version TEXT NOT NULL,
            notes TEXT NOT NULL,
            source_file TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE tokens_fts USING fts5(
            name,
            category,
            value,
            role,
            compose_token,
            spec_version,
            notes,
            content='design_tokens',
            content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TABLE index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def _split_markdown_sections(
    text: str,
    *,
    default_title: str,
    default_section: str,
    body_start_line: int,
) -> list[tuple[str, int, int, str]]:
    """Split markdown into `(heading, start_line, end_line, content)` chunks."""
    lines = text.splitlines()
    if not lines:
        return []

    start_idx = max(0, body_start_line - 1)
    chunks: list[tuple[str, int, int, str]] = []
    current_heading = default_title or default_section or "Overview"
    current_start = start_idx + 1
    buf: list[str] = []
    in_fence = False
    fence_char = ""

    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        line_no = idx + 1
        fence_match = _FENCE_RE.match(line.lstrip())
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
            elif marker[0] == fence_char:
                in_fence = False
                fence_char = ""
            buf.append(line)
            continue

        heading_match = None if in_fence else _HEADING_RE.match(line)
        if heading_match:
            if any(item.strip() for item in buf):
                chunks.append((current_heading, current_start, line_no - 1, "\n".join(buf).strip()))
            current_heading = heading_match.group(2).strip()
            current_start = line_no
            buf = [line]
        else:
            buf.append(line)

    if any(item.strip() for item in buf):
        chunks.append((current_heading, current_start, len(lines), "\n".join(buf).strip()))

    if not chunks:
        full_body = "\n".join(lines[start_idx:]).strip()
        if full_body:
            chunks.append((current_heading, start_idx + 1, len(lines), full_body))
    return chunks


def _infer_title(text: str, body_start_line: int, fallback: str) -> str:
    lines = text.splitlines()
    for line in lines[max(0, body_start_line - 1) :]:
        m = _HEADING_RE.match(line)
        if m:
            return m.group(2).strip()
    return fallback


def _index_markdown_file(
    conn: sqlite3.Connection,
    *,
    file_path: Path,
    rel_path: str,
    layer: str,
    default_source_id: str,
) -> int:
    text = file_path.read_text(encoding="utf-8", errors="replace")
    meta, body_start = parse_page_frontmatter(text)
    source_id = (meta.source_id if meta and meta.source_id else default_source_id)
    title = (meta.title if meta and meta.title else _infer_title(text, body_start, file_path.stem))
    section = (meta.section if meta and meta.section else file_path.parent.name)
    url = (meta.url if meta else "")

    chunks = _split_markdown_sections(
        text,
        default_title=title,
        default_section=section,
        body_start_line=body_start,
    )
    rows = [
        (layer, source_id, rel_path, title, section, heading, url, start_line, end_line, content)
        for heading, start_line, end_line, content in chunks
    ]
    if rows:
        conn.executemany(
            """
            INSERT INTO docs_meta (
                layer, source_id, path, title, section, heading, url, start_line, end_line, content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and str(v) != ""]
    return [str(value)]


def _extract_api_records(data: Any, source_file: str) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """Flexibly extract API symbols and version pins from `manifests/api/*.json`."""
    symbols: list[tuple[Any, ...]] = []
    versions: list[tuple[Any, ...]] = []

    def add_symbol(obj: dict[str, Any], default_pkg: str = "", default_art: str = "", default_ver: str = "") -> None:
        name = str(obj.get("name") or obj.get("symbol") or obj.get("composable") or "")
        sig = str(obj.get("signature") or obj.get("androidx_signature") or obj.get("cmp_signature") or "")
        if not name and not sig:
            return
        if not name:
            name = sig.split("(")[0].split()[-1]
        pkg = str(obj.get("package") or default_pkg or "")
        kind = str(obj.get("kind") or ("composable" if "Composable" in str(obj.get("annotations", "")) else "symbol"))
        annotations = _as_str_list(obj.get("annotations") or obj.get("opt_in") or obj.get("optIn"))
        artifact = str(obj.get("artifact") or obj.get("coordinate") or default_art or "")
        version = str(obj.get("version") or default_ver or "")
        targets = _as_str_list(obj.get("targets") or obj.get("platforms") or ["common"])
        androidx_sig = str(obj.get("androidx_signature") or obj.get("androidxSignature") or "")
        cmp_sig = str(obj.get("cmp_signature") or obj.get("cmpSignature") or obj.get("jetbrains_signature") or "")
        parity = str(obj.get("parity_status") or obj.get("parity") or obj.get("status") or "")
        doc = str(obj.get("doc") or obj.get("notes") or obj.get("description") or "")
        symbols.append(
            (
                name,
                pkg,
                kind,
                sig or androidx_sig or cmp_sig,
                json.dumps(annotations, ensure_ascii=False),
                artifact,
                version,
                json.dumps(targets, ensure_ascii=False),
                androidx_sig,
                cmp_sig,
                parity,
                doc,
                source_file,
                json.dumps(obj, ensure_ascii=False),
            )
        )

    def add_version(coord: str, obj: dict[str, Any], ecosystem: str = "") -> None:
        group_id = str(obj.get("group_id") or obj.get("group") or (coord.split(":")[0] if ":" in coord else ""))
        artifact_id = str(obj.get("artifact_id") or obj.get("artifact") or (coord.split(":")[1] if ":" in coord else coord))
        eco = str(obj.get("ecosystem") or ecosystem or ("jetbrains" if group_id.startswith("org.jetbrains") else "androidx"))
        stable = str(obj.get("stable") or "")
        rc = str(obj.get("rc") or "")
        beta = str(obj.get("beta") or "")
        alpha = str(obj.get("alpha") or "")
        latest = str(obj.get("latest") or alpha or beta or rc or stable or obj.get("version") or "")
        versions.append(
            (
                coord,
                group_id,
                artifact_id,
                eco,
                stable,
                rc,
                beta,
                alpha,
                latest,
                source_file,
                json.dumps(obj, ensure_ascii=False),
            )
        )

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                add_symbol(item)
        return symbols, versions

    if not isinstance(data, dict):
        return symbols, versions

    for key in ("symbols", "apis", "surface", "entries", "declarations"):
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    add_symbol(item)
        elif isinstance(items, dict):
            for sym_name, sym_obj in items.items():
                if isinstance(sym_obj, dict):
                    merged = {"name": sym_name, **sym_obj}
                    add_symbol(merged)

    # Support grouped packages/components dicts
    for key in ("packages", "components"):
        group_map = data.get(key)
        if isinstance(group_map, dict):
            for g_name, g_val in group_map.items():
                if isinstance(g_val, list):
                    for item in g_val:
                        if isinstance(item, dict):
                            add_symbol(item, default_pkg=g_name if "." in g_name else "")
                elif isinstance(g_val, dict):
                    if "symbols" in g_val and isinstance(g_val["symbols"], list):
                        for item in g_val["symbols"]:
                            if isinstance(item, dict):
                                add_symbol(item, default_pkg=g_name if "." in g_name else "")
                    else:
                        add_symbol({"name": g_name, **g_val})

    # Support version catalogs (`artifacts`, `versions`, `androidx`, `jetbrains`, `compose_multiplatform`)
    for key in ("artifacts", "versions"):
        vmap = data.get(key)
        if isinstance(vmap, dict):
            for coord, vobj in vmap.items():
                if isinstance(vobj, dict):
                    add_version(coord, vobj)
                elif isinstance(vobj, str):
                    add_version(coord, {"latest": vobj})
        elif isinstance(vmap, list):
            for vobj in vmap:
                if isinstance(vobj, dict):
                    coord = str(vobj.get("coordinate") or f"{vobj.get('group_id', '')}:{vobj.get('artifact_id', '')}".strip(":"))
                    if coord:
                        add_version(coord, vobj)

    for eco_key in ("androidx", "jetbrains", "compose_multiplatform"):
        emap = data.get(eco_key)
        if isinstance(emap, dict):
            for coord, vobj in emap.items():
                if isinstance(vobj, dict):
                    add_version(coord, vobj, ecosystem=eco_key)
                elif isinstance(vobj, str):
                    add_version(coord, {"latest": vobj}, ecosystem=eco_key)

    return symbols, versions


def _is_leaf_token_dict(node: dict[str, Any]) -> bool:
    if not node:
        return False
    if any(
        k in node
        for k in (
            "value",
            "default",
            "compose_token",
            "compose",
            "damping",
            "dampingRatio",
            "stiffness",
            "fontSize",
            "size",
            "cornerRadius",
            "Light",
            "Dark",
        )
    ):
        return True
    return all(not isinstance(v, (dict, list)) for v in node.values())


def _extract_token_records(data: Any, source_file: str) -> list[tuple[Any, ...]]:
    """Flexibly extract design tokens from `manifests/tokens/*.json`."""
    tokens: list[tuple[Any, ...]] = []
    seen: set[tuple[str, str]] = set()
    skip_top = {
        "schema_version",
        "source",
        "source_id",
        "generated_at",
        "upstream_version",
        "carbon_version",
        "dsdb_version",
        "dsdb_revision_create_time",
        "description",
        "hct_spec_notes",
    }

    def add_token(obj: dict[str, Any], default_cat: str = "", fallback_name: str = "") -> None:
        name = str(obj.get("name") or obj.get("token") or obj.get("key") or fallback_name or "")
        value = str(obj.get("value") or obj.get("default") or obj.get("hex") or obj.get("spec") or "")
        cat = str(obj.get("category") or default_cat or "")
        role = str(obj.get("role") or obj.get("group") or "")
        compose_tok = str(obj.get("compose_token") or obj.get("compose") or obj.get("api") or "")
        spec_ver = str(obj.get("spec_version") or obj.get("spec") or obj.get("version") or "")
        notes = str(obj.get("notes") or obj.get("description") or "")

        if not value:
            extras = {
                k: v
                for k, v in obj.items()
                if k
                not in {
                    "name",
                    "token",
                    "key",
                    "category",
                    "role",
                    "group",
                    "compose_token",
                    "compose",
                    "api",
                    "spec_version",
                    "spec",
                    "version",
                    "notes",
                    "description",
                }
                and v not in ("", None)
            }
            if extras:
                value = ", ".join(f"{k}={v}" for k, v in extras.items())

        if not name and not value:
            return
        dedup_key = (name, cat)
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        tokens.append(
            (name, cat, value, role, compose_tok, spec_ver, notes, source_file, json.dumps(obj, ensure_ascii=False))
        )

    def walk(node: Any, category: str = "", key_name: str = "") -> None:
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    add_token(item, default_cat=category)
            return
        if not isinstance(node, dict):
            return
        if category and _is_leaf_token_dict(node):
            add_token(node, default_cat=category, fallback_name=key_name)
            return
        for k, v in node.items():
            if not category and k in skip_top:
                continue
            if isinstance(v, list):
                next_cat = f"{category}.{k}" if category and k != "tokens" else (category or k)
                walk(v, category=next_cat)
            elif isinstance(v, dict):
                if _is_leaf_token_dict(v):
                    add_token(v, default_cat=category or k, fallback_name=k)
                else:
                    next_cat = f"{category}.{k}" if category else k
                    walk(v, category=next_cat, key_name=k)
            elif v is not None and category:
                add_token({"name": k, "value": str(v)}, default_cat=category)

    if isinstance(data, dict) and isinstance(data.get("tokens"), list):
        walk(data["tokens"], category="")
    walk(data)
    return tokens


def build_index(paths: RepoPaths | None = None) -> IndexStats:
    """Build `.corpus/index.db` from `knowledge/`, `.corpus/*/pages/`, `manifests/api/`, and `manifests/tokens/`."""
    repo = paths or get_paths()
    repo.corpus_dir.mkdir(parents=True, exist_ok=True)
    db_path = repo.index_db
    tmp_db = db_path.with_suffix(".db.tmp")
    if tmp_db.exists():
        tmp_db.unlink()

    conn = sqlite3.connect(tmp_db)
    try:
        _create_schema(conn)

        doc_chunks = 0
        knowledge_files = 0
        mirror_files = 0

        if repo.knowledge_dir.is_dir():
            for md_file in sorted(repo.knowledge_dir.rglob("*.md")):
                rel = md_file.relative_to(repo.root).as_posix()
                knowledge_files += 1
                doc_chunks += _index_markdown_file(
                    conn,
                    file_path=md_file,
                    rel_path=rel,
                    layer="knowledge",
                    default_source_id="knowledge",
                )

        if repo.corpus_dir.is_dir():
            for source_dir in sorted(repo.corpus_dir.iterdir()):
                if not source_dir.is_dir() or source_dir.name.startswith((".", "_")):
                    continue
                pages_dir = source_dir / "pages"
                if not pages_dir.is_dir():
                    continue
                for md_file in sorted(pages_dir.rglob("*.md")):
                    rel = md_file.relative_to(repo.root).as_posix()
                    mirror_files += 1
                    doc_chunks += _index_markdown_file(
                        conn,
                        file_path=md_file,
                        rel_path=rel,
                        layer="mirror",
                        default_source_id=source_dir.name,
                    )

        api_symbol_count = 0
        api_version_count = 0
        if repo.api_manifests_dir.is_dir():
            for json_file in sorted(repo.api_manifests_dir.glob("*.json")):
                rel = json_file.relative_to(repo.root).as_posix()
                try:
                    payload = json.loads(json_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                symbols, versions = _extract_api_records(payload, rel)
                if symbols:
                    conn.executemany(
                        """
                        INSERT INTO api_symbols (
                            name, package, kind, signature, annotations, artifact, version,
                            targets, androidx_signature, cmp_signature, parity_status, doc,
                            source_file, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        symbols,
                    )
                    api_symbol_count += len(symbols)
                if versions:
                    conn.executemany(
                        """
                        INSERT INTO api_versions (
                            coordinate, group_id, artifact_id, ecosystem, stable, rc, beta,
                            alpha, latest, source_file, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        versions,
                    )
                    api_version_count += len(versions)

        token_count = 0
        if repo.token_manifests_dir.is_dir():
            for json_file in sorted(repo.token_manifests_dir.glob("*.json")):
                rel = json_file.relative_to(repo.root).as_posix()
                try:
                    payload = json.loads(json_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                tokens = _extract_token_records(payload, rel)
                if tokens:
                    conn.executemany(
                        """
                        INSERT INTO design_tokens (
                            name, category, value, role, compose_token, spec_version, notes, source_file, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        tokens,
                    )
                    token_count += len(tokens)

        # Populate external-content FTS5 tables
        conn.execute("INSERT INTO docs_fts(docs_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO api_fts(api_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO tokens_fts(tokens_fts) VALUES('rebuild')")

        built_at = utc_now_iso()
        conn.executemany(
            "INSERT INTO index_meta (key, value) VALUES (?, ?)",
            [
                ("built_at", built_at),
                ("doc_chunks", str(doc_chunks)),
                ("knowledge_files", str(knowledge_files)),
                ("mirror_files", str(mirror_files)),
                ("api_symbols", str(api_symbol_count)),
                ("api_versions", str(api_version_count)),
                ("design_tokens", str(token_count)),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    tmp_db.replace(db_path)
    return IndexStats(
        db_path=db_path,
        doc_chunks=doc_chunks,
        knowledge_files=knowledge_files,
        mirror_files=mirror_files,
        api_symbols=api_symbol_count,
        api_versions=api_version_count,
        design_tokens=token_count,
        built_at=built_at,
    )
