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
    query_component,
    query_copy,
    query_tokens,
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
        "built_at": stats.built_at,
    }
    if args.json:
        _print_json(payload)
        return 0
    print(
        f"Built {stats.db_path}: {stats.doc_chunks} doc chunks "
        f"({stats.knowledge_files} knowledge, {stats.mirror_files} mirror), "
        f"{stats.api_symbols} API symbols, {stats.api_versions} artifact versions, "
        f"{stats.design_tokens} tokens."
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


def _cmd_api(paths: RepoPaths, args: argparse.Namespace) -> int:
    query = " ".join(args.query)
    res = query_api(paths, query, target=args.target, diff_only=args.diff, limit=args.limit)
    if args.json:
        _print_json(res)
        return 0

    if res["versions"]:
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
        if args.diff:
            all_res = query_api(paths, query, target=args.target, diff_only=False, limit=args.limit)
            if all_res["symbols"]:
                print(
                    f"No parity diffs for '{query}' — {len(all_res['symbols'])} matching symbol(s) "
                    "have identical signatures across AndroidX and CMP (omit --diff to inspect)."
                )
                return 0
        print(f"No API symbols matched: {query}")
        return 0

    print(f"API Symbols ({len(symbols)}):")
    for sym in symbols:
        clean_anns = [a.lstrip("@") for a in sym["annotations"] if a]
        ann = f" @{', @'.join(clean_anns)}" if clean_anns else ""
        parity = f" [{sym['parity_status']}]" if sym["parity_status"] else ""
        targets = ",".join(sym["targets"]) if sym["targets"] else "common"
        print(f"- {sym['package']}.{sym['name']} ({sym['kind']}, targets={targets}){parity}{ann}")
        if sym["signature"]:
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
    return 0


def _cmd_component(paths: RepoPaths, args: argparse.Namespace) -> int:
    name = " ".join(args.name)
    res = query_component(paths, name)
    if args.json:
        _print_json(res)
        return 0

    print(f"=== Component: {res['component']} ===")

    if res["knowledge"]:
        print("\n[Knowledge Guides]")
        for h in res["knowledge"][:5]:
            print(f"  - {h['path']}:{h['line']} ({h['heading']}) :: {h['snippet']}")

    if res["compose_apis"]:
        print("\n[Compose API Surface]")
        for sym in res["compose_apis"][:8]:
            clean_anns = [a.lstrip("@") for a in sym["annotations"] if a]
            ann = f" @{', @'.join(clean_anns)}" if clean_anns else ""
            parity = f" [{sym['parity_status']}]" if sym["parity_status"] else ""
            sig = (sym["signature"] or sym["androidx_signature"]).splitlines()[0]
            if len(sig) > 160:
                sig = sig[:157] + "..."
            print(f"  - {sym['name']}{parity}{ann}: {sig}")

    if res["tokens"]:
        print("\n[M3 Expressive Tokens]")
        for tok in res["tokens"][:8]:
            print(f"  - {tok['name']} ({tok['category']}): {tok['value']} {tok['compose_token']}")

    if res["m3_expressive"]:
        print("\n[Material 3 Spec]")
        for h in res["m3_expressive"]:
            print(f"  - {h['path']}:{h['line']} ({h['heading']}) :: {h['snippet']}")

    if res["compose_docs"]:
        print("\n[Compose Official Docs]")
        for h in res["compose_docs"]:
            print(f"  - [{h['source_id']}] {h['path']}:{h['line']} ({h['heading']})")

    if res["platform_hig"]:
        print("\n[Platform HIG Notes]")
        for h in res["platform_hig"]:
            print(f"  - [{h['source_id']}] {h['path']}:{h['line']} ({h['heading']}) :: {h['snippet']}")

    if not any(res[k] for k in ("knowledge", "compose_apis", "tokens", "m3_expressive", "compose_docs", "platform_hig")):
        print("No component entries found yet. Run `rtx sync` / `rtx index` or check spelling.")
    return 0


def _cmd_token(paths: RepoPaths, args: argparse.Namespace) -> int:
    query = " ".join(args.query)
    res = query_tokens(paths, query, category=args.category, limit=args.limit)
    if args.json:
        _print_json(res)
        return 0

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
    p_api.add_argument("query", nargs="+", help="Symbol name, package, annotation, or artifact query")
    p_api.add_argument("--target", choices=["common", "android", "desktop", "ios"], help="Filter by target")
    p_api.add_argument("--diff", action="store_true", help="Show only symbols with AndroidX vs CMP parity deltas")
    p_api.add_argument("--limit", type=int, default=30, help="Max symbol results")
    p_api.add_argument("--json", action="store_true", help="Emit JSON output")
    p_api.set_defaults(func=_cmd_api)

    p_comp = sub.add_parser("component", help="Unified M3E tokens + Compose API + Adaptive + HIG view")
    p_comp.add_argument("name", nargs="+", help="Component name (e.g. SplitButton, NavigationRail, Dialog)")
    p_comp.add_argument("--json", action="store_true", help="Emit JSON output")
    p_comp.set_defaults(func=_cmd_component)

    p_tok = sub.add_parser("token", help="Query M3 Expressive color, shape, typography, and motion tokens")
    p_tok.add_argument("query", nargs="+", help="Token query (e.g. MotionScheme, largeIncreased, displayLargeEmphasized)")
    p_tok.add_argument("--category", help="Filter by token category (color, shape, typography, motion, etc.)")
    p_tok.add_argument("--limit", type=int, default=40, help="Max token results")
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
