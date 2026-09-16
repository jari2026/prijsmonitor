"""Controle op de onderdelen die stil fout kunnen gaan: extractie en matching.

    python -m tests.test_pipeline

De HTML-fragmenten hieronder zijn nagebouwd naar wat de winkels in september 2026
daadwerkelijk uitleverden (JSON-LD-vorm per platform).
"""
from __future__ import annotations

import json
import sys

from monitor.extract import Offer, offers_from_html
from monitor.match import enrich, find_matches
from monitor.normalize import parse_size, parse_gloss, parse_color, product_line, size_label
from monitor.run import build_rows

FAILS: list[str] = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: kreeg {got!r}, verwacht {want!r}")


def page(ld: dict | list) -> str:
    return ('<html><head><script type="application/ld+json">'
            + json.dumps(ld) + "</script></head><body></body></html>")


# ---------------------------------------------------------------- normalisatie
def test_normalize():
    check("2,5 liter", parse_size("Sikkens Rubbol BL Satura 2,5 L")[0], 2.5)
    check("750ml", parse_size("Cetabever traplak 750 ml")[0], 0.75)
    check("125ml aaneen", parse_size("Flamant Samplepot 125ml 169 Angel")[0], 0.125)
    check("kilo", parse_size("Alabastine Muurvuller 5 kg")[1], 5.0)
    # '2-in-1' mag niet als inhoudsmaat gelezen worden
    check("2-in-1 valstrik", parse_size("Alabastine 2-in-1 Muurverf - 1 liter")[0], 1.0)
    check("artikelnr geen maat", parse_size("Artikel 5096124")[0], None)
    check("label", size_label(2.5, None), "2,5 L")
    check("label ml", size_label(0.75, None), "750 ml")
    check("hoogglans niet glans", parse_gloss("Wijzonol 4SO Hoogglans"), "hoogglans")
    check("satura=zijdeglans", parse_gloss("Rubbol BL Satura"), "zijdeglans")
    check("ral", parse_color("Lak RAL 9010 zijdeglans")[0], "ral-9010")
    check("mengkleur", parse_color("Pura Lakverf Mat - Mengkleur - 500 ml")[0], "mengkleur")
    check("lijn zonder merk", product_line("Sikkens Rubbol BL Satura 2,5 L", "sikkens"),
          "rubbol bl satura")


# ---------------------------------------------------------------- extractie
def test_extract_product_with_offer_array():
    """Verfwinkel.nl: Product met offers als lijst."""
    html = page({"@context": "http://schema.org", "@type": "Product",
                 "name": "Cetabever Natuurlijk Effect Trappen - Brown Wash",
                 "sku": "VW-CB1030.075BW", "mpn": "VW-CB1030.075BW",
                 "offers": [{"@type": "Offer", "priceCurrency": "EUR", "price": 29.25,
                             "availability": "http://schema.org/InStock"}]})
    offers = offers_from_html(html, "https://x/p.html", "verfwinkel")
    check("verfwinkel aantal", len(offers), 1)
    check("verfwinkel prijs", offers[0].price, 29.25)
    check("verfwinkel voorraad", offers[0].availability, "InStock")


def test_extract_productgroup_hasvariant():
    """Verf.nl: ProductGroup met AggregateOffer + per variant een echte prijs."""
    html = page({"@context": "https://schema.org", "@type": "ProductGroup",
                 "name": "Copperant Pura Lakverf Mat", "sku": "4725-PARENT",
                 "brand": {"@type": "Brand", "name": "Copperant"},
                 "offers": {"@type": "AggregateOffer", "lowPrice": "30.31", "highPrice": "131.32"},
                 "hasVariant": [
                     {"@type": "Product", "name": "Copperant Pura Lakverf Mat - Mengkleur - 500 ml",
                      "sku": "4730", "url": "https://x/p?sku=4730",
                      "offers": {"@type": "Offer", "price": "30.31", "priceCurrency": "EUR",
                                 "availability": "https://schema.org/InStock"}},
                     {"@type": "Product", "name": "Copperant Pura Lakverf Mat - Mengkleur - 1 l",
                      "sku": "4726", "url": "https://x/p?sku=4726",
                      "offers": {"@type": "Offer", "price": "55.56", "priceCurrency": "EUR"}}]})
    offers = offers_from_html(html, "https://x/p", "verfnl")
    check("verfnl varianten", len(offers), 2)
    check("verfnl variantprijs", sorted(o.price for o in offers), [30.31, 55.56])
    check("verfnl merk erft", offers[0].brand, "Copperant")
    check("verfnl eigen url", offers[0].url, "https://x/p?sku=4730")


