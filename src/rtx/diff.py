"""Incremental snapshot diffing, changelog generation, and reverse-citation impact analysis."""

from __future__ import annotations

import difflib
import gzip
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rtx.config import RepoPaths, get_paths
from rtx.index import _extract_api_records, _extract_token_records, _split_markdown_sections
from rtx.models import parse_page_frontmatter, sha256_text, utc_now_iso

_CORPUS_CITE_RE = re.compile(r"\.corpus/([A-Za-z0-9_.-]+/pages/[^\s)\]`\"'>]+?\.md)(?:#[^\s)\]`\"'>]+)?")


def _expand_brace_paths(rel_path: str) -> list[str]:
    if "{" not in rel_path or "}" not in rel_path:
        return [rel_path]
    m = re.match(r"^(.*)\{([^{}]+)\}(.*)$", rel_path)
    if not m:
        return [rel_path]
    prefix, body, suffix = m.group(1), m.group(2), m.group(3)
    return [f"{prefix}{item.strip()}{suffix}" for item in body.split(",") if item.strip()]
_BACKTICK_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def snapshot_path(paths: RepoPaths) -> Path:
    return paths.corpus_dir / "snapshot.json.gz"


def sync_diff_path(paths: RepoPaths) -> Path:
    return paths.corpus_dir / "sync-diff.json"


def capture_snapshot(paths: RepoPaths) -> dict[str, Any]:
    """Capture current state of `.corpus/*/pages/`, `manifests/api/`, and `manifests/tokens/`."""
    pages: dict[str, dict[str, Any]] = {}
    if paths.corpus_dir.is_dir():
        for source_dir in sorted(paths.corpus_dir.iterdir()):
            if not source_dir.is_dir() or source_dir.name.startswith((".", "_")):
                continue
            pages_dir = source_dir / "pages"
            if not pages_dir.is_dir():
                continue
            for md_file in sorted(pages_dir.rglob("*.md")):
                if md_file.name == "INDEX.md":
                    continue
                rel = md_file.relative_to(paths.root).as_posix()
                text = md_file.read_text(encoding="utf-8", errors="replace")
                meta, body_start = parse_page_frontmatter(text)
                digest = meta.sha256 if (meta and meta.sha256) else sha256_text(text)
                title = meta.title if (meta and meta.title) else md_file.stem
                section = meta.section if (meta and meta.section) else md_file.parent.name
                url = meta.url if meta else ""
                chunks = _split_markdown_sections(
                    text,
                    default_title=title,
                    default_section=section,
                    body_start_line=body_start,
                )
                sec_map: dict[str, str] = {}
                for heading, _s, _e, content in chunks:
                    key = heading
                    idx = 2
                    while key in sec_map:
                        key = f"{heading} ({idx})"
                        idx += 1
                    sec_map[key] = content
                pages[rel] = {
                    "source_id": source_dir.name,
                    "title": title,
                    "url": url,
                    "sha256": digest,
                    "sections": sec_map,
                }

    api_symbols: dict[str, dict[str, Any]] = {}
    api_versions: dict[str, dict[str, Any]] = {}
    if paths.api_manifests_dir.is_dir():
        for json_file in sorted(paths.api_manifests_dir.glob("*.json")):
            rel = json_file.relative_to(paths.root).as_posix()
            try:
                payload = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            syms, vers = _extract_api_records(payload, rel)
            for row in syms:
                name, pkg, kind, sig, anns_json, art, ver, targets_json, a_sig, c_sig, parity, _doc, _sf, _raw = row
                key = f"{pkg}.{name}" if pkg else name
                if art:
                    key = f"{key}@{art}"
                api_symbols[key] = {
                    "name": name,
                    "package": pkg,
                    "kind": kind,
                    "signature": sig,
                    "annotations": json.loads(anns_json),
                    "artifact": art,
                    "version": ver,
                    "targets": json.loads(targets_json),
                    "androidx_signature": a_sig,
                    "cmp_signature": c_sig,
                    "parity_status": parity,
                }
            for row in vers:
                coord, _g, _a, eco, stable, rc, beta, alpha, latest, _sf, _raw = row
                api_versions[coord] = {
                    "coordinate": coord,
                    "ecosystem": eco,
                    "stable": stable,
                    "rc": rc,
                    "beta": beta,
                    "alpha": alpha,
                    "latest": latest,
                }

    tokens: dict[str, dict[str, Any]] = {}
    if paths.token_manifests_dir.is_dir():
        for json_file in sorted(paths.token_manifests_dir.glob("*.json")):
            rel = json_file.relative_to(paths.root).as_posix()
            try:
                payload = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            for row in _extract_token_records(payload, rel):
                name, cat, value, role, compose_tok, spec_ver, _notes, _sf, _raw = row
                key = f"{cat}:{name}"
                tokens[key] = {
                    "name": name,
                    "category": cat,
                    "value": value,
                    "role": role,
                    "compose_token": compose_tok,
                    "spec_version": spec_ver,
                }

    return {
        "schema_version": 1,
        "captured_at": utc_now_iso(),
        "pages": pages,
        "api_symbols": api_symbols,
        "api_versions": api_versions,
        "tokens": tokens,
    }


