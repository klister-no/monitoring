#!/usr/bin/env python3
"""
Packaging Regulation Monitor v2.1
==================================
Daglig scanning av emballasjeregulering med Claude AI-analyse.
- Forbedret datodeteksjon
- Ukentlig executive summary
- Feedback/læringssystem
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import os
import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, quote_plus

# ─── Konfigurasjon ───────────────────────────────────────────────────────────

SOURCES = {
    "EUR-Lex": {
        "type": "EU/Regulering",
        "access": "åpen",
        "description": "EUs offisielle lovdatabase – alle dokumenter fritt tilgjengelig",
        "url": "https://eur-lex.europa.eu",
    },
    "EU Environment": {
        "type": "EU/Regulering",
        "access": "åpen",
        "description": "EU-kommisjonens miljøavdeling – fritt tilgjengelig",
        "url": "https://environment.ec.europa.eu",
    },
    "FreshPlaza": {
        "type": "Fagmedia",
        "access": "delvis åpen",
        "description": "Fagmedie for frukt og grønt – noen artikler krever registrering",
        "url": "https://www.freshplaza.com",
    },
    "Packaging Europe": {
        "type": "Fagmedia",
        "access": "delvis lukket",
        "description": "Europeisk emballasjefagblad – mye innhold bak betalingsmur",
        "url": "https://packagingeurope.com",
    },
    "Packaging World": {
        "type": "Fagmedia",
        "access": "delvis åpen",
        "description": "Globalt emballasjemagasin – de fleste artikler er åpne",
        "url": "https://www.packworld.com",
    },
    "Regjeringen.no": {
        "type": "Lovdata/Norge",
        "access": "åpen",
        "description": "Norske høringer, forskrifter og politiske dokumenter – fritt tilgjengelig",
        "url": "https://www.regjeringen.no",
    },
    "Miljødirektoratet": {
        "type": "Lovdata/Norge",
        "access": "åpen",
        "description": "Norsk miljømyndighet – all informasjon fritt tilgjengelig",
        "url": "https://www.miljodirektoratet.no",
    },
    "EUROPEN": {
        "type": "Bransjeorganisasjon",
        "access": "delvis åpen",
        "description": "European Organisation for Packaging – pressemeldinger åpne, rapporter for medlemmer",
        "url": "https://europen-packaging.eu",
    },
    "CEFLEX": {
        "type": "Bransjeorganisasjon",
        "access": "åpen",
        "description": "Konsortium for fleksibel emballasje og sirkulærøkonomi",
        "url": "https://ceflex.eu",
    },
    "LinkedIn (via Google)": {
        "type": "Sosialt/Fagnettverk",
        "access": "delvis åpen",
        "description": "Offentlige LinkedIn-innlegg og artikler funnet via Google-indeksering",
        "url": "https://www.linkedin.com",
    },
}

KEYWORDS_PRIMARY = [
    "PPWR", "packaging waste", "emballasje", "SUP directive",
    "single-use plastic", "engangsplast", "packaging regulation",
    "emballasjeforordning", "packaging and packaging waste",
]

KEYWORDS_MATERIAL = [
    "fiber packaging", "plastic packaging", "paper packaging",
    "cardboard packaging", "corrugated", "bølgepapp",
    "fiberemballasje", "plastemballasje", "bioplastic",
    "recyclable packaging", "compostable packaging",
    "recycled content", "resirkulert innhold",
]

KEYWORDS_SECTOR = [
    "fresh produce", "fruit vegetable packaging", "frukt grønt",
    "FMCG packaging", "food packaging", "berry packaging",
    "flower packaging", "blomsteremballasje", "beverage packaging",
    "drikkeemballasje", "juice packaging",
    "produce packaging", "fresh cut", "MAP packaging",
]

ALL_KEYWORDS = KEYWORDS_PRIMARY + KEYWORDS_MATERIAL + KEYWORDS_SECTOR

PRODUCT_CATEGORIES = {
    "Frukt og grønt": [
        "fruit", "vegetable", "produce", "berry", "berries", "salad",
        "fresh cut", "frukt", "grønt", "grønnsak", "bær", "salat",
        "tomato", "tomat", "avocado", "apple", "eple", "grape", "druer",
        "mushroom", "sopp", "herbs", "urter", "MAP", "modified atmosphere",
    ],
    "Drikke/juice": [
        "beverage", "juice", "drink", "bottle", "drikke", "flaske",
        "smoothie", "water", "vann", "liquid", "carton", "kartong",
        "PET bottle", "can", "boks",
    ],
    "Blomster": [
        "flower", "floral", "blomst", "bouquet", "bukett", "plant",
        "plante", "garden", "hage", "pot", "potte", "sleeve",
    ],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,no;q=0.8",
}

REQUEST_TIMEOUT = 15


# ─── Dataklasser ─────────────────────────────────────────────────────────────

@dataclass
class Article:
    title: str
    url: str
    source: str
    source_type: str
    source_access: str
    date: str = ""
    summary: str = ""
    matched_keywords: list = field(default_factory=list)
    relevance_categories: list = field(default_factory=list)
    relevance_score: int = 0
    article_accessible: bool = True
    paywall_detected: bool = False
    impact_assessment: str = ""
    ai_summary: str = ""
    ai_impact: str = ""
    content_snippet: str = ""


# ─── Hjelpefunksjoner ────────────────────────────────────────────────────────

def safe_request(url, timeout=REQUEST_TIMEOUT):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ {url}: {e}")
        return None


def extract_text(soup):
    if soup is None:
        return ""
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def match_keywords(text):
    text_lower = text.lower()
    return [kw for kw in ALL_KEYWORDS if kw.lower() in text_lower]


def assess_relevance(text, title):
    combined = (title + " " + text).lower()
    categories = []
    score = 0
    primary_hits = sum(1 for kw in KEYWORDS_PRIMARY if kw.lower() in combined)
    score += primary_hits * 20
    material_hits = sum(1 for kw in KEYWORDS_MATERIAL if kw.lower() in combined)
    score += material_hits * 10
    for cat, terms in PRODUCT_CATEGORIES.items():
        cat_hits = sum(1 for t in terms if t.lower() in combined)
        if cat_hits > 0:
            categories.append(cat)
            score += cat_hits * 15
    return min(score, 100), categories


def generate_impact(title, text, categories):
    combined = (title + " " + text).lower()
    impacts = []
    checks = [
        (["ban", "forbud", "prohibit", "restrict", "phase out"], "Mulige forbud/restriksjoner på nåværende emballasjeløsninger"),
        (["recycled content", "resirkulert", "mandatory", "obligatorisk"], "Krav til resirkulert innhold"),
        (["reuse", "gjenbruk", "refill", "return"], "Gjenbrukskrav – påvirker logistikk og design"),
        (["label", "merking", "marking", "sorting"], "Nye merkekrav"),
        (["epr", "producer responsibility", "produsentansvar"], "Utvidet produsentansvar – kostnadsøkning"),
        (["compost", "biodegradab", "bionedbrytbar"], "Endrede krav til komposterbar emballasje"),
        (["ppwr", "packaging and packaging waste"], "PPWR – direkte innvirkning på all EU/EØS-emballasje"),
        (["sup", "single-use", "engangs"], "SUP-direktivet – påvirker engangsemballasje"),
    ]
    for words, impact in checks:
        if any(w in combined for w in words):
            impacts.append(impact)
    cat_str = ", ".join(categories) if categories else "generelt emballasje"
    if not impacts:
        return f"Generell relevans for {cat_str}."
    return f"Relevant for {cat_str}: " + ". ".join(impacts[:3]) + "."


def deduplicate(articles):
    seen = set()
    unique = []
    for a in articles:
        if a.url not in seen:
            seen.add(a.url)
            unique.append(a)
    return unique


# ─── FORBEDRET DATODETEKSJON ────────────────────────────────────────────────

def extract_date_from_page(soup, resp_text):
    """Søker etter publiseringsdato via flere metoder."""

    # Metode 1: <time> tag med datetime-attributt
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        d = time_tag["datetime"][:10]
        if re.match(r"\d{4}-\d{2}-\d{2}", d):
            return d

    # Metode 2: <time> tag med tekstinnhold
    time_tag = soup.find("time")
    if time_tag:
        d = parse_date_text(time_tag.get_text(strip=True))
        if d:
            return d

    # Metode 3: Meta-tags (Open Graph, Dublin Core, schema.org)
    meta_names = [
        "article:published_time", "og:article:published_time",
        "datePublished", "date", "publish_date", "pubdate",
        "DC.date.issued", "DC.date", "sailthru.date",
        "article.published", "publication_date",
    ]
    for name in meta_names:
        tag = soup.find("meta", attrs={"property": name}) or \
              soup.find("meta", attrs={"name": name}) or \
              soup.find("meta", attrs={"itemprop": name})
        if tag and tag.get("content"):
            d = tag["content"][:10]
            if re.match(r"\d{4}-\d{2}-\d{2}", d):
                return d

    # Metode 4: JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string)
            if isinstance(ld, list):
                ld = ld[0]
            for key in ["datePublished", "dateCreated", "dateModified"]:
                if key in ld:
                    d = str(ld[key])[:10]
                    if re.match(r"\d{4}-\d{2}-\d{2}", d):
                        return d
        except (json.JSONDecodeError, TypeError, IndexError):
            pass

    # Metode 5: Dato-mønster i URL
    url_match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", resp_text[:500])
    if url_match:
        return f"{url_match.group(1)}-{url_match.group(2)}-{url_match.group(3)}"
    url_match = re.search(r"/(\d{4})-(\d{2})-(\d{2})/", resp_text[:500])
    if url_match:
        return f"{url_match.group(1)}-{url_match.group(2)}-{url_match.group(3)}"

    # Metode 6: Vanlige dato-elementer i HTML
    date_selectors = [
        ".date", ".post-date", ".article-date", ".published",
        ".entry-date", ".pub-date", ".timestamp", ".byline time",
        "[class*='date']", "[class*='Date']", "[class*='time']",
    ]
    for sel in date_selectors:
        el = soup.select_one(sel)
        if el:
            d = parse_date_text(el.get_text(strip=True))
            if d:
                return d

    return ""


def parse_date_text(text):
    """Forsøker å parse en datotekst til YYYY-MM-DD format."""
    if not text or len(text) > 80:
        return None

    text = text.strip()

    # ISO-format allerede
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)

    # Vanlige datoformater
    formats = [
        "%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y",
        "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
        "%d %B, %Y", "%d. %B %Y",
    ]

    # Norske måneder
    no_months = {
        "januar": "January", "februar": "February", "mars": "March",
        "april": "April", "mai": "May", "juni": "June",
        "juli": "July", "august": "August", "september": "September",
        "oktober": "October", "november": "November", "desember": "December",
    }
    text_en = text
    for no, en in no_months.items():
        text_en = text_en.replace(no, en).replace(no.capitalize(), en)

    for fmt in formats:
        try:
            dt = datetime.strptime(text_en, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def format_date_display(date_str):
    """Formaterer dato til lesbart norsk format med alder."""
    if not date_str:
        return '<span class="date date-unknown">📅 Dato ukjent</span>'
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        days_ago = (datetime.now() - dt).days
        if days_ago == 0:
            age = "i dag"
        elif days_ago == 1:
            age = "i går"
        elif days_ago < 7:
            age = f"{days_ago} dager siden"
        elif days_ago < 30:
            weeks = days_ago // 7
            age = f"{weeks} uke{'r' if weeks > 1 else ''} siden"
        elif days_ago < 365:
            months = days_ago // 30
            age = f"{months} mnd siden"
        else:
            years = days_ago // 365
            age = f"{years} år siden"

        formatted = dt.strftime("%d.%m.%Y")
        freshness = "fresh" if days_ago <= 7 else "recent" if days_ago <= 30 else "older"
        return f'<span class="date date-{freshness}">📅 {formatted} ({age})</span>'
    except ValueError:
        return f'<span class="date">📅 {date_str}</span>'


# ─── FEEDBACK/LÆRINGSSYSTEM ─────────────────────────────────────────────────

FEEDBACK_FILE = "feedback.json"

def load_feedback(output_dir):
    """Laster inn feedback fra tidligere kjøringer."""
    path = os.path.join(output_dir, FEEDBACK_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "instructions": [],
        "positive_examples": [],
        "negative_examples": [],
        "keyword_adjustments": [],
        "created": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
    }


def save_feedback(feedback, output_dir):
    """Lagrer feedback til fil."""
    feedback["last_updated"] = datetime.now().isoformat()
    path = os.path.join(output_dir, FEEDBACK_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(feedback, f, ensure_ascii=False, indent=2)


def build_feedback_context(feedback):
    """Bygger kontekst-tekst fra feedback for Claude-prompts."""
    if not feedback.get("instructions") and not feedback.get("positive_examples") and not feedback.get("negative_examples"):
        return ""

    ctx = "\n\n--- LÆRT KONTEKST FRA TIDLIGERE FEEDBACK ---\n"

    if feedback.get("instructions"):
        ctx += "\nBrukerspesifikke instruksjoner:\n"
        for inst in feedback["instructions"][-10:]:
            ctx += f"- {inst}\n"

    if feedback.get("positive_examples"):
        ctx += "\nEksempler på artikler brukeren fant SVÆRT RELEVANTE:\n"
        for ex in feedback["positive_examples"][-5:]:
            ctx += f"- \"{ex.get('title', '')}\" – grunn: {ex.get('reason', 'ikke oppgitt')}\n"

    if feedback.get("negative_examples"):
        ctx += "\nEksempler på artikler brukeren fant IRRELEVANTE:\n"
        for ex in feedback["negative_examples"][-5:]:
            ctx += f"- \"{ex.get('title', '')}\" – grunn: {ex.get('reason', 'ikke oppgitt')}\n"

    if feedback.get("keyword_adjustments"):
        ctx += "\nJusterte nøkkelord/prioriteringer:\n"
        for adj in feedback["keyword_adjustments"][-5:]:
            ctx += f"- {adj}\n"

    ctx += "--- SLUTT LÆRT KONTEKST ---\n"
    return ctx


# ─── HISTORIKK FOR UKENTLIG SAMMENDRAG ──────────────────────────────────────

HISTORY_FILE = "history.json"

def load_history(output_dir):
    """Laster inn artikkelog fra tidligere kjøringer."""
    path = os.path.join(output_dir, HISTORY_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"runs": []}


def save_history(history, output_dir):
    """Lagrer historikk. Beholder kun siste 30 dager."""
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    history["runs"] = [r for r in history["runs"] if r.get("date", "") >= cutoff]
    path = os.path.join(output_dir, HISTORY_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_to_history(history, articles):
    """Legger til dagens kjøring i historikken."""
    today = datetime.now().strftime("%Y-%m-%d")
    run = {
        "date": today,
        "count": len(articles),
        "articles": [{
            "title": a.title, "url": a.url, "source": a.source,
            "score": a.relevance_score, "categories": a.relevance_categories,
            "date": a.date, "accessible": a.article_accessible,
            "ai_summary": a.ai_summary[:200] if a.ai_summary else "",
            "ai_impact": a.ai_impact[:200] if a.ai_impact else "",
        } for a in sorted(articles, key=lambda x: x.relevance_score, reverse=True)[:20]],
    }
    history["runs"].append(run)


def get_week_articles(history):
    """Henter alle artikler fra siste 7 dager."""
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_articles = []
    seen_urls = set()
    for run in history.get("runs", []):
        if run.get("date", "") >= week_ago:
            for art in run.get("articles", []):
                if art["url"] not in seen_urls:
                    seen_urls.add(art["url"])
                    week_articles.append(art)
    return week_articles


# ─── Kildescannere ───────────────────────────────────────────────────────────

def make_article(title, href, source_name, **kwargs):
    src = SOURCES.get(source_name, {})
    kw = match_keywords(title + " " + kwargs.get("extra_text", ""))
    if not kw and not kwargs.get("force", False):
        return None
    text = kwargs.get("extra_text", title)
    score, cats = assess_relevance(text, title)
    score = min(score + kwargs.get("score_boost", 0), 100)
    for c in kwargs.get("extra_cats", []):
        if c not in cats:
            cats.append(c)
    return Article(
        title=title[:250], url=href, source=source_name,
        source_type=src.get("type", "Ukjent"),
        source_access=src.get("access", "ukjent"),
        summary=kwargs.get("summary", "")[:500],
        matched_keywords=kw if kw else kwargs.get("default_kw", ["emballasje"]),
        relevance_categories=cats, relevance_score=score,
        impact_assessment=generate_impact(title, text, cats),
    )


def scan_eurlex():
    print("\n🇪🇺 EUR-Lex...")
    articles = []
    for term in ["packaging+packaging+waste+regulation", "single+use+plastics+directive+packaging"]:
        url = f"https://eur-lex.europa.eu/search.html?scope=EURLEX&text={term}&type=quick"
        resp = safe_request(url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for r in soup.select(".SearchResult, li.result, .EurlexContent")[:10]:
            link_tag = r.find("a", href=True)
            if not link_tag:
                continue
            title = link_tag.get_text(strip=True)
            href = urljoin("https://eur-lex.europa.eu", link_tag["href"])
            text = extract_text(r)
            art = make_article(title, href, "EUR-Lex", extra_text=text, summary=text[:300])
            if art:
                articles.append(art)
        time.sleep(1)
    print(f"  ✓ {len(articles)}")
    return articles


def scan_eu_environment():
    print("\n🌍 EU Environment...")
    articles = []
    for url in [
        "https://environment.ec.europa.eu/topics/waste-and-recycling/packaging-waste_en",
        "https://environment.ec.europa.eu/topics/plastics/single-use-plastics_en",
    ]:
        resp = safe_request(url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("a", href=True):
            title = link.get_text(strip=True)
            if len(title) < 15:
                continue
            href = urljoin(url, link["href"])
            art = make_article(title, href, "EU Environment")
            if art:
                articles.append(art)
        time.sleep(1)
    return deduplicate(articles)


def scan_freshplaza():
    print("\n🍎 FreshPlaza...")
    articles = []
    for q in ["packaging", "packaging+regulation", "plastic+packaging+fruit",
              "sustainable+packaging", "packaging+waste"]:
        url = f"https://www.freshplaza.com/europe/article-search/?q={q}"
        resp = safe_request(url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            title = link.get_text(strip=True)
            if "/article/" not in href or len(title) < 20:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.freshplaza.com", href)
            art = make_article(title, href, "FreshPlaza",
                             score_boost=20, extra_cats=["Frukt og grønt"],
                             force="packaging" in title.lower(),
                             default_kw=["packaging", "fresh produce"])
            if art:
                articles.append(art)
        time.sleep(1)
    return deduplicate(articles)


def scan_packaging_europe():
    print("\n📦 Packaging Europe...")
    articles = []
    relevant = ["ppwr", "sup", "packaging", "plastic", "regulation",
                "recyclable", "reuse", "circular", "waste", "recycled"]
    for url in ["https://packagingeurope.com/news", "https://packagingeurope.com/sustainability"]:
        resp = safe_request(url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("a", href=True):
            title = link.get_text(strip=True)
            if len(title) < 20:
                continue
            href = urljoin(url, link["href"])
            force = any(w in title.lower() for w in relevant)
            art = make_article(title, href, "Packaging Europe",
                             force=force, default_kw=["packaging regulation"])
            if art:
                if "premium" in title.lower() or "member" in title.lower():
                    art.paywall_detected = True
                    art.article_accessible = False
                articles.append(art)
        time.sleep(1)
    return deduplicate(articles)


def scan_packaging_world():
    print("\n🌐 Packaging World...")
    articles = []
    resp = safe_request("https://www.packworld.com/sustainability")
    if not resp:
        return articles
    soup = BeautifulSoup(resp.text, "html.parser")
    for link in soup.find_all("a", href=True):
        title = link.get_text(strip=True)
        if len(title) < 20:
            continue
        href = urljoin("https://www.packworld.com", link["href"])
        art = make_article(title, href, "Packaging World")
        if art:
            articles.append(art)
    return deduplicate(articles)


def scan_regjeringen():
    print("\n🇳🇴 Regjeringen.no...")
    articles = []
    relevant = ["emballasje", "plast", "avfall", "sirkulær", "engangs", "gjenbruk", "resirkuler"]
    for term in ["emballasje+forordning", "engangsplast", "emballasje+avfall"]:
        url = f"https://www.regjeringen.no/no/sok/id86008/?term={term}"
        resp = safe_request(url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("a", href=True):
            title = link.get_text(strip=True)
            if len(title) < 15:
                continue
            href = urljoin("https://www.regjeringen.no", link["href"])
            force = any(w in title.lower() for w in relevant)
            art = make_article(title, href, "Regjeringen.no",
                             force=force, default_kw=["emballasje"])
            if art:
                articles.append(art)
        time.sleep(1)
    return deduplicate(articles)


def scan_miljodirektoratet():
    print("\n🌲 Miljødirektoratet...")
    articles = []
    for url in [
        "https://www.miljodirektoratet.no/ansvarsomrader/avfall/emballasje/",
        "https://www.miljodirektoratet.no/ansvarsomrader/avfall/avfallstyper/plastemballasje/",
    ]:
        resp = safe_request(url)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("a", href=True):
            title = link.get_text(strip=True)
            if len(title) < 10:
                continue
            href = urljoin("https://www.miljodirektoratet.no", link["href"])
            force = any(w in title.lower() for w in ["emballasje", "plast", "avfall"])
            art = make_article(title, href, "Miljødirektoratet",
                             force=force, default_kw=["emballasje"])
            if art:
                articles.append(art)
        time.sleep(1)
    return deduplicate(articles)


def scan_europen():
    print("\n🏭 EUROPEN...")
    articles = []
    resp = safe_request("https://europen-packaging.eu/news/")
    if not resp:
        return articles
    soup = BeautifulSoup(resp.text, "html.parser")
    for link in soup.find_all("a", href=True):
        title = link.get_text(strip=True)
        if len(title) < 15:
            continue
        href = urljoin("https://europen-packaging.eu", link["href"])
        force = any(w in title.lower() for w in ["ppwr", "packaging", "regulation", "directive"])
        art = make_article(title, href, "EUROPEN",
                         force=force, default_kw=["packaging regulation"])
        if art:
            articles.append(art)
    return deduplicate(articles)


def scan_ceflex():
    print("\n♻️ CEFLEX...")
    articles = []
    resp = safe_request("https://ceflex.eu/news/")
    if not resp:
        return articles
    soup = BeautifulSoup(resp.text, "html.parser")
    for link in soup.find_all("a", href=True):
        title = link.get_text(strip=True)
        if len(title) < 15:
            continue
        href = urljoin("https://ceflex.eu", link["href"])
        force = any(w in title.lower() for w in ["flexible", "packaging", "recycl", "design"])
        art = make_article(title, href, "CEFLEX",
                         force=force, default_kw=["recyclable packaging"])
        if art:
            articles.append(art)
    return deduplicate(articles)


def scan_linkedin_via_google():
    print("\n💼 LinkedIn (via Google)...")
    articles = []
    searches = [
        "site:linkedin.com PPWR packaging regulation",
        "site:linkedin.com packaging waste regulation EU",
        "site:linkedin.com SUP directive single use plastic packaging",
        "site:linkedin.com emballasje PPWR forordning",
        "site:linkedin.com fresh produce packaging sustainability",
        "site:linkedin.com FMCG packaging circular economy",
        "site:linkedin.com fruit vegetable packaging regulation",
        "site:linkedin.com flower packaging sustainable",
        "site:linkedin.com beverage packaging recycled content",
    ]
    for query in searches:
        encoded = quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}&num=10&tbs=qdr:m"
        resp = safe_request(url, timeout=12)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for result in soup.select("div.g, div[data-sokoban-container]"):
            link = result.find("a", href=True)
            if not link:
                continue
            href = link["href"]
            if "linkedin.com" not in href:
                continue
            if href.startswith("/url?"):
                import urllib.parse as up
                parsed = up.parse_qs(up.urlparse(href).query)
                href = parsed.get("q", [href])[0]
            if "linkedin.com" not in href:
                continue
            title_tag = result.find("h3")
            title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)
            if len(title) < 15:
                continue
            snippet_tag = result.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf]")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            combined_text = title + " " + snippet
            is_article = "/pulse/" in href
            is_post = "/posts/" in href or "/feed/" in href
            if not is_article and not is_post and "/company/" not in href:
                continue
            art = make_article(
                title, href, "LinkedIn (via Google)",
                extra_text=combined_text,
                summary=snippet[:500] if snippet else "",
                force=True, default_kw=["packaging regulation"],
            )
            if art:
                articles.append(art)
        time.sleep(2)
    articles = deduplicate(articles)
    print(f"  ✓ {len(articles)}")
    return articles


# ─── Innholdshenting med forbedret dato ──────────────────────────────────────

def fetch_article_content(article):
    resp = safe_request(article.url, timeout=10)
    if not resp:
        article.article_accessible = False
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    page_lower = resp.text.lower()

    # Detekter betalingsmur
    paywall_signs = [
        "paywall", "subscribe to read", "premium content",
        "sign in to continue", "become a member", "paid content",
        "subscribers only", "membership required", "unlock this article",
        "create a free account", "register to read",
    ]
    if any(s in page_lower for s in paywall_signs):
        article.paywall_detected = True
        article.article_accessible = False

    # Hent innhold
    content_areas = soup.select("article, .article-body, .post-content, .entry-content, main")
    text = extract_text(content_areas[0]) if content_areas else extract_text(soup.find("body"))

    if text and len(text) > 100:
        article.content_snippet = text[:2000]
        article.summary = text[:500].strip()
        kw = match_keywords(text)
        article.matched_keywords = list(set(article.matched_keywords + kw))
        score, cats = assess_relevance(text, article.title)
        article.relevance_score = max(article.relevance_score, score)
        article.relevance_categories = list(set(article.relevance_categories + cats))
        article.impact_assessment = generate_impact(article.title, text, article.relevance_categories)
    elif len(text) < 100:
        article.article_accessible = False

    # FORBEDRET datodeteksjon
    if not article.date:
        article.date = extract_date_from_page(soup, article.url)


# ─── Claude AI-analyse med feedback-kontekst ────────────────────────────────

def analyze_with_claude(articles, feedback_context=""):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ⚠ ANTHROPIC_API_KEY ikke satt – hopper over AI-analyse")
        return

    analyzable = [a for a in articles if a.article_accessible and a.content_snippet and a.relevance_score >= 30]
    analyzable.sort(key=lambda a: a.relevance_score, reverse=True)
    analyzable = analyzable[:15]

    if not analyzable:
        print("  ⚠ Ingen artikler med tilgjengelig innhold å analysere")
        return

    print(f"\n🤖 Claude AI-analyse av {len(analyzable)} artikler...")

    articles_text = ""
    for i, art in enumerate(analyzable):
        articles_text += f"""
