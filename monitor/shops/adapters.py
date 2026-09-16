"""Per winkelsysteem: hoe kom je aan prijs, inhoud en EAN."""
from __future__ import annotations

import json
import logging
import re

from ..extract import Offer, offers_from_html, jsonld_objects, _types, _gtin_of
from ..http import Fetcher
from ..normalize import clean_ean

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# WooCommerce Store API  (Verf-plaza)
# --------------------------------------------------------------------------

def woo_catalog(fetcher: Fetcher, base: str, *, per_page: int = 100,
                max_pages: int = 100, keep_types=("simple", "variable")) -> list[dict]:
    """Alle producten uit /wp-json/wc/store/v1/products.

    Kleurstalen (type 'color') vallen af; dat zijn geen verkoopbare blikken.
    """
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        url = f"{base}/wp-json/wc/store/v1/products?per_page={per_page}&page={page}"
        batch = fetcher.get_json(url, use_cache=False)
        if not batch:
            break
        out.extend(p for p in batch if p.get("type") in keep_types)
        if len(batch) < per_page:
            break
    log.info("Verf-plaza: %d verkoopbare producten uit de Store API", len(out))
    return out


def _woo_term_names(product: dict) -> dict[str, str]:
    """slug -> leesbare term, bv. '25-liter' -> '2,5 Liter'.

    Belangrijk: de variatie geeft alleen de slug, en die slug is dubbelzinnig.
    '25-liter' is 2,5 liter, niet 25 liter. Zonder deze vertaling gaat de
    inhoudsherkenning (en dus de matching) mis.
    """
    out: dict[str, str] = {}
    for attr in product.get("attributes") or []:
        for term in attr.get("terms") or []:
            slug, name = term.get("slug"), term.get("name")
            if slug and name:
                out[slug] = name
    return out


def woo_offers(fetcher: Fetcher, base: str, product: dict, shop: str,
               *, with_ean: bool = True) -> list[Offer]:
    """Eén WooCommerce-product -> één offer per variatie."""
    minor = (product.get("prices") or {}).get("currency_minor_unit", 2)
    div = 10 ** minor
    brand = next((b.get("name") for b in (product.get("brands") or [])), None)
    ean_by_sku = _woo_eans(fetcher, product) if with_ean else {}
    terms = _woo_term_names(product)

    variations = product.get("variations") or []
    if not variations:
        price = _cents(product.get("prices", {}).get("price"), div)
        if price is None:
            return []
        sku = product.get("sku") or None
        return [Offer(
            shop=shop, url=product.get("permalink", ""), name=_txt(product.get("name")),
            price=price, brand=brand, sku=sku,
            ean=ean_by_sku.get(sku) or (next(iter(ean_by_sku.values())) if len(ean_by_sku) == 1 else None),
            availability="InStock" if product.get("is_in_stock") else "OutOfStock",
            source="woo:simple",
        )]

    offers: list[Offer] = []
    for v in variations:
        detail = fetcher.get_json(f"{base}/wp-json/wc/store/v1/products/{v['id']}")
        if not detail:
            continue
        price = _cents((detail.get("prices") or {}).get("price"), div)
        if price is None:
            continue
        label = " / ".join(terms.get(a.get("value", ""), a.get("value", ""))
                           for a in (v.get("attributes") or [])) or None
        sku = detail.get("sku") or None
        offers.append(Offer(
            shop=shop, url=detail.get("permalink") or product.get("permalink", ""),
            name=_txt(f"{detail.get('name') or product.get('name')} {label or ''}"),
            price=price, brand=brand, sku=sku,
            ean=ean_by_sku.get(sku),
            availability="InStock" if detail.get("is_in_stock") else "OutOfStock",
            variant_label=_txt(label),
            source="woo:variation",
        ))
    return offers


