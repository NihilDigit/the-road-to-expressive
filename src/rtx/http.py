"""Shared conditional HTTP fetcher, robots.txt checker, cache index, and ledger."""

from __future__ import annotations

import gzip
import json
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rtx.config import DEFAULT_USER_AGENT
from rtx.models import LedgerEntry, sha256_bytes, utc_now_iso

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class FetchResult:
    """Result of an HTTP conditional fetch or check."""

    url: str
    final_url: str
    status: int
    body: bytes | None = None
    etag: str = ""
    last_modified: str = ""
    content_type: str = ""
    sha256: str = ""
    from_cache: bool = False
    not_modified: bool = False
    skipped_robots: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.skipped_robots and (200 <= self.status < 400)

    def text(self, encoding: str = "utf-8") -> str:
        if self.body is None:
            return ""
        return self.body.decode(encoding, errors="replace")


class RobotsCache:
    """Thread-safe per-origin `robots.txt` cache and policy checker."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: float = 10.0) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self._lock = threading.Lock()
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return True
        origin = f"{parsed.scheme}://{parsed.netloc}"

        with self._lock:
            cached = self._parsers.get(origin)
            found = origin in self._parsers

        if not found:
            parser = self._load_robots(origin)
            with self._lock:
                self._parsers.setdefault(origin, parser)
                cached = self._parsers[origin]

        if cached is None:
            return True
        return cached.can_fetch(self.user_agent, url)

    def _load_robots(self, origin: str) -> urllib.robotparser.RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        req = urllib.request.Request(
            robots_url,
            headers={"User-Agent": self.user_agent, "Accept": "text/plain,*/*"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                return None
            return None
        except Exception:
            return None

        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.parse(raw.splitlines())
        return rp


class HttpCacheIndex:
    """Persistent ETag / Last-Modified / SHA-256 index under `.corpus/<id>/raw/http_cache.json`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            self._entries = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._entries = data
        except Exception:
            self._entries = {}

    def get(self, url: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(url)
            return dict(entry) if entry is not None else None

    def put(self, url: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self._entries[url] = dict(entry)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(self.path)


class ProgressLedger:
    """Thread-safe progress and failure ledger for mirror adapters."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []

    def record(self, entry: LedgerEntry) -> None:
        with self._lock:
            self._entries.append(
                {
                    "url": entry.url,
                    "status": entry.status,
                    "http_status": entry.http_status,
                    "local_path": entry.local_path,
                    "error": entry.error,
                    "timestamp": entry.timestamp,
                }
            )

    def summary(self) -> dict[str, int]:
        counts = {"ok": 0, "not_modified": 0, "skipped_robots": 0, "failed": 0}
        with self._lock:
            for item in self._entries:
                st = item.get("status", "")
                counts[st] = counts.get(st, 0) + 1
        return counts

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "generated_at": utc_now_iso(),
                "entries": self._entries,
            }
            self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass
class ConditionalHttpClient:
    """Polite conditional HTTP client supporting ETag, Last-Modified, retries, and robots.txt."""

    cache_dir: Path | None = None
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 25.0
    max_retries: int = 3
    backoff_base: float = 0.75
    min_delay: float = 0.0
    respect_robots: bool = True
    cache_index: HttpCacheIndex | None = field(default=None, init=False)
    robots: RobotsCache = field(default_factory=RobotsCache, init=False)
    ledger: ProgressLedger | None = field(default=None, init=False)
    _host_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _last_host_time: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.robots = RobotsCache(user_agent=self.user_agent, timeout=min(self.timeout, 10.0))
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_index = HttpCacheIndex(self.cache_dir / "http_cache.json")
            self.ledger = ProgressLedger(self.cache_dir / "ledger.json")

    def _throttle(self, url: str) -> None:
        if self.min_delay <= 0:
            return
        host = urllib.parse.urlparse(url).netloc
        with self._host_lock:
            now = time.monotonic()
            prev = self._last_host_time.get(host, 0.0)
            wait = self.min_delay - (now - prev)
            if wait > 0:
                time.sleep(wait)
            self._last_host_time[host] = time.monotonic()

    def _decode_body(self, raw: bytes, content_encoding: str) -> bytes:
        enc = content_encoding.lower().strip()
        if enc == "gzip":
            return gzip.decompress(raw)
        if enc == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
        return raw

    def fetch(
        self,
        url: str,
        *,
        force_refresh: bool = False,
        headers: dict[str, str] | None = None,
        method: str = "GET",
    ) -> FetchResult:
        """Fetch URL with conditional headers (`If-None-Match` / `If-Modified-Since`) and retries."""
        if self.respect_robots and not self.robots.can_fetch(url):
            res = FetchResult(url=url, final_url=url, status=0, skipped_robots=True, error="Blocked by robots.txt")
            if self.ledger:
                self.ledger.record(LedgerEntry(url=url, status="skipped_robots", error="Blocked by robots.txt"))
            return res

        cached = None if (force_refresh or self.cache_index is None) else self.cache_index.get(url)
        req_headers: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        if headers:
            req_headers.update(headers)
        if cached:
            if cached.get("etag"):
                req_headers["If-None-Match"] = str(cached["etag"])
            if cached.get("last_modified"):
                req_headers["If-Modified-Since"] = str(cached["last_modified"])

        last_err = ""
        ctx = ssl.create_default_context()

        for attempt in range(self.max_retries + 1):
            self._throttle(url)
            req = urllib.request.Request(url, headers=req_headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                    status = int(getattr(resp, "status", 200))
                    final_url = resp.geturl()
                    resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                    raw = b"" if method == "HEAD" else resp.read()
                    body = self._decode_body(raw, resp_headers.get("content-encoding", "")) if raw else raw
                    digest = sha256_bytes(body) if body else (cached.get("sha256", "") if cached else "")
                    etag = resp_headers.get("etag", "")
                    last_mod = resp_headers.get("last-modified", "")
                    ctype = resp_headers.get("content-type", "")

                    if self.cache_index is not None and method == "GET":
                        self.cache_index.put(
                            url,
                            {
                                "etag": etag,
                                "last_modified": last_mod,
                                "sha256": digest,
                                "content_type": ctype,
                                "fetched_at": utc_now_iso(),
                            },
                        )
                    if self.ledger:
                        self.ledger.record(LedgerEntry(url=url, status="ok", http_status=status))
                    return FetchResult(
                        url=url,
                        final_url=final_url,
                        status=status,
                        body=body,
                        etag=etag,
                        last_modified=last_mod,
                        content_type=ctype,
                        sha256=digest,
                    )
            except urllib.error.HTTPError as exc:
                if exc.code == 304:
                    etag = exc.headers.get("ETag", "") or (cached.get("etag", "") if cached else "")
                    last_mod = exc.headers.get("Last-Modified", "") or (cached.get("last_modified", "") if cached else "")
                    if self.ledger:
                        self.ledger.record(LedgerEntry(url=url, status="not_modified", http_status=304))
                    return FetchResult(
                        url=url,
                        final_url=url,
                        status=304,
                        etag=etag,
                        last_modified=last_mod,
                        sha256=cached.get("sha256", "") if cached else "",
                        from_cache=True,
                        not_modified=True,
                    )
                last_err = f"HTTP {exc.code}: {exc.reason}"
                if exc.code not in _RETRYABLE_STATUS or attempt >= self.max_retries:
                    if self.ledger:
                        self.ledger.record(LedgerEntry(url=url, status="failed", http_status=exc.code, error=last_err))
                    return FetchResult(url=url, final_url=url, status=exc.code, error=last_err)

                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = self._retry_delay(attempt, retry_after)
                time.sleep(delay)
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                if attempt >= self.max_retries:
                    if self.ledger:
                        self.ledger.record(LedgerEntry(url=url, status="failed", error=last_err))
                    return FetchResult(url=url, final_url=url, status=0, error=last_err)
                time.sleep(self._retry_delay(attempt))

        return FetchResult(url=url, final_url=url, status=0, error=last_err or "Unknown error")

    def check(self, url: str) -> FetchResult:
        """Issue a conditional HEAD check (falling back to conditional GET if HEAD is rejected)."""
        res = self.fetch(url, method="HEAD")
        if res.status == 405:
            return self.fetch(url, method="GET")
        return res

    def save_state(self) -> None:
        if self.cache_index is not None:
            self.cache_index.save()
        if self.ledger is not None:
            self.ledger.save()

    def _retry_delay(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), 30.0)
        return self.backoff_base * (2**attempt) + random.uniform(0.05, 0.35)