--- ARTIKKEL {i+1} ---
Kilde: {art.source} ({art.source_type})
Tittel: {art.title}
Dato: {art.date or 'Ukjent'}
Innhold: {art.content_snippet[:800]}
Kategorier: {', '.join(art.relevance_categories) if art.relevance_categories else 'Ikke kategorisert'}
---
"""

    prompt = f"""Du er en ekspert på emballasjeregulering i EU/EØS med spesialkompetanse på PPWR (Packaging and Packaging Waste Regulation), SUP-direktivet, og emballasje for FMCG-markedet.
{feedback_context}
Analyser følgende {len(analyzable)} artikler og gi for HVER artikkel:

1. **Sammendrag** (2-3 setninger på norsk): Hva handler artikkelen om?
2. **Innvirkning** (2-3 setninger på norsk): Hvordan kan dette påvirke en bedrift som produserer emballasje for:
   - Frukt og grønnsaker (skåler, flow-wrap, clamshells, MAP-pakninger)
   - Drikke og juice (flasker, kartonger)
   - Blomster (sleeves, innpakking, potter)

Svar BARE med JSON i dette formatet, ingen annen tekst:
[
  {{
    "article_index": 1,
    "summary": "Norsk sammendrag her...",
    "impact": "Norsk innvirkningsvurdering her..."
  }}
]

