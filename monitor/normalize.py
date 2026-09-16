"""Tekst -> vergelijkbare velden: merk, productlijn, inhoud, glansgraad, kleur.

Alles wat met matchen te maken heeft hangt hier aan. Als een match fout gaat,
is dit meestal het bestand dat aangepast moet worden.
"""
from __future__ import annotations

import html
import re
import unicodedata

# --------------------------------------------------------------------------
# Inhoud / volume
# --------------------------------------------------------------------------

# 2,5 liter | 2.5L | 750 ml | 125ml | 1 ltr | 0,75 l | 5 kg | 400 gram
_VOLUME_RE = re.compile(
    r"(?<![\w.,])(\d{1,4}(?:[.,]\d{1,3})?)\s*"
    r"(ml|milliliter|cl|l|lt|ltr|liter|litre|kg|kilo|kilogram|g|gr|gram)"
    r"(?![\w])",
    re.IGNORECASE,
)

_TO_LITER = {
    "ml": 0.001, "milliliter": 0.001, "cl": 0.01,
    "l": 1.0, "lt": 1.0, "ltr": 1.0, "liter": 1.0, "litre": 1.0,
}
_TO_KG = {"kg": 1.0, "kilo": 1.0, "kilogram": 1.0, "g": 0.001, "gr": 0.001, "gram": 0.001}


def parse_size(text: str) -> tuple[float | None, float | None, str | None]:
    """Geef (liters, kilos, letterlijke tekst) terug voor de eerste inhoudsmaat.

    Pakt bewust de *grootste* plausibele match: "Alabastine 2-in-1 1 liter" mag
    niet op de "2" van 2-in-1 vallen.
    """
    best: tuple[float | None, float | None, str] | None = None
    for m in _VOLUME_RE.finditer(text or ""):
        raw = m.group(0)
        num = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        liters = kilos = None
        if unit in _TO_LITER:
            liters = round(num * _TO_LITER[unit], 4)
            if liters > 250:            # onzin, waarschijnlijk een artikelnummer
                continue
        elif unit in _TO_KG:
            kilos = round(num * _TO_KG[unit], 4)
            if kilos > 250:
                continue
        if best is None:
            best = (liters, kilos, raw)
        else:
            # voorkeur voor liters boven kilo's, en voor de grootste waarde
            cur = best[0] or best[1] or 0
            new = liters or kilos or 0
            if (liters is not None and best[0] is None) or new > cur:
                best = (liters, kilos, raw)
    if best is None:
        return None, None, None
    return best


def size_label(liters: float | None, kilos: float | None) -> str | None:
    """Nette, vergelijkbare weergave: 2,5 L / 750 ml / 5 kg."""
    if liters is not None:
        if liters < 1:
            return f"{int(round(liters * 1000))} ml"
        txt = f"{liters:.3f}".rstrip("0").rstrip(".")
        return f"{txt.replace('.', ',')} L"
    if kilos is not None:
        if kilos < 1:
            return f"{int(round(kilos * 1000))} g"
        txt = f"{kilos:.3f}".rstrip("0").rstrip(".")
        return f"{txt.replace('.', ',')} kg"
    return None


# --------------------------------------------------------------------------
# Glansgraad
# --------------------------------------------------------------------------

_GLOSS = [
    ("hoogglans", ("hoogglans", "high gloss", "hoog glans")),
    ("glans", ("glans", "gloss")),
    ("halfglans", ("halfglans", "half glans", "semi gloss", "semi-gloss")),
    ("zijdeglans", ("zijdeglans", "zijde glans", "satin", "satura", "silk")),
    ("zijdemat", ("zijdemat", "zijde mat", "eggshell", "ei glans")),
    ("extra mat", ("extra mat", "supermat", "super mat", "dead flat", "vol mat", "volmat")),
    ("mat", ("mat", "matt", "matte")),
]
# volgorde: langste/meest specifieke eerst zodat "hoogglans" niet als "glans" telt
_GLOSS_ORDER = ["hoogglans", "halfglans", "zijdeglans", "zijdemat", "extra mat", "glans", "mat"]


def parse_gloss(text: str) -> str | None:
    low = f" {_fold(text)} "
    found = {}
    for canon, needles in _GLOSS:
        for n in needles:
            if f" {n} " in low or f" {n}," in low or f"-{n}" in low:
                found[canon] = True
                break
    for canon in _GLOSS_ORDER:
        if canon in found:
            return canon
    return None


# --------------------------------------------------------------------------
# Merk
# --------------------------------------------------------------------------

