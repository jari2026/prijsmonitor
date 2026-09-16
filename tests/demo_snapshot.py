"""Bouwt docs/data uit een echte meting van 16 september 2026.

Dit is geen verzonnen voorbeeld: de prijzen zijn op die dag opgehaald bij
Verf-plaza (WooCommerce Store API), De Verfzaak en Decoprof (Lightspeed, exact
op EAN) en Verfwinkel.nl (Magento). Het dient om het dashboard te kunnen zien
voordat de GitHub Action voor het eerst draait; daarna overschrijft de echte
run deze bestanden.

    python -m tests.demo_snapshot
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from monitor.extract import Offer
from monitor.match import enrich
from monitor.run import DATA, build_rows, update_history

VP = "https://www.verf-plaza.nl"

# (naam incl. variant, sku, ean, prijs, pad)
OWN = [
    ("Alabastine Kit en Stickerverwijderaar 100 ml", "5096124", "8710839296520", 11.59, "alabastine-kit-en-stickerverwijderaar"),
    ("Alabastine Kneedbaar Hout donker eiken/noten 75 gram", "5096010", "8710839108403", 4.63, "alabastine-kneedbaar-hout"),
    ("Alabastine Kneedbaar Hout essen/beuken 75 gram", "5096013", "8710839108700", 4.63, "alabastine-kneedbaar-hout"),
    ("Alabastine Kneedbaar Hout meranti/mahonie 75 gram", "5096009", "8710839108304", 4.63, "alabastine-kneedbaar-hout"),
    ("Alabastine Kneedbaar Hout midden eik/teak 75 gram", "5096012", "8710839108601", 4.63, "alabastine-kneedbaar-hout"),
    ("Alabastine Kneedbaar Hout licht eiken 75 gram", "5096008", "8710839108205", 4.63, "alabastine-kneedbaar-hout"),
    ("Alabastine Kneedbaar Hout naturel/vuren 75 gram", "5096006", "8710839108106", 4.63, "alabastine-kneedbaar-hout"),
    ("Alabastine Kneedbaar Hout wit 75 gram", "5096011", "8710839108502", 4.63, "alabastine-kneedbaar-hout"),
    ("Alabastine Spackspray 300 ml", "6035382", "8710839369255", 23.99, "alabastine-spackspray"),
    ("Alabastine Houtrot Reparatieplaatjes", "5314835", "8710839114459", 5.99, "alabastine-houtrot-reparatieplaatjes"),
    ("Alabastine Allesvuller wit 330 gram", "5095984", "8710839103156", 5.99, "alabastine-allesvuller"),
    ("Alabastine Spackvuller wit 330 gram", "5095989", "8710839103385", 11.59, "alabastine-spackvuller"),
    ("Alabastine Houtrot Reparatieset 500 gram", "5096024", "8710839112356", 37.43, "alabastine-houtrot-reparatieset"),
    ("Alabastine Houtplamuur Universeel 250 gram", "5096155", "8710839365066", 7.27, "alabastine-houtplamuur-universeel"),
    ("Alabastine Snelplamuur 400 gram", "5096163", "8710839367107", 12.79, "alabastine-snelplamuur"),
    ("Alabastine Snelplamuur 225 gram", "5096162", "8710839367053", 9.59, "alabastine-snelplamuur"),
    ("Alabastine Muurvuller 500 gram", "5095961", "8710839100056", 4.55, "alabastine-muurvuller"),
    ("Alabastine Muurvuller 1 kg", "5095962", "8710839100117", 8.39, "alabastine-muurvuller"),
    ("Alabastine Muurvuller 2 kg", "5095963", "8710839100155", 14.39, "alabastine-muurvuller"),
    ("Alabastine Voorstrijk Sneldrogend 1 liter", "5256697", "8710839114107", 8.39, "alabastine-voorstrijk-sneldrogend"),
    ("Alabastine Voorstrijk Sneldrogend 2,5 liter", "5256698", "8710839114114", 14.79, "alabastine-voorstrijk-sneldrogend"),
    ("Alabastine Voorstrijk Sneldrogend 5 liter", "5129718", "8710839110482", 25.19, "alabastine-voorstrijk-sneldrogend"),
    ("Alabastine Voorstrijk Sneldrogend 10 liter", "5129719", "8710839110499", 48.39, "alabastine-voorstrijk-sneldrogend"),
    ("Alabastine Houtreparatie 150 gram", "5096022", "8710839112004", 15.59, "alabastine-houtreparatie"),
    ("Alabastine Houtreparatie 500 gram", "5096021", "8710839112059", 27.99, "alabastine-houtreparatie"),
    ("Alabastine Houtrotimpregneer 250 ml", "5485957", "8710839112554", 18.39, "alabastine-houtrotimpregneer"),
    ("Alabastine Houtrotvuller 500 gram", "5096023", "8710839112349", 31.19, "alabastine-houtrotvuller"),
    ("Alabastine Houtrotvuller 1 kg", "5096025", "8710839112387", 53.19, "alabastine-houtrotvuller"),
    ("Alabastine Houtvuller wit 330 gram", "5096029", "8710839112820", 11.99, "alabastine-houtvuller"),
    ("Flexa Mooi Makkelijk Radiatoren lichte kleur 0,75 liter", "5778878", "8711113492171", 24.88, "flexa-mooi-makkelijk-radiatoren"),
    ("Flexa Mooi Makkelijk Radiatoren donkere kleur 0,75 liter", "5778877", "8711113492164", 24.88, "flexa-mooi-makkelijk-radiatoren"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans lichte kleur 0,5 liter", "5123840", "8711113110327", 21.69, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans donkere kleur 0,5 liter", "5123842", "8711113110341", 21.69, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans lichte kleur 1 liter", "5123843", "8711113110358", 36.04, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans donkere kleur 1 liter", "5123845", "8711113110372", 36.04, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans lichte kleur 2,5 liter", "5124038", "8711113110440", 81.37, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans lichte kleur 0,5 liter", "5123846", "8711113110259", 21.69, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans donkere kleur 0,5 liter", "5123848", "8711113110273", 21.69, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans donkere kleur 1 liter", "5123861", "8711113110303", 30.84, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans lichte kleur 1 liter", "5123849", "8711113110280", 30.84, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans lichte kleur 2,5 liter", "5123862", "8711113110310", 79.09, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
]

# Exact op EAN gevonden: (ean, prijs, naam, url)
DEVERFZAAK = [
    ("8710839100056", 5.27, "Alabastine Muurvuller 500 gram", "alabastine-muurvuller"),
    ("8710839103156", 10.13, "Alabastine Allesvuller 330 gram tube", "alabastine-alles-vuller"),
    ("8710839103385", 13.37, "Alabastine Spackvuller 330 gram", "alabastine-spackvuller-330-gram"),
    ("8710839108106", 5.36, "Alabastine Kneedbaar Hout 75 gram Naturel", "alabastine-kneedbaar-hout-75-gram-naturel"),
    ("8710839108205", 5.36, "Alabastine Kneedbaar Hout 75 gram Licht Eiken", "alabastine-kneedbaar-hout-75-gram-licht-eiken"),
    ("8710839108304", 5.36, "Alabastine Kneedbaar Hout 75 gram Mahoni", "alabastine-kneedbaar-hout-75-gram-mahoni"),
    ("8710839108403", 5.36, "Alabastine Kneedbaar Hout 75 gram Eiken/Noten", "alabastine-kneedbaar-hout-75-gram-eiken-noten"),
    ("8710839108502", 5.36, "Alabastine Kneedbaar Hout 75 gram Wit", "alabastine-kneedbaar-hout-75-gram-wit"),
    ("8710839108601", 5.36, "Alabastine Kneedbaar Hout 75 gram Midden Eiken", "alabastine-kneedbaar-hout-75-gram-midden-eiken"),
    ("8710839108700", 5.36, "Alabastine Kneedbaar Hout 75 gram Essen/Beuken", "alabastine-kneedbaar-hout-75-gram-essen-beuken"),
    ("8710839112356", 50.27, "Alabastine Houtrot Reparatieset 500 gram", "alabastine-houtrot-reparatieset-500-gram"),
    ("8710839114107", 9.68, "Alabastine Voorstrijk Sneldrogend Transparant 1 liter", "alabastine-voorstrijk-sneldrogend-10-liter"),
    ("8710839114459", 6.93, "Alabastine Houtrot Reparatieplaatjes Standaard", "alabastine-houtrot-reparatieplaatjes"),
    ("8710839296520", 13.37, "Alabastine Kit- en Stickerverwijderaar 100 ml", "alabastine-kit-en-sticker-verwijderaar-100-ml"),
    ("8710839365066", 8.37, "Alabastine Houtplamuur Universeel 250 gram", "alabastine-houtplamuur-universeel"),
    ("8710839367053", 11.07, "Alabastine Snelplamuur 225 gram", "alabastine-snelplamuur"),
    ("8710839369255", 22.49, "Alabastine Spackspray 300 ml", "alabastine-spackspray-300-ml"),
    ("8710839112004", 18.00, "Alabastine Houtreparatie 150 gram", "alabastine-houtreparatie"),
    ("8710839112387", 61.34, "Alabastine Houtrotvuller 1 kg", "alabastine-houtrotvuller"),
    ("8710839112554", 20.69, "Alabastine Houtrot Impregneer 250 ml", "alabastine-houtrot-impregneer-250-ml"),
    ("8710839112820", 13.82, "Alabastine Houtvuller 330 gram Wit", "alabastine-houtvuller-330-gram-wit"),
    ("8711113110259", 19.19, "Flexa Strak in de Lak Buitenlak Zijdeglans 0,5 liter Wit", "strak-in-de-lak-buitenlak-zijdeglans"),
    ("8711113110327", 19.19, "Flexa Strak in de Lak Buitenlak Hoogglans 0,5 liter Wit", "strak-in-de-lak-buitenlak-hoogglans"),
]

DECOPROF = [
    ("8710839100056", 4.92, "Alabastine Muur Vuller 500 gram", "alabastine-muurvuller-poeder"),
    ("8710839103156", 9.44, "Alabastine Allesvuller 330 gram Wit", "alabastine-allesvuller-kant-en-klaar"),
    ("8710839103385", 12.48, "Alabastine Spackvuller 330 gram", "spackvuller-96299838"),
    ("8710839108106", 5.00, "Alabastine Kneedbaar Hout 75 gram Naturel", "alabastine-kneedbaarhout-donker-eiken-noten"),
    ("8710839112356", 46.92, "Alabastine Houtrot Reparatieset 500 gram", "alabastine-houtrotvulset"),
    ("8710839114107", 9.04, "Alabastine Sneldrogende Voorstrijk Transparant 1 liter", "sneldrogende-voorstrijk-96299820"),
    ("8710839114459", 6.48, "Alabastine Reparatieplaatjes 1 set", "reparatieplaatjes-96299772"),
    ("8710839296520", 12.48, "Alabastine Kit- en Sticker Verwijderaar 100 ml", "alabastine-kit-en-sticker-verwijderaar"),
    ("8710839365066", 7.80, "Alabastine Houtplamuur Universeel 250 gram Gebroken wit", "alabastine-houtplamuur"),
    ("8710839367053", 10.32, "Alabastine Snelplamuur 225 gram", "alabastine-snelplamuur"),
    ("8710839369255", 25.84, "Alabastine Spack Spray 300 ml", "alabastine-spack-spuitbus"),
    ("8710839112004", 16.80, "Alabastine Houtreparatie 150 gram", "alabastine-houtreparatie"),
    ("8710839112349", 33.56, "Alabastine Houtrotvuller 500 gram", "alabastine-houtrotvuller-500gr"),
    ("8710839112554", 19.80, "Alabastine Houtrotstop 1K 250 ml", "alabastine-houtrotstop"),
    ("8710839112820", 12.88, "Alabastine Houtvuller Tube 330 gram Wit", "houtvuller-tube-96299697"),
]

# Magento: geen EAN per variant, wel de echte prijs per inhoudsmaat.
VERFWINKEL = [
    ("Alabastine Houtrot Impregneer 250 ml", 16.50, "alab-impregneer-250ml-houtrotstop"),
    ("Alabastine Allesvuller Kant&Klaar Tube 330 gram", 8.50, "alabastine-allesvuller-kant-en-klaar"),
    ("Alabastine Houtreparatie 150 gram", 14.25, "alabastine-houtreparatie"),
    ("Alabastine Houtrot Reparatieset 500 gram", 40.25, "alabastine-houtrot-reparatie-set-500gr"),
    ("Alabastine Houtrotvuller 500 gram", 27.95, "alabastine-houtrotvuller"),
    ("Alabastine Houtvuller Wit Tube 330 gram", 10.75, "alabastine-houtvuller-tube-wit"),
    ("Alabastine Kit- en Stickerverwijderaar 100 ml", 10.50, "alabastine-kit-en-stickerverwijderaar"),
    ("Alabastine Kneedbaar Hout Donker Eiken/Noten 75 gram", 4.25, "alabastine-kneedbaar-hout-donker-eiken-noten"),
    ("Alabastine Kneedbaar Hout Essen/Beuken 75 gram", 4.25, "alabastine-kneedbaar-hout-essen-beuken"),
    ("Alabastine Kneedbaar Hout Licht Eiken 75 gram", 4.25, "alabastine-kneedbaar-hout-licht-eiken"),
    ("Alabastine Kneedbaar Hout Meranti/Mahonie 75 gram", 4.25, "alabastine-kneedbaar-hout-meratani-mahonie"),
    ("Alabastine Kneedbaar Hout Midden Eiken/Teak 75 gram", 4.25, "alabastine-kneedbaar-hout-midden-eiken-teak"),
    ("Alabastine Kneedbaar Hout Naturel/Vuren 75 gram", 4.25, "alabastine-kneedbaar-hout-naturel-vuren"),
    ("Alabastine Kneedbaar Hout Wit 75 gram", 4.25, "alabastine-kneedbaar-hout-wit"),
    ("Alabastine Reparatieplaatjes", 5.75, "alabastine-reparatieplaatjes"),
    ("Alabastine Snelplamuur 125 ml Tube", 8.75, "alabastine-snelplamuur-tube-125ml"),
    ("Alabastine Spack Spray 300 ml", 21.75, "alabastine-spack-spray"),
    ("Alabastine Spackvuller 330 gram Tube", 10.50, "alabastine-spackvuller-tube-330gr"),
    ("Flexa Mooi Makkelijk Radiatoren 750 ml Kleur", 28.75, "flexa-mooi-makkelijk-radiatoren"),
    ("Flexa Mooi Makkelijk Radiatoren 750 ml Donkere kleur", 28.75, "flexa-mooi-makkelijk-radiatoren"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans 500 ml Kleur", 19.19, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans 1 liter Kleur", 30.75, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans 1 liter Donkere kleur", 30.75, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Hoogglans 500 ml Donkere kleur", 19.19, "flexa-strak-in-de-lak-buitenlak-hoogglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans 500 ml Kleur", 19.19, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans 1 liter Kleur", 30.75, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans 1 liter Donkere kleur", 30.75, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
    ("Flexa Strak in de Lak Buitenlak Zijdeglans 500 ml Donkere kleur", 19.19, "flexa-strak-in-de-lak-buitenlak-zijdeglans"),
]

SHOPS = {
    "verfplaza": "Verf-plaza", "verfwinkel": "Verfwinkel.nl", "verfnl": "Verf.nl",
    "onlineverf": "Onlineverf.nl", "verfwebwinkel": "Verfwebwinkel.nl",
    "deverfzaak": "De Verfzaak", "decoprof": "Decoprof",
}


def brand_of(name: str) -> str:
    return name.split()[0]


def main() -> None:
    own = [enrich(Offer(shop="verfplaza", url=f"{VP}/{slug}/", name=name, price=price,
                        brand=brand_of(name), ean=ean, sku=sku,
                        availability="InStock", source="woo:variation"))
           for name, sku, ean, price, slug in OWN]

    pool = []
    for shop, base, rows in (("deverfzaak", "https://www.deverfzaak.nl", DEVERFZAAK),
                             ("decoprof", "https://www.decoprof.nl", DECOPROF)):
        for ean, price, name, slug in rows:
            pool.append(enrich(Offer(shop=shop, url=f"{base}/{slug}.html", name=name,
                                     price=price, brand=brand_of(name), ean=ean,
                                     availability="InStock", source="lightspeed:variant")))
    for name, price, slug in VERFWINKEL:
        pool.append(enrich(Offer(shop="verfwinkel", url=f"https://www.verfwinkel.nl/{slug}.html",
                                 name=name, price=price, brand=brand_of(name),
                                 availability="InStock", source="magento:variant")))

    rows = build_rows(own, pool, {}, 0.6)
    stamp = "2026-09-16"
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "latest.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": stamp, "shops": SHOPS, "rows": rows,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    update_history(rows, stamp)

    matched = sum(1 for r in rows if r["competitors"])
    by_pos: dict[str, int] = {}
    for r in rows:
        by_pos[r["position"]] = by_pos.get(r["position"], 0) + 1
    print(f"{len(rows)} eigen artikelen, {matched} met minstens één concurrent")
    print("posities:", by_pos)
    for r in rows:
        if not r["competitors"]:
            print("  geen match:", r["name"])


if __name__ == "__main__":
    main()