{articles_text}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        analyses = json.loads(text)
        for analysis in analyses:
            idx = analysis.get("article_index", 0) - 1
            if 0 <= idx < len(analyzable):
                analyzable[idx].ai_summary = analysis.get("summary", "")
                analyzable[idx].ai_impact = analysis.get("impact", "")
        print(f"  ✓ AI-analyse fullført for {len(analyses)} artikler")
    except Exception as e:
        print(f"  ⚠ Claude API-feil: {e}")


def generate_daily_summary(articles, feedback_context=""):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    top = sorted(articles, key=lambda a: a.relevance_score, reverse=True)[:10]
    if not top:
        return None

    articles_brief = "\n".join(
        f"- [{a.source}] {a.title} (score: {a.relevance_score}, "
        f"kategorier: {', '.join(a.relevance_categories)}, "
        f"dato: {a.date or 'ukjent'}, "
        f"{'åpen' if a.article_accessible else 'lukket'})"
        for a in top
    )

    prompt = f"""Du er en rådgiver for en emballasjebedrift som leverer til frukt/grønt, drikke og blomstermarkedet i Norden.
{feedback_context}
Basert på dagens scan av emballasjekilder, skriv et kort daglig sammendrag på norsk (5-8 setninger) som:
1. Oppsummerer de viktigste funnene
2. Fremhever hva som krever umiddelbar oppmerksomhet
3. Gir en anbefaling om hva bedriften bør følge opp

Her er dagens topp-artikler:
{articles_brief}

Skriv sammendraget direkte, ingen JSON, bare ren tekst."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]
        return text.strip()
    except Exception as e:
        print(f"  ⚠ Daglig sammendrag feilet: {e}")
        return None


# ─── UKENTLIG EXECUTIVE SUMMARY ─────────────────────────────────────────────

def generate_weekly_summary(history, feedback_context=""):
    """Genererer ukentlig executive summary hver mandag."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    # Sjekk om det er mandag
    if datetime.now().weekday() != 0:
        return None

    week_articles = get_week_articles(history)
    if not week_articles:
        return None

    print(f"\n📋 Genererer ukentlig executive summary ({len(week_articles)} artikler)...")

    articles_brief = "\n".join(
        f"- [{a.get('source', '?')}] {a.get('title', '?')} "
        f"(score: {a.get('score', 0)}, kategorier: {', '.join(a.get('categories', []))}, "
        f"dato: {a.get('date', 'ukjent')})"
        f"{' – AI: ' + a.get('ai_summary', '')[:100] if a.get('ai_summary') else ''}"
        for a in sorted(week_articles, key=lambda x: x.get("score", 0), reverse=True)[:20]
    )

    prompt = f"""Du er en senior rådgiver for en nordisk emballasjebedrift som leverer emballasjeløsninger til:
- Frukt og grønnsaker (skåler, flow-wrap, clamshells, MAP-pakninger, bæremballasje)
- Drikke og juice (PET-flasker, kartonger, bokser)
- Blomster (sleeves, innpakningsfilm, potter)
{feedback_context}
Skriv en UKENTLIG EXECUTIVE SUMMARY på norsk (10-15 setninger) basert på denne ukens funn. Strukturer det slik:

**SITUASJONSBILDE**: Hva er hovedtrendene denne uken? (2-3 setninger)

**FRUKT & GRØNT**: Spesifikke implikasjoner for frukt- og grøntemballasje (2-3 setninger)

**DRIKKE**: Spesifikke implikasjoner for drikkeemballasje (2-3 setninger)

**BLOMSTER**: Spesifikke implikasjoner for blomsteremballasje (1-2 setninger)

**ANBEFALT HANDLING**: Hva bør bedriften gjøre denne uken? (2-3 setninger)

Her er denne ukens artikler:
{articles_brief}

Skriv direkte, ingen JSON. Bruk overskriftene over."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]
        print("  ✓ Ukentlig summary generert")
        return text.strip()
    except Exception as e:
        print(f"  ⚠ Ukentlig summary feilet: {e}")
        return None


# ─── HTML-rapport ────────────────────────────────────────────────────────────

def generate_html_report(articles, daily_summary, weekly_summary, output_path):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    articles.sort(key=lambda a: a.relevance_score, reverse=True)

    total = len(articles)
    accessible = len([a for a in articles if a.article_accessible])
    paywalled = len([a for a in articles if a.paywall_detected])
    with_date = len([a for a in articles if a.date])
    by_type = {}
    for a in articles:
        by_type[a.source_type] = by_type.get(a.source_type, 0) + 1

    high = [a for a in articles if a.relevance_score >= 60]
    medium = [a for a in articles if 30 <= a.relevance_score < 60]
    low = [a for a in articles if a.relevance_score < 30]

    source_rows = ""
    for name, info in SOURCES.items():
        count = len([a for a in articles if a.source == name])
        source_rows += f"""<tr>
