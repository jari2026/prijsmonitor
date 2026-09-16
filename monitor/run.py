"""Haalt prijzen op, koppelt ze en schrijft de data voor het dashboard weg.

    python -m monitor.run --limit 40

Uitvoer:
    docs/data/latest.json   momentopname + matches
    docs/data/history.json  prijsverloop per artikel per winkel
    docs/data/report.json   wat ging goed / mis in deze run
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .discover import filter_by_brands, product_urls
from .extract import Offer
from .http import Fetcher
from .match import (Item, apply_overrides, enrich, find_matches, load_overrides)
from .shops.adapters import (ADAPTERS, EAN_FINDERS, woo_catalog,
                             woo_offers, woo_products_by_slug)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
log = logging.getLogger("monitor")


# --------------------------------------------------------------------------

def load_watchlist(path: Path) -> tuple[set[str], set[str]]:
    """(slugs, skus) waarop het eigen assortiment gefilterd wordt."""
    slugs: set[str] = set()
    skus: set[str] = set()
    if not path.exists():
        return slugs, skus
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            url = (row.get("url") or "").strip()
            sku = (row.get("sku") or "").strip()
            if url:
                slugs.add(url.rstrip("/").rsplit("/", 1)[-1])
            if sku:
                skus.add(sku)
    return slugs, skus


def select_own(products: list[dict], slugs: set[str], skus: set[str], limit: int) -> list[dict]:
    if slugs or skus:
        chosen = [p for p in products
                  if p.get("slug") in slugs or str(p.get("sku") or "") in skus]
        missing = len(slugs | skus) - len(chosen)
        if missing > 0:
            log.warning("%d regels uit de watchlist niet teruggevonden in de catalogus", missing)
        return chosen
    # geen watchlist: neem producten met varianten (echte blikken, geen losse artikelen)
    ranked = sorted(products, key=lambda p: -len(p.get("variations") or []))
    return ranked[:limit]


# --------------------------------------------------------------------------

def gather_by_ean(fetcher: Fetcher, key: str, shop: dict,
                  eans: list[str]) -> tuple[list[Offer], dict]:
    """Twee requests per artikel, en de match is per definitie goed."""
    finder = EAN_FINDERS[shop["ean_lookup"]]
    offers: list[Offer] = []
    found = 0
    for i, ean in enumerate(eans, 1):
        try:
            hits = finder(fetcher, shop["base"], ean, key)
        except Exception as e:                           # noqa: BLE001
            log.debug("%s: EAN %s -> %s", shop["label"], ean, e)
            hits = []
        if hits:
            found += 1
            offers.extend(hits)
        if i % 50 == 0:
            log.info("%s: %d/%d EAN's opgezocht, %d gevonden", shop["label"], i, len(eans), found)
    stats = {"methode": "ean-zoek", "gezocht": len(eans), "gevonden": found, "offers": len(offers)}
    log.info("%s: %s", shop["label"], stats)
    return offers, stats


def gather_competitor(fetcher: Fetcher, key: str, shop: dict, brands: set[str],
                      max_pages: int) -> tuple[list[Offer], dict]:
    adapter = ADAPTERS[shop["adapter"]]
    urls = product_urls(fetcher, shop)
    focused = filter_by_brands(urls, brands)
    if not focused:
        log.warning("%s: geen URL's die een van de gezochte merken noemen", shop["label"])
    focused = focused[:max_pages]

    offers: list[Offer] = []
    for i, url in enumerate(focused, 1):
        try:
            offers.extend(adapter(fetcher, url, key))
        except Exception as e:                       # één rotte pagina stopt de run niet
            log.debug("%s: %s -> %s", shop["label"], url, e)
        if i % 100 == 0:
            log.info("%s: %d/%d pagina's, %d offers", shop["label"], i, len(focused), len(offers))

    stats = {"methode": "sitemap", "sitemap_urls": len(urls), "bezocht": len(focused),
             "offers": len(offers), "met_ean": sum(1 for o in offers if o.ean)}
    log.info("%s: %s", shop["label"], stats)
    return offers, stats


# --------------------------------------------------------------------------

def build_rows(own_items: list[Item], pool: list[Item], overrides, threshold: float) -> list[dict]:
    pool_by_url = {i.offer.url: i for i in pool}
    rows = []
    for own in own_items:
        matches = find_matches(own, pool, threshold=threshold)
        matches = apply_overrides(own, matches, pool_by_url, overrides)
        comp = []
        for m in matches:
            o = m.item.offer
            comp.append({
                "shop": o.shop, "url": o.url, "name": o.name, "price": o.price,
                "price_old": o.price_old, "availability": o.availability,
                "ean": o.ean, "sku": o.sku, "size": m.item.size,
                "price_per_liter": m.item.price_per_liter,
                "score": m.score, "method": m.method,
            })
        prices = [c["price"] for c in comp if c["price"]]
        own_price = own.offer.price
        cheapest = min(prices) if prices else None
        rows.append({
            "sku": own.offer.sku, "name": own.offer.name, "url": own.offer.url,
            "brand": own.brand, "line": own.line, "size": own.size,
            "liters": own.liters, "kilos": own.kilos,
            "gloss": own.gloss, "color": own.color, "ean": own.offer.ean,
            "price": own_price, "price_per_liter": own.price_per_liter,
            "availability": own.offer.availability,
            "competitors": comp,
            "cheapest_competitor": cheapest,
            "position": _position(own_price, prices),
            "delta_vs_cheapest": (round(own_price - cheapest, 2)
                                  if own_price and cheapest else None),
            "delta_pct": (round((own_price - cheapest) / cheapest * 100, 1)
                          if own_price and cheapest else None),
        })
    return rows


def _position(own_price, prices) -> str:
    if not own_price or not prices:
        return "onbekend"
    cheapest = min(prices)
    if own_price < cheapest - 0.005:
        return "goedkoopste"
    if abs(own_price - cheapest) <= 0.005:
        return "gelijk"
    if own_price > max(prices) + 0.005:
        return "duurste"
    return "duurder"


# --------------------------------------------------------------------------

def update_history(rows: list[dict], stamp: str) -> dict:
    path = DATA / "history.json"
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for row in rows:
        key = row["sku"] or row["url"]
        series = hist.setdefault(key, {})
        _append(series.setdefault("verfplaza", []), stamp, row["price"])
        for c in row["competitors"]:
            _append(series.setdefault(c["shop"], []), stamp, c["price"])
    path.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return hist


def _append(series: list, stamp: str, price) -> None:
    if price is None:
        return
    if series and series[-1][1] == price:
        return                                   # alleen wijzigingen bewaren
    if series and series[-1][0] == stamp:
        series[-1] = [stamp, price]
        return
    series.append([stamp, price])


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config" / "shops.yaml"))
    ap.add_argument("--limit", type=int, default=40, help="aantal eigen producten zonder watchlist")
    ap.add_argument("--max-pages", type=int, default=1200, help="max productpagina's per winkel")
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--only", help="komma-gescheiden winkelsleutels")
    ap.add_argument("--force-sitemap", action="store_true",
                    help="ook de op EAN doorzoekbare winkels via de sitemap doorlopen")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    crawl = cfg.get("crawl", {})
    fetcher = Fetcher(
        user_agent=crawl.get("user_agent", "prijsmonitor/1.0"),
        rps=crawl.get("requests_per_second", 1.0),
        timeout=crawl.get("timeout_seconds", 30),
        retries=crawl.get("retries", 3),
    )

    own_key = cfg["own"]
    own_cfg = cfg["shops"][own_key]
    DATA.mkdir(parents=True, exist_ok=True)

    # 1. eigen assortiment
    slugs, skus = load_watchlist(ROOT / "config" / "watchlist.csv")
    if slugs and not skus:
        # Gericht opvragen is sneller en betrouwbaarder dan de hele catalogus.
        selected = woo_products_by_slug(fetcher, own_cfg["base"], sorted(slugs))
        gevonden = {p.get("slug") for p in selected}
        for ontbreekt in sorted(slugs - gevonden):
            log.warning("watchlist: geen product met slug %r op de site", ontbreekt)
    else:
        selected = select_own(woo_catalog(fetcher, own_cfg["base"]), slugs, skus, args.limit)
    log.info("%d eigen producten geselecteerd", len(selected))

    own_offers: list[Offer] = []
    for p in selected:
        own_offers.extend(woo_offers(fetcher, own_cfg["base"], p, own_key,
                                     with_ean=own_cfg.get("enrich_ean_from_page", True)))
    own_items = [enrich(o) for o in own_offers]
    log.info("%d eigen artikelen (varianten), %d met EAN",
             len(own_items), sum(1 for i in own_items if i.offer.ean))

    brands = {i.brand for i in own_items if i.brand}
    log.info("merken in scope: %s", ", ".join(sorted(brands)) or "(geen)")

    # 2. concurrenten
    own_eans = sorted({i.offer.ean for i in own_items if i.offer.ean})
    wanted = set((args.only or "").split(",")) - {""} or None
    pool: list[Item] = []
    shop_stats = {}
    for key, shop in cfg["shops"].items():
        if key == own_key or (wanted and key not in wanted):
            continue
        # Winkels die op EAN te doorzoeken zijn: exact opzoeken. De rest: de
        # sitemap langs, beperkt tot de merken die we volgen.
        if shop.get("ean_lookup") and own_eans and not args.force_sitemap:
            offers, stats = gather_by_ean(fetcher, key, shop, own_eans)
        else:
            offers, stats = gather_competitor(fetcher, key, shop, brands, args.max_pages)
        shop_stats[key] = stats
        pool.extend(enrich(o) for o in offers)

    # 3. koppelen
    overrides = load_overrides(ROOT / "config" / "overrides.csv")
    rows = build_rows(own_items, pool, overrides, args.threshold)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    matched = sum(1 for r in rows if r["competitors"])

    (DATA / "latest.json").write_text(json.dumps({
        "generated_at": generated,
        "date": stamp,
        "shops": {k: v["label"] for k, v in cfg["shops"].items()},
        "rows": rows,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    update_history(rows, stamp)

    report = {
        "generated_at": generated,
        "eigen_producten": len(selected),
        "eigen_artikelen": len(own_items),
        "artikelen_met_match": matched,
        "artikelen_zonder_match": len(rows) - matched,
        "matches_via_ean": sum(1 for r in rows for c in r["competitors"] if c["method"] == "ean"),
        "matches_via_naam": sum(1 for r in rows for c in r["competitors"] if c["method"] == "naam+inhoud"),
        "winkels": shop_stats,
        "http": fetcher.stats,
    }
    (DATA / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("klaar: %d/%d artikelen met minstens één match", matched, len(rows))
    log.info("http: %s", fetcher.stats)


if __name__ == "__main__":
    main()
