"""Uit een productpagina: naam, merk, EAN, prijs, varianten.

Werkt op server-gerenderde HTML. Volgorde van betrouwbaarheid:
  1. schema.org JSON-LD (Product / ProductGroup met hasVariant)
  2. microdata (itemprop)
  3. OpenGraph meta (product:price:amount)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from .normalize import clean_ean


@dataclass
class Offer:
    """Eén koopbaar artikel: een specifieke inhoud/kleur bij één winkel."""
    shop: str
    url: str
    name: str
    price: float | None = None
    currency: str = "EUR"
    brand: str | None = None
    ean: str | None = None
    sku: str | None = None
    availability: str | None = None
    variant_label: str | None = None
    price_old: float | None = None
    source: str = ""            # welke extractiemethode
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------

def _walk(node, out):
    if isinstance(node, list):
        for n in node:
            _walk(n, out)
    elif isinstance(node, dict):
        if "@type" in node:
            out.append(node)
        for v in node.values():
            _walk(v, out)


def jsonld_objects(html: str) -> list[dict]:
    tree = HTMLParser(html)
    objs: list[dict] = []
    for tag in tree.css('script[type="application/ld+json"]'):
        raw = tag.text(deep=True, strip=False)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            # sommige shops zetten meerdere objecten achter elkaar
            try:
                data = json.loads("[" + raw.replace("}\n{", "},{") + "]")
            except ValueError:
                continue
        _walk(data, objs)
    return objs


def _types(obj: dict) -> set[str]:
    t = obj.get("@type")
    if isinstance(t, str):
        return {t}
    if isinstance(t, list):
        return {str(x) for x in t}
    return set()


def _price_of(offers) -> tuple[float | None, str | None, float | None]:
    """(prijs, beschikbaarheid, oude prijs) uit een Offer/AggregateOffer."""
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None, None, None
    price = offers.get("price") or offers.get("lowPrice")
    avail = offers.get("availability")
    if isinstance(avail, str):
        avail = avail.rsplit("/", 1)[-1]
    try:
        price = float(str(price).replace(",", ".")) if price is not None else None
    except ValueError:
        price = None
    return price, avail, None


def _brand_of(obj: dict) -> str | None:
    b = obj.get("brand")
    if isinstance(b, dict):
        return b.get("name")
    if isinstance(b, str):
        return b
    if isinstance(b, list) and b:
        return _brand_of({"brand": b[0]})
    return None


def _gtin_of(obj: dict) -> str | None:
    for key in ("gtin13", "gtin", "gtin14", "gtin12", "gtin8", "ean", "isbn"):
        v = obj.get(key)
        if v:
            e = clean_ean(v)
            if e:
                return e
    return None


def offers_from_html(html: str, url: str, shop: str) -> list[Offer]:
    """Alle koopbare varianten op deze pagina."""
    objs = jsonld_objects(html)
    products = [o for o in objs if _types(o) & {"Product", "ProductGroup"}]
    # _walk levert ook de varianten *in* een ProductGroup op; die horen niet
    # nog eens als los product geteld te worden.
    nested = {id(v) for p in products for v in _as_list(p.get("hasVariant"))}
    products = [p for p in products if id(p) not in nested]
    out: list[Offer] = []

    for p in products:
        brand = _brand_of(p)
        variants = p.get("hasVariant")
        if isinstance(variants, dict):
            variants = [variants]
        if isinstance(variants, list) and variants:
            for v in variants:
                if not isinstance(v, dict):
                    continue
                price, avail, old = _price_of(v.get("offers"))
                if price is None:
                    continue
                out.append(Offer(
                    shop=shop,
                    url=_abs(v.get("url") or url, url),
                    name=_clean(v.get("name") or p.get("name") or ""),
                    price=price,
                    brand=_brand_of(v) or brand,
                    ean=_gtin_of(v) or _gtin_of(p),
                    sku=str(v.get("sku") or "") or None,
                    availability=avail,
                    source="jsonld:hasVariant",
                ))
            if out:
                continue

        if "ProductGroup" in _types(p) and not p.get("offers"):
            continue
        price, avail, old = _price_of(p.get("offers"))
        if price is None:
            continue
        out.append(Offer(
            shop=shop,
            url=url,
            name=_clean(p.get("name") or ""),
            price=price,
            brand=brand,
            ean=_gtin_of(p),
            sku=str(p.get("sku") or p.get("mpn") or "") or None,
            availability=avail,
            source="jsonld:product",
        ))

    if out:
        _fill_missing_ean(out, html)
        return out

    fallback = _from_meta(html, url, shop)
    if fallback:
        _fill_missing_ean(fallback, html)
    return fallback


_META_PRICE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:)?product:price:amount["\'][^>]*content=["\']([\d.,]+)',
    re.IGNORECASE)
_META_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)', re.IGNORECASE)
_META_BRAND = re.compile(
    r'<meta[^>]+property=["\'](?:og:)?product:brand["\'][^>]*content=["\']([^"\']+)', re.IGNORECASE)


def _from_meta(html: str, url: str, shop: str) -> list[Offer]:
    m = _META_PRICE.search(html)
    if not m:
        return []
    try:
        price = float(m.group(1).replace(",", "."))
    except ValueError:
        return []
    title = _META_TITLE.search(html)
    brand = _META_BRAND.search(html)
    return [Offer(
        shop=shop, url=url,
        name=_clean(title.group(1) if title else ""),
        price=price,
        brand=_clean(brand.group(1)) if brand else None,
        source="opengraph",
    )]


_EAN_LABEL = re.compile(
    r"(?:ean|gtin|barcode|streepjescode)[^0-9]{0,24}(\d{8,14})(?!\d)", re.IGNORECASE)


def _fill_missing_ean(offers: list[Offer], html: str) -> None:
    """Laatste redmiddel: een EAN die ergens in de specificatietabel staat."""
    if all(o.ean for o in offers):
        return
    hits = {clean_ean(m.group(1)) for m in _EAN_LABEL.finditer(html)}
    hits.discard(None)
    if len(hits) == 1 and len(offers) == 1:
        offers[0].ean = hits.pop()


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _clean(s: str) -> str:
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(s or "")).strip()


def _abs(href: str, base: str) -> str:
    return urljoin(base, href or "")