def save_snapshot(paths: RepoPaths, snapshot: dict[str, Any]) -> Path:
    path = snapshot_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".gz.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False)
    tmp.replace(path)
    return path


def load_snapshot(paths: RepoPaths) -> dict[str, Any] | None:
    path = snapshot_path(paths)
    if not path.is_file():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _section_diffs(old_sections: dict[str, str], new_sections: dict[str, str]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    all_headings = list(dict.fromkeys([*old_sections.keys(), *new_sections.keys()]))
    for heading in all_headings:
        old_text = old_sections.get(heading)
        new_text = new_sections.get(heading)
        if old_text == new_text:
            continue
        if old_text is None:
            preview = (new_text or "").splitlines()[:8]
            changes.append({"heading": heading, "status": "added", "diff_lines": [f"+ {ln}" for ln in preview]})
        elif new_text is None:
            preview = old_text.splitlines()[:8]
            changes.append({"heading": heading, "status": "removed", "diff_lines": [f"- {ln}" for ln in preview]})
        else:
            diff_lines = list(
                difflib.unified_diff(
                    old_text.splitlines(),
                    new_text.splitlines(),
                    fromfile="before",
                    tofile="after",
                    n=1,
                    lineterm="",
                )
            )
            # Strip unified diff header lines (--- / +++)
            body_lines = [ln for ln in diff_lines[2:] if ln][:30]
            changes.append({"heading": heading, "status": "modified", "diff_lines": body_lines})
        if len(changes) >= 12:
            break
    return changes


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Compute structured page, API surface, version, and token diffs between two snapshots."""
    old_pages: dict[str, Any] = old.get("pages", {})
    new_pages: dict[str, Any] = new.get("pages", {})

    added_pages: list[dict[str, Any]] = []
    removed_pages: list[dict[str, Any]] = []
    modified_pages: list[dict[str, Any]] = []

    for rel in sorted(new_pages.keys() - old_pages.keys()):
        p = new_pages[rel]
        added_pages.append({"source_id": p["source_id"], "path": rel, "title": p["title"], "url": p["url"]})

    for rel in sorted(old_pages.keys() - new_pages.keys()):
        p = old_pages[rel]
        removed_pages.append({"source_id": p["source_id"], "path": rel, "title": p["title"], "url": p["url"]})

    for rel in sorted(old_pages.keys() & new_pages.keys()):
        op = old_pages[rel]
        np = new_pages[rel]
        if op.get("sha256") == np.get("sha256") and op.get("sections") == np.get("sections"):
            continue
        sec_changes = _section_diffs(op.get("sections", {}), np.get("sections", {}))
        if sec_changes or op.get("sha256") != np.get("sha256"):
            modified_pages.append(
                {
                    "source_id": np["source_id"],
                    "path": rel,
                    "title": np["title"],
                    "url": np["url"],
                    "changed_sections": sec_changes,
                }
            )

    # API versions diff
    old_vers: dict[str, Any] = old.get("api_versions", {})
    new_vers: dict[str, Any] = new.get("api_versions", {})
    version_bumps: list[dict[str, Any]] = []
    for coord in sorted(old_vers.keys() | new_vers.keys()):
        ov = old_vers.get(coord, {})
        nv = new_vers.get(coord, {})
        if (
            ov.get("latest") != nv.get("latest")
            or ov.get("alpha") != nv.get("alpha")
            or ov.get("beta") != nv.get("beta")
            or ov.get("rc") != nv.get("rc")
            or ov.get("stable") != nv.get("stable")
        ):
            version_bumps.append(
                {
                    "coordinate": coord,
                    "ecosystem": nv.get("ecosystem") or ov.get("ecosystem", ""),
                    "old_latest": ov.get("latest", ""),
                    "new_latest": nv.get("latest", ""),
                    "old_alpha": ov.get("alpha", ""),
                    "new_alpha": nv.get("alpha", ""),
                    "old_stable": ov.get("stable", ""),
                    "new_stable": nv.get("stable", ""),
                }
            )

    # API symbols diff
    old_syms: dict[str, Any] = old.get("api_symbols", {})
    new_syms: dict[str, Any] = new.get("api_symbols", {})
    added_symbols: list[dict[str, Any]] = []
    removed_symbols: list[dict[str, Any]] = []
    graduated_opt_ins: list[dict[str, Any]] = []
    signature_changes: list[dict[str, Any]] = []

    for key in sorted(new_syms.keys() - old_syms.keys()):
        s = new_syms[key]
        added_symbols.append(
            {
                "name": s["name"],
                "package": s["package"],
                "artifact": s["artifact"],
                "annotations": s["annotations"],
                "signature": s["signature"],
                "parity_status": s["parity_status"],
            }
        )

    for key in sorted(old_syms.keys() - new_syms.keys()):
        s = old_syms[key]
        removed_symbols.append({"name": s["name"], "package": s["package"], "artifact": s["artifact"]})

    for key in sorted(old_syms.keys() & new_syms.keys()):
        osym = old_syms[key]
        nsym = new_syms[key]
        old_ann = set(osym.get("annotations", []))
        new_ann = set(nsym.get("annotations", []))
        if old_ann != new_ann:
            graduated_opt_ins.append(
                {
                    "name": nsym["name"],
                    "package": nsym["package"],
                    "removed_annotations": sorted(old_ann - new_ann),
                    "added_annotations": sorted(new_ann - old_ann),
                }
            )
        if (
            osym.get("signature") != nsym.get("signature")
            or osym.get("androidx_signature") != nsym.get("androidx_signature")
            or osym.get("cmp_signature") != nsym.get("cmp_signature")
            or osym.get("parity_status") != nsym.get("parity_status")
        ):
            signature_changes.append(
                {
                    "name": nsym["name"],
                    "package": nsym["package"],
                    "old_signature": osym.get("signature", ""),
                    "new_signature": nsym.get("signature", ""),
                    "old_parity": osym.get("parity_status", ""),
                    "new_parity": nsym.get("parity_status", ""),
                }
            )

    # Tokens diff
    old_toks: dict[str, Any] = old.get("tokens", {})
    new_toks: dict[str, Any] = new.get("tokens", {})
    added_tokens: list[dict[str, Any]] = []
    removed_tokens: list[dict[str, Any]] = []
    changed_tokens: list[dict[str, Any]] = []

    for key in sorted(new_toks.keys() - old_toks.keys()):
        t = new_toks[key]
        added_tokens.append(
            {"name": t["name"], "category": t["category"], "value": t["value"], "compose_token": t["compose_token"]}
        )

    for key in sorted(old_toks.keys() - new_toks.keys()):
        t = old_toks[key]
        removed_tokens.append({"name": t["name"], "category": t["category"], "old_value": t["value"]})

    for key in sorted(old_toks.keys() & new_toks.keys()):
        ot = old_toks[key]
        nt = new_toks[key]
        if ot.get("value") != nt.get("value") or ot.get("compose_token") != nt.get("compose_token"):
            changed_tokens.append(
                {
                    "name": nt["name"],
                    "category": nt["category"],
                    "old_value": ot.get("value", ""),
                    "new_value": nt.get("value", ""),
                    "old_compose_token": ot.get("compose_token", ""),
                    "new_compose_token": nt.get("compose_token", ""),
                }
            )

    has_changes = any(
        [
            added_pages,
            removed_pages,
            modified_pages,
            version_bumps,
            added_symbols,
            removed_symbols,
            graduated_opt_ins,
            signature_changes,
            added_tokens,
            removed_tokens,
            changed_tokens,
        ]
    )

    return {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "baseline_at": old.get("captured_at", ""),
        "has_changes": has_changes,
        "summary": {
            "pages_added": len(added_pages),
            "pages_removed": len(removed_pages),
            "pages_modified": len(modified_pages),
            "api_version_bumps": len(version_bumps),
            "api_symbols_added": len(added_symbols),
            "api_symbols_removed": len(removed_symbols),
            "api_opt_in_changes": len(graduated_opt_ins),
            "api_signature_changes": len(signature_changes),
            "tokens_added": len(added_tokens),
            "tokens_removed": len(removed_tokens),
            "tokens_changed": len(changed_tokens),
        },
        "pages": {
            "added": added_pages,
            "removed": removed_pages,
            "modified": modified_pages,
        },
        "api": {
            "version_bumps": version_bumps,
            "added_symbols": added_symbols,
            "removed_symbols": removed_symbols,
            "graduated_opt_ins": graduated_opt_ins,
            "signature_changes": signature_changes,
        },
        "tokens": {
            "added": added_tokens,
            "removed": removed_tokens,
            "changed": changed_tokens,
        },
    }


def write_sync_diff(paths: RepoPaths, diff: dict[str, Any]) -> Path:
    out = sync_diff_path(paths)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load_sync_diff(paths: RepoPaths) -> dict[str, Any] | None:
    path = sync_diff_path(paths)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def get_changelog(paths: RepoPaths, *, since_last: bool = False) -> dict[str, Any]:
    """Return latest `.corpus/sync-diff.json`, or compute live diff vs `.corpus/snapshot.json.gz`."""
    saved_diff = load_sync_diff(paths)
    baseline = load_snapshot(paths)
    if since_last and saved_diff is not None:
        return saved_diff

    if baseline is not None:
        live = capture_snapshot(paths)
        live_diff = diff_snapshots(baseline, live)
        if live_diff["has_changes"] or saved_diff is None:
            return live_diff

    if saved_diff is not None:
        return saved_diff

    # No baseline yet: initialize baseline cleanly with 0 changes
    snap = capture_snapshot(paths)
    save_snapshot(paths, snap)
    empty = diff_snapshots(snap, snap)
    empty["note"] = "Initialized baseline snapshot (.corpus/snapshot.json.gz). Future syncs will diff against this baseline."
    return empty


def format_changelog_markdown(diff: dict[str, Any]) -> str:
    """Format a sync diff payload into concise Agent-readable Markdown."""
    s = diff.get("summary", {})
    lines = [
        "# Corpus Sync Changelog",
        "",
        f"- Generated: `{diff.get('generated_at', '')}` (baseline: `{diff.get('baseline_at', '-') or 'initial'}`)",
        f"- Pages: +{s.get('pages_added', 0)} added, ~{s.get('pages_modified', 0)} modified, -{s.get('pages_removed', 0)} removed",
        f"- API Surface: {s.get('api_version_bumps', 0)} version bump(s), +{s.get('api_symbols_added', 0)}/-{s.get('api_symbols_removed', 0)} symbols, {s.get('api_opt_in_changes', 0)} opt-in change(s), {s.get('api_signature_changes', 0)} signature change(s)",
        f"- Tokens: +{s.get('tokens_added', 0)} added, ~{s.get('tokens_changed', 0)} changed, -{s.get('tokens_removed', 0)} removed",
    ]
    if diff.get("note"):
        lines.extend(["", f"> {diff['note']}"])

    api = diff.get("api", {})
    if api.get("version_bumps"):
        lines.extend(["", "## Maven Version Bumps"])
        for v in api["version_bumps"][:20]:
            lines.append(
                f"- `{v['coordinate']}` ({v['ecosystem']}): `{v['old_latest'] or '-'}` -> `{v['new_latest'] or '-'}` "
                f"(alpha `{v['old_alpha'] or '-'}` -> `{v['new_alpha'] or '-'}`)"
            )

    if api.get("graduated_opt_ins"):
        lines.extend(["", "## Opt-In / Graduation Changes"])
        for g in api["graduated_opt_ins"][:25]:
            rem = ", ".join(g["removed_annotations"]) or "-"
            add = ", ".join(g["added_annotations"]) or "-"
            lines.append(f"- `{g['package']}.{g['name']}`: removed=[{rem}] added=[{add}]")

    if api.get("signature_changes"):
        lines.extend(["", "## API Signature & Parity Changes"])
        for sc in api["signature_changes"][:25]:
            lines.append(f"- `{sc['package']}.{sc['name']}` (parity: `{sc['old_parity']}` -> `{sc['new_parity']}`)")
            if sc["old_signature"] != sc["new_signature"]:
                lines.append(f"  - before: `{sc['old_signature'][:160]}`")
                lines.append(f"  - after:  `{sc['new_signature'][:160]}`")

    if api.get("added_symbols") or api.get("removed_symbols"):
        lines.extend(["", "## Added / Removed API Symbols"])
        for sym in api.get("added_symbols", [])[:20]:
            ann = f" ({', '.join(sym['annotations'])})" if sym.get("annotations") else ""
            lines.append(f"- + `{sym['package']}.{sym['name']}`{ann}")
        for sym in api.get("removed_symbols", [])[:20]:
            lines.append(f"- - `{sym['package']}.{sym['name']}`")

    toks = diff.get("tokens", {})
    if toks.get("changed") or toks.get("added") or toks.get("removed"):
        lines.extend(["", "## Design Token Changes"])
        for t in toks.get("changed", [])[:25]:
            lines.append(f"- ~ `{t['name']}` ({t['category']}): `{t['old_value']}` -> `{t['new_value']}`")
        for t in toks.get("added", [])[:15]:
            lines.append(f"- + `{t['name']}` ({t['category']}): `{t['value']}`")
        for t in toks.get("removed", [])[:15]:
            lines.append(f"- - `{t['name']}` ({t['category']}): was `{t['old_value']}`")

    pages = diff.get("pages", {})
    if pages.get("added") or pages.get("removed") or pages.get("modified"):
        lines.extend(["", "## Mirror Page Changes"])
        for p in pages.get("added", [])[:20]:
            lines.append(f"- + `{p['path']}` ({p['title']})")
        for p in pages.get("removed", [])[:20]:
            lines.append(f"- - `{p['path']}` ({p['title']})")
        for p in pages.get("modified", [])[:20]:
            lines.append(f"- ~ `{p['path']}` ({p['title']})")
            for sec in p.get("changed_sections", [])[:4]:
                lines.append(f"  - [{sec['status']}] `{sec['heading']}`")
                for dl in sec.get("diff_lines", [])[:6]:
                    lines.append(f"    {dl}")

    return "\n".join(lines)


@dataclass(slots=True)
class KnowledgeAudit:
    """Reverse citation impact and live staleness findings for `knowledge/`."""

    impacted_sections: list[dict[str, Any]] = field(default_factory=list)
    live_advisories: list[dict[str, Any]] = field(default_factory=list)
    citation_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "impacted_sections": self.impacted_sections,
            "live_advisories": self.live_advisories,
            "citation_counts": self.citation_counts,
        }


def analyze_impact(paths: RepoPaths, diff: dict[str, Any] | None = None) -> KnowledgeAudit:
    """Scan `knowledge/**/*.md` citations against `sync-diff.json` and live API/token manifests."""
    active_diff = diff if diff is not None else get_changelog(paths)

    # Load live API symbols and tokens from manifests
    snap_now = capture_snapshot(paths)
    live_apis: dict[str, list[dict[str, Any]]] = {}
    for sym in snap_now["api_symbols"].values():
        live_apis.setdefault(sym["name"], []).append(sym)

    live_tokens: dict[str, dict[str, Any]] = {}
    for tok in snap_now["tokens"].values():
        if tok["name"]:
            live_tokens[tok["name"]] = tok
        if tok["compose_token"]:
            live_tokens[tok["compose_token"]] = tok

    # Index diff triggers for O(1) lookup
    changed_pages: dict[str, str] = {}
    for p in active_diff.get("pages", {}).get("modified", []):
        changed_pages[p["path"]] = "mirror page modified"
    for p in active_diff.get("pages", {}).get("removed", []):
        changed_pages[p["path"]] = "mirror page removed"

    changed_symbols: dict[str, str] = {}
    api_diff = active_diff.get("api", {})
    for sym in api_diff.get("removed_symbols", []):
        changed_symbols[sym["name"]] = "API symbol removed"
    for sym in api_diff.get("graduated_opt_ins", []):
        rem = ", ".join(sym.get("removed_annotations", []))
        add = ", ".join(sym.get("added_annotations", []))
        changed_symbols[sym["name"]] = f"opt-in changed (removed=[{rem}], added=[{add}])"
    for sym in api_diff.get("signature_changes", []):
        changed_symbols[sym["name"]] = f"API signature/parity changed ({sym.get('old_parity')} -> {sym.get('new_parity')})"
    for sym in api_diff.get("added_symbols", []):
        changed_symbols[sym["name"]] = "API symbol added"

    changed_tokens: dict[str, str] = {}
    tok_diff = active_diff.get("tokens", {})
    for t in tok_diff.get("changed", []):
        reason = f"token value changed ({t['old_value']} -> {t['new_value']})"
        if t.get("name"):
            changed_tokens[t["name"]] = reason
        if t.get("new_compose_token"):
            changed_tokens[t["new_compose_token"]] = reason
    for t in tok_diff.get("removed", []):
        if t.get("name"):
            changed_tokens[t["name"]] = "token removed"

    impacted_map: dict[tuple[str, str], dict[str, Any]] = {}
    advisories: list[dict[str, Any]] = []
    corpus_cites = 0
    api_cites = 0
    token_cites = 0

    if not paths.knowledge_dir.is_dir():
        return KnowledgeAudit(citation_counts={"corpus": 0, "api": 0, "tokens": 0})

    def add_impact(kpath: str, heading: str, line_no: int, reason: str, ref: str) -> None:
        key = (kpath, heading)
        entry = impacted_map.setdefault(
            key,
            {"knowledge_file": kpath, "heading": heading, "line": line_no, "reasons": []},
        )
        item = f"{reason}: `{ref}`"
        if item not in entry["reasons"]:
            entry["reasons"].append(item)

    for md_file in sorted(paths.knowledge_dir.rglob("*.md")):
        rel = md_file.relative_to(paths.root).as_posix()
        lines = md_file.read_text(encoding="utf-8", errors="replace").splitlines()
        current_heading = md_file.stem
        in_fence = False
        fence_char = ""

        for line_no, line in enumerate(lines, start=1):
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

            if not in_fence:
                hm = _HEADING_RE.match(line)
                if hm:
                    current_heading = hm.group(2).strip()

            # 1. Corpus page citations
            for m in _CORPUS_CITE_RE.finditer(line):
                for rel_item in _expand_brace_paths(m.group(1)):
                    corpus_cites += 1
                    cited_rel = f".corpus/{rel_item}"
                    if cited_rel in changed_pages:
                        add_impact(rel, current_heading, line_no, changed_pages[cited_rel], cited_rel)
                    source_name = rel_item.split("/", 1)[0]
                    if (paths.corpus_dir / source_name / "pages").is_dir() and not (paths.root / cited_rel).is_file():
                        advisories.append(
                            {
                                "knowledge_file": rel,
                                "line": line_no,
                                "heading": current_heading,
                                "type": "missing_corpus_citation",
                                "detail": f"Cited `{cited_rel}` not found in locally synced `.corpus/{source_name}/pages/`",
                            }
                        )

            # 2. Backticked API & token citations
            for m in _BACKTICK_RE.finditer(line):
                ident = m.group(1)
                short = ident.split(".")[-1].split("(")[0]
                if short in live_apis or ident in live_apis:
                    api_cites += 1
                    sym_key = short if short in changed_symbols else ident
                    if sym_key in changed_symbols:
                        add_impact(rel, current_heading, line_no, changed_symbols[sym_key], ident)

                    # Live opt-in staleness check when line explicitly pairs `@OptIn(ExperimentalMaterial3ExpressiveApi`
                    # or `@ExperimentalMaterial3ExpressiveApi` with a non-annotation symbol
                    if (
                        not short.startswith("Experimental")
                        and (
                            "@OptIn(ExperimentalMaterial3ExpressiveApi" in line
                            or "@ExperimentalMaterial3ExpressiveApi" in line
                        )
                        and not any(
                            w in line.lower() for w in ("graduated", "previous", "legacy", "prior", "before", "removed", "alpha")
                        )
                    ):
                        entries = live_apis.get(short) or live_apis.get(ident) or []
                        non_ann = [e for e in entries if e.get("kind") != "annotation"]
                        if non_ann and all(
                            "ExperimentalMaterial3ExpressiveApi" not in " ".join(e.get("annotations", []))
                            for e in non_ann
                        ):
                            advisories.append(
                                {
                                    "knowledge_file": rel,
                                    "line": line_no,
                                    "heading": current_heading,
                                    "type": "graduated_opt_in_drift",
                                    "detail": f"`{short}` no longer carries @ExperimentalMaterial3ExpressiveApi in manifests/api/",
                                }
                            )

                if ident in live_tokens or short in live_tokens:
                    token_cites += 1
                    tok_key = ident if ident in changed_tokens else short
                    if tok_key in changed_tokens:
                        add_impact(rel, current_heading, line_no, changed_tokens[tok_key], ident)

    impacted = sorted(impacted_map.values(), key=lambda x: (x["knowledge_file"], x["line"]))
    return KnowledgeAudit(
        impacted_sections=impacted,
        live_advisories=advisories,
        citation_counts={"corpus": corpus_cites, "api": api_cites, "tokens": token_cites},
    )