<td><strong>{name}</strong></td>
<td>{info["type"]}</td>
<td><span class="access-badge {info["access"].replace(" ", "-")}">{info["access"]}</span></td>
<td>{info["description"]}</td>
<td class="count">{count}</td></tr>"""

    # Weekly summary section
    weekly_section = ""
    if weekly_summary:
        formatted = weekly_summary.replace("**SITUASJONSBILDE**", '<h3 class="ws-h">📊 Situasjonsbilde</h3>')
        formatted = formatted.replace("**FRUKT & GRØNT**", '<h3 class="ws-h">🥬 Frukt & Grønt</h3>')
        formatted = formatted.replace("**DRIKKE**", '<h3 class="ws-h">🥤 Drikke</h3>')
        formatted = formatted.replace("**BLOMSTER**", '<h3 class="ws-h">💐 Blomster</h3>')
        formatted = formatted.replace("**ANBEFALT HANDLING**", '<h3 class="ws-h">⚡ Anbefalt handling</h3>')
        formatted = formatted.replace("\n", "<br>")
        weekly_section = f"""
<section class="weekly-summary">
<h2>📋 Ukentlig Executive Summary</h2>
<div class="weekly-box">{formatted}</div>
</section>"""

    daily_section = ""
    if daily_summary:
        daily_section = f"""