def _woo_eans(fetcher: Fetcher, product: dict) -> dict[str, str]:
    """De Store API geeft geen EAN; de productpagina wel (JSON-LD hasVariant)."""
    url = product.get("permalink")
    if not url:
        return {}
    html = fetcher.get_text(url)
    if not html:
        return {}
    mapping: dict[str, str] = {}
    for obj in jsonld_objects(html):
        if not (_types(obj) & {"Product", "ProductGroup"}):
            continue
        for v in _as_list(obj.get("hasVariant")) + [obj]:
            if not isinstance(v, dict):
                continue
            sku, ean = v.get("sku"), _gtin_of(v)
            if sku and ean:
                mapping[str(sku)] = ean
    return mapping


# --------------------------------------------------------------------------
# Lightspeed eCom  (De Verfzaak, Decoprof)
# --------------------------------------------------------------------------

def lightspeed_offers(fetcher: Fetcher, url: str, shop: str) -> list[Offer]:
    data = fetcher.get_json(url.rstrip("/") + "?format=json")
    if not isinstance(data, dict):
        return []
    p = data.get("product")
    if not isinstance(p, dict):
        return []

    brand = (p.get("brand") or {}).get("title") if isinstance(p.get("brand"), dict) else None
    base_name = _txt(p.get("fulltitle") or p.get("title"))
    variants = p.get("variants")
    offers: list[Offer] = []

    if isinstance(variants, dict) and variants:
        for v in variants.values():
            if not isinstance(v, dict) or v.get("active") is False:
                continue
            price = (v.get("price") or {}).get("price_incl")
            if price is None:
                continue
            label = _txt(v.get("title"))
            stock = (v.get("stock") or {}).get("available")
            offers.append(Offer(
                shop=shop, url=url,
                name=f"{base_name} {label}".strip(),
                price=float(price),
                price_old=_opt_float((v.get("price") or {}).get("price_old_incl")),
                brand=brand, ean=clean_ean(v.get("ean")), sku=str(v.get("sku") or "") or None,
                availability="InStock" if stock else "OutOfStock",
                variant_label=label, source="lightspeed:variant",
            ))
        if offers:
            return offers

    price = (p.get("price") or {}).get("price_incl")
    if price is None:
        return []
    return [Offer(
        shop=shop, url=url, name=base_name, price=float(price),
        price_old=_opt_float((p.get("price") or {}).get("price_old_incl")),
        brand=brand, ean=clean_ean(p.get("ean")), sku=str(p.get("sku") or "") or None,
        availability="InStock" if (p.get("stock") or {}).get("available") else "OutOfStock",
        source="lightspeed:product",
    )]


# --------------------------------------------------------------------------
# Server-gerenderde JSON-LD  (Verfwinkel, Verfwebwinkel, Verf.nl, Onlineverf)
# --------------------------------------------------------------------------

def jsonld_offers(fetcher: Fetcher, url: str, shop: str) -> list[Offer]:
    html = fetcher.get_text(url)
    if not html:
        return []
    return offers_from_html(html, url, shop)


# --------------------------------------------------------------------------
# Magento 2  (Verfwinkel.nl)
# --------------------------------------------------------------------------
# Een Magento-productpagina toont in de JSON-LD maar één prijs: die van de
# goedkoopste variant. Alle inhoudsmaten staan wél in het configuratieblok dat
# de maatkiezer aanstuurt. Zonder dat blok zou elke maat dezelfde prijs krijgen.

_MAGENTO_CFG = "initConfigurableOptionsWithColors("


def _json_after(text: str, start: int) -> dict | None:
    """Het eerste complete { ... }-object vanaf `start`."""
    i = text.find("{", start)
    if i < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(i, min(len(text), i + 2_000_000)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i:j + 1])
                except ValueError:
                    return None
    return None


def magento_variants(html: str) -> list[tuple[str, float]]:
    """[(optielabel, prijs incl. btw)] uit het configureerbare product."""
    pos = html.find(_MAGENTO_CFG)
    if pos < 0:
        return []
    cfg = _json_after(html, pos + len(_MAGENTO_CFG))
    if not isinstance(cfg, dict):
        return []
    prices = cfg.get("optionPrices") or {}
    out: list[tuple[str, float]] = []
    for attr in (cfg.get("attributes") or {}).values():
        for opt in attr.get("options") or []:
            label = _txt(opt.get("label"))
            for pid in opt.get("products") or []:
                amount = ((prices.get(str(pid)) or {}).get("finalPrice") or {}).get("amount")
                if label and amount is not None:
                    out.append((label, round(float(amount), 2)))
                    break
    return out