def test_extract_offer_object_plus_ean_in_spec():
    """Verfwebwinkel: Product met offers als object; EAN alleen in de spectabel."""
    html = page({"@context": "https://schema.org", "@type": "Product",
                 "name": "Flamant Samplepot 125ml 169 Angel", "sku": "360185",
                 "brand": {"@type": "Brand", "name": "Flamant"},
                 "offers": {"@type": "Offer", "price": 9, "priceCurrency": "EUR",
                            "availability": "https://schema.org/InStock"}})
    html = html.replace("</body>", "<tr><td>EAN</td><td>5412345678908</td></tr></body>")
    offers = offers_from_html(html, "https://x/p.html", "verfwebwinkel")
    check("vww prijs", offers[0].price, 9.0)
    check("vww ean uit tabel", offers[0].ean, "5412345678908")


def test_extract_opengraph_fallback():
    """Onlineverf: geen Product-JSON-LD, wel OpenGraph."""
    html = ('<html><head>'
            '<meta property="og:title" content="Anza MICMEX Muurverfset 6-delig">'
            '<meta property="product:price:amount" content="23.84">'
            '<meta property="product:price:currency" content="EUR">'
            '</head><body></body></html>')
    offers = offers_from_html(html, "https://x/p/", "onlineverf")
    check("og aantal", len(offers), 1)
    check("og prijs", offers[0].price, 23.84)
    check("og bron", offers[0].source, "opengraph")


def test_extract_ignores_breadcrumbs():
    html = page([{"@context": "https://schema.org", "@type": "BreadcrumbList",
                  "itemListElement": [{"@type": "ListItem", "position": 1,
                                       "item": {"@id": "https://x/", "name": "Home"}}]}])
    check("breadcrumb genegeerd", offers_from_html(html, "https://x/", "verfwinkel"), [])


# ---------------------------------------------------------------- matching
def o(shop, name, price, **kw):
    return Offer(shop=shop, url=f"https://{shop}/{abs(hash(name))}", name=name, price=price, **kw)


def test_match_on_ean():
    own = enrich(o("verfplaza", "Alabastine 2-in-1 Muurverf Badkamer en Keuken 1 liter", 27.95,
                   ean="8710839146009", sku="A1"))
    pool = [enrich(o("decoprof", "Alabastine 2in1 Muurverf Badkamer En Keuken 1 LTR - Wit", 26.24,
                     ean="8710839146009")),
            enrich(o("deverfzaak", "Iets heel anders 1 liter", 28.12, ean="8710839146009"))]
    ms = find_matches(own, pool)
    check("ean: beide winkels", sorted(m.item.offer.shop for m in ms), ["decoprof", "deverfzaak"])
    check("ean: score", ms[0].score, 1.0)
    check("ean: methode", ms[0].method, "ean")


def test_match_on_name_and_size():
    own = enrich(o("verfplaza", "Sikkens Rubbol BL Satura 2,5 L", 89.95, brand="Sikkens", sku="S1"))
    pool = [
        enrich(o("verfwinkel", "Sikkens Rubbol BL Satura 2,5 liter", 94.50, brand="Sikkens")),
        enrich(o("verfnl", "Sikkens Rubbol BL Satura 1 l", 44.00, brand="Sikkens")),       # andere inhoud
        enrich(o("decoprof", "Sikkens Rubbol AZ Hoogglans 2,5 L", 92.00, brand="Sikkens")),  # andere lijn
        enrich(o("deverfzaak", "Wijzonol Rubbol BL Satura 2,5 L", 88.00, brand="Wijzonol")), # ander merk
    ]
    ms = find_matches(own, pool)
    check("naam: alleen de juiste", [m.item.offer.shop for m in ms], ["verfwinkel"])
    check("naam: methode", ms[0].method, "naam+inhoud")


def test_match_rejects_color_and_gloss_conflict():
    own = enrich(o("verfplaza", "Flexa Strak in de Lak RAL 9010 zijdeglans 750 ml", 24.95,
                   brand="Flexa", sku="F1"))
    pool = [enrich(o("verfwinkel", "Flexa Strak in de Lak RAL 7016 zijdeglans 750 ml", 23.95, brand="Flexa")),
            enrich(o("verfnl", "Flexa Strak in de Lak RAL 9010 hoogglans 750 ml", 22.95, brand="Flexa"))]
    check("kleur/glans conflict geweigerd", find_matches(own, pool), [])


