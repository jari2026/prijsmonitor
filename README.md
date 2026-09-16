# Prijsmonitor Verf-plaza

Vergelijkt de prijzen van het eigen assortiment met die van zes concurrenten,
per artikel en per inhoudsmaat. Draait gratis op GitHub Actions, publiceert een
dashboard op GitHub Pages.

## Hoe het werkt

1. **Eigen assortiment** komt uit de WooCommerce Store API van verf-plaza.nl
   (`/wp-json/wc/store/v1/products`). Prijs per variatie, en de EAN per variatie
   uit de JSON-LD op de productpagina.
2. **Concurrenten** worden per winkel op de manier opgehaald die daar werkt:

   | Winkel | Systeem | Hoe |
   |---|---|---|
   | Verfwinkel.nl | Magento 2 | zoeken op EAN, prijs per inhoudsmaat uit het configuratieblok |
   | De Verfzaak | Lightspeed | `/search/<ean>/?format=json` — exact, met EAN per variant |
   | Decoprof | Lightspeed | idem |
   | Verfwebwinkel.nl | Shopware 6 | sitemap + JSON-LD op de productpagina |
   | Verf.nl | BigCommerce | sitemap + `ProductGroup.hasVariant` (prijs per variant) |
   | Onlineverf.nl | BigCommerce | sitemap + OpenGraph-prijs |

3. **Koppelen** gebeurt in deze volgorde: gelijke EAN (zeker), anders merk +
   inhoud + naamovereenkomst, en `config/overrides.csv` gaat boven alles.
4. **Uitvoer** in `docs/data/`: `latest.json` (momentopname), `history.json`
   (prijsverloop) en `report.json` (wat er in de run goed en mis ging).

Een match wordt nooit gemaakt als de inhoudsmaat niet klopt. Liever een gat in
de tabel dan een prijs die 2,5 liter met 1 liter vergelijkt.

## Instellen

1. Maak een lege repository aan op GitHub en push deze map erheen.
2. **Settings → Pages → Source: GitHub Actions**.
3. **Settings → Actions → General → Workflow permissions: Read and write**.
4. **Actions → Prijzen bijwerken → Run workflow**.

Daarna draait hij elke dag om 06:00 Nederlandse tijd, en staat het dashboard op
`https://<gebruikersnaam>.github.io/<repo>/`.

## Zelf draaien

```bash
pip install -r requirements.txt
python -m monitor.run --limit 40          # zonder watchlist: 40 producten
python -m monitor.run --only deverfzaak -v  # één winkel, met logregels
python -m tests.test_pipeline             # controles op extractie en matching
```

## Bijsturen

**`config/watchlist.csv`** — welke eigen producten gevolgd worden. Eén regel per
product, met de product-URL of het artikelnummer. Leeg laten = de producten met
de meeste varianten, tot `--limit`.

```csv
url,sku,notitie
https://www.verf-plaza.nl/alabastine-muurvuller/,,bestseller
,5123849,
```

**`config/overrides.csv`** — handmatige koppelingen. Een lege `competitor_url`
onderdrukt wat de automaat vond; dat is de manier om een foute match weg te
halen.

```csv
own_sku,shop,competitor_url,notitie
5095961,verfwinkel,https://www.verfwinkel.nl/alabastine-muurvuller-poeder.html,zelfde blik
5096029,decoprof,,dit is een ander product
```

**`config/shops.yaml`** — winkels, snelheid (standaard 1 request per seconde) en
de user-agent waarmee we ons bekendmaken.

## Waar het mis kan gaan

- **Magento toont de prijs van de goedkoopste variant.** Daarom wordt bij
  Verfwinkel.nl het configuratieblok uitgelezen; zonder dat zou elke maat
  dezelfde prijs krijgen. Als hun thema verandert, valt dat blok weg en blijven
  er gaten in de tabel — geen verkeerde prijzen.
- **Sommige eigen EAN's kloppen niet** (te kort, of een reeks cijfers als
  plaatsvervanger). Die worden genegeerd; het artikel valt dan terug op
  naam-en-inhoudmatching.
- **Variantslugs zijn dubbelzinnig.** `25-liter` in een URL betekent 2,5 liter.
  De leesbare termnaam uit de Store API wordt gebruikt, niet de slug.
- **Prijzen zijn inclusief btw** en zonder verzendkosten of staffelkorting.

## Structuur

```
monitor/normalize.py       inhoud, glansgraad, kleur, merk uit productnamen
monitor/extract.py         JSON-LD / microdata / OpenGraph van een productpagina
monitor/shops/adapters.py  per winkelsysteem: WooCommerce, Lightspeed, Magento
monitor/discover.py        sitemaps uitklappen en filteren
monitor/match.py           EAN-match, naam+inhoudmatch, overrides
monitor/run.py             de run zelf
docs/index.html            het dashboard
tests/test_pipeline.py     controles
tests/demo_snapshot.py     de eerste meting (16-09-2026) om mee te kijken
```