# Schrijfwijzen die per winkel verschillen -> één noemer.
BRAND_ALIASES = {
    "traelyx": "trae-lyx", "trae lyx": "trae-lyx", "traelyx ": "trae-lyx",
    "rustoleum": "rust-oleum", "rust oleum": "rust-oleum",
    "farrow ball": "farrow-and-ball", "farrow & ball": "farrow-and-ball",
    "farrow and ball": "farrow-and-ball", "f&b": "farrow-and-ball",
    "little greene paint company": "little-greene", "little greene": "little-greene",
    "sigma coatings": "sigma", "sikkens": "sikkens", "akzonobel": "sikkens",
    "painting the past": "painting-the-past",
    "pure paint": "pure-and-original", "pure original": "pure-and-original",
    "pure & original": "pure-and-original",
    "dekker co": "dekker", "dekker & co": "dekker",
    "brantho korrux": "brantho-korrux",
    "koopmans": "koopmans", "hermadix": "hermadix", "cetabever": "cetabever",
}


def normalize_brand(raw: str | None) -> str | None:
    if not raw:
        return None
    folded = _fold(raw)
    if folded in BRAND_ALIASES:
        return BRAND_ALIASES[folded]
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return BRAND_ALIASES.get(slug, slug) or None


# --------------------------------------------------------------------------
# Kleur
# --------------------------------------------------------------------------

_RAL_RE = re.compile(r"\bral\s*[-\s]?(\d{4})\b", re.IGNORECASE)
_NCS_RE = re.compile(r"\bncs\s*[-\s]?(s?\s*\d{4}\s*-?\s*[a-z0-9]+)\b", re.IGNORECASE)

_MIX_WORDS = ("mengkleur", "mengbaar", "op kleur", "kleur naar keuze", "alle kleuren",
              "mix", "kleurcode", "gemengd")


def parse_color(text: str) -> tuple[str | None, str | None]:
    """(genormaliseerde kleur, kleursysteem)."""
    t = text or ""
    m = _RAL_RE.search(t)
    if m:
        return f"ral-{m.group(1)}", "RAL"
    m = _NCS_RE.search(t)
    if m:
        return "ncs-" + re.sub(r"\s+", "", m.group(1).lower()), "NCS"
    low = _fold(t)
    for w in _MIX_WORDS:
        if w in low:
            return "mengkleur", "mengkleur"
    for w in ("wit", "white", "gebroken wit", "zuiver wit", "ral9010", "transparant", "blank", "kleurloos"):
        if re.search(rf"\b{re.escape(w)}\b", low):
            return re.sub(r"[^a-z0-9]+", "-", w), "standaard"
    return None, None


# --------------------------------------------------------------------------
# Varianttermen die twee anders identieke producten uit elkaar houden
# --------------------------------------------------------------------------

# Staat zo'n woord bij de één wél en bij de ander niet, dan zijn het andere
# producten -- ook al klopt merk, inhoud en de rest van de naam. Gevonden in
# de praktijk: "Voorstrijk Sneldrogend" (transparant) werd gekoppeld aan
# "Voorstrijk Sneldrogend Dekkend" op bijna het dubbele van de prijs.
# Als stam genoteerd, zodat "rolbaar" en "rolbare" allebei worden herkend.
VARIANT_MARKERS = (
    "dekkend", "transparant", "poeder", "pasta", "rolba", "spuitba",
    "navulling", "testpot", "kleurstaal",
)


def variant_markers(text: str) -> set[str]:
    low = f" {_fold(text)} "
    return {m for m in VARIANT_MARKERS if f" {m}" in low or f"-{m}" in low}


# --------------------------------------------------------------------------
# Productlijn: naam minus merk, inhoud, kleur en ruis
# --------------------------------------------------------------------------

_NOISE = (
    "kopen", "bestellen", "online", "goedkoop", "aanbieding", "actie", "nu", "voordelig",
    "verfplaza", "verf-plaza", "verfwinkel", "verfwebwinkel", "decoprof", "verfzaak",
    "onlineverf", "gratis", "verzending", "per stuk", "stuk", "nl", "www",
)


def product_line(name: str, brand: str | None = None) -> str:
    """Kernnaam van het product, zonder merk/inhoud/kleur/marketing."""
    t = _fold(name)
    if brand:
        b = _fold(brand)
        t = t.replace(b, " ")
        t = t.replace(b.replace("-", " "), " ")
    t = _VOLUME_RE.sub(" ", t)
    t = _RAL_RE.sub(" ", t)
    t = _NCS_RE.sub(" ", t)
    for w in _NOISE:
        t = re.sub(rf"\b{re.escape(w)}\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    tokens = [w for w in t.split() if len(w) > 1 or w.isdigit()]
    return " ".join(tokens).strip()


def line_tokens(line: str) -> set[str]:
    return {w for w in line.split() if w not in {"verf", "de", "en", "van", "voor", "met"}}


# --------------------------------------------------------------------------
# EAN
# --------------------------------------------------------------------------

def clean_ean(raw) -> str | None:
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) in (8, 12, 13, 14) and not set(digits) == {"0"}:
        return digits.zfill(13) if len(digits) in (12, 13) else digits
    return None


# --------------------------------------------------------------------------

def _fold(s: str) -> str:
    """lowercase, accentloos, entiteitvrij, enkele spaties."""
    s = html.unescape(s or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " en ")
    return re.sub(r"\s+", " ", s).strip()


fold = _fold