def test_match_rejects_variant_markers():
    """Echte valse koppelingen uit de run van 16-09-2026.

    Merk, inhoud en het grootste deel van de naam kloppen; één woord maakt er
    een ander product van. Zonder deze regel stond er 44,48 naast 25,19.
    """
    def paar(eigen, concurrent):
        return (enrich(o("verfplaza", eigen, 1.0, brand="Alabastine", sku="T")),
                [enrich(o("verfwebwinkel", concurrent, 2.0, brand="Alabastine"))])

    weg = [
        ("Alabastine Voorstrijk Sneldrogend 5 Liter",
         "Alabastine rolbare voorstrijk sneldrogend - wit - 5L"),
        ("Alabastine Voorstrijk Sneldrogend 2,5 Liter",
         "Alabastine Voorstrijk Sneldrogend Dekkend - 2,5L Wit"),
        ("Alabastine Houtrotvuller 1 kg",
         "Alabastine Houtrotvuller - Poeder - Naturel/vuren - 1kg"),
    ]
    for eigen, concurrent in weg:
        own, pool = paar(eigen, concurrent)
        check(f"variant geweigerd: {concurrent[:40]}", find_matches(own, pool), [])

    blijft = [
        ("Alabastine Spackspray 300 ml", "Alabastine Spackspray - 300ml"),
        ("Alabastine Houtplamuur Universeel 250 gram", "Alabastine Houtplamuur - Universeel - 250g"),
        ("Alabastine Houtvuller Wit / 330 Gram", "Alabastine Houtvuller - Wit - 330g"),
        ("Alabastine Snelplamuur 225 Gram", "Alabastine Snelplamuur - 225g"),
    ]
    for eigen, concurrent in blijft:
        own, pool = paar(eigen, concurrent)
        check(f"variant behouden: {concurrent[:40]}", len(find_matches(own, pool)), 1)


def test_rows_and_position():
    own = [enrich(o("verfplaza", "Alabastine Muurvuller 1 liter", 9.95, brand="Alabastine", sku="A9"))]
    pool = [enrich(o("verfwinkel", "Alabastine Muurvuller 1 liter", 11.50, brand="Alabastine")),
            enrich(o("decoprof", "Alabastine Muurvuller 1 liter", 10.25, brand="Alabastine"))]
    rows = build_rows(own, pool, {}, 0.6)
    r = rows[0]
    check("rij: aantal concurrenten", len(r["competitors"]), 2)
    check("rij: goedkoopste concurrent", r["cheapest_competitor"], 10.25)
    check("rij: positie", r["position"], "goedkoopste")
    check("rij: verschil", r["delta_vs_cheapest"], -0.30)
    check("rij: prijs per liter", r["price_per_liter"], 9.95)

    duur = [enrich(o("verfplaza", "Alabastine Muurvuller 1 liter", 12.95, brand="Alabastine", sku="A9"))]
    check("rij: duurste", build_rows(duur, pool, {}, 0.6)[0]["position"], "duurste")


def test_overrides_block_and_force():
    own = [enrich(o("verfplaza", "Histor Perfect Finish 2,5 L", 59.95, brand="Histor", sku="H1"))]
    wrong = enrich(o("verfwinkel", "Histor Perfect Finish 2,5 L", 61.00, brand="Histor"))
    right = enrich(o("verfwinkel", "Histor Perfect Finish Zijdeglans 2,5 L", 57.50, brand="Histor"))
    pool = [wrong, right]
    forced = build_rows(own, pool, {("H1", "verfwinkel"): right.offer.url}, 0.6)[0]
    check("override: forceert", forced["competitors"][0]["url"], right.offer.url)
    check("override: methode", forced["competitors"][0]["method"], "handmatig")
    blocked = build_rows(own, pool, {("H1", "verfwinkel"): None}, 0.6)[0]
    check("override: blokkeert", blocked["competitors"], [])


# ----------------------------------------------------------------
def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:                    # noqa: BLE001
                FAILS.append(f"{name} wierp {type(e).__name__}: {e}")
    if FAILS:
        print("MISLUKT:")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("alle controles goed")


if __name__ == "__main__":
    main()