def magento_offers(fetcher: Fetcher, url: str, shop: str) -> list[Offer]:
    html = fetcher.get_text(url)
    if not html:
        return []
    base = offers_from_html(html, url, shop)
    variants = magento_variants(html)
    if not variants or not base:
        return base
    head = base[0]
    return [Offer(
        shop=shop, url=url, name=_txt(f"{head.name} {label}"), price=price,
        brand=head.brand, ean=None, sku=head.sku,
        availability=head.availability, variant_label=label,
        source="magento:variant",
    ) for label, price in variants]


ADAPTERS = {
    "lightspeed": lightspeed_offers,
    "jsonld": jsonld_offers,
    "magento": magento_offers,
}


# --------------------------------------------------------------------------

def _cents(value, div: int) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(int(value) / div, 2)
    except (TypeError, ValueError):
        try:
            return round(float(str(value).replace(",", ".")), 2)
        except ValueError:
            return None


def _opt_float(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _txt(s) -> str:
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(str(s or ""))).strip()


# --------------------------------------------------------------------------
# Opzoeken op EAN  (exact, geen giswerk)
# --------------------------------------------------------------------------
# Drie van de zes winkels vinden een artikel rechtstreeks op zijn EAN. Dat is
# twee requests per artikel in plaats van een hele catalogus doorlopen, en de
# match is per definitie goed.

def lightspeed_find_by_ean(fetcher: Fetcher, base: str, ean: str, shop: str) -> list[Offer]:
    data = fetcher.get_json(f"{base}/search/{ean}/?format=json", use_cache=False)
    for item in _ls_items(data):
        url = item.get("url") or ""
        if not url:
            continue
        full = url if url.startswith("http") else f"{base}/{url.lstrip('/')}"
        hits = [o for o in lightspeed_offers(fetcher, full, shop) if o.ean == ean]
        if hits:
            return hits
    return []


def _ls_items(data) -> list[dict]:
    if not isinstance(data, dict):
        return []
    products = ((data.get("collection") or {}).get("products")
                or (data.get("catalog") or {}).get("products"))
    if isinstance(products, dict):
        return [v for v in products.values() if isinstance(v, dict)]
    if isinstance(products, list):
        return [v for v in products if isinstance(v, dict)]
    return []


_MAGENTO_LINK = re.compile(
    r'class="[^"]*product-item-link[^"]*"\s+href="([^"]+)"|href="([^"]+)"[^>]*class="[^"]*product-item-link',
    re.IGNORECASE)


def magento_find_by_ean(fetcher: Fetcher, base: str, ean: str, shop: str) -> list[Offer]:
    html = fetcher.get_text(f"{base}/catalogsearch/result/?q={ean}", use_cache=False)
    if not html:
        return []
    links, seen = [], set()
    for m in _MAGENTO_LINK.finditer(html):
        href = (m.group(1) or m.group(2) or "").split("?")[0]
        if href.startswith("http") and href not in seen:
            seen.add(href)
            links.append(href)
    # Een zoekopdracht op een exacte EAN hoort één treffer te geven. Meer dan
    # een handvol betekent dat de zoekmachine op iets anders is gaan lijken --
    # dan liever niets dan een verkeerde koppeling.
    if not links or len(links) > 3:
        return []
    # De EAN wijst de pagina aan, maar Magento koppelt hem aan het ouderproduct:
    # welke inhoudsmaat erbij hoort staat er niet bij. Daarom geven we alle
    # varianten terug zonder EAN en laat de matcher op merk + inhoud beslissen.
    return magento_offers(fetcher, links[0], shop)


EAN_FINDERS = {
    "lightspeed": lightspeed_find_by_ean,
    "magento": magento_find_by_ean,
}
