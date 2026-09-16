"""Beleefde HTTP-client: 1 request per seconde per host, retries, caching binnen een run."""
from __future__ import annotations

import gzip
import io
import logging
import threading
import time
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)


class Fetcher:
    def __init__(self, user_agent: str, rps: float = 1.0, timeout: int = 30, retries: int = 3):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "nl-NL,nl;q=0.9",
        })
        self.min_interval = 1.0 / rps if rps > 0 else 0.0
        self.timeout = timeout
        self.retries = retries
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._cache: dict[str, bytes] = {}
        self.stats = {"requests": 0, "cached": 0, "errors": 0}

    def _wait(self, url: str) -> None:
        host = urlsplit(url).netloc
        with self._lock:
            prev = self._last.get(host, 0.0)
            delay = self.min_interval - (time.monotonic() - prev)
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()

    def get_bytes(self, url: str, *, use_cache: bool = True) -> bytes | None:
        if use_cache and url in self._cache:
            self.stats["cached"] += 1
            return self._cache[url]
        last_err = None
        for attempt in range(self.retries):
            self._wait(url)
            try:
                r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                self.stats["requests"] += 1
                if r.status_code == 404:
                    return None
                if r.status_code in (429, 503):
                    time.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.content
                if url.endswith(".gz") or r.headers.get("content-type", "").startswith("application/gzip"):
                    try:
                        data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
                    except OSError:
                        pass
                if use_cache:
                    self._cache[url] = data
                return data
            except requests.RequestException as e:      # netwerk, TLS, timeout
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        self.stats["errors"] += 1
        log.warning("kon %s niet ophalen: %s", url, last_err)
        return None

    def get_text(self, url: str, **kw) -> str | None:
        data = self.get_bytes(url, **kw)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")

    def get_json(self, url: str, **kw):
        import json
        txt = self.get_text(url, **kw)
        if not txt:
            return None
        try:
            return json.loads(txt)
        except ValueError:
            return None
