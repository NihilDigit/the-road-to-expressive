"""Workspace paths, source discovery, and runtime constants for `rtx`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MAX_LINE_LENGTH = 4000
DEFAULT_USER_AGENT = "RoadToExpressiveBot/0.1 (+https://github.com/local/the-road-to-expressive)"

EXPECTED_SOURCES: tuple[str, ...] = (
    "m3-expressive",
    "google-design",
    "compose-android",
    "compose-multiplatform",
    "compose-maven-api",
    "apple-hig",
    "windows-fluent",
    "linux-hig",
    "writing-style",
)


@dataclass(frozen=True, slots=True)
class RepoPaths:
    """Resolved repository and `.corpus/` runtime directories."""

    root: Path

    @property
    def corpus_dir(self) -> Path:
        return self.root / ".corpus"

    @property
    def index_db(self) -> Path:
        return self.corpus_dir / "index.db"

    @property
    def sources_dir(self) -> Path:
        return self.root / "sources"

    @property
    def manifests_dir(self) -> Path:
        return self.root / "manifests"

    @property
    def source_manifests_dir(self) -> Path:
        return self.manifests_dir / "sources"

    @property
    def api_manifests_dir(self) -> Path:
        return self.manifests_dir / "api"

    @property
    def token_manifests_dir(self) -> Path:
        return self.manifests_dir / "tokens"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "knowledge"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    def source_corpus_dir(self, source_id: str) -> Path:
        return self.corpus_dir / source_id

    def source_pages_dir(self, source_id: str) -> Path:
        return self.source_corpus_dir(source_id) / "pages"

    def source_assets_dir(self, source_id: str) -> Path:
        return self.source_corpus_dir(source_id) / "assets"

    def source_raw_dir(self, source_id: str) -> Path:
        return self.source_corpus_dir(source_id) / "raw"

    def source_corpus_manifest(self, source_id: str) -> Path:
        return self.source_corpus_dir(source_id) / "manifest.json"

    def source_committed_manifest(self, source_id: str) -> Path:
        return self.source_manifests_dir / f"{source_id}.json"


@dataclass(frozen=True, slots=True)
class SourceAdapter:
    """Discovered source adapter metadata."""

    source_id: str
    script_path: Path | None
    readme_path: Path | None
    committed_manifest: Path
    corpus_manifest: Path
    pages_dir: Path

    @property
    def has_adapter(self) -> bool:
        return self.script_path is not None and self.script_path.is_file()


def get_repo_root(start: Path | str | None = None) -> Path:
    """Locate the repository root containing `pyproject.toml` or `.git`.

    When invoked from another working directory (e.g. `uv run --project <corpus> rtx ...`),
    prefer the editable package root (`Path(__file__).resolve().parents[2]`) before `Path.cwd()`.
    """
    env_root = os.environ.get("RTX_ROOT")
    if env_root and start is None:
        return Path(env_root).resolve()

    if start is not None:
        base = Path(start).resolve()
        for current in (base, *base.parents):
            if (current / "pyproject.toml").is_file() or (current / ".git").exists():
                return current
        return base

    pkg_root = Path(__file__).resolve().parents[2]
    if (pkg_root / "pyproject.toml").is_file() and (pkg_root / "src" / "rtx").is_dir():
        return pkg_root

    cwd = Path.cwd().resolve()
    for current in (cwd, *cwd.parents):
        if (current / "pyproject.toml").is_file() or (current / ".git").exists():
            return current

    return cwd


def get_paths(root: Path | str | None = None) -> RepoPaths:
    """Return a `RepoPaths` object for the resolved repository root."""
    return RepoPaths(root=get_repo_root(root))


def discover_sources(paths: RepoPaths) -> list[SourceAdapter]:
    """Discover all configured, implemented, or synced sources dynamically."""
    ids: set[str] = set(EXPECTED_SOURCES)

    if paths.sources_dir.is_dir():
        for entry in paths.sources_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith((".", "_")):
                ids.add(entry.name)

    if paths.source_manifests_dir.is_dir():
        for entry in paths.source_manifests_dir.glob("*.json"):
            ids.add(entry.stem)

    if paths.corpus_dir.is_dir():
        for entry in paths.corpus_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith((".", "_")):
                ids.add(entry.name)

    adapters: list[SourceAdapter] = []
    for source_id in sorted(ids):
        src_dir = paths.sources_dir / source_id
        script = src_dir / "refresh.py"
        readme = src_dir / "README.md"
        adapters.append(
            SourceAdapter(
                source_id=source_id,
                script_path=script if script.is_file() else None,
                readme_path=readme if readme.is_file() else None,
                committed_manifest=paths.source_committed_manifest(source_id),
                corpus_manifest=paths.source_corpus_manifest(source_id),
                pages_dir=paths.source_pages_dir(source_id),
            )
        )
    return adapters
