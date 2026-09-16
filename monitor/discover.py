"""Product-URL's vinden via de sitemap(s) van een winkel."""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from .http import Fetcher

log = logging.getLogger(__name__)

_LOC = re.compile(rb"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


def sitemap_urls(fetcher: Fetcher, sitemap_url: str, *, max_depth: int = 3) -> list[str]:
    """Alle <loc>'s, sitemap-indexen worden uitgeklapt."""
    seen: set[str] = set()
    out: list[str] = []
    queue: list[tuple[str, int]] = [(sitemap_url, 0)]

    while queue:
        url, depth = queue.pop(0)
        if url in seen or depth > max_depth:
            continue
        seen.add(url)
        data = fetcher.get_bytes(url)
        if not data:
            continue
        is_index = b"<sitemapindex" in data[:2000].lower()
        locs = [m.group(1).decode("utf-8", "replace") for m in _LOC.finditer(data)]
        if is_index:
            for loc in locs:
                queue.append((loc, depth + 1))
        else:
            out.extend(locs)
    return out


def robots_sitemaps(fetcher: Fetcher, base: str) -> list[str]:
    txt = fetcher.get_text(f"{base}/robots.txt") or ""
    return re.findall(r"(?im)^\s*sitemap:\s*(\S+)", txt)


def product_urls(fetcher: Fetcher, shop: dict) -> list[str]:
    """Sitemap-URL's gefilterd tot waarschijnlijke productpagina's."""
    urls = sitemap_urls(fetcher, shop["sitemap"])
    if not urls:
        # De ingestelde sitemap gaf niets terug; kijk wat robots.txt aanwijst.
        log.warning("%s: sitemap %s leverde niets op, robots.txt proberen",
                    shop["label"], shop["sitemap"])
        for alt in robots_sitemaps(fetcher, shop["base"]):
            urls.extend(sitemap_urls(fetcher, alt))
    include = re.compile(shop["product_url_pattern"]) if shop.get("product_url_pattern") else None
    exclude = re.compile(shop["exclude_url_pattern"]) if shop.get("exclude_url_pattern") else None

    keep = []
    for u in urls:
        path = urlsplit(u).path
        if include and not include.search(path):
            continue
        if exclude and exclude.search(path):
            continue
        keep.append(u)
    log.info("%s: %d sitemap-URL's -> %d productkandidaten", shop["label"], len(urls), len(keep))
    return keep


def filter_by_brands(urls: list[str], brand_slugs: set[str]) -> list[str]:
    """Alleen URL's waarvan de slug een van deze merken noemt.

    Dit houdt het aantal requests klein: we halen niet de hele catalogus op,
    alleen de merken die in de watchlist voorkomen.
    """
    if not brand_slugs:
        return urls
    needles = set()
    for b in brand_slugs:
        needles.add(b)
        needles.add(b.replace("-", ""))
        needles.update(b.split("-"))
    needles = {n for n in needles if len(n) >= 4}

    keep = []
    for u in urls:
        slug = urlsplit(u).path.lower()
        if any(n in slug for n in needles):
            keep.append(u)
    return keep
