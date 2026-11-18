#!/usr/bin/env python3
"""Live Maven artifact discovery, javap bytecode API surface extraction,
AndroidX vs JetBrains Compose Multiplatform parity diffing, and AndroidX
release notes mirroring.

Outputs:
  - manifests/api/compose-versions.json
  - manifests/api/material3-expressive-surface.json
  - manifests/sources/compose-maven-api.json
  - .corpus/compose-maven-api/jars/*
  - .corpus/compose-maven-api/pages/**/*.md (including INDEX.md & releases/)
  - .corpus/compose-maven-api/manifest.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / ".corpus" / "compose-maven-api"
SOURCE_ID = "compose-maven-api"
USER_AGENT = "TheRoadToExpressive-MavenInspector/1.0 (+local research corpus)"
MAX_LINE_LENGTH = 4000
MAX_WORKERS = 10

GOOGLE_MAVEN = "https://dl.google.com/dl/android/maven2"
MAVEN_CENTRAL = "https://repo1.maven.org/maven2"
JETBRAINS_DEV = "https://maven.pkg.jetbrains.space/public/p/compose/dev"
ANDROID_DEV = "https://developer.android.com"

# Tracked Maven coordinates: (key, repo_base, group_id, artifact_id, role)
MAVEN_ARTIFACTS: list[tuple[str, str, str, str, str]] = [
    ("androidx-compose-bom", GOOGLE_MAVEN, "androidx.compose", "compose-bom", "bom-stable"),
    ("androidx-compose-bom-alpha", GOOGLE_MAVEN, "androidx.compose", "compose-bom-alpha", "bom-alpha"),
    ("androidx-compose-bom-beta", GOOGLE_MAVEN, "androidx.compose", "compose-bom-beta", "bom-beta"),
    ("androidx-material3", GOOGLE_MAVEN, "androidx.compose.material3", "material3", "androidx-ui"),
    ("androidx-material3-nav-suite", GOOGLE_MAVEN, "androidx.compose.material3", "material3-adaptive-navigation-suite", "androidx-ui"),
    ("androidx-adaptive", GOOGLE_MAVEN, "androidx.compose.material3.adaptive", "adaptive", "androidx-adaptive"),
    ("androidx-adaptive-layout", GOOGLE_MAVEN, "androidx.compose.material3.adaptive", "adaptive-layout", "androidx-adaptive"),
    ("androidx-adaptive-navigation", GOOGLE_MAVEN, "androidx.compose.material3.adaptive", "adaptive-navigation", "androidx-adaptive"),
    ("androidx-adaptive-navigation3", GOOGLE_MAVEN, "androidx.compose.material3.adaptive", "adaptive-navigation3", "androidx-adaptive"),
    ("androidx-ui", GOOGLE_MAVEN, "androidx.compose.ui", "ui", "androidx-core"),
    ("androidx-foundation", GOOGLE_MAVEN, "androidx.compose.foundation", "foundation", "androidx-core"),
    ("androidx-animation", GOOGLE_MAVEN, "androidx.compose.animation", "animation", "androidx-core"),
    ("androidx-runtime", GOOGLE_MAVEN, "androidx.compose.runtime", "runtime", "androidx-core"),
    ("androidx-navigation3-runtime", GOOGLE_MAVEN, "androidx.navigation3", "navigation3-runtime", "androidx-nav3"),
    ("androidx-navigation3-ui", GOOGLE_MAVEN, "androidx.navigation3", "navigation3-ui", "androidx-nav3"),
    ("androidx-lifecycle-viewmodel-compose", GOOGLE_MAVEN, "androidx.lifecycle", "lifecycle-viewmodel-compose", "androidx-lifecycle"),
    ("androidx-lifecycle-viewmodel-navigation3", GOOGLE_MAVEN, "androidx.lifecycle", "lifecycle-viewmodel-navigation3", "androidx-lifecycle"),
    ("cmp-gradle-plugin", MAVEN_CENTRAL, "org.jetbrains.compose", "compose-gradle-plugin", "cmp-plugin"),
    ("cmp-runtime", MAVEN_CENTRAL, "org.jetbrains.compose.runtime", "runtime", "cmp-core"),
    ("cmp-ui", MAVEN_CENTRAL, "org.jetbrains.compose.ui", "ui", "cmp-core"),
    ("cmp-ui-graphics", MAVEN_CENTRAL, "org.jetbrains.compose.ui", "ui-graphics", "cmp-core"),
    ("cmp-foundation", MAVEN_CENTRAL, "org.jetbrains.compose.foundation", "foundation", "cmp-core"),
    ("cmp-animation", MAVEN_CENTRAL, "org.jetbrains.compose.animation", "animation", "cmp-core"),
    ("cmp-skiko-awt", MAVEN_CENTRAL, "org.jetbrains.skiko", "skiko-awt", "cmp-skiko"),
    ("cmp-material3", MAVEN_CENTRAL, "org.jetbrains.compose.material3", "material3", "cmp-ui"),
    ("cmp-material3-nav-suite", MAVEN_CENTRAL, "org.jetbrains.compose.material3", "material3-adaptive-navigation-suite", "cmp-ui"),
    ("cmp-adaptive", MAVEN_CENTRAL, "org.jetbrains.compose.material3.adaptive", "adaptive", "cmp-adaptive"),
    ("cmp-adaptive-layout", MAVEN_CENTRAL, "org.jetbrains.compose.material3.adaptive", "adaptive-layout", "cmp-adaptive"),
    ("cmp-adaptive-navigation", MAVEN_CENTRAL, "org.jetbrains.compose.material3.adaptive", "adaptive-navigation", "cmp-adaptive"),
    ("cmp-adaptive-navigation3", MAVEN_CENTRAL, "org.jetbrains.compose.material3.adaptive", "adaptive-navigation3", "cmp-adaptive"),
    ("cmp-navigation3-ui", MAVEN_CENTRAL, "org.jetbrains.androidx.navigation3", "navigation3-ui", "cmp-nav3"),
    ("cmp-lifecycle-viewmodel-compose", MAVEN_CENTRAL, "org.jetbrains.androidx.lifecycle", "lifecycle-viewmodel-compose", "cmp-lifecycle"),
    ("cmp-lifecycle-viewmodel-navigation3", MAVEN_CENTRAL, "org.jetbrains.androidx.lifecycle", "lifecycle-viewmodel-navigation3", "cmp-lifecycle"),
]

# Paired targets for bytecode inspection & parity comparison
PAIRED_BYTECODE_MODULES: list[dict[str, str]] = [
    {"module": "material3", "androidx_key": "androidx-material3", "cmp_key": "cmp-material3"},
    {"module": "material3-adaptive-navigation-suite", "androidx_key": "androidx-material3-nav-suite", "cmp_key": "cmp-material3-nav-suite"},
    {"module": "adaptive", "androidx_key": "androidx-adaptive", "cmp_key": "cmp-adaptive"},
    {"module": "adaptive-layout", "androidx_key": "androidx-adaptive-layout", "cmp_key": "cmp-adaptive-layout"},
    {"module": "adaptive-navigation", "androidx_key": "androidx-adaptive-navigation", "cmp_key": "cmp-adaptive-navigation"},
    {"module": "adaptive-navigation3", "androidx_key": "androidx-adaptive-navigation3", "cmp_key": "cmp-adaptive-navigation3"},
    {"module": "navigation3-ui", "androidx_key": "androidx-navigation3-ui", "cmp_key": "cmp-navigation3-ui"},
]

EXTRA_BYTECODE_MODULES: list[dict[str, str]] = [
    {"module": "navigation3-runtime", "key": "androidx-navigation3-runtime", "platform": "android"},
]

RELEASE_NOTE_PATHS: list[tuple[str, str]] = [
    ("compose-material3", "/jetpack/androidx/releases/compose-material3"),
    ("compose-material3-adaptive", "/jetpack/androidx/releases/compose-material3-adaptive"),
    ("compose-ui", "/jetpack/androidx/releases/compose-ui"),
    ("compose-foundation", "/jetpack/androidx/releases/compose-foundation"),
    ("navigation3", "/jetpack/androidx/releases/navigation3"),
]

EXPRESSIVE_WATCHLIST: list[tuple[str, str]] = [
    ("MaterialExpressiveTheme", "Theme & Tokens"),
    ("MaterialTheme", "Theme & Tokens"),
    ("MotionScheme", "Theme & Tokens"),
    ("Shapes", "Theme & Tokens"),
    ("Typography", "Theme & Tokens"),
    ("ColorScheme", "Theme & Tokens"),
    ("MaterialShapes", "Theme & Tokens"),
    ("ButtonGroup", "Expressive Buttons"),
    ("ButtonGroupDefaults", "Expressive Buttons"),
    ("ButtonGroupScope", "Expressive Buttons"),
    ("ButtonDefaults", "Expressive Buttons"),
    ("SplitButtonLayout", "Expressive Buttons"),
    ("SplitButtonDefaults", "Expressive Buttons"),
    ("ToggleButton", "Expressive Buttons"),
    ("ToggleButtonDefaults", "Expressive Buttons"),
    ("IconToggleButton", "Expressive Buttons"),
    ("FilledIconToggleButton", "Expressive Buttons"),
    ("OutlinedIconToggleButton", "Expressive Buttons"),
    ("FloatingActionButtonMenu", "Expressive Actions & Toolbars"),
    ("FloatingActionButtonMenuItem", "Expressive Actions & Toolbars"),
    ("ToggleFloatingActionButton", "Expressive Actions & Toolbars"),
    ("ToggleFloatingActionButtonDefaults", "Expressive Actions & Toolbars"),
    ("HorizontalFloatingToolbar", "Expressive Actions & Toolbars"),
    ("VerticalFloatingToolbar", "Expressive Actions & Toolbars"),
    ("FloatingToolbarDefaults", "Expressive Actions & Toolbars"),
    ("FloatingToolbarColors", "Expressive Actions & Toolbars"),
    ("FloatingToolbarScrollBehavior", "Expressive Actions & Toolbars"),
    ("LoadingIndicator", "Expressive Progress & Loading"),
    ("ContainedLoadingIndicator", "Expressive Progress & Loading"),
    ("LoadingIndicatorDefaults", "Expressive Progress & Loading"),
    ("PullToRefreshDefaults", "Expressive Progress & Loading"),
    ("LinearWavyProgressIndicator", "Expressive Progress & Loading"),
    ("CircularWavyProgressIndicator", "Expressive Progress & Loading"),
    ("WavyProgressIndicatorDefaults", "Expressive Progress & Loading"),
    ("MediumFlexibleTopAppBar", "Expressive Navigation & App Bars"),
    ("LargeFlexibleTopAppBar", "Expressive Navigation & App Bars"),
    ("TopAppBarDefaults", "Expressive Navigation & App Bars"),
    ("AppBarRow", "Expressive Navigation & App Bars"),
    ("AppBarColumn", "Expressive Navigation & App Bars"),
    ("WideNavigationRail", "Expressive Navigation & App Bars"),
    ("WideNavigationRailItem", "Expressive Navigation & App Bars"),
    ("WideNavigationRailDefaults", "Expressive Navigation & App Bars"),
    ("WideNavigationRailState", "Expressive Navigation & App Bars"),
    ("ShortNavigationBar", "Expressive Navigation & App Bars"),
    ("ShortNavigationBarItem", "Expressive Navigation & App Bars"),
    ("ShortNavigationBarDefaults", "Expressive Navigation & App Bars"),
    ("ListItem", "Expressive Lists, Search & Carousel"),
    ("SegmentedListItem", "Expressive Lists, Search & Carousel"),
    ("ListItemDefaults", "Expressive Lists, Search & Carousel"),
    ("ListItemShapes", "Expressive Lists, Search & Carousel"),
    ("HorizontalMultiBrowseCarousel", "Expressive Lists, Search & Carousel"),
    ("HorizontalUncontainedCarousel", "Expressive Lists, Search & Carousel"),
    ("HorizontalCenteredHeroCarousel", "Expressive Lists, Search & Carousel"),
    ("SearchBar", "Expressive Lists, Search & Carousel"),
    ("ExpandedFullScreenSearchBar", "Expressive Lists, Search & Carousel"),
    ("ExpandedDockedSearchBar", "Expressive Lists, Search & Carousel"),
    ("NavigationSuiteScaffold", "Adaptive & Navigation 3"),
    ("NavigationSuiteScaffoldLayout", "Adaptive & Navigation 3"),
    ("NavigationSuite", "Adaptive & Navigation 3"),
    ("NavigationSuiteType", "Adaptive & Navigation 3"),
    ("ListDetailPaneScaffold", "Adaptive & Navigation 3"),
    ("SupportingPaneScaffold", "Adaptive & Navigation 3"),
    ("ListDetailSceneStrategy", "Adaptive & Navigation 3"),
    ("SupportingPaneSceneStrategy", "Adaptive & Navigation 3"),
    ("ThreePaneScaffoldScene", "Adaptive & Navigation 3"),
    ("ThreePaneScaffoldNavigator", "Adaptive & Navigation 3"),
    ("PaneScaffoldDirective", "Adaptive & Navigation 3"),
    ("WindowAdaptiveInfo", "Adaptive & Navigation 3"),
    ("currentWindowAdaptiveInfo", "Adaptive & Navigation 3"),
    ("NavDisplay", "Adaptive & Navigation 3"),
    ("NavEntry", "Adaptive & Navigation 3"),
    ("NavBackStack", "Adaptive & Navigation 3"),
    ("rememberNavBackStack", "Adaptive & Navigation 3"),
    ("SceneStrategy", "Adaptive & Navigation 3"),
    ("SinglePaneSceneStrategy", "Adaptive & Navigation 3"),
    ("DialogSceneStrategy", "Adaptive & Navigation 3"),
]

OPT_IN_ANNOTATIONS = {
    "androidx.compose.material3.ExperimentalMaterial3ExpressiveApi",
    "androidx.compose.material3.ExperimentalMaterial3Api",
    "androidx.compose.material3.adaptive.ExperimentalMaterial3AdaptiveApi",
    "androidx.compose.material3.windowsizeclass.ExperimentalMaterial3WindowSizeClassApi",
    "androidx.compose.foundation.ExperimentalFoundationApi",
    "androidx.compose.foundation.layout.ExperimentalLayoutApi",
    "androidx.compose.ui.ExperimentalComposeUiApi",
    "androidx.compose.animation.ExperimentalAnimationApi",
    "androidx.compose.animation.ExperimentalSharedTransitionApi",
    "androidx.navigation3.runtime.ExperimentalNavigation3Api",
    "androidx.navigation3.ui.ExperimentalNavigation3Api",
}


# ---------------------------------------------------------------------------
# Helpers & HTTP
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, obj: Any) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def wrap_long_lines(text: str, limit: int = MAX_LINE_LENGTH) -> str:
    """Ensure every line stays <= limit characters for grep friendliness."""
    out: list[str] = []
    for line in text.splitlines():
        if len(line) <= limit:
            out.append(line)
        else:
            # Break cleanly at spaces or commas if possible
            rem = line
            while len(rem) > limit:
                cut = rem.rfind(" ", 0, limit)
                if cut < limit // 2:
                    cut = rem.rfind(",", 0, limit)
                if cut < limit // 2:
                    cut = limit
                else:
                    cut += 1
                out.append(rem[:cut].rstrip())
                rem = rem[cut:].lstrip()
            if rem:
                out.append(rem)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def render_frontmatter(
    *,
    source_id: str,
    url: str,
    title: str,
    section: str,
    fetched_at: str,
    last_modified: str | None,
    body: str,
) -> str:
    body_bytes = body.encode("utf-8")
    digest = sha256_bytes(body_bytes)
    safe_title = title.replace('"', '\\"')
    lines = [
        "---",
        f"source_id: {source_id}",
        f"url: {url}",
        f'title: "{safe_title}"',
        f"section: {section}",
        f"fetched_at: {fetched_at}",
        f"last_modified: {last_modified or ''}",
        f"sha256: {digest}",
        "---",
        "",
    ]
    return wrap_long_lines("\n".join(lines) + body)


class FetchError(RuntimeError):
    def __init__(self, url: str, message: str, status: int | None = None):
        super().__init__(f"{url}: {message}")
        self.url = url
        self.message = message
        self.status = status


def fetch_url(
    url: str,
    *,
    accept: str = "*/*",
    etag: str | None = None,
    last_modified: str | None = None,
    attempts: int = 4,
    timeout: float = 30.0,
) -> tuple[int, bytes, dict[str, str]]:
    """Fetch URL with conditional headers and retry on transient TLS/HTTP errors."""
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Encoding": "gzip",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            with urlopen(Request(url, headers=headers), timeout=timeout) as resp:
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                data = resp.read()
                if "gzip" in hdrs.get("content-encoding", "").lower():
                    data = gzip.decompress(data)
                return resp.status, data, hdrs
        except HTTPError as err:
            if err.code == 304:
                hdrs = {k.lower(): v for k, v in err.headers.items()}
                return 304, b"", hdrs
            if err.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise FetchError(url, f"HTTP {err.code}", status=err.code) from err
            last_err = err
        except (URLError, ssl.SSLError, TimeoutError, OSError) as err:
            last_err = err
        time.sleep(min(12.0, 1.2 * (2 ** (attempt - 1))))
    raise FetchError(url, str(last_err or "unknown error"))


# ---------------------------------------------------------------------------
# Version Parsing & Maven Resolution
# ---------------------------------------------------------------------------

STAGE_ORDER = {
    "dev": 0,
    "snapshot": 0,
    "alpha": 1,
    "a": 1,
    "beta": 2,
    "b": 2,
    "rc": 3,
    "cr": 3,
}


def parse_version(ver: str) -> tuple[tuple[int, ...], int, int, str]:
    """Sort key: ((major, minor, patch, ...), stage_rank, stage_num, raw)."""
    base, _, pre = ver.partition("-")
    nums: list[int] = []
    for part in base.split("."):
        m = re.match(r"(\d+)", part)
        nums.append(int(m.group(1)) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    if not pre:
        return (tuple(nums), 4, 0, ver)
    pre_low = pre.lower()
    m = re.match(r"([a-z]+)[._-]?(\d+)?", pre_low)
    if m:
        tag = m.group(1)
        num = int(m.group(2)) if m.group(2) else 0
        rank = STAGE_ORDER.get(tag, 0)
        return (tuple(nums), rank, num, ver)
    return (tuple(nums), 0, 0, ver)


def classify_channel(ver: str) -> str:
    if "-" not in ver:
        return "stable"
    pre = ver.split("-", 1)[1].lower()
    if pre.startswith("rc"):
        return "rc"
    if pre.startswith("beta") or re.match(r"^b\d", pre):
        return "beta"
    if pre.startswith("alpha") or re.match(r"^a\d", pre):
        return "alpha"
    return "dev"


def summarize_versions(versions: list[str]) -> dict[str, Any]:
    ordered = sorted(set(versions), key=parse_version)
    by_channel: dict[str, str | None] = {
        "stable": None,
        "rc": None,
        "beta": None,
        "alpha": None,
        "dev": None,
    }
    for v in ordered:
        ch = classify_channel(v)
        by_channel[ch] = v
    return {
        "total_versions": len(ordered),
        "stable": by_channel["stable"] or "",
        "rc": by_channel["rc"] or "",
        "beta": by_channel["beta"] or "",
        "alpha": by_channel["alpha"] or "",
        "dev": by_channel["dev"] or "",
        "latest": ordered[-1] if ordered else "",
        "latest_any": ordered[-1] if ordered else None,
        "latest_stable": by_channel["stable"],
        "latest_rc": by_channel["rc"],
        "latest_beta": by_channel["beta"],
        "latest_alpha": by_channel["alpha"],
        "latest_dev": by_channel["dev"],
        "recent_versions": ordered[-10:],
    }


def maven_path(group_id: str, artifact_id: str) -> str:
    return f"{group_id.replace('.', '/')}/{artifact_id}"


def fetch_maven_versions(repo_base: str, group_id: str, artifact_id: str, *, attempts: int = 4, timeout: float = 30.0) -> list[str]:
    url = f"{repo_base}/{maven_path(group_id, artifact_id)}/maven-metadata.xml"
    _, data, _ = fetch_url(url, accept="application/xml,text/xml", attempts=attempts, timeout=timeout)
    root = ET.fromstring(data)
    return [el.text.strip() for el in root.findall(".//versioning/versions/version") if el.text]


def parse_bom_pom(repo_base: str, group_id: str, artifact_id: str, version: str) -> dict[str, str]:
    url = f"{repo_base}/{maven_path(group_id, artifact_id)}/{version}/{artifact_id}-{version}.pom"
    _, data, _ = fetch_url(url, accept="application/xml,text/xml")
    root = ET.fromstring(data)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}", 1)[0] + "}"
    pins: dict[str, str] = {}
    for dep in root.findall(f".//{ns}dependencyManagement/{ns}dependencies/{ns}dependency"):
        g = dep.findtext(f"{ns}groupId", "").strip()
        a = dep.findtext(f"{ns}artifactId", "").strip()
        v = dep.findtext(f"{ns}version", "").strip()
        if g and a and v:
            pins[f"{g}:{a}"] = v
    return pins


def inspect_cmp_module_redirects(repo_base: str, group_id: str, artifact_id: str, version: str) -> dict[str, Any]:
    base_dir = f"{repo_base}/{maven_path(group_id, artifact_id)}/{version}"
    mod_url = f"{base_dir}/{artifact_id}-{version}.module"
    result: dict[str, Any] = {"module_url": mod_url, "android_redirect": None, "desktop_artifact": None}
    try:
        _, data, _ = fetch_url(mod_url, accept="application/json")
        mod = json.loads(data.decode("utf-8"))
    except Exception:
        return result

    for v in mod.get("variants", []):
        vname = v.get("name", "")
        avail = (v.get("available-at") or {}).get("url")
        if vname == "androidApiElements-published" and avail:
            android_mod_url = urllib.parse.urljoin(mod_url, avail)
            try:
                _, adata, _ = fetch_url(android_mod_url, accept="application/json")
                amod = json.loads(adata.decode("utf-8"))
                deps = []
                for av in amod.get("variants", []):
                    if av.get("name") == "androidApiElements-published":
                        for d in av.get("dependencies", []):
                            dg = d.get("group", "")
                            dm = d.get("module", "")
                            dv = (d.get("version") or {}).get("requires")
                            if dg.startswith("androidx.") and dv:
                                deps.append(f"{dg}:{dm}:{dv}")
                result["android_redirect"] = sorted(set(deps))
            except Exception:
                pass
        elif vname == "desktopApiElements-published" and avail:
            result["desktop_artifact"] = urllib.parse.urljoin(mod_url, avail)
    return result


# ---------------------------------------------------------------------------
# Artifact Download (JAR / AAR -> classes.jar)
# ---------------------------------------------------------------------------

def resolve_artifact_binary_url(repo_base: str, group_id: str, artifact_id: str, version: str, target: str) -> tuple[str, str]:
    """Resolve the downloadable .jar or .aar URL via Gradle .module metadata.
    target is 'android' or 'desktop'. Returns (url, ext).
    """
    mod_url = f"{repo_base}/{maven_path(group_id, artifact_id)}/{version}/{artifact_id}-{version}.module"
    _, data, _ = fetch_url(mod_url, accept="application/json")
    mod = json.loads(data.decode("utf-8"))

    want_variant = "androidApiElements-published" if target == "android" else "desktopApiElements-published"
    for v in mod.get("variants", []):
        if v.get("name") == want_variant:
            avail = (v.get("available-at") or {}).get("url")
            if avail:
                sub_url = urllib.parse.urljoin(mod_url, avail)
                _, sdata, _ = fetch_url(sub_url, accept="application/json")
                smod = json.loads(sdata.decode("utf-8"))
                for sv in smod.get("variants", []):
                    if sv.get("name") == want_variant and sv.get("files"):
                        fobj = sv["files"][0]
                        fname = fobj.get("url") or fobj["name"]
                        ext = Path(fname).suffix.lower()
                        return urllib.parse.urljoin(sub_url, fname), ext
            elif v.get("files"):
                fobj = v["files"][0]
                fname = fobj.get("url") or fobj["name"]
                ext = Path(fname).suffix.lower()
                return urllib.parse.urljoin(mod_url, fname), ext
    # Fallback to direct jar/aar
    ext = ".aar" if target == "android" else ".jar"
    return f"{repo_base}/{maven_path(group_id, artifact_id)}/{version}/{artifact_id}-{version}{ext}", ext


def ensure_jar_on_disk(
    jars_dir: Path,
    cache_meta: dict[str, Any],
    name_key: str,
    url: str,
    ext: str,
    *,
    refresh: bool = False,
    check_only: bool = False,
) -> tuple[Path | None, str]:
    """Download JAR or AAR (extracting classes.jar) into jars_dir. Returns (jar_path, status)."""
    jar_path = jars_dir / f"{name_key}.jar"
    prev = cache_meta.get(name_key) or {}
    if jar_path.exists() and prev.get("url") == url and not refresh and not check_only:
        return jar_path, "cached"

    validators = prev if prev.get("url") == url else {}
    status_code, data, hdrs = fetch_url(
        url,
        etag=validators.get("etag"),
        last_modified=validators.get("last_modified"),
    )
    if status_code == 304 and jar_path.exists():
        return jar_path, "unchanged"
    if check_only:
        changed = prev.get("url") != url or prev.get("sha256") != sha256_bytes(data)
        return (jar_path if jar_path.exists() else None), ("changed" if changed else "unchanged")

    if ext == ".aar":
        with zipfile.ZipFile(io_bytes(data)) as zf:
            if "classes.jar" not in zf.namelist():
                raise RuntimeError(f"AAR {url} missing classes.jar")
            jar_bytes = zf.read("classes.jar")
    else:
        jar_bytes = data

    write_bytes(jar_path, jar_bytes)
    cache_meta[name_key] = {
        "url": url,
        "ext": ext,
        "etag": hdrs.get("etag"),
        "last_modified": hdrs.get("last-modified"),
        "sha256": sha256_bytes(jar_bytes),
        "bytes": len(jar_bytes),
    }
    return jar_path, "downloaded"


def io_bytes(data: bytes):
    import io
    return io.BytesIO(data)


# ---------------------------------------------------------------------------
# javap Bytecode Inspector
# ---------------------------------------------------------------------------

KT_INLINE_SUFFIX_RE = re.compile(r"-[A-Za-z0-9_-]{7}$")
COMP_SOURCE_INFO_RE = re.compile(r"C\(([^)]+)\)N\(([^)]*)\)")


def simplify_type(raw_type: str) -> str:
    t = raw_type.strip()
    t = t.replace("java.lang.String", "String")
    t = t.replace("java.lang.Boolean", "Boolean")
    t = t.replace("java.lang.Integer", "Int")
    t = t.replace("java.lang.Float", "Float")
    t = t.replace("java.lang.Long", "Long")
    t = t.replace("java.lang.Object", "Any")
    t = t.replace("kotlin.Unit", "Unit")
    t = t.replace("kotlin.Boolean", "Boolean")
    t = t.replace("kotlin.Int", "Int")
    t = t.replace("kotlin.Float", "Float")
    t = t.replace("kotlin.Long", "Long")
    t = t.replace("kotlin.String", "String")
    # Shorten common androidx / kotlin packages for display while preserving clarity
    t = re.sub(r"\b(?:java\.util|kotlin\.collections|kotlin\.jvm\.functions)\.", "", t)
    t = re.sub(r"\bandroidx\.compose\.(?:material3(?:\.adaptive(?:\.navigation3|\.layout|\.navigation)?)?|ui(?:\.[a-z]+)?|foundation(?:\.[a-z]+)?|runtime|animation(?:\.core)?)\.", "", t)
    t = re.sub(r"\bandroidx\.navigation3\.(?:runtime|ui)\.", "", t)
    t = re.sub(r"\bandroidx\.graphics\.shapes\.", "", t)
    t = re.sub(r"\?\s+super\s+", "", t)
    t = re.sub(r"\?\s+extends\s+", "", t)
    return t


def split_top_level_args(arg_str: str) -> list[str]:
    args: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in arg_str:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            item = "".join(cur).strip()
            if item:
                args.append(item)
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        args.append(tail)
    return args


def should_inspect_class(entry_name: str) -> bool:
    if not entry_name.endswith(".class"):
        return False
    if entry_name.startswith("META-INF/") or entry_name in {"module-info.class", "package-info.class"}:
        return False
    if "/internal/" in entry_name:
        return False
    base = entry_name[:-6]
    # Keep top-level classes and named nested classes (e.g., Foo$Companion),
    # skip anonymous/lambda/synthetic $ classes.
    if "$" in base:
        parts = base.split("$")[1:]
        for p in parts:
            if not p or p[0].isdigit() or p in {"WhenMappings", "DefaultImpls"} or "inlined" in p or "lambda" in p:
                return False
    return True


def parse_javap_output(output: str) -> dict[str, dict[str, Any]]:
    """Parse `javap -p -v` output into structured class + method records."""
    classes: dict[str, dict[str, Any]] = {}
    blocks = re.split(r"(?=^Classfile )", output, flags=re.M)

    for block in blocks:
        if not block.startswith("Classfile "):
            continue
        lines = block.splitlines()
        class_fqcn = ""
        class_kind = "class"
        is_public_class = False
        class_annotations: list[str] = []
        class_deprecated = False
        methods: list[dict[str, Any]] = []
        fields: list[dict[str, Any]] = []

        # Map constant-pool sourceInformation strings if present
        cp_source_info: dict[str, list[str]] = {}
        i = 0
        n = len(lines)

        # Scan constant pool & class declaration
        while i < n:
            line = lines[i]
            m_src = COMP_SOURCE_INFO_RE.search(line)
            if m_src and " = Utf8 " in line:
                cname = m_src.group(1)
                pnames = [p.strip() for p in m_src.group(2).split(",") if p.strip()]
                if pnames:
                    cp_source_info.setdefault(cname, pnames)
            m_cls = re.match(r"^(public\s+)?(?:final\s+|abstract\s+|sealed\s+)?(class|interface|enum)\s+([^\s<{]+)", line)
            if m_cls and not line.startswith(" "):
                is_public_class = bool(m_cls.group(1))
                class_kind = m_cls.group(2)
                class_fqcn = m_cls.group(3)
            if line.strip() == "{":
                i += 1
                break
            i += 1

        if not class_fqcn or not is_public_class:
            continue

        # Read member declarations until closing `}` and trailing class attributes
        in_class_body = True
        while i < n:
            line = lines[i]
            if in_class_body and line.strip() == "}":
                in_class_body = False
                i += 1
                continue

            if not in_class_body:
                # Trailing class-level attributes (Deprecated, RuntimeVisible/InvisibleAnnotations)
                s = line.strip()
                if s == "Deprecated: true":
                    class_deprecated = True
                elif re.match(r"^[a-zA-Z0-9_.]+(?:\(|$)", s) and "." in s and not s.startswith(("Compiled", "SourceFile", "InnerClasses", "Nest", "Bootstrap", "Runtime", "kotlin.Metadata")):
                    ann = s.split("(", 1)[0].strip()
                    if ann not in class_annotations:
                        class_annotations.append(ann)
                i += 1
                continue

            # Field declaration: `  public static final ...;`
            m_field = re.match(r"^  (public\s+.+?\s+([A-Za-z0-9_$]+));\s*$", line)
            if m_field and "(" not in line:
                fdecl = m_field.group(1)
                fname = m_field.group(2)
                i += 1
                f_anns: list[str] = []
                f_dep = False
                while i < n and lines[i].startswith("    "):
                    sub = lines[i].strip()
                    if sub == "Deprecated: true":
                        f_dep = True
                    elif "." in sub and re.match(r"^[a-zA-Z0-9_.]+(?:\(|$)", sub):
                        ann = sub.split("(", 1)[0].strip()
                        if ann not in f_anns:
                            f_anns.append(ann)
                    i += 1
                if fname not in {"INSTANCE", "Companion", "$stable"}:
                    fields.append({"name": fname, "decl": fdecl, "annotations": f_anns, "deprecated": f_dep})
                continue

            # Method declaration: `  public ... name(...);`
            m_meth = re.match(r"^  (public\s+[^\(]+?\s+([^\s(]+)\((.*)\)(?:\s+throws\s+[^;]+)?);\s*$", line)
            if m_meth:
                full_decl = m_meth.group(1)
                jvm_name = m_meth.group(2)
                raw_params = split_top_level_args(m_meth.group(3))
                is_static = " static " in f" {full_decl} "
                # Extract return type from prefix before jvm_name
                prefix = full_decl[: full_decl.rfind(jvm_name)].strip()
                tokens = prefix.split()
                ret_type = tokens[-1] if tokens else "void"

                i += 1
                m_anns: list[str] = []
                m_dep = False
                m_sig: str | None = None
                m_source_info_str: str | None = None
                local_vars: dict[int, str] = {}
                in_lvt = False

                while i < n and lines[i].startswith("    "):
                    sub = lines[i].strip()
                    if sub == "Deprecated: true":
                        m_dep = True
                    elif sub.startswith("Signature:"):
                        m_sig = sub.split("//", 1)[1].strip() if "//" in sub else None
                    elif "String C(" in sub and ")N(" in sub:
                        m_source_info_str = sub.split("//", 1)[1].strip()
                    elif sub == "LocalVariableTable:":
                        in_lvt = True
                    elif in_lvt:
                        if sub.startswith(("Start ", "LineNumberTable", "StackMapTable", "Runtime", "Signature:", "Exceptions:", "MethodParameters:")):
                            if not sub.startswith("Start "):
                                in_lvt = False
                        else:
                            parts = sub.split()
                            # Format: Start Length Slot Name Signature
                            if len(parts) >= 5 and parts[2].isdigit():
                                slot = int(parts[2])
                                vname = parts[3]
                                if slot not in local_vars:
                                    local_vars[slot] = vname
                    elif lines[i].startswith("        ") and "." in sub and re.match(r"^[a-zA-Z0-9_.]+(?:\(|$)", sub):
                        ann = sub.split("(", 1)[0].strip()
                        if ann not in m_anns:
                            m_anns.append(ann)
                    i += 1

                # Filter synthetic / bridge / internal Compose compiler helpers
                if (
                    jvm_name.startswith(("access$", "get$", "set$"))
                    or "$default" in jvm_name
                    or "$lambda$" in jvm_name
                    or jvm_name in {"copy$default", "equals", "hashCode", "toString"}
                ):
                    continue

                kotlin_name = KT_INLINE_SUFFIX_RE.sub("", jvm_name)
                is_composable = "androidx.compose.runtime.Composable" in m_anns

                # Strip Compose compiler synthetic trailing parameters (Composer, int $changed..., int $default...)
                display_types = list(raw_params)
                if is_composable:
                    while display_types and display_types[-1] == "int":
                        display_types.pop()
                    if display_types and display_types[-1] == "androidx.compose.runtime.Composer":
                        display_types.pop()
                        # Check if another trailing int group exists before Composer? No, Composer is before $changed ints.

                # Resolve parameter names
                param_names: list[str] = []
                if m_source_info_str:
                    msi = COMP_SOURCE_INFO_RE.search(m_source_info_str)
                    if msi:
                        param_names = [p.split(":", 1)[0].strip() for p in msi.group(2).split(",") if p.strip()]
                if len(param_names) != len(display_types):
                    # Try LocalVariableTable
                    start_slot = 0 if is_static else 1
                    lvt_names: list[str] = []
                    slot_cursor = start_slot
                    for ptype in display_types:
                        vname = local_vars.get(slot_cursor, "")
                        if vname and not vname.startswith("$"):
                            lvt_names.append(vname)
                        else:
                            lvt_names.append(f"p{len(lvt_names)}")
                        slot_cursor += 2 if ptype in {"long", "double"} else 1
                    if any(not x.startswith("p") for x in lvt_names):
                        param_names = lvt_names
                    else:
                        param_names = [f"p{idx}" for idx in range(len(display_types))]

                # Also extract inline value-class type hints from sourceInformation (e.g. `color:c#ui.graphics.Color`)
                type_hints: dict[str, str] = {}
                if m_source_info_str:
                    msi = COMP_SOURCE_INFO_RE.search(m_source_info_str)
                    if msi:
                        for raw_p in msi.group(2).split(","):
                            if ":c#" in raw_p:
                                pn, _, hint = raw_p.partition(":c#")
                                type_hints[pn.strip()] = hint.strip().split(".")[-1]

                params_out: list[dict[str, str]] = []
                for idx, ptype in enumerate(display_types):
                    pname = param_names[idx] if idx < len(param_names) else f"p{idx}"
                    stype = type_hints.get(pname) or simplify_type(ptype)
                    params_out.append({"name": pname, "type": stype, "raw_type": ptype})

                methods.append({
                    "name": kotlin_name,
                    "jvm_name": jvm_name,
                    "is_static": is_static,
                    "is_composable": is_composable,
                    "return_type": simplify_type(ret_type),
                    "params": params_out,
                    "annotations": m_anns,
                    "deprecated": m_dep,
                    "signature": m_sig,
                })
                continue

            i += 1

        # Inherit class-level annotations for experimental status
        for m in methods:
            all_anns = sorted(set(class_annotations) | set(m["annotations"]))
            m["opt_ins"] = [a.rsplit(".", 1)[-1] for a in all_anns if a in OPT_IN_ANNOTATIONS or "Experimental" in a]
            m["deprecated"] = m["deprecated"] or class_deprecated

        pkg = class_fqcn.rsplit(".", 1)[0] if "." in class_fqcn else ""
        simple = class_fqcn.rsplit(".", 1)[-1]
        classes[class_fqcn] = {
            "fqcn": class_fqcn,
            "package": pkg,
            "simple_name": simple,
            "kind": class_kind,
            "annotations": class_annotations,
            "opt_ins": [a.rsplit(".", 1)[-1] for a in class_annotations if a in OPT_IN_ANNOTATIONS or "Experimental" in a],
            "deprecated": class_deprecated,
            "methods": methods,
            "fields": fields,
        }
    return classes


def inspect_jar_with_javap(jar_path: Path, workers: int = 8) -> dict[str, dict[str, Any]]:
    with zipfile.ZipFile(jar_path) as zf:
        class_names = sorted(
            n[:-6].replace("/", ".")
            for n in zf.namelist()
            if should_inspect_class(n)
        )
    if not class_names:
        return {}

    batches = [class_names[i : i + 30] for i in range(0, len(class_names), 30)]
    merged: dict[str, dict[str, Any]] = {}

    def run_batch(batch: list[str]) -> dict[str, dict[str, Any]]:
        out = subprocess.check_output(
            ["javap", "-cp", str(jar_path), "-p", "-v", *batch],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return parse_javap_output(out)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        for res in pool.map(run_batch, batches):
            merged.update(res)
    return merged


def extract_token_constants(jar_path: Path, workers: int = 8) -> dict[str, dict[str, str]]:
    """Run `javap -constants -c -p` on `androidx/compose/material3/tokens/*.class`
    to extract exact compiled numeric constants and token getter values (e.g.
    NavigationRailCollapsedTokens.ContainerWidth = 96.0.dp).
    """
    with zipfile.ZipFile(jar_path) as zf:
        token_classes = sorted(
            n[:-6].replace("/", ".")
            for n in zf.namelist()
            if n.endswith(".class") and "/tokens/" in n and "$" not in n
        )
    if not token_classes:
        return {}

    batches = [token_classes[i : i + 30] for i in range(0, len(token_classes), 30)]
    results: dict[str, dict[str, str]] = {}

    def run_batch(batch: list[str]) -> str:
        return subprocess.check_output(
            ["javap", "-cp", str(jar_path), "-constants", "-c", "-p", *batch],
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    outputs: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        outputs = list(pool.map(run_batch, batches))

    for text in outputs:
        cur_class = ""
        cur_method = ""
        method_lines: list[str] = []
        last_field = ""

        def flush_method() -> None:
            nonlocal cur_method, method_lines
            if not cur_class or not cur_method or cur_method in {"<init>", "<clinit>"}:
                method_lines = []
                return
            prop = cur_method[3:] if cur_method.startswith("get") else cur_method
            prop = KT_INLINE_SUFFIX_RE.sub("", prop)
            body = "\n".join(method_lines)
            val = ""
            # Check Dp.constructor-impl or Sp
            m_dp = re.search(r"//\s*(?:double|float)\s+([-0-9.eE]+)[df]", body)
            if m_dp and "Dp.\"constructor-impl\"" in body:
                val = f"{m_dp.group(1)}.dp"
            elif m_dp and "TextUnitKt.getSp" in body:
                val = f"{m_dp.group(1)}.sp"
            elif "dconst_0" in body and "Dp.\"constructor-impl\"" in body:
                val = "0.0.dp"
            elif "dconst_1" in body and "Dp.\"constructor-impl\"" in body:
                val = "1.0.dp"
            elif "fconst_0" in body and "Dp.\"constructor-impl\"" in body:
                val = "0.0.dp"
            elif m_dp:
                val = m_dp.group(1)
            else:
                m_tok = re.search(r"Method\s+androidx/compose/material3/tokens/([A-Za-z0-9_]+)\.\"(?:get)?([A-Za-z0-9_]+?)(?:-[A-Za-z0-9_-]{7})?\"", body)
                if m_tok:
                    tname = m_tok.group(2)
                    if tname.startswith("get"):
                        tname = tname[3:]
                    val = f"{m_tok.group(1)}.{tname}"
                else:
                    m_field_ref = re.search(r"Field\s+androidx/compose/material3/tokens/([A-Za-z0-9_]+)\.([A-Za-z0-9_]+):", body)
                    if m_field_ref and m_field_ref.group(2) != "INSTANCE":
                        val = f"{m_field_ref.group(1)}.{m_field_ref.group(2)}"
            if val:
                results.setdefault(cur_class, {})[prop] = val
            method_lines = []

        for line in text.splitlines():
            m_cls = re.match(r"^public\s+(?:final\s+)?(?:class|enum|interface)\s+([^\s{]+)", line)
            if m_cls:
                flush_method()
                cur_class = m_cls.group(1).rsplit(".", 1)[-1]
                cur_method = ""
                last_field = ""
                continue
            m_fld = re.match(r"^  public static final\s+\S+\s+([A-Za-z0-9_$]+);", line)
            if m_fld:
                flush_method()
                cur_method = ""
                last_field = m_fld.group(1)
                continue
            m_cv = re.match(r"^\s+ConstantValue:\s+\S+\s+(.+)$", line)
            if m_cv and cur_class and last_field:
                results.setdefault(cur_class, {})[last_field] = m_cv.group(1).strip()
                continue
            m_m = re.match(r"^  public final\s+\S+\s+([^\s(]+)\(", line)
            if m_m:
                flush_method()
                cur_method = m_m.group(1)
                last_field = ""
                continue
            if cur_method:
                method_lines.append(line)
        flush_method()
    return results


def format_method_signature(m: dict[str, Any]) -> str:
    prefix = "@Composable " if m["is_composable"] else ""
    params = ", ".join(f"{p['name']}: {p['type']}" for p in m["params"])
    ret = f": {m['return_type']}" if m["return_type"] != "void" else ""
    return f"{prefix}fun {m['name']}({params}){ret}"


def collect_symbol_index(classes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index by logical symbol name (functions + classes/objects) for fast query & parity diff."""
    symbols: dict[str, dict[str, Any]] = {}

    for fqcn, cinfo in classes.items():
        sname = cinfo["simple_name"]
        # Record non-*Kt classes/interfaces/objects themselves
        if not sname.endswith("Kt"):
            entry = symbols.setdefault(sname, {
                "symbol": sname,
                "kind": cinfo["kind"],
                "packages": set(),
                "fqcn": fqcn,
                "opt_ins": set(cinfo["opt_ins"]),
                "deprecated": cinfo["deprecated"],
                "overloads": [],
            })
            entry["packages"].add(cinfo["package"])
            entry["opt_ins"].update(cinfo["opt_ins"])
            for m in cinfo["methods"]:
                if m["name"] in {"<init>", "getINSTANCE"}:
                    continue
                entry["overloads"].append({
                    "owner": fqcn,
                    "signature": format_method_signature(m),
                    "is_composable": m["is_composable"],
                    "opt_ins": m["opt_ins"],
                    "deprecated": m["deprecated"],
                    "params": m["params"],
                })
        else:
            # Top-level Kotlin file class (*Kt): index each public method as a top-level symbol
            for m in cinfo["methods"]:
                mname = m["name"]
                entry = symbols.setdefault(mname, {
                    "symbol": mname,
                    "kind": "composable" if m["is_composable"] else "function",
                    "packages": set(),
                    "fqcn": f"{cinfo['package']}.{mname}" if cinfo["package"] else mname,
                    "opt_ins": set(),
                    "deprecated": False,
                    "overloads": [],
                })
                entry["packages"].add(cinfo["package"])
                entry["opt_ins"].update(m["opt_ins"])
                entry["deprecated"] = entry["deprecated"] or m["deprecated"]
                entry["overloads"].append({
                    "owner": fqcn,
                    "signature": format_method_signature(m),
                    "is_composable": m["is_composable"],
                    "opt_ins": m["opt_ins"],
                    "deprecated": m["deprecated"],
                    "params": m["params"],
                })

    # Convert sets to sorted lists
    for s in symbols.values():
        s["packages"] = sorted(s["packages"])
        s["opt_ins"] = sorted(s["opt_ins"])
    return symbols


