"""Command-line interface (`rtx`) for The Road to Expressive corpus."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from rtx.config import RepoPaths, discover_sources, get_paths
from rtx.diff import (
    analyze_impact,
    capture_snapshot,
    diff_snapshots,
    format_changelog_markdown,
    get_changelog,
    load_snapshot,
    save_snapshot,
    write_sync_diff,
)
from rtx.index import build_index
from rtx.query import (
    get_status,
    query_api,
    query_api_batch,
    query_component,
    query_component_batch,
    query_copy,
    query_source,
    query_source_batch,
    query_spec,
    query_spec_batch,
    query_tokens,
    query_tokens_batch,
    run_doctor,
    search_corpus,
)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _cmd_status(paths: RepoPaths, args: argparse.Namespace) -> int:
    status = get_status(paths)
    if args.json:
        _print_json(status)
        return 0

    print(f"Repository: {status['root']}")
    print(
        f"Index DB:   {'ready' if status['index_exists'] else 'not built'}"
        + (
            f" (chunks={status['index_meta'].get('doc_chunks', '?')}, "
            f"api_symbols={status['index_meta'].get('api_symbols', '?')}, "
            f"kotlin_sources={status['index_meta'].get('kotlin_sources', '0')}, "
            f"tokens={status['index_meta'].get('design_tokens', '?')}, "
            f"built_at={status['index_meta'].get('built_at', '?')})"
            if status["index_exists"]
            else ""
        )
    )
    print(
        f"Knowledge:  {status['knowledge_count']} file(s) | "
        f"API manifests: {len(status['api_manifests'])} | "
        f"Token manifests: {len(status['token_manifests'])}"
    )
    print("\nSources:")
    print(f"  {'SOURCE':<24} {'ADAPTER':<8} {'LOCAL':<7} {'MANIFEST':<8} {'STATUS':<10} {'VERSION / FETCHED'}")
    print(f"  {'-' * 24} {'-' * 8} {'-' * 7} {'-' * 8} {'-' * 10} {'-' * 24}")
    for s in status["sources"]:
        ver_info = s["upstream_version"] or s["fetched_at"] or "-"
        print(
            f"  {s['source_id']:<24} "
            f"{('yes' if s['has_adapter'] else 'no'):<8} "
            f"{str(s['live_pages']):<7} "
            f"{str(s['manifest_pages']):<8} "
            f"{s['status']:<10} "
            f"{ver_info}"
        )
    return 0


def _adapter_supported_flags(script_path: Path) -> set[str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        help_text = proc.stdout + "\n" + proc.stderr
    except Exception:
        return set()
    flags: set[str] = set()
    for flag in ("--check", "--refresh", "--no-assets", "--workers", "--verify"):
        if flag in help_text:
            flags.add(flag)
    return flags


def _cmd_sync(paths: RepoPaths, args: argparse.Namespace) -> int:
    adapters = {a.source_id: a for a in discover_sources(paths)}
    if args.all or not args.sources:
        targets = [a for a in adapters.values() if a.has_adapter]
    else:
        targets = []
        for name in args.sources:
            if name not in adapters:
                print(f"Unknown source: {name}", file=sys.stderr)
                return 2
            if not adapters[name].has_adapter:
                print(f"Source '{name}' has no refresh.py adapter yet.", file=sys.stderr)
                return 2
            targets.append(adapters[name])

    if not targets:
        print("No source adapters found under sources/*/refresh.py.")
        return 0

    before_snap = None
    if not args.check:
        before_snap = load_snapshot(paths) or capture_snapshot(paths)

    failures = 0
    for adapter in targets:
        assert adapter.script_path is not None
        supported = _adapter_supported_flags(adapter.script_path)
        cmd = [sys.executable, str(adapter.script_path)]
        if args.check and "--check" in supported:
            cmd.append("--check")
        if args.refresh and "--refresh" in supported:
            cmd.append("--refresh")
        if args.no_assets and "--no-assets" in supported:
            cmd.append("--no-assets")
        if args.workers is not None and "--workers" in supported:
            cmd.extend(["--workers", str(args.workers)])
        if args.verify and "--verify" in supported:
            cmd.append("--verify")

        print(f"==> [{adapter.source_id}] {' '.join(cmd[1:])}")
        proc = subprocess.run(cmd, cwd=paths.root, check=False)
        if proc.returncode != 0:
            failures += 1
            print(f"!! [{adapter.source_id}] exited with code {proc.returncode}", file=sys.stderr)

    if not args.check:
        stats = build_index(paths)
        print(
            f"Indexed {stats.doc_chunks} chunks ({stats.knowledge_files} knowledge, "
            f"{stats.mirror_files} mirror), {stats.api_symbols} API symbols, "
            f"{stats.design_tokens} tokens -> {stats.db_path}"
        )
        assert before_snap is not None
        after_snap = capture_snapshot(paths)
        diff = diff_snapshots(before_snap, after_snap)
        diff_file = write_sync_diff(paths, diff)
        save_snapshot(paths, after_snap)
        s = diff["summary"]
        print(
            f"Sync diff written -> {diff_file} "
            f"(pages +{s['pages_added']}/~{s['pages_modified']}/-{s['pages_removed']}, "
            f"api bumps={s['api_version_bumps']}, tokens ~{s['tokens_changed']})"
        )
        if args.diff_report:
            print()
            print(format_changelog_markdown(diff))

    return 1 if failures else 0


def _cmd_index(paths: RepoPaths, args: argparse.Namespace) -> int:
    stats = build_index(paths)
    payload = {
        "db_path": str(stats.db_path),
        "doc_chunks": stats.doc_chunks,
        "knowledge_files": stats.knowledge_files,
        "mirror_files": stats.mirror_files,
        "api_symbols": stats.api_symbols,
        "api_versions": stats.api_versions,
        "design_tokens": stats.design_tokens,
        "kotlin_sources": stats.kotlin_sources,
        "built_at": stats.built_at,
    }
    if args.json:
        _print_json(payload)
        return 0
    print(
        f"Built {stats.db_path}: {stats.doc_chunks} doc chunks "
        f"({stats.knowledge_files} knowledge, {stats.mirror_files} mirror), "
        f"{stats.api_symbols} API symbols, {stats.api_versions} artifact versions, "
        f"{stats.kotlin_sources} Kotlin source symbols, {stats.design_tokens} tokens."
    )
    return 0


def _cmd_search(paths: RepoPaths, args: argparse.Namespace) -> int:
    query = " ".join(args.query)
    hits = search_corpus(
        paths,
        query,
        source=args.source,
        layer=args.layer,
        limit=args.limit,
    )
    if args.json:
        _print_json({"query": query, "count": len(hits), "hits": [h.to_dict() for h in hits]})
        return 0

    if not hits:
        print(f"No results for: {query}")
        return 0

    for idx, hit in enumerate(hits, start=1):
        loc = f"{hit.path}:{hit.line}"
        src_tag = f"[{hit.layer}:{hit.source_id}]"
        print(f"{idx}. {src_tag} {hit.title} > {hit.heading}")
        print(f"   {loc}" + (f"  ({hit.url})" if hit.url else ""))
        if hit.snippet:
            print(f"   {hit.snippet}")
    return 0


def _print_api_result(paths: RepoPaths, res: dict, *, target: str | None, diff_only: bool, limit: int, show_versions: bool = True) -> None:
    query = res["query"]
    if show_versions and res["versions"]:
        print("Tracked Maven Versions:")
        for v in res["versions"]:
            print(
                f"  - {v['coordinate']} ({v['ecosystem']}): "
                f"latest={v['latest'] or '-'} | alpha={v['alpha'] or '-'} | "
                f"beta={v['beta'] or '-'} | rc={v['rc'] or '-'} | stable={v['stable'] or '-'}"
            )
        print()

    symbols = res["symbols"]
    if not symbols:
        if diff_only:
            all_res = query_api(paths, query, target=target, diff_only=False, limit=limit)
            if all_res["symbols"]:
                print(
                    f"No parity diffs for '{query}' — {len(all_res['symbols'])} matching symbol(s) "
                    "have identical signatures across AndroidX and CMP (omit --diff to inspect)."
                )
                return
        print(f"No API symbols matched: {query}")
        return

    print(f"API Symbols ({len(symbols)}):")
    for sym in symbols:
        clean_anns = [a.lstrip("@") for a in sym["annotations"] if a]
        ann = f" @{', @'.join(clean_anns)}" if clean_anns else ""
        parity = f" [{sym['parity_status']}]" if sym["parity_status"] else ""
        targets = ",".join(sym["targets"]) if sym["targets"] else "common"
        print(f"- {sym['package']}.{sym['name']} ({sym['kind']}, targets={targets}){parity}{ann}")
        kt_sigs = sym.get("kotlin_signatures") or []
        if kt_sigs:
            for kt_sig in kt_sigs[:2]:
                kt_lines = kt_sig.splitlines()
                print(f"  kotlin:   {kt_lines[0]}")
                for extra_line in kt_lines[1:14]:
                    print(f"            {extra_line}")
                if len(kt_lines) > 14:
                    print(f"            ... (+{len(kt_lines) - 14} more lines; run `rtx source {sym['name']}`)")
        if sym["signature"] and (not kt_sigs or sym["signature"].strip() != kt_sigs[0].strip()):
            for sig_line in sym["signature"].splitlines()[:6]:
                print(f"  sig:      {sig_line}")
            if len(sym["signature"].splitlines()) > 6:
                print(f"  ... (+{len(sym['signature'].splitlines()) - 6} more overloads; pass --json for all)")
        if sym["androidx_signature"] and sym["androidx_signature"] != sym["signature"]:
            for sig_line in sym["androidx_signature"].splitlines()[:4]:
                print(f"  androidx: {sig_line}")
        if sym["cmp_signature"] and sym["cmp_signature"] != sym["signature"]:
            for sig_line in sym["cmp_signature"].splitlines()[:4]:
                print(f"  cmp:      {sig_line}")
        if sym["artifact"] or sym["version"]:
            print(f"  artifact: {sym['artifact']} {sym['version']} ({sym['source_file']})")


def _cmd_api(paths: RepoPaths, args: argparse.Namespace) -> int:
    queries = list(args.query)
    if len(queries) == 1:
        res = query_api(paths, queries[0], target=args.target, diff_only=args.diff, limit=args.limit)
        if args.json:
            _print_json(res)
            return 0
        _print_api_result(paths, res, target=args.target, diff_only=args.diff, limit=args.limit)
        return 0

    batch = query_api_batch(paths, queries, target=args.target, diff_only=args.diff, limit=args.limit)
    if args.json:
        _print_json(batch)
        return 0

    seen_coords: set[str] = set()
    all_versions: list[dict] = []
    for item in batch["results"]:
        for v in item["versions"]:
            if v["coordinate"] not in seen_coords:
                seen_coords.add(v["coordinate"])
                all_versions.append(v)
    if all_versions:
        print("Tracked Maven Versions:")
        for v in all_versions:
            print(
                f"  - {v['coordinate']} ({v['ecosystem']}): "
                f"latest={v['latest'] or '-'} | alpha={v['alpha'] or '-'} | "
                f"beta={v['beta'] or '-'} | rc={v['rc'] or '-'} | stable={v['stable'] or '-'}"
            )
        print()

    for idx, item in enumerate(batch["results"], start=1):
        print(f"=== [{idx}/{len(queries)}] API: {item['query']} ===")
        _print_api_result(paths, item, target=args.target, diff_only=args.diff, limit=args.limit, show_versions=False)
        if idx < len(queries):
            print()
    return 0


def _print_indented(text: str, prefix: str = "  ") -> None:
    for line in text.splitlines():
        if line.strip():
            print(f"{prefix}{line}")
        else:
            print()


def _print_component_result(res: dict) -> None:
    print(f"=== Component: {res['component']} ===")

    dossiers = res.get("m3_dossier") or []
    for dossier in dossiers:
        url_part = f" ({dossier['url']})" if dossier.get("url") else ""
        print(f"\n[M3 Expressive Official Spec: {dossier['title']}]")
        print(f"  Source: {dossier['path']}{url_part}")

        if dossier.get("overview_and_variants"):
            print("\n  -- Overview & Variants --")
            _print_indented(dossier["overview_and_variants"], "  ")

        if dossier.get("usage"):
            print("\n  -- Usage & When to Use / Avoid --")
            _print_indented(dossier["usage"], "  ")

        if dossier.get("do_dont_rules"):
            print("\n  -- Official Do & Don't Rules --")
            for cap in dossier["do_dont_rules"]:
                print(f"  - {cap}")

        if dossier.get("adaptive_and_placement"):
            print("\n  -- Adaptive Design & Placement --")
            _print_indented(dossier["adaptive_and_placement"], "  ")

        if dossier.get("behavior"):
            print("\n  -- Behavior --")
            _print_indented(dossier["behavior"], "  ")

    hig_counterparts = res.get("hig_counterparts") or []
    if hig_counterparts:
        print("\n[Desktop & Mobile HIG Counterparts]")
        for item in hig_counterparts:
            url_part = f" ({item['url']})" if item.get("url") else ""
            print(f"  - [{item['source_id']}] {item['title']} :: {item['path']}{url_part}")
            _print_indented(item["summary"], "    ")

    if res["knowledge"]:
        print("\n[Knowledge Engineering Notes]")
        for h in res["knowledge"][:5]:
            print(f"  - {h['path']}:{h['line']} ({h['heading']}) :: {h['snippet']}")

    if res["tokens"]:
        print("\n[Key M3 Expressive Tokens]")
        for tok in res["tokens"][:8]:
            comp = f" | {tok['compose_token']}" if tok["compose_token"] else ""
            print(f"  - {tok['name']} ({tok['category']}): {tok['value']}{comp}")

    if res["compose_apis"]:
        print("\n[Compose Kotlin Signatures & Defaults]")
        for sym in res["compose_apis"][:8]:
            clean_anns = [a.lstrip("@") for a in sym["annotations"] if a]
            ann = f" @{', @'.join(clean_anns)}" if clean_anns else ""
            parity = f" [{sym['parity_status']}]" if sym["parity_status"] else ""
            kt_sigs = sym.get("kotlin_signatures") or []
            if kt_sigs:
                print(f"  - {sym['name']}{parity}{ann}:")
                kt_lines = kt_sigs[0].splitlines()
                for ln in kt_lines[:10]:
                    print(f"      {ln}")
                if len(kt_lines) > 10:
                    print(f"      ... (+{len(kt_lines) - 10} lines; run `rtx source {sym['name']}`)")
            else:
                sig = (sym["signature"] or sym["androidx_signature"]).splitlines()[0]
                if len(sig) > 160:
                    sig = sig[:157] + "..."
                print(f"  - {sym['name']}{parity}{ann}: {sig}")

    if not dossiers and res["m3_expressive"]:
        print("\n[Material 3 Spec]")
        for h in res["m3_expressive"]:
            print(f"  - {h['path']}:{h['line']} ({h['heading']}) :: {h['snippet']}")

    if not any(
        res.get(k)
        for k in ("m3_dossier", "hig_counterparts", "knowledge", "compose_apis", "tokens", "m3_expressive", "platform_hig")
    ):
        print("No component entries found yet. Run `rtx sync` / `rtx index` or check spelling.")


def _cmd_component(paths: RepoPaths, args: argparse.Namespace) -> int:
    names = list(args.name)
    if len(names) == 1:
        res = query_component(paths, names[0])
        if args.json:
            _print_json(res)
            return 0
        _print_component_result(res)
        return 0

    batch = query_component_batch(paths, names)
    if args.json:
        _print_json(batch)
        return 0
    for idx, item in enumerate(batch["results"], start=1):
        _print_component_result(item)
        if idx < len(names):
            print()
    return 0


def _print_spec_result(res: dict) -> None:
    sections = res["sections"]
    if not sections:
        print(f"No upstream design spec sections matched: {res['query']}")
        return

    for idx, sec in enumerate(sections, start=1):
        url_part = f" ({sec['url']})" if sec.get("url") else ""
        print(f"=== [{idx}/{len(sections)}] [{sec['source_id']}] {sec['title']} > {sec['heading']} ===")
        print(f"Source: {sec['path']}:{sec['start_line']}-{sec['end_line']}{url_part}\n")
        print(sec["content"])
        if idx < len(sections):
            print()


def _cmd_spec(paths: RepoPaths, args: argparse.Namespace) -> int:
    raw_args = list(args.query)
    # If multiple quoted multi-word queries were passed, run as batch; otherwise join unquoted words into one query.
    if len(raw_args) > 1 and any(any(ch.isspace() for ch in item) for item in raw_args):
        queries = raw_args
    else:
        queries = [" ".join(raw_args)]

    if len(queries) == 1:
        res = query_spec(paths, queries[0], source=args.source, limit=args.limit, max_chars=args.max_chars)
        if args.json:
            _print_json(res)
            return 0
        _print_spec_result(res)
        return 0

    batch = query_spec_batch(paths, queries, source=args.source, limit=args.limit, max_chars=args.max_chars)
    if args.json:
        _print_json(batch)
        return 0
    for idx, item in enumerate(batch["results"], start=1):
        print(f"########## Spec Query [{idx}/{len(queries)}]: {item['query']} ##########")
        _print_spec_result(item)
        if idx < len(queries):
            print()
    return 0


def _print_source_result(res: dict) -> None:
    matches = res["matches"]
    if not matches:
        print(
            f"No Kotlin/Java source declarations matched '{res['symbol']}'. "
            "Run `rtx sync compose-maven-api` and `rtx index` if `source-index.json` has not been built yet."
        )
        return

    for idx, m in enumerate(matches, start=1):
        fq = f"{m['fq_package']}.{m['qualified_name']}" if m["fq_package"] else m["qualified_name"]
        clean_anns = [a.lstrip("@") for a in m["annotations"] if a]
        ann = f" @{', @'.join(clean_anns)}" if clean_anns else ""
        coord = f"{m['coordinate']}:{m['version']}" if m["coordinate"] else m["artifact_key"]
        print(f"=== [{idx}/{len(matches)}] {fq} ({m['visibility']} {m['kind']}){ann} ===")
        print(f"Artifact: {coord} ({m['platform']})")
        print(f"Source:   .corpus/compose-maven-api/sources/{m['jar_name']}!{m['entry_path']}:{m['display_start_line']}-{m['display_end_line']}")
        if m.get("also_in"):
            print(f"Also in:  {', '.join(m['also_in'][:3])}")
        print()
        if m.get("source_code"):
            print(m["source_code"])
            if m.get("truncated_lines"):
                print(
                    f"... (+{m['truncated_lines']} more lines; pass --max-lines {m['end_line'] - m['start_line'] + 20} to view full body)"
                )
        else:
            if m.get("kdoc"):
                print(f"/* {m['kdoc']} */")
            if m.get("kotlin_signature"):
                print(m["kotlin_signature"])
        if idx < len(matches):
            print()


def _cmd_source(paths: RepoPaths, args: argparse.Namespace) -> int:
    symbols = list(args.symbol)
    if len(symbols) == 1:
        res = query_source(
            paths,
            symbols[0],
            artifact=args.artifact,
            context_lines=args.context_lines,
            limit=args.limit,
            max_lines=args.max_lines,
        )
        if args.json:
            _print_json(res)
            return 0
        _print_source_result(res)
        return 0

    batch = query_source_batch(
        paths,
        symbols,
        artifact=args.artifact,
        context_lines=args.context_lines,
        limit=args.limit,
        max_lines=args.max_lines,
    )
    if args.json:
        _print_json(batch)
        return 0
    for idx, item in enumerate(batch["results"], start=1):
        print(f"########## Source [{idx}/{len(symbols)}]: {item['symbol']} ##########")
        _print_source_result(item)
        if idx < len(symbols):
            print()
    return 0


def _print_token_result(res: dict) -> None:
    query = res["query"]
    if res["tokens"]:
        print(f"Design Tokens ({len(res['tokens'])}):")
        for t in res["tokens"]:
            comp = f" | compose={t['compose_token']}" if t["compose_token"] else ""
            spec = f" [{t['spec_version']}]" if t["spec_version"] else ""
            print(f"  - {t['name']} ({t['category']}){spec}: {t['value']}{comp}")
            if t["notes"]:
                print(f"    {t['notes']}")
    else:
        print(f"No structured tokens matched '{query}' in manifests/tokens/.")

    if res["knowledge_refs"]:
        print("\nRelated Knowledge References:")
        for ref in res["knowledge_refs"][:4]:
            print(f"  - {ref['path']}:{ref['line']} ({ref['heading']}) :: {ref['snippet']}")


def _cmd_token(paths: RepoPaths, args: argparse.Namespace) -> int:
    queries = list(args.query)
    if len(queries) == 1:
        res = query_tokens(paths, queries[0], category=args.category, limit=args.limit)
        if args.json:
            _print_json(res)
            return 0
        _print_token_result(res)
        return 0

    batch = query_tokens_batch(paths, queries, category=args.category, limit=args.limit)
    if args.json:
        _print_json(batch)
        return 0
    for idx, item in enumerate(batch["results"], start=1):
        print(f"=== [{idx}/{len(queries)}] Token: {item['query']} ===")
        _print_token_result(item)
        if idx < len(queries):
            print()
    return 0


def _cmd_copy(paths: RepoPaths, args: argparse.Namespace) -> int:
    topic = " ".join(args.topic)
    res = query_copy(paths, topic, limit=args.limit)
    if args.json:
        _print_json(res)
        return 0

    results = res["results"]
    if not results:
        print(f"No UX writing / copywriting rules matched: {topic}")
        return 0

    for idx, hit in enumerate(results, start=1):
        print(f"{idx}. [{hit['layer']}:{hit['source_id']}] {hit['title']} > {hit['heading']}")
        print(f"   {hit['path']}:{hit['line']}")
        if hit["snippet"]:
            print(f"   {hit['snippet']}")
    return 0


def _cmd_changelog(paths: RepoPaths, args: argparse.Namespace) -> int:
    diff = get_changelog(paths, since_last=args.since_last)
    if args.json:
        _print_json(diff)
        return 0
    print(format_changelog_markdown(diff))
    return 0


def _cmd_impact(paths: RepoPaths, args: argparse.Namespace) -> int:
    audit = analyze_impact(paths)
    if args.json:
        _print_json(audit.to_dict())
        return 0

    c = audit.citation_counts
    print(
        f"Scanned knowledge/ citations: {c['corpus']} corpus page refs, "
        f"{c['api']} API symbol refs, {c['tokens']} token refs."
    )
    if audit.impacted_sections:
        print(f"\nImpacted knowledge sections ({len(audit.impacted_sections)}):")
        for item in audit.impacted_sections:
            print(f"  - {item['knowledge_file']}:{item['line']} ({item['heading']})")
            for reason in item["reasons"]:
                print(f"      * {reason}")
    else:
        print("\nNo knowledge sections impacted by current sync diff.")

    if audit.live_advisories:
        print(f"\nLive manifest staleness advisories ({len(audit.live_advisories)}):")
        for adv in audit.live_advisories[:25]:
            print(f"  - {adv['knowledge_file']}:{adv['line']} [{adv['type']}] {adv['detail']}")
    return 0


def _cmd_doctor(paths: RepoPaths, args: argparse.Namespace) -> int:
    report = run_doctor(paths)
    if args.json:
        _print_json(report)
        return 0 if report["ok"] else 1

    print(f"Checked markdown files: {report['checked_files']}")
    print(f"FTS5 index health:      {'OK' if report['fts_ok'] else 'FAILED'}")
    if report["warnings"]:
        print(f"\nWarnings ({len(report['warnings'])}):")
        for w in report["warnings"][:20]:
            print(f"  - {w}")
    if report["errors"]:
        print(f"\nErrors ({len(report['errors'])}):")
        for e in report["errors"]:
            print(f"  - {e}")
        for ll in report["long_lines"]:
            print(f"    long line: {ll['path']}:{ll['line']} ({ll['length']} chars)")
        for bl in report["broken_links"]:
            print(f"    broken link: {bl['path']}:{bl['line']} -> {bl['target']}")
        return 1

    print("\nAll integrity checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtx",
        description="The Road to Expressive: M3E, Compose Multiplatform, HIG & UX Writing corpus CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Show sync status, page counts, version pins, and index state")
    p_status.add_argument("--json", action="store_true", help="Emit JSON output")
    p_status.set_defaults(func=_cmd_status)

    p_sync = sub.add_parser("sync", help="Run source refresh adapters and rebuild .corpus/index.db")
    p_sync.add_argument("sources", nargs="*", help="Source IDs to sync (or omit / pass --all)")
    p_sync.add_argument("--all", action="store_true", help="Sync all discovered source adapters")
    p_sync.add_argument("--check", action="store_true", help="Check upstream freshness without rewriting")
    p_sync.add_argument("--refresh", action="store_true", help="Force conditional cache bypass")
    p_sync.add_argument("--no-assets", action="store_true", help="Skip downloading binary image/SVG assets")
    p_sync.add_argument("--workers", type=int, default=10, help="Concurrent HTTP workers per adapter")
    p_sync.add_argument("--verify", action="store_true", help="Run adapter structural verification")
    p_sync.add_argument("--diff-report", action="store_true", help="Print Markdown changelog after sync")
    p_sync.set_defaults(func=_cmd_sync)

    p_index = sub.add_parser("index", help="Rebuild .corpus/index.db SQLite FTS5 index")
    p_index.add_argument("--json", action="store_true", help="Emit JSON output")
    p_index.set_defaults(func=_cmd_index)

    p_search = sub.add_parser("search", help="BM25 search across knowledge, mirrors, APIs, and tokens")
    p_search.add_argument("query", nargs="+", help="Search query")
    p_search.add_argument("--source", help="Filter by source_id (e.g. m3-expressive, apple-hig)")
    p_search.add_argument(
        "--layer",
        choices=["knowledge", "mirror", "api", "tokens"],
        help="Filter by corpus layer",
    )
    p_search.add_argument("--limit", type=int, default=15, help="Max results (default: 15)")
    p_search.add_argument("--json", action="store_true", help="Emit JSON output")
    p_search.set_defaults(func=_cmd_search)

    p_api = sub.add_parser("api", help="Query Maven/bytecode API signatures & AndroidX vs CMP parity")
    p_api.add_argument("query", nargs="+", help="One or more symbol names, packages, annotations, or artifact queries")
    p_api.add_argument("--target", choices=["common", "android", "desktop", "ios"], help="Filter by target")
    p_api.add_argument("--diff", action="store_true", help="Show only symbols with AndroidX vs CMP parity deltas")
    p_api.add_argument("--limit", type=int, default=30, help="Max symbol results per query")
    p_api.add_argument("--json", action="store_true", help="Emit JSON output")
    p_api.set_defaults(func=_cmd_api)

    p_comp = sub.add_parser("component", help="Lossless official M3E spec dossier + HIG counterparts + tokens + Kotlin defaults")
    p_comp.add_argument("name", nargs="+", help="One or more component names (e.g. SearchBar Carousel Tabs Snackbar NavigationRail)")
    p_comp.add_argument("--json", action="store_true", help="Emit JSON output")
    p_comp.set_defaults(func=_cmd_component)

    p_spec = sub.add_parser("spec", help="Read complete, noise-stripped official M3E & HIG design sections for patterns/layouts")
    p_spec.add_argument("query", nargs="+", help="Design pattern query (or multiple quoted queries)")
    p_spec.add_argument("--source", help="Filter by source_id (e.g. m3-expressive, apple-hig, windows-fluent, linux-hig, compose-android, google-design)")
    p_spec.add_argument("--limit", type=int, default=5, help="Max sections per query (default: 5)")
    p_spec.add_argument("--max-chars", type=int, default=1600, help="Max characters per section body (default: 1600)")
    p_spec.add_argument("--json", action="store_true", help="Emit JSON output")
    p_spec.set_defaults(func=_cmd_spec)

    p_src = sub.add_parser("source", help="Read upstream Kotlin/Java KDoc + source code from cached Maven *-sources.jar")
    p_src.add_argument("symbol", nargs="+", help="One or more symbol names (e.g. HorizontalMultiBrowseCarousel TabRowDefaults.PrimaryIndicator SkiaLayer)")
    p_src.add_argument("--artifact", help="Filter by artifact key, coordinate, jar name, or platform (e.g. cmp-material3, skiko, foundation)")
    p_src.add_argument("--context-lines", type=int, default=0, help="Extra surrounding source lines above and below (default: 0)")
    p_src.add_argument("--limit", type=int, default=5, help="Max matches per symbol (default: 5)")
    p_src.add_argument("--max-lines", type=int, default=140, help="Max lines to print per match (default: 140)")
    p_src.add_argument("--json", action="store_true", help="Emit JSON output")
    p_src.set_defaults(func=_cmd_source)

    p_tok = sub.add_parser("token", help="Query M3 Expressive color, shape, typography, and motion tokens")
    p_tok.add_argument("query", nargs="+", help="One or more token queries (e.g. MotionScheme largeIncreased displayLargeEmphasized)")
    p_tok.add_argument("--category", help="Filter by token category (color, shape, typography, motion, etc.)")
    p_tok.add_argument("--limit", type=int, default=40, help="Max token results per query")
    p_tok.add_argument("--json", action="store_true", help="Emit JSON output")
    p_tok.set_defaults(func=_cmd_token)

    p_copy = sub.add_parser("copy", help="Query UI copywriting, microcopy, AP Style, and CJK rules")
    p_copy.add_argument("topic", nargs="+", help="Copy topic (e.g. 'sentence case', 'error message', 'numerals')")
    p_copy.add_argument("--limit", type=int, default=15, help="Max results")
    p_copy.add_argument("--json", action="store_true", help="Emit JSON output")
    p_copy.set_defaults(func=_cmd_copy)

    p_chg = sub.add_parser("changelog", help="Show incremental page, API surface, and token diffs")
    p_chg.add_argument("--since-last", action="store_true", help="Show last saved .corpus/sync-diff.json")
    p_chg.add_argument("--json", action="store_true", help="Emit JSON output")
    p_chg.set_defaults(func=_cmd_changelog)

    p_imp = sub.add_parser("impact", help="Map sync diffs and live manifest drift to impacted knowledge/ files")
    p_imp.add_argument("--json", action="store_true", help="Emit JSON output")
    p_imp.set_defaults(func=_cmd_impact)

    p_doc = sub.add_parser("doctor", help="Verify corpus integrity, <=4000 line lengths, links, and FTS5 health")
    p_doc.add_argument("--json", action="store_true", help="Emit JSON output")
    p_doc.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = get_paths()
    return int(args.func(paths, args))


if __name__ == "__main__":
    raise SystemExit(main())
