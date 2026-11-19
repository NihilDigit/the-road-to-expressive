"""Unit and integration tests for `rtx` foundation, HTTP cache, FTS5 indexing, CLI, and doctor."""

from __future__ import annotations

import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rtx.cli import main
from rtx.config import RepoPaths, get_repo_root
from rtx.diff import analyze_impact, capture_snapshot, diff_snapshots, save_snapshot, write_sync_diff
from rtx.http import ConditionalHttpClient
from rtx.index import build_index
from rtx.models import PageMetadata, SourceManifest, format_page_frontmatter, parse_page_frontmatter, wrap_long_lines
from rtx.query import (
    clean_spec_markdown,
    get_status,
    query_api,
    query_component,
    query_copy,
    query_source,
    query_spec,
    query_tokens,
    run_doctor,
    search_corpus,
)


def _write_skill(root: Path) -> None:
    skill = root / "skills" / "expressive-ui" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: expressive-ui\ndescription: Test skill\n---\n\n# Expressive UI\n",
        encoding="utf-8",
    )


def _seed_repo(root: Path) -> RepoPaths:
    (root / ".gitignore").write_text(".corpus/\n.venv/\n__pycache__/\n", encoding="utf-8")
    _write_skill(root)

    # Knowledge layer
    kdir = root / "knowledge"
    (kdir / "02-components").mkdir(parents=True, exist_ok=True)
    (kdir / "05-ux-writing").mkdir(parents=True, exist_ok=True)
    (kdir / "INDEX.md").write_text(
        "# Knowledge Index\n\n- [Split Button](02-components/split-button.md)\n- [Copy Guide](05-ux-writing/style.md)\n",
        encoding="utf-8",
    )
    (kdir / "02-components" / "split-button.md").write_text(
        "# Split Button\n\n## M3 Expressive Anatomy\n\nUse `@OptIn(ExperimentalMaterial3ExpressiveApi::class)` with `SplitButtonLayout`.\n",
        encoding="utf-8",
    )
    (kdir / "05-ux-writing" / "style.md").write_text(
        "# UX Writing & AP Style\n\n## Sentence Case & Confirmations\n\nUse sentence case for button labels and name the destructive verb.\n",
        encoding="utf-8",
    )

    # Mirror layer
    pages = root / ".corpus" / "m3-expressive" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    meta = PageMetadata(
        source_id="m3-expressive",
        url="https://m3.material.io/components/split-button",
        title="Split button",
        section="components",
        fetched_at="2026-11-18T00:00:00Z",
        last_modified="2026-11-01",
        sha256="abc123",
    )
    (pages / "split-button.md").write_text(
        format_page_frontmatter(meta) + "# Split button\n\nA split button pairs a primary action with a trailing menu.\n",
        encoding="utf-8",
    )
    manifest = SourceManifest(
        source_id="m3-expressive",
        name="Material 3 Expressive",
        base_url="https://m3.material.io",
        fetched_at="2026-11-18T00:00:00Z",
        page_count=1,
        status="ok",
        upstream_version="2026-11",
    )
    manifest.write_json(root / ".corpus" / "m3-expressive" / "manifest.json")
    manifest.write_json(root / "manifests" / "sources" / "m3-expressive.json")

    # API manifests
    api_dir = root / "manifests" / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "compose-versions.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "androidx.compose.material3:material3": {
                        "ecosystem": "androidx",
                        "stable": "1.4.0",
                        "alpha": "1.5.0-alpha29",
                        "latest": "1.5.0-rc01",
                    },
                    "org.jetbrains.compose.material3:material3": {
                        "ecosystem": "jetbrains",
                        "stable": "1.9.0",
                        "alpha": "1.13.0-alpha02",
                        "latest": "1.13.0-beta02",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (api_dir / "material3-expressive-surface.json").write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "name": "SplitButtonLayout",
                        "package": "androidx.compose.material3",
                        "kind": "composable",
                        "signature": "fun SplitButtonLayout(leadingButton: @Composable () -> Unit, trailingButton: @Composable () -> Unit)",
                        "annotations": ["ExperimentalMaterial3ExpressiveApi"],
                        "artifact": "androidx.compose.material3:material3",
                        "version": "1.5.0-alpha29",
                        "targets": ["common", "android", "desktop", "ios"],
                        "androidx_signature": "fun SplitButtonLayout(leading, trailing)",
                        "cmp_signature": "fun SplitButtonLayout(leading, trailing)",
                        "parity_status": "parity",
                    },
                    {
                        "name": "VerticalFloatingToolbar",
                        "package": "androidx.compose.material3",
                        "kind": "composable",
                        "signature": "fun VerticalFloatingToolbar(expanded: Boolean)",
                        "annotations": ["ExperimentalMaterial3ExpressiveApi"],
                        "artifact": "androidx.compose.material3:material3",
                        "version": "1.5.0-alpha29",
                        "targets": ["android"],
                        "androidx_signature": "fun VerticalFloatingToolbar(expanded: Boolean)",
                        "cmp_signature": "",
                        "parity_status": "androidx_only",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    # Token manifests
    tok_dir = root / "manifests" / "tokens"
    tok_dir.mkdir(parents=True, exist_ok=True)
    (tok_dir / "m3-expressive-tokens.json").write_text(
        json.dumps(
            {
                "shapes": {
                    "scale": {
                        "large-increased": {
                            "token": "md.sys.shape.corner-value.large-increased",
                            "compose_token": "Shapes.largeIncreased",
                            "value": "20dp",
                        }
                    }
                },
                "tokens": [
                    {
                        "name": "md.sys.motion.spring.expressive.fast.spatial",
                        "category": "motion-spring",
                        "value": "dampingRatio=0.6, stiffness=800.0",
                        "compose_token": "MotionScheme.expressive().fastSpatialSpec()",
                        "spec_version": "M3 Expressive",
                        "notes": "Fast spatial spring for SplitButton morph",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    return RepoPaths(root=root)


def test_frontmatter_and_line_wrapping(tmp_path: Path) -> None:
    meta = PageMetadata(
        source_id="apple-hig",
        url="https://developer.apple.com/design/human-interface-guidelines/buttons",
        title="Buttons",
        section="Components",
        fetched_at="2026-11-18T00:00:00Z",
        last_modified="Thu, 06 Aug 2026 02:58:13 GMT",
        sha256="deadbeef",
    )
    yaml_doc = format_page_frontmatter(meta, style="yaml") + "# Buttons\nBody\n"
    parsed, body_line = parse_page_frontmatter(yaml_doc)
    assert parsed is not None
    assert parsed.source_id == "apple-hig"
    assert parsed.title == "Buttons"
    assert body_line >= 10

    comment_doc = format_page_frontmatter(meta, style="comment") + "# Buttons\n"
    parsed_c, _ = parse_page_frontmatter(comment_doc)
    assert parsed_c is not None
    assert parsed_c.url == meta.url

    long_line = ("word " * 1000).strip()
    wrapped = wrap_long_lines(long_line, max_len=4000)
    assert all(len(line) <= 4000 for line in wrapped.splitlines())

    # List sections tolerance in SourceManifest
    manifest_path = tmp_path / "m.json"
    manifest_path.write_text(json.dumps({"source_id": "x", "sections": ["A", "B"], "page_error_count": 2}), encoding="utf-8")
    loaded = SourceManifest.from_json(manifest_path)
    assert list(loaded.sections.keys()) == ["A", "B"]
    assert loaded.failed_count == 2


def test_conditional_http_client_etag_and_robots(tmp_path: Path) -> None:
    hits = {"doc": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/robots.txt":
                body = b"User-agent: *\nDisallow: /private/\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/doc":
                hits["doc"] += 1
                if self.headers.get("If-None-Match") == '"v1"':
                    self.send_response(304)
                    self.send_header("ETag", '"v1"')
                    self.end_headers()
                    return
                body = b"<h1>Hello Expressive</h1>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("ETag", '"v1"')
                self.send_header("Last-Modified", "Wed, 18 Nov 2026 00:00:00 GMT")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        client = ConditionalHttpClient(cache_dir=tmp_path / "raw")

        first = client.fetch(f"{base}/doc")
        assert first.ok
        assert first.status == 200
        assert "Hello Expressive" in first.text()

        second = client.fetch(f"{base}/doc")
        assert second.ok
        assert second.status == 304
        assert second.not_modified

        blocked = client.fetch(f"{base}/private/secret")
        assert not blocked.ok
        assert blocked.skipped_robots

        client.save_state()
        assert (tmp_path / "raw" / "http_cache.json").is_file()
        assert client.ledger is not None
        summary = client.ledger.summary()
        assert summary["ok"] == 1
        assert summary["not_modified"] == 1
        assert summary["skipped_robots"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_index_queries_and_doctor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    paths = _seed_repo(tmp_path)
    monkeypatch.setenv("RTX_ROOT", str(tmp_path))

    stats = build_index(paths)
    assert stats.knowledge_files == 3
    assert stats.mirror_files == 1
    assert stats.api_symbols == 2
    assert stats.api_versions == 2
    assert stats.design_tokens >= 2

    hits = search_corpus(paths, "SplitButtonLayout")
    assert hits
    assert hits[0].layer == "knowledge"
    assert hits[0].line >= 1

    mirror_hits = search_corpus(paths, "trailing menu", layer="mirror", source="m3-expressive")
    assert mirror_hits
    assert mirror_hits[0].url == "https://m3.material.io/components/split-button"

    api_diff = query_api(paths, "Toolbar", diff_only=True)
    assert len(api_diff["symbols"]) == 1
    assert api_diff["symbols"][0]["name"] == "VerticalFloatingToolbar"

    api_common = query_api(paths, "SplitButtonLayout", target="desktop")
    assert len(api_common["symbols"]) == 1
    api_ios = query_api(paths, "SplitButtonLayout", target="ios")
    assert len(api_ios["symbols"]) == 1

    tok = query_tokens(paths, "largeIncreased", category="shape")
    assert tok["tokens"]
    assert tok["tokens"][0]["value"] == "20dp"

    comp = query_component(paths, "SplitButton")
    assert comp["compose_apis"]
    assert comp["knowledge"]

    copy_res = query_copy(paths, "sentence case destructive")
    assert copy_res["results"]
    assert "05-ux-writing" in copy_res["results"][0]["path"]

    status = get_status(paths)
    assert status["knowledge_count"] == 3
    assert status["index_exists"] is True

    doc_ok = run_doctor(paths)
    assert doc_ok["ok"] is True

    # Test CLI subcommands end-to-end
    assert main(["status", "--json"]) == 0
    assert main(["search", "SplitButton", "--json"]) == 0
    assert main(["api", "material3", "--diff"]) == 0
    assert main(["component", "SplitButton"]) == 0
    assert main(["token", "MotionScheme"]) == 0
    assert main(["copy", "sentence case"]) == 0
    assert main(["doctor"]) == 0
    capsys.readouterr()

    # Create a dummy source adapter and test `rtx sync`
    adapter = tmp_path / "sources" / "demo-src" / "refresh.py"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(
        "import argparse\np = argparse.ArgumentParser()\np.add_argument('--no-assets', action='store_true')\np.parse_args()\nprint('synced demo')\n",
        encoding="utf-8",
    )
    assert main(["sync", "demo-src", "--no-assets", "--workers", "4"]) == 0

    # Doctor should catch broken relative links, empty mirrors, and >4000 char lines
    (tmp_path / ".corpus" / "empty-mirror" / "pages").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge" / "02-components" / "broken.md").write_text(
        "# Broken\n\nSee [missing](does-not-exist.md).\n\n" + ("x" * 4005) + "\n",
        encoding="utf-8",
    )
    doc_bad = run_doctor(paths)
    assert doc_bad["ok"] is False
    assert doc_bad["broken_links"]
    assert doc_bad["long_lines"]
    assert any("empty mirror" in err for err in doc_bad["errors"])
    assert main(["doctor"]) == 1


def test_changelog_and_citation_impact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _seed_repo(tmp_path)
    monkeypatch.setenv("RTX_ROOT", str(tmp_path))

    # Cite mirror page, API symbol, and token in knowledge/
    kfile = tmp_path / "knowledge" / "02-components" / "split-button.md"
    kfile.write_text(
        "# Split Button\n\n"
        "## M3 Expressive Anatomy\n\n"
        "See [M3 Split Button](../../.corpus/m3-expressive/pages/split-button.md).\n"
        "Use `@OptIn(ExperimentalMaterial3ExpressiveApi::class)` with `SplitButtonLayout`.\n"
        "Corner token: `Shapes.largeIncreased`.\n",
        encoding="utf-8",
    )

    before = capture_snapshot(paths)
    save_snapshot(paths, before)

    # Simulate an incremental sync updating a mirror page, graduating an API opt-in, bumping Maven version, and changing a token
    page = tmp_path / ".corpus" / "m3-expressive" / "pages" / "split-button.md"
    meta = PageMetadata(
        source_id="m3-expressive",
        url="https://m3.material.io/components/split-button",
        title="Split button",
        section="components",
        fetched_at="2026-11-19T00:00:00Z",
        last_modified="2026-11-19",
        sha256="def456",
    )
    page.write_text(
        format_page_frontmatter(meta)
        + "# Split button\n\nA split button pairs a primary action with a trailing menu and updated spacing.\n",
        encoding="utf-8",
    )

    # Graduate SplitButtonLayout from @ExperimentalMaterial3ExpressiveApi
    surf_path = tmp_path / "manifests" / "api" / "material3-expressive-surface.json"
    surf = json.loads(surf_path.read_text(encoding="utf-8"))
    surf["symbols"][0]["annotations"] = []
    surf_path.write_text(json.dumps(surf), encoding="utf-8")

    # Bump version
    ver_path = tmp_path / "manifests" / "api" / "compose-versions.json"
    ver = json.loads(ver_path.read_text(encoding="utf-8"))
    ver["artifacts"]["androidx.compose.material3:material3"]["latest"] = "1.5.0"
    ver_path.write_text(json.dumps(ver), encoding="utf-8")

    # Change token value
    tok_path = tmp_path / "manifests" / "tokens" / "m3-expressive-tokens.json"
    tok = json.loads(tok_path.read_text(encoding="utf-8"))
    tok["shapes"]["scale"]["large-increased"]["value"] = "22dp"
    tok_path.write_text(json.dumps(tok), encoding="utf-8")

    after = capture_snapshot(paths)
    diff = diff_snapshots(before, after)
    assert diff["has_changes"] is True
    assert diff["summary"]["pages_modified"] == 1
    assert diff["summary"]["api_version_bumps"] == 1
    assert diff["summary"]["api_opt_in_changes"] == 1
    assert diff["summary"]["tokens_changed"] == 1
    assert diff["pages"]["modified"][0]["changed_sections"][0]["diff_lines"]

    write_sync_diff(paths, diff)
    save_snapshot(paths, after)

    audit = analyze_impact(paths, diff)
    assert len(audit.impacted_sections) == 1
    reasons_text = " ".join(audit.impacted_sections[0]["reasons"])
    assert "mirror page modified" in reasons_text
    assert "opt-in changed" in reasons_text
    assert "token value changed" in reasons_text
    assert any(adv["type"] == "graduated_opt_in_drift" for adv in audit.live_advisories)

    # CLI changelog and impact commands
    assert main(["changelog", "--since-last", "--json"]) == 0
    assert main(["impact", "--json"]) == 0
    capsys.readouterr()

    # Also test `rtx sync --diff-report`
    adapter = tmp_path / "sources" / "demo-src" / "refresh.py"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text("print('ok')\n", encoding="utf-8")
    assert main(["sync", "demo-src", "--diff-report"]) == 0
    out = capsys.readouterr().out
    assert "# Corpus Sync Changelog" in out
    assert (tmp_path / ".corpus" / "sync-diff.json").is_file()


def test_cross_repo_root_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Invoking `rtx` when CWD is another git repo still resolves to the corpus root."""
    external_repo = tmp_path / "external-app"
    (external_repo / ".git").mkdir(parents=True)
    monkeypatch.delenv("RTX_ROOT", raising=False)
    monkeypatch.chdir(external_repo)

    resolved = get_repo_root()
    assert (resolved / "pyproject.toml").is_file()
    assert (resolved / "src" / "rtx").is_dir()
    assert resolved != external_repo


def test_batch_api_component_and_token_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _seed_repo(tmp_path)
    monkeypatch.setenv("RTX_ROOT", str(tmp_path))
    build_index(paths)

    # Batch `rtx api` text and JSON
    assert main(["api", "SplitButtonLayout", "VerticalFloatingToolbar", "--target", "android"]) == 0
    api_text = capsys.readouterr().out
    assert "=== [1/2] API: SplitButtonLayout ===" in api_text
    assert "=== [2/2] API: VerticalFloatingToolbar ===" in api_text
    assert "SplitButtonLayout" in api_text
    assert "VerticalFloatingToolbar" in api_text

    assert main(["api", "SplitButtonLayout", "VerticalFloatingToolbar", "--json"]) == 0
    api_json = json.loads(capsys.readouterr().out)
    assert api_json["queries"] == ["SplitButtonLayout", "VerticalFloatingToolbar"]
    assert len(api_json["results"]) == 2
    assert api_json["results"][0]["symbols"][0]["name"] == "SplitButtonLayout"
    assert api_json["results"][1]["symbols"][0]["name"] == "VerticalFloatingToolbar"

    # Batch `rtx component` text and JSON
    assert main(["component", "SplitButton", "VerticalFloatingToolbar"]) == 0
    comp_text = capsys.readouterr().out
    assert "=== Component: SplitButton ===" in comp_text
    assert "=== Component: VerticalFloatingToolbar ===" in comp_text

    assert main(["component", "SplitButton", "VerticalFloatingToolbar", "--json"]) == 0
    comp_json = json.loads(capsys.readouterr().out)
    assert comp_json["queries"] == ["SplitButton", "VerticalFloatingToolbar"]
    assert len(comp_json["results"]) == 2
    assert comp_json["results"][0]["component"] == "SplitButton"

    # Batch `rtx token` text and JSON
    assert main(["token", "largeIncreased", "MotionScheme"]) == 0
    tok_text = capsys.readouterr().out
    assert "=== [1/2] Token: largeIncreased ===" in tok_text
    assert "=== [2/2] Token: MotionScheme ===" in tok_text

    assert main(["token", "largeIncreased", "MotionScheme", "--json"]) == 0
    tok_json = json.loads(capsys.readouterr().out)
    assert tok_json["queries"] == ["largeIncreased", "MotionScheme"]
    assert len(tok_json["results"]) == 2
    assert tok_json["results"][0]["tokens"][0]["value"] == "20dp"


def _seed_spec_and_sources(root: Path) -> RepoPaths:
    paths = _seed_repo(root)

    # Rich M3 component pages with noise (images, video, Implementation Status, XR) + real Do/Don't captions
    comp_dir = root / ".corpus" / "m3-expressive" / "pages" / "components"
    comp_dir.mkdir(parents=True, exist_ok=True)
    search_meta = PageMetadata(
        source_id="m3-expressive",
        url="https://m3.material.io/components/search",
        title="Search",
        section="components",
        fetched_at="2026-11-19T00:00:00Z",
        last_modified="2026-11-19",
        sha256="search123",
    )
    (comp_dir / "search.md").write_text(
        format_page_frontmatter(search_meta)
        + "# Search\n\n"
        + "![Search](https://firebasestorage.googleapis.com/v0/b/design-spec/o/search.png?alt=media)\n\n"
        + "## Overview\n\n"
        + "- Use search for navigating a product with queries\n"
        + "[Video](https://firebasestorage.googleapis.com/v0/b/design-spec/o/search.mp4?alt=media)\n\n"
        + "_When inputting text, search suggestions appear below the search bar_\n\n"
        + "## Usage\n\n"
        + "Search helps people find information quickly.\n\n"
        + "### Different ways to search\n\n"
        + "- Search bar: Use to search contents in a specific view\n"
        + "- Search app bar: Use when search is the primary global function\n\n"
        + "_Use a maximum of two trailing icons_\n\n"
        + "_Don't place duplicate search controls on the same screen_\n\n"
        + "## Adaptive design\n\n"
        + "- **Docked layout**: Best for medium and expanded windows\n"
        + "- **Full-screen layout**: Default for compact breakpoints\n\n"
        + "## Behavior\n\n"
        + "The back icon releases focus and dismisses suggestions.\n\n"
        + "## XR\n\n"
        + "## Variants\n\n"
        + "Spatial XR search orbiter should never leak into default mobile/desktop dossiers.\n\n"
        + "## Accessibility\n\n"
        + "Screen readers must announce autocomplete results.\n\n"
        + "### Implementation Status: Search\n\n"
        + "| Platform / Library | Type | Status | Reference |\n"
        + "| --- | --- | --- | --- |\n"
        + "| Flutter | FLUTTER_IMPLEMENTATION | AVAILABLE | https://api.flutter.dev |\n"
        + "| Web | LIT_IMPLEMENTATION | UNAVAILABLE | |\n\n"
        + "## Component Design Tokens\n\n"
        + "| Token Set | Token | Context | Value | Resolved |\n"
        + "| --- | --- | --- | --- | --- |\n"
        + "| Search - Bar | `md.comp.search-bar.container.height` | default | `56dp` | `56dp` |\n",
        encoding="utf-8",
    )

    snackbar_meta = PageMetadata(
        source_id="m3-expressive",
        url="https://m3.material.io/components/snackbar",
        title="Snackbar",
        section="components",
        fetched_at="2026-11-19T00:00:00Z",
        last_modified="2026-11-19",
        sha256="snack123",
    )
    (comp_dir / "snackbar.md").write_text(
        format_page_frontmatter(snackbar_meta)
        + "# Snackbar\n\n"
        + "![Snackbar](https://firebasestorage.googleapis.com/v0/b/design-spec/o/snackbar.png?alt=media)\n\n"
        + "## Overview\n\n"
        + "- Snackbars provide brief transient feedback at the bottom of the UI\n\n"
        + "## Usage\n\n"
        + "Snackbars communicate low-priority transient messages without blocking user interaction.\n\n"
        + "| Component | Priority | User action |\n"
        + "| --- | --- | --- |\n"
        + "| Snackbar | Low priority | Optional: disappears automatically |\n"
        + "| Dialog | High priority | Required: blocks app usage |\n\n"
        + "_Avoid placing snackbars in front of navigation components_\n\n"
        + "_Don't use a filled or elevated button in a snackbar_\n",
        encoding="utf-8",
    )

    # Matching Apple HIG page with watchOS noise that must be stripped
    apple_dir = root / ".corpus" / "apple-hig" / "pages"
    apple_dir.mkdir(parents=True, exist_ok=True)
    apple_meta = PageMetadata(
        source_id="apple-hig",
        url="https://developer.apple.com/design/human-interface-guidelines/search-fields",
        title="Search fields",
        section="Components",
        fetched_at="2026-11-19T00:00:00Z",
        last_modified="2026-11-19",
        sha256="apple123",
    )
    (apple_dir / "search-fields.md").write_text(
        format_page_frontmatter(apple_meta)
        + "# Search fields\n\n"
        + "![Apple Search](https://developer.apple.com/images/search.png)\n\n"
        + "A search field lets people search a collection of content.\n\n"
        + "## Best practices\n\n"
        + "**Use placeholder text to clarify scope.** Start filtering immediately as someone types.\n\n"
        + "## Platform considerations\n\n"
        + "*No additional considerations for visionOS*.\n\n"
        + "### macOS\n\n"
        + "Place the search field in the trailing toolbar area.\n\n"
        + "### watchOS\n\n"
        + "Digital Crown watchOS dictation guidance should not leak.\n",
        encoding="utf-8",
    )

    # Synthetic Maven *-sources.jar + source-index.json
    sources_dir = root / ".corpus" / "compose-maven-api" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    carousel_kt = "\n".join(
        [
            "package androidx.compose.material3.carousel",
            "",
            "/**",
            " * Multi-browse carousel displaying large, medium, and small items.",
            " */",
            "@Composable",
            "fun HorizontalMultiBrowseCarousel(",
            "    state: CarouselState,",
            "    preferredItemWidth: Dp,",
            "    modifier: Modifier = Modifier,",
            "    flingBehavior: TargetedFlingBehavior = CarouselDefaults.singleAdvanceFlingBehavior(state = state),",
            "    content: @Composable CarouselItemScope.(itemIndex: Int) -> Unit,",
            ") {",
            "    // Carousel body",
            "    Carousel(state = state, modifier = modifier, flingBehavior = flingBehavior, content = content)",
            "}",
            "",
            "object TabRowDefaults {",
            "    /**",
            "     * Primary indicator aligned to tab content width.",
            "     */",
            "    @Composable",
            "    fun PrimaryIndicator(",
            "        modifier: Modifier = Modifier,",
            "        width: Dp = 24.dp,",
            "    ) {",
            "        Spacer(modifier)",
            "    }",
            "}",
        ]
    )
    jar_name = "cmp-material3-1.13.0-rc01-sources.jar"
    entry_path = "commonMain/androidx/compose/material3/carousel/Carousel.kt"
    with zipfile.ZipFile(sources_dir / jar_name, "w") as zf:
        zf.writestr(entry_path, carousel_kt)

    source_index = {
        "schema_version": 1,
        "generated_at": "2026-11-19T00:00:00Z",
        "sources_dir": ".corpus/compose-maven-api/sources",
        "jar_count": 1,
        "symbol_count": 2,
        "jars": {jar_name: {"jar_name": jar_name, "artifact_key": "cmp-material3", "version": "1.13.0-rc01"}},
        "symbols": [
            {
                "name": "HorizontalMultiBrowseCarousel",
                "owner": "",
                "qualified_name": "HorizontalMultiBrowseCarousel",
                "fq_package": "androidx.compose.material3.carousel",
                "kind": "composable",
                "visibility": "public",
                "is_composable": True,
                "annotations": ["Composable"],
                "jar_name": jar_name,
                "artifact_key": "cmp-material3",
                "coordinate": "org.jetbrains.compose.material3:material3",
                "version": "1.13.0-rc01",
                "platform": "common",
                "entry_path": entry_path,
                "kdoc_start_line": 3,
                "start_line": 6,
                "end_line": 16,
                "has_defaults": True,
                "kotlin_signature": (
                    "@Composable\n"
                    "fun HorizontalMultiBrowseCarousel(\n"
                    "    state: CarouselState,\n"
                    "    preferredItemWidth: Dp,\n"
                    "    modifier: Modifier = Modifier,\n"
                    "    flingBehavior: TargetedFlingBehavior = CarouselDefaults.singleAdvanceFlingBehavior(state = state),\n"
                    "    content: @Composable CarouselItemScope.(itemIndex: Int) -> Unit,\n"
                    ")"
                ),
                "kdoc": "Multi-browse carousel displaying large, medium, and small items.",
            },
            {
                "name": "PrimaryIndicator",
                "owner": "TabRowDefaults",
                "qualified_name": "TabRowDefaults.PrimaryIndicator",
                "fq_package": "androidx.compose.material3.carousel",
                "kind": "composable",
                "visibility": "public",
                "is_composable": True,
                "annotations": ["Composable"],
                "jar_name": jar_name,
                "artifact_key": "cmp-material3",
                "coordinate": "org.jetbrains.compose.material3:material3",
                "version": "1.13.0-rc01",
                "platform": "common",
                "entry_path": entry_path,
                "kdoc_start_line": 19,
                "start_line": 22,
                "end_line": 28,
                "has_defaults": True,
                "kotlin_signature": "@Composable\nfun PrimaryIndicator(\n    modifier: Modifier = Modifier,\n    width: Dp = 24.dp,\n)",
                "kdoc": "Primary indicator aligned to tab content width.",
            },
        ],
    }
    (root / ".corpus" / "compose-maven-api" / "source-index.json").write_text(
        json.dumps(source_index, indent=2), encoding="utf-8"
    )

    # Add HorizontalMultiBrowseCarousel to API manifest (without defaults in javap sig)
    surf_path = root / "manifests" / "api" / "material3-expressive-surface.json"
    surf = json.loads(surf_path.read_text(encoding="utf-8"))
    surf["symbols"].append(
        {
            "name": "HorizontalMultiBrowseCarousel",
            "package": "androidx.compose.material3.carousel",
            "kind": "composable",
            "signature": "@Composable fun HorizontalMultiBrowseCarousel(state: CarouselState, preferredItemWidth: Dp, modifier: Modifier, flingBehavior: TargetedFlingBehavior)",
            "annotations": [],
            "artifact": "org.jetbrains.compose.material3:material3",
            "version": "1.13.0-rc01",
            "targets": ["common", "android", "desktop"],
            "androidx_signature": "@Composable fun HorizontalMultiBrowseCarousel(state: CarouselState, preferredItemWidth: Dp, modifier: Modifier, flingBehavior: TargetedFlingBehavior)",
            "cmp_signature": "@Composable fun HorizontalMultiBrowseCarousel(state: CarouselState, preferredItemWidth: Dp, modifier: Modifier, flingBehavior: TargetedFlingBehavior)",
            "parity_status": "identical",
        }
    )
    surf_path.write_text(json.dumps(surf, indent=2), encoding="utf-8")

    return paths


def test_component_dossier_noise_free_and_spec_and_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _seed_spec_and_sources(tmp_path)
    monkeypatch.setenv("RTX_ROOT", str(tmp_path))

    stats = build_index(paths)
    assert stats.kotlin_sources == 2

    # 1. clean_spec_markdown strips images/videos (including URLs with parens `(1)` and nested alt brackets `[No role]`),
    #    Flutter tables, and watchOS/XR while keeping italic captions
    cleaned = clean_spec_markdown(
        "![Img [No role]](https://firebasestorage.googleapis.com/x%20(1).png?alt=media)\n"
        "[Video](https://firebasestorage.googleapis.com/demo%20(1).mp4?alt=media)\n"
        "_Don't duplicate buttons_\n\n### watchOS\nWatch text\n\n### macOS\nDesktop text\n"
    )
    assert "firebasestorage" not in cleaned
    assert "alt=media" not in cleaned
    assert ".mp4)" not in cleaned
    assert "_Don't duplicate buttons_" in cleaned
    assert "Watch text" not in cleaned
    assert "Desktop text" in cleaned

    # 2. Lossless `rtx component SearchBar` resolves `components/search.md` + `apple-hig/search-fields.md` cleanly
    comp = query_component(paths, "SearchBar")
    assert comp["m3_dossier"]
    dossier = comp["m3_dossier"][0]
    assert dossier["path"].endswith("components/search.md")
    assert "Docked layout" in dossier["adaptive_and_placement"]
    assert any("Don't place duplicate search controls" in r for r in dossier["do_dont_rules"])
    assert "firebasestorage" not in json.dumps(comp)
    assert "FLUTTER_IMPLEMENTATION" not in json.dumps(comp)
    assert "Spatial XR search orbiter" not in json.dumps(comp)
    assert comp["hig_counterparts"]
    assert "trailing toolbar area" in comp["hig_counterparts"][0]["summary"]
    assert "Digital Crown" not in comp["hig_counterparts"][0]["summary"]

    assert main(["component", "SearchBar", "Snackbar"]) == 0
    comp_out = capsys.readouterr().out
    assert "=== Component: SearchBar ===" in comp_out
    assert "[M3 Expressive Official Spec: Search]" in comp_out
    assert "-- Official Do & Don't Rules --" in comp_out
    assert "firebasestorage" not in comp_out
    assert "FLUTTER_IMPLEMENTATION" not in comp_out
    assert "Digital Crown" not in comp_out

    # 3. `rtx spec` returns complete coherent sections with comparison tables & captions
    spec = query_spec(paths, "transient feedback snackbar dialog", limit=3)
    assert spec["sections"]
    top_body = spec["sections"][0]["content"]
    assert "Low priority" in top_body
    assert "_Avoid placing snackbars in front of navigation components_" in top_body
    assert "firebasestorage" not in top_body

    assert main(["spec", "transient feedback snackbar dialog", "--limit", "2"]) == 0
    spec_out = capsys.readouterr().out
    assert "[m3-expressive] Snackbar > Usage" in spec_out
    assert "firebasestorage" not in spec_out

    # Batch quoted `rtx spec`
    assert main(["spec", "transient feedback snackbar", "search bar docked", "--json"]) == 0
    spec_batch = json.loads(capsys.readouterr().out)
    assert len(spec_batch["results"]) == 2

    # 4. `rtx api` enriches symbols with Kotlin default parameters from `kotlin_sources`
    api = query_api(paths, "HorizontalMultiBrowseCarousel")
    assert api["symbols"]
    kt_sigs = api["symbols"][0]["kotlin_signatures"]
    assert any("CarouselDefaults.singleAdvanceFlingBehavior" in s for s in kt_sigs)

    assert main(["api", "HorizontalMultiBrowseCarousel"]) == 0
    api_out = capsys.readouterr().out
    assert "CarouselDefaults.singleAdvanceFlingBehavior" in api_out

    # 5. `rtx source` reads exact KDoc + Kotlin source body with line numbers from cached `*-sources.jar`
    src = query_source(paths, "HorizontalMultiBrowseCarousel")
    assert src["matches"]
    m0 = src["matches"][0]
    assert m0["has_defaults"] is True
    assert "CarouselDefaults.singleAdvanceFlingBehavior" in m0["source_code"]
    assert "Multi-browse carousel" in m0["source_code"]

    src_q = query_source(paths, "TabRowDefaults.PrimaryIndicator", artifact="cmp-material3")
    assert src_q["matches"]
    assert "width: Dp = 24.dp" in src_q["matches"][0]["source_code"]

    assert main(["source", "HorizontalMultiBrowseCarousel", "TabRowDefaults.PrimaryIndicator", "--context-lines", "1"]) == 0
    src_out = capsys.readouterr().out
    assert "HorizontalMultiBrowseCarousel" in src_out
    assert "TabRowDefaults.PrimaryIndicator" in src_out
    assert "CarouselDefaults.singleAdvanceFlingBehavior" in src_out
    assert "width: Dp = 24.dp" in src_out

    # 6. `rtx component` excludes `internal` declarations and surfaces prefixed public composables
    si_path = tmp_path / ".corpus" / "compose-maven-api" / "source-index.json"
    si_data = json.loads(si_path.read_text(encoding="utf-8"))
    si_data["symbols"].extend(
        [
            {
                "name": "SearchBarImpl",
                "owner": "",
                "qualified_name": "SearchBarImpl",
                "fq_package": "androidx.compose.material3",
                "kind": "composable",
                "visibility": "internal",
                "is_composable": True,
                "annotations": ["Composable"],
                "jar_name": "cmp-material3-1.13.0-rc01-sources.jar",
                "artifact_key": "cmp-material3",
                "coordinate": "org.jetbrains.compose.material3:material3",
                "version": "1.13.0-rc01",
                "platform": "common",
                "entry_path": "commonMain/androidx/compose/material3/SearchBar.kt",
                "kdoc_start_line": 1,
                "start_line": 1,
                "end_line": 5,
                "has_defaults": True,
                "kotlin_signature": "@Composable\ninternal fun SearchBarImpl(modifier: Modifier = Modifier)",
                "kdoc": "",
            },
            {
                "name": "DockedSearchBar",
                "owner": "",
                "qualified_name": "DockedSearchBar",
                "fq_package": "androidx.compose.material3",
                "kind": "composable",
                "visibility": "public",
                "is_composable": True,
                "annotations": ["Composable"],
                "jar_name": "cmp-material3-1.13.0-rc01-sources.jar",
                "artifact_key": "cmp-material3",
                "coordinate": "org.jetbrains.compose.material3:material3",
                "version": "1.13.0-rc01",
                "platform": "common",
                "entry_path": "commonMain/androidx/compose/material3/SearchBar.kt",
                "kdoc_start_line": 10,
                "start_line": 10,
                "end_line": 15,
                "has_defaults": True,
                "kotlin_signature": "@Composable\nfun DockedSearchBar(modifier: Modifier = Modifier)",
                "kdoc": "Docked search bar.",
            },
        ]
    )
    si_path.write_text(json.dumps(si_data, indent=2), encoding="utf-8")
    build_index(paths)

    comp_search = query_component(paths, "SearchBar")
    api_names = [s["name"] for s in comp_search["compose_apis"]]
    assert "DockedSearchBar" in api_names
    assert "SearchBarImpl" not in api_names
    assert all("internal fun " not in s for sym in comp_search["compose_apis"] for s in sym.get("kotlin_signatures", []))