def compare_symbol_surfaces(
    android_syms: dict[str, dict[str, Any]],
    cmp_syms: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    all_names = sorted(set(android_syms) | set(cmp_syms))
    diff: dict[str, dict[str, Any]] = {}
    for name in all_names:
        a = android_syms.get(name)
        c = cmp_syms.get(name)
        if a and not c:
            status = "android_only"
        elif c and not a:
            status = "cmp_only"
        else:
            assert a and c
            a_sigs = {o["signature"] for o in a["overloads"]}
            c_sigs = {o["signature"] for o in c["overloads"]}
            a_opt = set(a["opt_ins"])
            c_opt = set(c["opt_ins"])
            if a_opt != c_opt:
                status = "opt_in_delta"
            elif a_sigs != c_sigs:
                status = "overload_delta"
            else:
                status = "identical"
        diff[name] = {
            "symbol": name,
            "parity_status": status,
            "android": {
                "present": bool(a),
                "kind": a["kind"] if a else None,
                "packages": a["packages"] if a else [],
                "opt_ins": a["opt_ins"] if a else [],
                "overload_count": len(a["overloads"]) if a else 0,
                "signatures": [o["signature"] for o in a["overloads"][:12]] if a else [],
            },
            "desktop_cmp": {
                "present": bool(c),
                "kind": c["kind"] if c else None,
                "packages": c["packages"] if c else [],
                "opt_ins": c["opt_ins"] if c else [],
                "overload_count": len(c["overloads"]) if c else 0,
                "signatures": [o["signature"] for o in c["overloads"][:12]] if c else [],
            },
        }
    return diff


# ---------------------------------------------------------------------------
# Minimal Devsite HTML -> Markdown for AndroidX Release Notes
# ---------------------------------------------------------------------------

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
DROP_TAGS = {"script", "style", "template", "noscript", "svg", "form", "button", "iframe", "devsite-toc", "devsite-feedback", "devsite-page-rating", "devsite-actions", "devsite-content-footer"}


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
            k = k.strip().lower()
            v = v.strip()
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


class SimpleReleaseNotesParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.drop_depth = 0
        self.in_pre = False
        self.in_code = False
        self.in_heading = 0
        self.in_li = False
        self.link_href: str | None = None
        self.link_buf: list[str] = []
        self.out: list[str] = []
        self.row_cells: list[str] = []
        self.table_rows: list[list[str]] = []
        self.in_cell = False
        self.cell_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag not in VOID_TAGS:
            self.stack.append(tag)
        if tag in DROP_TAGS or "nocontent" in (attr_map.get("class") or "").split() or "data-nosnippet" in attr_map:
            if tag not in VOID_TAGS:
                self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self.in_heading = int(tag[1])
            self.out.append("\n\n" + "#" * self.in_heading + " ")
        elif tag == "p":
            self.out.append("\n\n")
        elif tag == "br":
            self.out.append("\n" if self.in_pre else " ")
        elif tag == "pre":
            self.in_pre = True
            lang = attr_map.get("syntax", "").lower()
            self.out.append(f"\n\n```{lang}\n")
        elif tag == "code" and not self.in_pre:
            self.in_code = True
            self.out.append("`")
        elif tag == "li":
            self.in_li = True
            self.out.append("\n- ")
        elif tag == "a":
            self.link_href = attr_map.get("href", "")
            self.link_buf = []
        elif tag == "table":
            self.table_rows = []
        elif tag == "tr":
            self.row_cells = []
        elif tag in {"td", "th"}:
            self.in_cell = True
            self.cell_buf = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        if self.drop_depth:
            if tag in DROP_TAGS:
                self.drop_depth = max(0, self.drop_depth - 1)
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self.in_heading = 0
            self.out.append("\n\n")
        elif tag == "pre":
            self.in_pre = False
            self.out.append("\n```\n\n")
        elif tag == "code" and not self.in_pre:
            self.in_code = False
            self.out.append("`")
        elif tag == "li":
            self.in_li = False
        elif tag == "a":
            label = re.sub(r"\s+", " ", "".join(self.link_buf)).strip()
            href = self.link_href or ""
            if href.startswith("/"):
                href = ANDROID_DEV + href
            chunk = f"[{label}]({href})" if label and href.startswith("http") else label
            if self.in_cell:
                self.cell_buf.append(chunk)
            else:
                self.out.append(chunk)
            self.link_href = None
            self.link_buf = []
        elif tag in {"td", "th"}:
            self.in_cell = False
            cell = re.sub(r"\s+", " ", "".join(self.cell_buf)).strip().replace("|", "\\|")
            self.row_cells.append(cell)
        elif tag == "tr":
            if self.row_cells:
                self.table_rows.append(self.row_cells)
        elif tag == "table" and self.table_rows:
            w = max(len(r) for r in self.table_rows)
            hdr = [self.table_rows[0][i] if i < len(self.table_rows[0]) else "" for i in range(w)]
            lines = ["| " + " | ".join(hdr) + " |", "| " + " | ".join("---" for _ in range(w)) + " |"]
            for row in self.table_rows[1:]:
                cells = [row[i] if i < len(row) else "" for i in range(w)]
                lines.append("| " + " | ".join(cells) + " |")
            self.out.append("\n\n" + "\n".join(lines) + "\n\n")
            self.table_rows = []

    def handle_data(self, data: str) -> None:
        if self.drop_depth:
            return
        if self.link_href is not None:
            self.link_buf.append(data)
            return
        if self.in_cell:
            self.cell_buf.append(data)
            return
        if self.in_pre:
            self.out.append(data)
        else:
            cleaned = re.sub(r"[ \t\r\n]+", " ", data)
            self.out.append(cleaned)


def parse_release_notes_html(markup: str) -> tuple[str, str]:
    m_h1 = re.search(r"<h1[^>]*>(.*?)</h1>", markup, re.S | re.I)
    title = re.sub(r"<[^>]+>", "", html.unescape(m_h1.group(1))).strip() if m_h1 else "AndroidX Release Notes"
    marker = markup.find("devsite-article-body")
    if marker == -1:
        return title, ""
    start = markup.rfind("<div", 0, marker)
    end = markup.find("</article>", marker)
    slice_html = markup[start if start != -1 else marker : end if end != -1 else len(markup)]
    parser = SimpleReleaseNotesParser()
    parser.feed(slice_html)
    parser.close()
    md = "".join(parser.out)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return title, md


# ---------------------------------------------------------------------------
# Markdown Reference Pages
# ---------------------------------------------------------------------------

def build_versions_markdown(versions_doc: dict[str, Any]) -> str:
    lines = [
        "# Live Compose & Material 3 Expressive Maven Versions",
        "",
        f"Snapshot timestamp: `{versions_doc['fetched_at']}`",
        "",
        "| Artifact Key | Coordinate | Repo | Stable | Latest RC | Latest Beta | Latest Alpha | Latest Any |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, rec in versions_doc["artifacts"].items():
        coord = f"`{rec['group_id']}:{rec['artifact_id']}`"
        lines.append(
            f"| `{key}` | {coord} | {rec['repo']} | `{rec.get('latest_stable') or '-'}` | "
            f"`{rec.get('latest_rc') or '-'}` | `{rec.get('latest_beta') or '-'}` | "
            f"`{rec.get('latest_alpha') or '-'}` | `{rec.get('latest_any') or '-'}` |"
        )
    lines.append("")

    for bom_key in ("androidx-compose-bom", "androidx-compose-bom-alpha"):
        bom = versions_doc.get("boms", {}).get(bom_key)
        if not bom:
            continue
        lines.append(f"## BOM Pins: `{bom_key}` (`{bom['version']}`)")
        lines.append("")
        lines.append("| Coordinate | Pinned Version |")
        lines.append("| --- | --- |")
        for coord, ver in sorted(bom["pins"].items()):
            if any(k in coord for k in ("material3", "ui:ui", "foundation:foundation", "animation:animation", "runtime:runtime")):
                lines.append(f"| `{coord}` | `{ver}` |")
        lines.append("")

    redirects = versions_doc.get("cmp_android_redirects", {})
    if redirects:
        lines.append("## JetBrains CMP -> AndroidX Redirects (from `.module` metadata)")
        lines.append("")
        lines.append("| CMP Artifact | Version | AndroidX Target Dependencies |")
        lines.append("| --- | --- | --- |")
        for k, info in sorted(redirects.items()):
            deps = ", ".join(f"`{d}`" for d in (info.get("android_redirect") or [])) or "-"
            lines.append(f"| `{k}` | `{info['version']}` | {deps} |")
        lines.append("")
    return "\n".join(lines)


def build_parity_diff_markdown(surface: dict[str, Any]) -> str:
    lines = [
        "# AndroidX vs JetBrains Compose Multiplatform Bytecode Parity Diff",
        "",
        f"Verified via JDK `javap` on `{surface['generated_at']}`.",
        "",
        "## Inspected Module Pairs",
        "",
        "| Module | AndroidX Version | CMP Desktop Version | Identical | Opt-In Delta | Overload Delta | Android Only | CMP Only |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for mod, mdata in surface["modules"].items():
        s = mdata["summary"]
        lines.append(
            f"| `{mod}` | `{mdata['android_version']}` | `{mdata['cmp_version']}` | "
            f"{s['identical']} | {s['opt_in_delta']} | {s['overload_delta']} | "
            f"{s['android_only']} | {s['cmp_only']} |"
        )
    lines.append("")

    lines.append("## Material 3 Expressive & Navigation 3 Watchlist Parity")
    lines.append("")
    lines.append("| Symbol | Category | Module | Parity Status | Android Opt-Ins | CMP Opt-Ins | Overloads (Android / CMP) |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for item in surface["watchlist"]:
        a_opt = ", ".join(f"`@{o}`" for o in item["android_opt_ins"]) or "stable"
        c_opt = ", ".join(f"`@{o}`" for o in item["cmp_opt_ins"]) or "stable"
        lines.append(
            f"| `{item['symbol']}` | {item['category']} | `{item['module']}` | `{item['parity_status']}` | "
            f"{a_opt} | {c_opt} | {item['android_overloads']} / {item['cmp_overloads']} |"
        )
    lines.append("")

    # Highlight non-identical watchlist items in detail
    deltas = [w for w in surface["watchlist"] if w["parity_status"] != "identical"]
    if deltas:
        lines.append("## Detailed Watchlist Deltas")
        lines.append("")
        for item in deltas:
            lines.append(f"### `{item['symbol']}` (`{item['parity_status']}` in `{item['module']}`)")
            lines.append("")
            if item["android_signatures"]:
                lines.append("**AndroidX signatures:**")
                lines.append("```kotlin")
                lines.extend(item["android_signatures"][:8])
                lines.append("```")
            if item["cmp_signatures"]:
                lines.append("**JetBrains CMP desktop signatures:**")
                lines.append("```kotlin")
                lines.extend(item["cmp_signatures"][:8])
                lines.append("```")
            lines.append("")
    return "\n".join(lines)


def build_watchlist_reference_markdown(surface: dict[str, Any], title: str, categories: set[str]) -> str:
    lines = [
        f"# {title}",
        "",
        f"Bytecode-verified signatures from JDK `javap` (`{surface['generated_at']}`).",
        "",
    ]
    for item in surface["watchlist"]:
        if item["category"] not in categories:
            continue
        lines.append(f"## `{item['symbol']}` ({item['category']})")
        lines.append("")
        lines.append(f"- **Module**: `{item['module']}`")
        lines.append(f"- **Parity**: `{item['parity_status']}`")
        lines.append(f"- **AndroidX Opt-In**: {', '.join(f'`@{o}`' for o in item['android_opt_ins']) or 'None (graduated)'}")
        lines.append(f"- **CMP Opt-In**: {', '.join(f'`@{o}`' for o in item['cmp_opt_ins']) or 'None (graduated)'}")
        sigs = item["android_signatures"] or item["cmp_signatures"]
        if sigs:
            lines.append("")
            lines.append("```kotlin")
            lines.extend(sigs[:10])
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


def build_token_constants_markdown(token_constants: dict[str, dict[str, str]], generated_at: str) -> str:
    lines = [
        "# Material 3 Bytecode Token Constants (`androidx.compose.material3.tokens.*`)",
        "",
        f"Extracted via `javap -constants -c -p` on `{generated_at}`.",
        "",
    ]
    for cls_name in sorted(token_constants):
        props = token_constants[cls_name]
        if not props:
            continue
        lines.append(f"## `{cls_name}`")
        lines.append("")
        lines.append("| Token Property | Bytecode Value |")
        lines.append("| --- | --- |")
        for k, v in sorted(props.items()):
            lines.append(f"| `{k}` | `{v}` |")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    out: Path = args.out.resolve()
    jars_dir = out / "jars"
    pages_dir = out / "pages"
    raw_dir = out / "raw"
    meta_dir = out / "metadata"
    for d in (jars_dir, pages_dir, raw_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)

    api_dir = REPO_ROOT / "manifests" / "api"
    sources_manifest_dir = REPO_ROOT / "manifests" / "sources"
    api_dir.mkdir(parents=True, exist_ok=True)
    sources_manifest_dir.mkdir(parents=True, exist_ok=True)

    if args.verify:
        return verify_outputs(out, api_dir, sources_manifest_dir)

    fetched_at = utc_now()

    # 1. Discover Maven versions concurrently (Google Maven + Maven Central + JetBrains Compose Dev)
    print("Querying Google Maven, Maven Central & JetBrains Compose Dev metadata...", flush=True)
    artifacts_info: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []

    # Probe JetBrains Compose Dev once upfront so unreachable TLS/firewalls don't stall every coordinate
    jb_dev_reachable = False
    jb_dev_probe_err: str | None = None
    try:
        fetch_maven_versions(JETBRAINS_DEV, "org.jetbrains.compose.material3", "material3", attempts=1, timeout=10.0)
        jb_dev_reachable = True
    except Exception as err:
        jb_dev_probe_err = f"{type(err).__name__}: {err}"

    def query_one(item: tuple[str, str, str, str, str]) -> tuple[str, dict[str, Any] | None, str | None]:
        key, repo_base, gid, aid, role = item
        repo_label = "google" if "google.com" in repo_base else "maven-central"
        try:
            central_vers = fetch_maven_versions(repo_base, gid, aid)
            merged_vers = list(central_vers)
            active_repo_base = repo_base
            dev_only_latest: str | None = None

            if repo_base == MAVEN_CENTRAL and jb_dev_reachable:
                try:
                    dev_vers = fetch_maven_versions(JETBRAINS_DEV, gid, aid, attempts=2, timeout=15.0)
                    central_set = set(central_vers)
                    merged_vers = sorted(central_set | set(dev_vers), key=parse_version)
                    if merged_vers and merged_vers[-1] not in central_set:
                        active_repo_base = JETBRAINS_DEV
                        repo_label = "jetbrains-dev"
                        dev_only_latest = merged_vers[-1]
                except Exception:
                    pass

            summary = summarize_versions(merged_vers)
            summary.update({
                "key": key,
                "coordinate": f"{gid}:{aid}",
                "group_id": gid,
                "artifact_id": aid,
                "ecosystem": "jetbrains" if gid.startswith("org.jetbrains") else "androidx",
                "repo": repo_label,
                "repo_base": active_repo_base,
                "jetbrains_dev_latest": dev_only_latest,
                "role": role,
            })
            return key, summary, None
        except Exception as err:
            return key, None, f"{type(err).__name__}: {err}"

    workers = max(1, min(MAX_WORKERS, args.workers))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for key, info, err in pool.map(query_one, MAVEN_ARTIFACTS):
            if info is not None:
                artifacts_info[key] = info
            elif err:
                errors.append({"artifact": key, "error": err})

    jb_dev_latest = (artifacts_info.get("cmp-material3") or {}).get("jetbrains_dev_latest")
    if not jb_dev_latest and jb_dev_reachable:
        try:
            dev_vers = fetch_maven_versions(JETBRAINS_DEV, "org.jetbrains.compose.material3", "material3", attempts=1, timeout=10.0)
            jb_dev_latest = summarize_versions(dev_vers).get("latest_any")
        except Exception:
            jb_dev_latest = None

    # Parse BOMs
    boms: dict[str, Any] = {}
    for bom_key in ("androidx-compose-bom", "androidx-compose-bom-alpha", "androidx-compose-bom-beta"):
        info = artifacts_info.get(bom_key)
        if not info or not info.get("latest_any"):
            continue
        try:
            pins = parse_bom_pom(info["repo_base"], info["group_id"], info["artifact_id"], info["latest_any"])
            boms[bom_key] = {"version": info["latest_any"], "pins": pins}
        except Exception as err:
            errors.append({"artifact": bom_key, "error": f"bom pom: {err}"})

    # Parse CMP -> AndroidX redirects
    cmp_redirects: dict[str, Any] = {}
    for cmp_key in ("cmp-material3", "cmp-material3-nav-suite", "cmp-adaptive", "cmp-adaptive-navigation3", "cmp-navigation3-ui"):
        info = artifacts_info.get(cmp_key)
        if info and info.get("latest_any"):
            rinfo = inspect_cmp_module_redirects(info["repo_base"], info["group_id"], info["artifact_id"], info["latest_any"])
            cmp_redirects[cmp_key] = {"version": info["latest_any"], **rinfo}

    versions_doc = {
        "schema_version": 1,
        "fetched_at": fetched_at,
        "repositories": {
            "google_maven": GOOGLE_MAVEN,
            "maven_central": MAVEN_CENTRAL,
            "jetbrains_compose_dev": JETBRAINS_DEV,
        },
        "jetbrains_dev_reachable": jb_dev_reachable,
        "jetbrains_dev_probe_error": jb_dev_probe_err,
        "jetbrains_dev_material3_latest": jb_dev_latest,
        "artifacts": {
            v["coordinate"]: {kk: vv for kk, vv in v.items() if kk != "repo_base"}
            for v in artifacts_info.values()
        },
        "artifacts_by_key": {k: {kk: vv for kk, vv in v.items() if kk != "repo_base"} for k, v in artifacts_info.items()},
        "boms": boms,
        "cmp_android_redirects": cmp_redirects,
    }

    if args.check:
        prev_versions = read_json(api_dir / "compose-versions.json", {})
        prev_arts = prev_versions.get("artifacts_by_key") or prev_versions.get("artifacts", {})
        changed = []
        for k, v in artifacts_info.items():
            old_latest = (prev_arts.get(k) or {}).get("latest_any")
            if old_latest != v.get("latest_any"):
                changed.append({"artifact": k, "previous": old_latest, "current": v.get("latest_any")})
        print(json.dumps({"checked_at": fetched_at, "changed_versions": changed, "errors": errors}, indent=2))
        return 0

    write_json(api_dir / "compose-versions.json", versions_doc)
    print(f"Wrote {api_dir / 'compose-versions.json'} ({len(artifacts_info)} coordinates)", flush=True)

    # 2. Download JARs/AARs and run javap
    jar_cache_path = meta_dir / "jar-cache.json"
    jar_cache: dict[str, Any] = read_json(jar_cache_path, {})

    download_tasks: list[tuple[str, str, str, str, str, str]] = []
    for pair in PAIRED_BYTECODE_MODULES:
        mod = pair["module"]
        ai = artifacts_info.get(pair["androidx_key"])
        ci = artifacts_info.get(pair["cmp_key"])
        if ai and ai.get("latest_any"):
            download_tasks.append((f"{mod}__android", ai["repo_base"], ai["group_id"], ai["artifact_id"], ai["latest_any"], "android"))
        if ci and ci.get("latest_any"):
            download_tasks.append((f"{mod}__cmp", ci["repo_base"], ci["group_id"], ci["artifact_id"], ci["latest_any"], "desktop"))
    for extra in EXTRA_BYTECODE_MODULES:
        ei = artifacts_info.get(extra["key"])
        if ei and ei.get("latest_any"):
            download_tasks.append((f"{extra['module']}__{extra['platform']}", ei["repo_base"], ei["group_id"], ei["artifact_id"], ei["latest_any"], extra["platform"]))

    jar_paths: dict[str, Path] = {}
    for name_key, repo_base, gid, aid, ver, target in download_tasks:
        try:
            bin_url, ext = resolve_artifact_binary_url(repo_base, gid, aid, ver, target)
            jp, status = ensure_jar_on_disk(jars_dir, jar_cache, name_key, bin_url, ext, refresh=args.refresh)
            if jp is not None:
                jar_paths[name_key] = jp
                print(f"  jar {name_key} ({ver}): {status}", flush=True)
        except Exception as err:
            errors.append({"jar": name_key, "error": f"{type(err).__name__}: {err}"})
            print(f"  ERR jar {name_key}: {err}", file=sys.stderr)

    write_json(jar_cache_path, jar_cache)

    print("Running javap bytecode inspection...", flush=True)
    inspected_symbols: dict[str, dict[str, Any]] = {}
    for name_key, jp in sorted(jar_paths.items()):
        t0 = time.time()
        classes = inspect_jar_with_javap(jp, workers=workers)
        syms = collect_symbol_index(classes)
        inspected_symbols[name_key] = syms
        print(f"  javap {name_key}: {len(classes)} classes, {len(syms)} symbols in {time.time() - t0:.1f}s", flush=True)

    token_constants: dict[str, dict[str, str]] = {}
    if "material3__android" in jar_paths:
        t0 = time.time()
        token_constants = extract_token_constants(jar_paths["material3__android"], workers=workers)
        print(f"  javap tokens: {len(token_constants)} token classes in {time.time() - t0:.1f}s", flush=True)

    # Optional historical CMP alpha-to-beta drift check (1.12.0-alpha03 vs latest CMP)
    historical_alpha_delta: dict[str, Any] = {}
    cmp_m3_info = artifacts_info.get("cmp-material3") or {}
    if cmp_m3_info.get("latest_any") and cmp_m3_info.get("latest_any") != "1.12.0-alpha03":
        try:
            old_url, old_ext = resolve_artifact_binary_url(
                cmp_m3_info["repo_base"], cmp_m3_info["group_id"], cmp_m3_info["artifact_id"], "1.12.0-alpha03", "desktop"
            )
            old_jp, _ = ensure_jar_on_disk(jars_dir, jar_cache, "material3__cmp_1_12_0_alpha03", old_url, old_ext, refresh=args.refresh)
            if old_jp is not None:
                key_classes = [
                    "androidx.compose.material3.ListItemKt",
                    "androidx.compose.material3.SplitButtonKt",
                    "androidx.compose.material3.AppBarKt",
                    "androidx.compose.material3.LoadingIndicatorKt",
                    "androidx.compose.material3.ButtonGroupKt",
                    "androidx.compose.material3.FloatingToolbarKt",
                    "androidx.compose.material3.WideNavigationRailKt",
                    "androidx.compose.material3.NavigationBarKt",
                    "androidx.compose.material3.MaterialThemeKt",
                ]
                out_old = subprocess.check_output(
                    ["javap", "-cp", str(old_jp), "-p", "-v", *key_classes],
                    text=True, encoding="utf-8", errors="replace",
                )
                old_syms = collect_symbol_index(parse_javap_output(out_old))
                cur_syms = inspected_symbols.get("material3__cmp", {})
                delta_items: dict[str, Any] = {}
                for sname in ("SegmentedListItem", "ListItem", "SplitButtonLayout", "MediumFlexibleTopAppBar", "LargeFlexibleTopAppBar", "LoadingIndicator", "ButtonGroup", "HorizontalFloatingToolbar", "WideNavigationRail", "ShortNavigationBar", "MaterialExpressiveTheme"):
                    o = old_syms.get(sname)
                    c = cur_syms.get(sname)
                    if o or c:
                        delta_items[sname] = {
                            "1.12.0-alpha03": {
                                "present": bool(o),
                                "opt_ins": o["opt_ins"] if o else [],
                                "overload_count": len(o["overloads"]) if o else 0,
                            },
                            cmp_m3_info["latest_any"]: {
                                "present": bool(c),
                                "opt_ins": c["opt_ins"] if c else [],
                                "overload_count": len(c["overloads"]) if c else 0,
                            },
                        }
                historical_alpha_delta = {
                    "baseline_cmp_version": "1.12.0-alpha03",
                    "current_cmp_version": cmp_m3_info["latest_any"],
                    "symbols": delta_items,
                }
        except Exception as err:
            errors.append({"historical_alpha_delta": f"{type(err).__name__}: {err}"})

    # 3. Build parity diff & expressive surface JSON
    modules_out: dict[str, Any] = {}
    all_module_diffs: dict[str, dict[str, Any]] = {}
    for pair in PAIRED_BYTECODE_MODULES:
        mod = pair["module"]
        ai = artifacts_info.get(pair["androidx_key"], {})
        ci = artifacts_info.get(pair["cmp_key"], {})
        a_syms = inspected_symbols.get(f"{mod}__android", {})
        c_syms = inspected_symbols.get(f"{mod}__cmp", {})
        diff = compare_symbol_surfaces(a_syms, c_syms)
        all_module_diffs[mod] = diff

        counts = {"identical": 0, "opt_in_delta": 0, "overload_delta": 0, "android_only": 0, "cmp_only": 0}
        for d in diff.values():
            counts[d["parity_status"]] += 1

        modules_out[mod] = {
            "android_coordinate": f"{ai.get('group_id')}:{ai.get('artifact_id')}",
            "android_version": ai.get("latest_any"),
            "cmp_coordinate": f"{ci.get('group_id')}:{ci.get('artifact_id')}",
            "cmp_version": ci.get("latest_any"),
            "summary": counts,
            "symbols": diff,
        }

    # Standalone extra modules (e.g. navigation3-runtime)
    extra_out: dict[str, Any] = {}
    for extra in EXTRA_BYTECODE_MODULES:
        mod = extra["module"]
        ei = artifacts_info.get(extra["key"], {})
        syms = inspected_symbols.get(f"{mod}__{extra['platform']}", {})
        extra_out[mod] = {
            "coordinate": f"{ei.get('group_id')}:{ei.get('artifact_id')}",
            "version": ei.get("latest_any"),
            "symbol_count": len(syms),
            "symbols": {
                k: {
                    "kind": v["kind"],
                    "packages": v["packages"],
                    "opt_ins": v["opt_ins"],
                    "overload_count": len(v["overloads"]),
                    "signatures": [o["signature"] for o in v["overloads"][:12]],
                }
                for k, v in sorted(syms.items())
            },
        }

    # Build watchlist summary
    watchlist_out: list[dict[str, Any]] = []
    for sym_name, category in EXPRESSIVE_WATCHLIST:
        found_mod = None
        found_entry = None
        for pair in PAIRED_BYTECODE_MODULES:
            mod = pair["module"]
            entry = all_module_diffs.get(mod, {}).get(sym_name)
            if entry:
                found_mod = mod
                found_entry = entry
                break
        if found_entry and found_mod:
            watchlist_out.append({
                "symbol": sym_name,
                "category": category,
                "module": found_mod,
                "parity_status": found_entry["parity_status"],
                "android_opt_ins": found_entry["android"]["opt_ins"],
                "cmp_opt_ins": found_entry["desktop_cmp"]["opt_ins"],
                "android_overloads": found_entry["android"]["overload_count"],
                "cmp_overloads": found_entry["desktop_cmp"]["overload_count"],
                "android_signatures": found_entry["android"]["signatures"],
                "cmp_signatures": found_entry["desktop_cmp"]["signatures"],
            })
        else:
            # Check extra modules (e.g. NavEntry, NavBackStack in navigation3-runtime)
            for emod, edata in extra_out.items():
                esym = edata["symbols"].get(sym_name)
                if esym:
                    watchlist_out.append({
                        "symbol": sym_name,
                        "category": category,
                        "module": emod,
                        "parity_status": "android_runtime_shared",
                        "android_opt_ins": esym["opt_ins"],
                        "cmp_opt_ins": esym["opt_ins"],
                        "android_overloads": esym["overload_count"],
                        "cmp_overloads": esym["overload_count"],
                        "android_signatures": esym["signatures"],
                        "cmp_signatures": esym["signatures"],
                    })
                    break

    # Flatten all bytecode-verified symbols into `ApiSymbol` schema for rtx index
    flat_symbols: list[dict[str, Any]] = []
    for mod, mdata in modules_out.items():
        a_ver = mdata.get("android_version") or ""
        c_ver = mdata.get("cmp_version") or ""
        coord_str = f"{mdata.get('android_coordinate')} / {mdata.get('cmp_coordinate')}"
        ver_str = f"android={a_ver}, cmp={c_ver}"
        for sym_name, sdata in mdata["symbols"].items():
            a_info = sdata["android"]
            c_info = sdata["desktop_cmp"]
            targets = []
            if a_info["present"]:
                targets.append("android")
            if c_info["present"]:
                targets.extend(["desktop", "common"])
            pkgs = sorted(set(a_info["packages"]) | set(c_info["packages"]))
            anns = sorted({f"@{o}" for o in (a_info["opt_ins"] + c_info["opt_ins"])})
            a_sig = "\n".join(a_info["signatures"][:6])
            c_sig = "\n".join(c_info["signatures"][:6])
            flat_symbols.append({
                "name": sym_name,
                "package": pkgs[0] if pkgs else "",
                "kind": a_info["kind"] or c_info["kind"] or "symbol",
                "signature": a_sig or c_sig,
                "annotations": anns,
                "artifact": coord_str,
                "version": ver_str,
                "targets": targets,
                "androidx_signature": a_sig,
                "cmp_signature": c_sig,
                "parity_status": sdata["parity_status"],
                "doc": f"Module `{mod}` | Android opt-ins: {a_info['opt_ins']} | CMP opt-ins: {c_info['opt_ins']}",
            })
    for emod, edata in extra_out.items():
        for sym_name, sdata in edata["symbols"].items():
            anns = sorted({f"@{o}" for o in sdata["opt_ins"]})
            sig = "\n".join(sdata["signatures"][:6])
            flat_symbols.append({
                "name": sym_name,
                "package": sdata["packages"][0] if sdata["packages"] else "",
                "kind": sdata["kind"],
                "signature": sig,
                "annotations": anns,
                "artifact": edata["coordinate"],
                "version": edata["version"] or "",
                "targets": ["android", "common"],
                "androidx_signature": sig,
                "cmp_signature": "",
                "parity_status": "android_runtime_shared",
                "doc": f"Module `{emod}`",
            })

    surface_doc = {
        "schema_version": 1,
        "generated_at": fetched_at,
        "tool": "javap (OpenJDK 21)",
        "watchlist": watchlist_out,
        "symbols": flat_symbols,
        "token_constants": token_constants,
        "historical_alpha_delta": historical_alpha_delta,
        "modules": modules_out,
        "extra_modules": extra_out,
    }
    write_json(api_dir / "material3-expressive-surface.json", surface_doc)
    print(f"Wrote {api_dir / 'material3-expressive-surface.json'} ({len(watchlist_out)} watchlist items)", flush=True)

    # 4. Fetch AndroidX Release Notes (respecting robots.txt)
    print("Fetching AndroidX release notes...", flush=True)
    release_pages: list[dict[str, Any]] = []
    rel_cache_path = meta_dir / "releases-cache.json"
    rel_cache: dict[str, Any] = read_json(rel_cache_path, {})
    try:
        _, rbytes, _ = fetch_url(f"{ANDROID_DEV}/robots.txt", accept="text/plain")
        robots = RobotsTxt(rbytes.decode("utf-8", errors="replace"))
    except Exception as err:
        robots = RobotsTxt("")
        errors.append({"robots": ANDROID_DEV, "error": str(err)})

    for slug, path in RELEASE_NOTE_PATHS:
        url = ANDROID_DEV + path
        if not robots.allows(path):
            errors.append({"release_notes": url, "error": "robots-disallowed"})
            continue
        prev = rel_cache.get(path) or {}
        raw_html_path = raw_dir / f"{slug}.html.gz"
        try:
            if raw_html_path.exists() and not args.refresh:
                markup = gzip.decompress(raw_html_path.read_bytes()).decode("utf-8", errors="replace")
                last_mod = prev.get("last_modified")
            else:
                st, rdata, rhdrs = fetch_url(url, accept="text/html", etag=prev.get("etag"), last_modified=prev.get("last_modified"))
                if st == 304 and raw_html_path.exists():
                    markup = gzip.decompress(raw_html_path.read_bytes()).decode("utf-8", errors="replace")
                    last_mod = prev.get("last_modified")
                else:
                    write_bytes(raw_html_path, gzip.compress(rdata, 6))
                    markup = rdata.decode("utf-8", errors="replace")
                    last_mod = rhdrs.get("last-modified")
                    rel_cache[path] = {"etag": rhdrs.get("etag"), "last_modified": last_mod}
            title, body = parse_release_notes_html(markup)
            md_text = render_frontmatter(
                source_id=SOURCE_ID,
                url=url,
                title=title,
                section="releases",
                fetched_at=fetched_at,
                last_modified=last_mod,
                body=body,
            )
            rel_out = pages_dir / "releases" / f"{slug}.md"
            write_text(rel_out, md_text)
            release_pages.append({"slug": f"releases/{slug}", "title": title, "url": url})
        except Exception as err:
            errors.append({"release_notes": url, "error": f"{type(err).__name__}: {err}"})
    write_json(rel_cache_path, rel_cache)

    # 5. Write generated Markdown API reference & diff pages
    generated_pages = [
        ("versions-and-boms", "Live Compose & Material 3 Expressive Maven Versions", "versions", build_versions_markdown(versions_doc), GOOGLE_MAVEN),
        ("parity-diff", "AndroidX vs JetBrains CMP Bytecode Parity Diff", "parity", build_parity_diff_markdown(surface_doc), MAVEN_CENTRAL),
        (
            "expressive-api-reference",
            "Material 3 Expressive Bytecode API Reference",
            "api-reference",
            build_watchlist_reference_markdown(
                surface_doc,
                "Material 3 Expressive Bytecode API Reference",
                {"Theme & Tokens", "Expressive Buttons", "Expressive Actions & Toolbars", "Expressive Progress & Loading", "Expressive Navigation & App Bars", "Expressive Lists, Search & Carousel"},
            ),
            GOOGLE_MAVEN,
        ),
        (
            "adaptive-and-navigation3-api",
            "Adaptive & Navigation 3 Bytecode API Reference",
            "api-reference",
            build_watchlist_reference_markdown(
                surface_doc,
                "Adaptive & Navigation 3 Bytecode API Reference",
                {"Adaptive & Navigation 3"},
            ),
            GOOGLE_MAVEN,
        ),
        (
            "material3-token-constants",
            "Material 3 Bytecode Token Constants",
            "tokens",
            build_token_constants_markdown(token_constants, fetched_at),
            GOOGLE_MAVEN,
        ),
    ]

    page_records: list[dict[str, Any]] = []
    for slug, title, section, body, src_url in generated_pages:
        md = render_frontmatter(
            source_id=SOURCE_ID,
            url=src_url,
            title=title,
            section=section,
            fetched_at=fetched_at,
            last_modified=fetched_at,
            body=body,
        )
        p = pages_dir / f"{slug}.md"
        write_text(p, md)
        page_records.append({"slug": slug, "title": title, "section": section, "url": src_url, "path": f"pages/{slug}.md"})

    for rp in release_pages:
        page_records.append({"slug": rp["slug"], "title": rp["title"], "section": "releases", "url": rp["url"], "path": f"pages/{rp['slug']}.md"})

    index_lines = [
        "# Compose Maven API & Expressive Surface Index",
        "",
        f"Updated: `{fetched_at}` (inspected with JDK `javap`)",
        "",
        "## Generated Reference Pages",
        "",
    ]
    for rec in page_records:
        if rec["section"] != "releases":
            index_lines.append(f"- [{rec['title']}]({rec['slug']}.md) (`{rec['section']}`)")
    index_lines.extend(["", "## AndroidX Release Notes", ""])
    for rec in page_records:
        if rec["section"] == "releases":
            index_lines.append(f"- [{rec['title']}]({rec['slug']}.md) — {rec['url']}")
    index_lines.append("")
    write_text(pages_dir / "INDEX.md", "\n".join(index_lines))

    # 6. Write manifests aligned with rtx.models.SourceManifest
    section_counts: dict[str, int] = {}
    for rec in page_records:
        sec = rec.get("section") or "other"
        section_counts[sec] = section_counts.get(sec, 0) + 1

    manifest = {
        "source_id": SOURCE_ID,
        "name": "Compose Maven API & Material 3 Expressive Bytecode Surface",
        "base_url": GOOGLE_MAVEN,
        "fetched_at": fetched_at,
        "page_count": len(page_records) + 1,
        "asset_count": len(jar_paths),
        "failed_count": len(errors),
        "status": "ok" if not errors else "partial",
        "upstream_version": f"androidx-m3={((artifacts_info.get('androidx-material3') or {}).get('latest_any') or '')} / cmp-m3={((artifacts_info.get('cmp-material3') or {}).get('latest_any') or '')}",
        "versions": {
            "androidx_compose_bom": (artifacts_info.get("androidx-compose-bom") or {}).get("latest_any") or "",
            "androidx_compose_bom_alpha": (artifacts_info.get("androidx-compose-bom-alpha") or {}).get("latest_any") or "",
            "androidx_material3": (artifacts_info.get("androidx-material3") or {}).get("latest_any") or "",
            "androidx_adaptive": (artifacts_info.get("androidx-adaptive") or {}).get("latest_any") or "",
            "androidx_navigation3_ui": (artifacts_info.get("androidx-navigation3-ui") or {}).get("latest_any") or "",
            "cmp_gradle_plugin": (artifacts_info.get("cmp-gradle-plugin") or {}).get("latest_any") or "",
            "cmp_material3": (artifacts_info.get("cmp-material3") or {}).get("latest_any") or "",
            "cmp_adaptive": (artifacts_info.get("cmp-adaptive") or {}).get("latest_any") or "",
            "cmp_navigation3_ui": (artifacts_info.get("cmp-navigation3-ui") or {}).get("latest_any") or "",
            "cmp_skiko_awt": (artifacts_info.get("cmp-skiko-awt") or {}).get("latest_any") or "",
        },
        "sections": section_counts,
        "notes": f"JDK javap bytecode verification across {len(jar_paths)} JARs/AARs; {len(flat_symbols)} symbols indexed ({len(watchlist_out)} watchlist items).",
        "coordinate_count": len(artifacts_info),
        "watchlist_count": len(watchlist_out),
        "symbol_count": len(flat_symbols),
        "modules_inspected": list(modules_out.keys()) + list(extra_out.keys()),
        "failures": errors,
    }
    write_json(out / "manifest.json", manifest)
    write_json(sources_manifest_dir / f"{SOURCE_ID}.json", manifest)
    print(f"Done. Pages: {len(page_records)}, Errors: {len(errors)}", flush=True)
    return 0 if not errors else 1


def verify_outputs(out: Path, api_dir: Path, sources_manifest_dir: Path) -> int:
    problems: list[str] = []
    for req_json in (
        api_dir / "compose-versions.json",
        api_dir / "material3-expressive-surface.json",
        sources_manifest_dir / f"{SOURCE_ID}.json",
        out / "manifest.json",
    ):
        if not req_json.exists():
            problems.append(f"missing {req_json}")

    pages_dir = out / "pages"
    md_files = sorted(pages_dir.rglob("*.md")) if pages_dir.exists() else []
    if not md_files:
        problems.append("no markdown pages found")
    max_len = 0
    for md in md_files:
        for idx, line in enumerate(md.read_text(encoding="utf-8").splitlines(), start=1):
            if len(line) > max_len:
                max_len = len(line)
            if len(line) > MAX_LINE_LENGTH:
                problems.append(f"{md.name}:{idx} line length {len(line)} > {MAX_LINE_LENGTH}")

    surface = read_json(api_dir / "material3-expressive-surface.json", {})
    if len(surface.get("watchlist", [])) < 20:
        problems.append(f"watchlist too small: {len(surface.get('watchlist', []))}")

    report = {
        "checked_at": utc_now(),
        "markdown_files": len(md_files),
        "max_line_length": max_len,
        "watchlist_count": len(surface.get("watchlist", [])),
        "problems": problems,
        "passed": not problems,
    }
    write_json(out / "metadata" / "verify.json", report)
    print(json.dumps(report, indent=2))
    return 0 if not problems else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="runtime output directory")
    parser.add_argument("--workers", type=int, default=8, help="concurrent workers (max 10)")
    parser.add_argument("--no-assets", action="store_true", help="skip non-code visual assets (accepted for CLI parity)")
    parser.add_argument("--refresh", action="store_true", help="ignore local caches and re-download")
    parser.add_argument("--check", action="store_true", help="check upstream Maven versions for changes")
    parser.add_argument("--verify", action="store_true", help="verify generated JSON & Markdown fidelity")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
