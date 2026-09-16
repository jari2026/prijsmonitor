"""Eigen artikelen koppelen aan die van concurrenten.

Volgorde:
  1. EAN gelijk            -> zeker (1.00)
  2. merk + inhoud + naam  -> score tussen 0 en 1, drempel instelbaar
  3. handmatige overrides  -> altijd leidend, ook om een foute match te blokkeren
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from .extract import Offer
from .normalize import (
    fold, line_tokens, normalize_brand, parse_color, parse_gloss,
    parse_size, product_line, size_label, variant_markers,
)

log = logging.getLogger(__name__)


@dataclass
class Item:
    """Een offer plus alles wat eruit af te leiden valt."""
    offer: Offer
    brand: str | None
    line: str
    tokens: set[str]
    liters: float | None
    kilos: float | None
    size: str | None
    gloss: str | None
    color: str | None
    markers: set[str]

    @property
    def price_per_liter(self) -> float | None:
        if self.offer.price and self.liters:
            return round(self.offer.price / self.liters, 2)
        return None


def enrich(offer: Offer) -> Item:
    full = " ".join(filter(None, [offer.name, offer.variant_label]))
    brand = normalize_brand(offer.brand) or _brand_from_name(offer.name)
    liters, kilos, _ = parse_size(full)
    color, _ = parse_color(full)
    return Item(
        offer=offer,
        brand=brand,
        line=product_line(offer.name, brand),
        tokens=line_tokens(product_line(full, brand)),
        liters=liters, kilos=kilos,
        size=size_label(liters, kilos),
        gloss=parse_gloss(full),
        color=color,
        markers=variant_markers(full),
    )


_KNOWN_BRANDS = [
    "sikkens", "sigma", "flexa", "histor", "wijzonol", "alabastine", "rambo", "hermadix",
    "cetabever", "koopmans", "trae-lyx", "rust-oleum", "farrow-and-ball", "little-greene",
    "painting-the-past", "pure-and-original", "flamant", "copperant", "magpaint", "soudal",
    "anza", "motip", "international", "ciranova", "prochemko", "dekker", "brantho-korrux",
    "boonstoppel", "drenth", "epifanes", "owatrol", "linitop", "remmers", "caparol",
]


def _brand_from_name(name: str) -> str | None:
    low = fold(name)
    flat = low.replace("-", " ")
    for b in _KNOWN_BRANDS:
        if b.replace("-", " ") in flat:
            return b
    return None


# --------------------------------------------------------------------------

def size_matches(a: Item, b: Item) -> bool:
    if a.liters is not None and b.liters is not None:
        return abs(a.liters - b.liters) <= max(0.01, a.liters * 0.02)
    if a.kilos is not None and b.kilos is not None:
        return abs(a.kilos - b.kilos) <= max(0.01, a.kilos * 0.02)
    return False            # zonder inhoud aan beide kanten geen match


def color_conflict(a: Item, b: Item) -> bool:
    return bool(a.color and b.color and a.color != b.color)


def gloss_conflict(a: Item, b: Item) -> bool:
    return bool(a.gloss and b.gloss and a.gloss != b.gloss)


def marker_conflict(a: Item, b: Item) -> bool:
    """Een varianttermijn die maar aan één kant staat, betekent: ander product."""
    return bool(a.markers ^ b.markers)


def name_score(a: Item, b: Item) -> float:
    if not a.tokens or not b.tokens:
        return 0.0
    inter = a.tokens & b.tokens
    union = a.tokens | b.tokens
    jaccard = len(inter) / len(union)
    # dekking van de kortste naam telt zwaarder: "Rubbol BL Satura" in een
    # langere concurrentnaam mag gewoon een match zijn
    coverage = len(inter) / min(len(a.tokens), len(b.tokens))
    return round(0.4 * jaccard + 0.6 * coverage, 3)


@dataclass
class Match:
    item: Item
    score: float
    method: str


def find_matches(own: Item, pool: list[Item], *, threshold: float = 0.6) -> list[Match]:
    """Beste kandidaat per winkel."""
    best: dict[str, Match] = {}

    for cand in pool:
        shop = cand.offer.shop
        if own.offer.ean and cand.offer.ean and own.offer.ean == cand.offer.ean:
            m = Match(cand, 1.0, "ean")
        else:
            if own.brand and cand.brand and own.brand != cand.brand:
                continue
            if not size_matches(own, cand):
                continue
            if (color_conflict(own, cand) or gloss_conflict(own, cand)
                    or marker_conflict(own, cand)):
                continue
            score = name_score(own, cand)
            if score < threshold:
                continue
            m = Match(cand, score, "naam+inhoud")

        prev = best.get(shop)
        if prev is None or m.score > prev.score:
            best[shop] = m

    return sorted(best.values(), key=lambda m: -m.score)


# --------------------------------------------------------------------------
# Handmatige correcties
# --------------------------------------------------------------------------

def load_overrides(path: Path) -> dict[tuple[str, str], str | None]:
    """config/overrides.csv: own_sku,shop,competitor_url

    Een lege competitor_url betekent: voor deze winkel is er geen match,
    onderdruk wat de automaat vindt.
    """
    out: dict[tuple[str, str], str | None] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = ((row.get("own_sku") or "").strip(), (row.get("shop") or "").strip())
            if not key[0] or not key[1]:
                continue
            out[key] = (row.get("competitor_url") or "").strip() or None
    log.info("%d handmatige koppelingen geladen", len(out))
    return out


def apply_overrides(own: Item, matches: list[Match], pool_by_url: dict[str, Item],
                    overrides: dict[tuple[str, str], str | None]) -> list[Match]:
    sku = own.offer.sku or ""
    if not sku:
        return matches
    result = {m.item.offer.shop: m for m in matches}
    for (own_sku, shop), url in overrides.items():
        if own_sku != sku:
            continue
        if url is None:
            result.pop(shop, None)
        elif url in pool_by_url:
            result[shop] = Match(pool_by_url[url], 1.0, "handmatig")
    return sorted(result.values(), key=lambda m: -m.score)