<section class="daily-summary">
<h2>🤖 AI Daglig Sammendrag</h2>
<div class="summary-box">{daily_summary}</div>
</section>"""

    # Feedback section
    feedback_section = """
<section class="feedback-section">
<h2>🎓 Gi feedback – gjør monitoren smartere</h2>
<p class="feedback-info">Rediger filen <code>feedback.json</code> i repoet for å gjøre AI-analysen bedre over tid:</p>
<div class="feedback-examples">
<div class="fb-card">
<strong>Legg til instruksjoner:</strong>
<code>"instructions": ["Vi bruker hovedsakelig PET og rPET for bærskåler", "Norske regler er viktigere enn tyske"]</code>
</div>
<div class="fb-card">
<strong>Marker gode artikler:</strong>
<code>"positive_examples": [{"title": "PPWR reuse targets...", "reason": "Direkte relevant for våre bærskåler"}]</code>
</div>
<div class="fb-card">
<strong>Marker irrelevante artikler:</strong>
<code>"negative_examples": [{"title": "Cosmetics packaging...", "reason": "Vi jobber ikke med kosmetikk"}]</code>
</div>
</div>
</section>"""

    def access_badge(art):
        if art.paywall_detected:
            return '<span class="access-badge lukket">🔒 Betalingsmur</span>'
        elif not art.article_accessible:
            return '<span class="access-badge lukket">🚫 Utilgjengelig</span>'
        else:
            badge_class = art.source_access.replace(" ", "-")
            return f'<span class="access-badge {badge_class}">{"🔓 " if "åpen" in art.source_access else "🔒 "}{art.source_access}</span>'

    def card(art):
        cats = "".join(f'<span class="cat-tag">{c}</span>' for c in art.relevance_categories)
        kws = "".join(f'<span class="kw-tag">{k}</span>' for k in art.matched_keywords[:5])
        sc = "#22763d" if art.relevance_score >= 60 else "#c78c1c" if art.relevance_score >= 30 else "#999"
        date_html = format_date_display(art.date)

        summary_html = ""
        if art.ai_summary:
            summary_html = f'<div class="ai-block"><span class="ai-label">🤖 AI-sammendrag</span><p>{art.ai_summary}</p></div>'
        elif art.summary:
            summary_html = f'<p class="summary">{art.summary[:300]}...</p>'

        impact_html = ""
        if art.ai_impact:
            impact_html = f'<div class="ai-block impact"><span class="ai-label">💡 AI-vurdering</span><p>{art.ai_impact}</p></div>'
        elif art.impact_assessment:
            impact_html = f'<div class="impact-basic"><strong>💡</strong> {art.impact_assessment}</div>'

        return f"""<div class="card">
<div class="card-top">
<div class="score" style="background:{sc}">{art.relevance_score}</div>
<div class="meta">
<span class="src-badge {art.source_type.lower().replace('/', '-')}">{art.source}</span>
{access_badge(art)} {date_html}
</div></div>
<h3><a href="{art.url}" target="_blank" rel="noopener">{art.title}</a></h3>
{summary_html}{impact_html}
<div class="tags">{cats}{kws}</div></div>"""

    def section(title, icon, arts, desc=""):
        if not arts:
            return f'<section class="sec"><h2>{icon} {title} <span class="cnt">(0)</span></h2><p class="empty">Ingen artikler i denne kategorien.</p></section>'
        return f'<section class="sec"><h2>{icon} {title} <span class="cnt">({len(arts)})</span></h2>{f"<p class=desc>{desc}</p>" if desc else ""}{"".join(card(a) for a in arts)}</section>'

    html = f"""<!DOCTYPE html>
<html lang="no">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📦 Emballasjeregulering Monitor – {now}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Playfair+Display:wght@700&display=swap');
:root{{--bg:#f4f1eb;--card:#fff;--text:#1a1a2e;--muted:#6c757d;--green:#22763d;--green-lt:#d8f3dc;--border:#dee2e6;--ai-bg:#eef2ff;--ai-border:#818cf8}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.65}}
.wrap{{max-width:1100px;margin:0 auto;padding:1.5rem}}
header{{background:linear-gradient(135deg,#0a1628 0%,#1a2742 40%,#2d4a3e 100%);color:#fff;padding:3rem 2rem}}
header h1{{font-family:'Playfair Display',serif;font-size:2.4rem;margin-bottom:.3rem}}
header .sub{{opacity:.75;font-size:1rem;margin-bottom:.3rem}}
header .ts{{opacity:.45;font-size:.85rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.8rem;margin:1.5rem 0;padding:1.25rem;background:var(--card);border-radius:14px;box-shadow:0 2px 12px rgba(0,0,0,.05)}}
.stat{{text-align:center;padding:.4rem}}
.stat .n{{font-size:1.8rem;font-weight:700;color:var(--green)}}
.stat .l{{font-size:.78rem;color:var(--muted);margin-top:.1rem}}
.sources-section,.weekly-summary,.daily-summary,.feedback-section{{margin:2rem 0}}
.sources-section h2,.weekly-summary h2,.daily-summary h2,.feedback-section h2,.sec h2{{font-family:'Playfair Display',serif;font-size:1.4rem;margin-bottom:1rem;padding-bottom:.5rem;border-bottom:2px solid var(--green)}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.04)}}
th{{background:#1a2742;color:#fff;padding:.7rem 1rem;text-align:left;font-size:.85rem}}
td{{padding:.6rem 1rem;border-bottom:1px solid var(--border);font-size:.88rem}}
td.count{{text-align:center;font-weight:700;color:var(--green)}}
tr:hover{{background:#f8f9fa}}
.access-badge{{display:inline-block;padding:2px 9px;border-radius:20px;font-size:.72rem;font-weight:600}}
.access-badge.åpen{{background:#d4edda;color:#155724}}
.access-badge.delvis-åpen{{background:#fff3cd;color:#856404}}
.access-badge.delvis-lukket{{background:#fde2d8;color:#a84200}}
.access-badge.lukket{{background:#f8d7da;color:#721c24}}
.weekly-summary{{padding:0}}
.weekly-box{{background:linear-gradient(135deg,#f0fdf4,#ecfdf5);border-left:4px solid var(--green);padding:1.5rem;border-radius:8px;font-size:.95rem;line-height:1.7}}
.ws-h{{color:var(--green);font-size:1rem;margin:1rem 0 .3rem;font-family:'DM Sans',sans-serif}}
.ws-h:first-child{{margin-top:0}}
.daily-summary .summary-box{{background:linear-gradient(135deg,#eef2ff,#f0ebff);border-left:4px solid var(--ai-border);padding:1.25rem;border-radius:8px;font-size:.95rem;line-height:1.7}}
.feedback-section .feedback-info{{color:var(--muted);margin-bottom:1rem}}
.feedback-examples{{display:grid;gap:.8rem}}
.fb-card{{background:var(--card);padding:1rem;border-radius:8px;border:1px solid var(--border)}}
.fb-card strong{{display:block;margin-bottom:.3rem;font-size:.9rem}}
.fb-card code{{display:block;background:#f8f8f8;padding:.5rem;border-radius:4px;font-size:.78rem;overflow-x:auto;white-space:pre-wrap}}
.date{{font-size:.78rem;color:var(--muted)}}
.date-fresh{{color:var(--green);font-weight:500}}
.date-recent{{color:#856404}}
.date-older{{color:var(--muted)}}
.date-unknown{{color:#ccc;font-style:italic}}
.cnt{{font-weight:400;color:var(--muted);font-size:.95rem}}
.desc,.empty{{color:var(--muted);margin-bottom:1rem;font-size:.92rem}}
.card{{background:var(--card);border-radius:10px;padding:1.25rem 1.5rem;margin-bottom:.85rem;box-shadow:0 1px 4px rgba(0,0,0,.04);border-left:4px solid var(--border);transition:transform .15s}}
.card:hover{{transform:translateX(3px)}}
.card-top{{display:flex;align-items:center;gap:.6rem;margin-bottom:.6rem;flex-wrap:wrap}}
.score{{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:.82rem;flex-shrink:0}}
.meta{{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap}}
.src-badge{{padding:2px 9px;border-radius:20px;font-size:.72rem;font-weight:600;color:#fff}}
.src-badge.eu-regulering{{background:#003399}}
.src-badge.fagmedia{{background:#d35400}}
.src-badge.lovdata-norge{{background:#6c3483}}
.src-badge.bransjeorganisasjon{{background:#2c3e50}}
.src-badge.sosialt-fagnettverk{{background:#0077b5}}
h3{{font-size:1.05rem;margin-bottom:.4rem}}
h3 a{{color:var(--text);text-decoration:none}}
h3 a:hover{{color:var(--green);text-decoration:underline}}
.summary{{color:var(--muted);font-size:.88rem;margin-bottom:.6rem}}
.ai-block{{background:var(--ai-bg);border-left:3px solid var(--ai-border);border-radius:6px;padding:.7rem 1rem;margin-bottom:.6rem;font-size:.88rem}}
.ai-block.impact{{background:#fef9e7;border-left-color:#f1c40f}}
.ai-label{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--ai-border);display:block;margin-bottom:.25rem}}
.ai-block.impact .ai-label{{color:#b7950b}}
.ai-block p{{margin:0;line-height:1.5}}
.impact-basic{{background:#fef9e7;border-left:3px solid #f1c40f;border-radius:6px;padding:.6rem .9rem;font-size:.86rem;margin-bottom:.6rem}}
.tags{{display:flex;gap:.35rem;flex-wrap:wrap}}
.cat-tag{{background:var(--green-lt);color:var(--green);padding:2px 7px;border-radius:4px;font-size:.72rem;font-weight:500}}
.kw-tag{{background:#eef;color:#555;padding:2px 7px;border-radius:4px;font-size:.7rem}}
footer{{text-align:center;padding:2rem;color:var(--muted);font-size:.82rem}}
footer a{{color:var(--green)}}
@media(max-width:768px){{.wrap{{padding:1rem}}header{{padding:2rem 1rem}}header h1{{font-size:1.6rem}}.stats{{grid-template-columns:repeat(3,1fr)}}table{{font-size:.8rem}}th,td{{padding:.4rem .5rem}}}}
</style>
</head>
<body>
<header><div class="wrap">
<h1>📦 Emballasjeregulering Monitor</h1>
<p class="sub">PPWR · SUP-direktivet · Emballasjelovgivning · Frukt & Grønt · Drikke · Blomster</p>
<p class="ts">Sist skannet: {now} · Neste: i morgen kl 06:00</p>
</div></header>
<div class="wrap">
<div class="stats">
<div class="stat"><div class="n">{total}</div><div class="l">Totalt</div></div>
<div class="stat"><div class="n">{accessible}</div><div class="l">Tilgjengelige</div></div>
<div class="stat"><div class="n">{paywalled}</div><div class="l">Betalingsmur</div></div>
<div class="stat"><div class="n">{with_date}</div><div class="l">Med dato</div></div>
<div class="stat"><div class="n">{len(high)}</div><div class="l">Høy relevans</div></div>
<div class="stat"><div class="n">{by_type.get('EU/Regulering', 0)}</div><div class="l">EU/Regulering</div></div>
<div class="stat"><div class="n">{by_type.get('Fagmedia', 0)}</div><div class="l">Fagmedia</div></div>
<div class="stat"><div class="n">{by_type.get('Lovdata/Norge', 0)}</div><div class="l">Norske kilder</div></div>
</div>
{weekly_section}
{daily_section}
<section class="sources-section">
<h2>📡 Kilder og tilgangsstatus</h2>
<table>
<thead><tr><th>Kilde</th><th>Type</th><th>Tilgang</th><th>Beskrivelse</th><th>Funn</th></tr></thead>
<tbody>{source_rows}</tbody></table></section>
{section("Høy relevans", "🔴", high, "Direkte relevant for emballasje innen frukt/grønt, drikke og blomster.")}
{section("Medium relevans", "🟡", medium, "Emballasjeregulering med indirekte relevans.")}
{section("Lavere relevans", "⚪", low, "Generelle artikler om emballasje og regulering.")}
{feedback_section}
</div>
<footer>
<p>Packaging Regulation Monitor v2.1 – Oppdatert {now}</p>
<p>Kilder: {' · '.join(SOURCES.keys())}</p>
<p style="margin-top:.5rem">Daglig kl 06:00 via GitHub Actions · AI: Claude (Anthropic) · Feedback-drevet læring</p>
</footer>
</body></html>"""

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"📄 HTML: {output_path}")


def generate_json_data(articles, daily_summary, weekly_summary, output_path):
    data = {
        "generated": datetime.now().isoformat(),
        "count": len(articles),
        "daily_summary": daily_summary or "",
        "weekly_summary": weekly_summary or "",
        "sources": {name: {**info, "article_count": len([a for a in articles if a.source == name])} for name, info in SOURCES.items()},
        "articles": [{
            "title": a.title, "url": a.url, "source": a.source,
            "source_type": a.source_type, "source_access": a.source_access,
            "date": a.date, "summary": a.ai_summary or a.summary[:300],
            "keywords": a.matched_keywords[:5], "categories": a.relevance_categories,
            "score": a.relevance_score, "accessible": a.article_accessible,
            "paywall": a.paywall_detected,
            "impact": a.ai_impact or a.impact_assessment,
        } for a in articles],
    }
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"📊 JSON: {output_path}")


def generate_email_html(articles, daily_summary, weekly_summary):
    now = datetime.now().strftime("%d.%m.%Y")
    top = sorted(articles, key=lambda a: a.relevance_score, reverse=True)[:10]

    summary_block = ""
    if weekly_summary:
        clean = weekly_summary.replace("**SITUASJONSBILDE**", "<b>📊 Situasjonsbilde:</b>")
        clean = clean.replace("**FRUKT & GRØNT**", "<b>🥬 Frukt & Grønt:</b>")
        clean = clean.replace("**DRIKKE**", "<b>🥤 Drikke:</b>")
        clean = clean.replace("**BLOMSTER**", "<b>💐 Blomster:</b>")
        clean = clean.replace("**ANBEFALT HANDLING**", "<b>⚡ Handling:</b>")
        clean = clean.replace("\n", "<br>")
        summary_block = f'<div style="background:#f0fdf4;border-left:4px solid #22763d;padding:15px;margin:15px 0;border-radius:6px"><strong style="color:#22763d">📋 Ukentlig Executive Summary</strong><p style="margin:8px 0 0;line-height:1.6;color:#333">{clean}</p></div>'
    elif daily_summary:
        summary_block = f'<div style="background:#eef2ff;border-left:4px solid #818cf8;padding:15px;margin:15px 0;border-radius:6px"><strong style="color:#4338ca">🤖 Daglig sammendrag</strong><p style="margin:8px 0 0;line-height:1.6;color:#333">{daily_summary}</p></div>'

    rows = ""
    for a in top:
        access = "🔓" if a.article_accessible and not a.paywall_detected else "🔒"
        score_color = "#22763d" if a.relevance_score >= 60 else "#c78c1c" if a.relevance_score >= 30 else "#999"
        cats = ", ".join(a.relevance_categories) if a.relevance_categories else "–"
        date_str = a.date if a.date else "–"
        rows += f'<tr><td style="padding:8px;border-bottom:1px solid #eee;text-align:center"><span style="background:{score_color};color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:bold">{a.relevance_score}</span></td><td style="padding:8px;border-bottom:1px solid #eee">{access} <a href="{a.url}" style="color:#1a1a2e">{a.title[:80]}</a></td><td style="padding:8px;border-bottom:1px solid #eee;font-size:13px;color:#666">{a.source}</td><td style="padding:8px;border-bottom:1px solid #eee;font-size:13px;color:#666">{date_str}</td><td style="padding:8px;border-bottom:1px solid #eee;font-size:13px;color:#666">{cats}</td></tr>'

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;background:#f8f8f8;padding:20px">
<div style="background:linear-gradient(135deg,#0a1628,#2d4a3e);color:#fff;padding:25px;border-radius:10px 10px 0 0">
<h1 style="margin:0;font-size:22px">📦 Emballasjeregulering Monitor</h1>
<p style="margin:5px 0 0;opacity:.7;font-size:14px">Daglig rapport – {now}</p></div>
<div style="background:#fff;padding:20px;border-radius:0 0 10px 10px">
<p style="color:#666;font-size:14px">Fant <strong>{len(articles)}</strong> artikler. <strong>{len([a for a in articles if a.relevance_score >= 60])}</strong> med høy relevans.</p>
{summary_block}
<h2 style="font-size:16px;border-bottom:2px solid #22763d;padding-bottom:5px;margin-top:20px">Topp {len(top)} artikler</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px"><thead><tr style="background:#f8f8f8"><th style="padding:8px;text-align:center">Score</th><th style="padding:8px;text-align:left">Artikkel</th><th style="padding:8px;text-align:left">Kilde</th><th style="padding:8px;text-align:left">Dato</th><th style="padding:8px;text-align:left">Kategori</th></tr></thead><tbody>{rows}</tbody></table>
<p style="margin-top:20px;text-align:center"><a href="$PAGES_URL" style="background:#22763d;color:#fff;padding:10px 25px;border-radius:6px;text-decoration:none;font-weight:bold">Se full rapport →</a></p>
</div>
<p style="text-align:center;color:#999;font-size:12px;margin-top:15px">Packaging Regulation Monitor v2.1 · Daglig kl 06:00</p>
</body></html>"""


# ─── Hovedprogram ────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("📦 Packaging Regulation Monitor v2.1")
    print("=" * 60)
    print(f"Tid: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

    output_dir = os.environ.get("OUTPUT_DIR", "docs")
    os.makedirs(output_dir, exist_ok=True)

    # Last feedback og historikk
    feedback = load_feedback(output_dir)
    feedback_context = build_feedback_context(feedback)
    history = load_history(output_dir)

    if feedback_context:
        print("🎓 Feedback-kontekst lastet inn")

    all_articles = []
    scanners = [
        scan_eurlex, scan_eu_environment, scan_freshplaza,
        scan_packaging_europe, scan_packaging_world,
        scan_regjeringen, scan_miljodirektoratet,
        scan_europen, scan_ceflex, scan_linkedin_via_google,
    ]

    for scanner in scanners:
        try:
            all_articles.extend(scanner())
        except Exception as e:
            print(f"  ⚠ {scanner.__name__}: {e}")

    print(f"\n📊 Totalt: {len(all_articles)}")

    # Hent innhold og datoer fra topp-artikler
    top = sorted(all_articles, key=lambda a: a.relevance_score, reverse=True)[:30]
    print(f"🔍 Henter innhold fra {len(top)} artikler...")
    for art in top:
        try:
            fetch_article_content(art)
        except Exception:
            pass
        time.sleep(0.5)

    unique = deduplicate(all_articles)
    print(f"✅ {len(unique)} unike artikler")
    print(f"📅 {len([a for a in unique if a.date])} med dato funnet")

    # Claude AI-analyse med feedback
    analyze_with_claude(unique, feedback_context)

    # Daglig sammendrag
    daily_summary = generate_daily_summary(unique, feedback_context)
    if daily_summary:
        print("📝 Daglig sammendrag generert")

    # Legg til i historikk
    add_to_history(history, unique)
    save_history(history, output_dir)

    # Ukentlig executive summary (kun mandager)
    weekly_summary = generate_weekly_summary(history, feedback_context)

    # Generer rapporter
    generate_html_report(unique, daily_summary, weekly_summary, os.path.join(output_dir, "index.html"))
    generate_json_data(unique, daily_summary, weekly_summary, os.path.join(output_dir, "data.json"))

    # E-post
    email_html = generate_email_html(unique, daily_summary, weekly_summary)
    with open(os.path.join(output_dir, "email.html"), "w", encoding="utf-8") as f:
        f.write(email_html)
    print(f"📧 E-post generert")

    # Opprett feedback-fil hvis den ikke finnes
    if not os.path.exists(os.path.join(output_dir, FEEDBACK_FILE)):
        save_feedback(feedback, output_dir)
        print("🎓 Feedback-fil opprettet")

    with open(os.path.join(output_dir, "last_updated.txt"), "w") as f:
        f.write(datetime.now().isoformat())

    print(f"\n{'=' * 60}")
    print(f"✅ Ferdig! Alt i {output_dir}/")
    return unique


if __name__ == "__main__":
    main()
