import os
import re
import json
import time
import random
import hashlib
import html
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

# ---------- Réglages ----------
# Modèles essayés dans l'ordre (les 2 premiers sont retentés à la fin si besoin)
MODELS = [
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
TIMEOUT = 150
PARIS = ZoneInfo("Europe/Paris")
DATA_DIR = "data"
LATEST = os.path.join(DATA_DIR, "latest.json")
HISTORY = os.path.join(DATA_DIR, "history.json")
BANK = os.path.join(DATA_DIR, "quiz_bank.json")

FEEDS = [
    ("franceinfo", "https://www.francetvinfo.fr/titres.rss"),
    ("franceinfo Monde", "https://www.francetvinfo.fr/monde.rss"),
    ("France 24", "https://www.france24.com/fr/rss"),
    ("Le Monde", "https://www.lemonde.fr/rss/une.xml"),
]

THEMES = [
    "science",
    "sport",
    "santé et corps humain",
    "mythologie grecque",
    "vie courante (argent, droit, logement, cuisine, consommation)",
    "histoire",
    "géographie et pays du monde",
    "origine des grands événements ou conflits actuels",
    "nature et animaux",
    "technologie",
    "arts et littérature",
    "économie",
]

NOW = datetime.now(PARIS)
MODE = os.environ.get("MODE", "").strip()
if MODE not in ("morning", "evening"):
    MODE = "morning" if NOW.hour < 12 else "evening"
TODAY = NOW.strftime("%Y-%m-%d")
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
MIDNIGHT = NOW.replace(hour=0, minute=0, second=0, microsecond=0)

STOP = {
    "dans", "avec", "pour", "dont", "cette", "leurs", "entre", "après", "avant",
    "sous", "vers", "chez", "plus", "sont", "être", "faire", "fait", "mais",
    "comme", "tout", "tous", "elle", "elles", "nous", "vous", "this", "that",
}

MEDIA_NS = "{http://search.yahoo.com/mrss/}"
BROWSER_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
IMG_CACHE = {}


# ---------- Outils ----------
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clean_text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def words(s):
    return {w for w in re.findall(r"[a-zà-ÿ0-9]+", (s or "").lower()) if len(w) > 3 and w not in STOP}


def similar(a, b):
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    inter = len(wa & wb)
    return inter >= 3 and inter / min(len(wa), len(wb)) >= 0.6


# ---------- Images ----------
def rss_image(it):
    """Image fournie directement par le flux RSS (si elle existe)."""
    for tag in ("content", "thumbnail"):
        for el in it.iter(MEDIA_NS + tag):
            u = (el.get("url") or "").strip()
            kind = (el.get("type") or "") + (el.get("medium") or "")
            if u.startswith("http") and "video" not in kind:
                return u
    enc = it.find("enclosure")
    if enc is not None:
        u = (enc.get("url") or "").strip()
        if u.startswith("http") and (enc.get("type") or "").startswith("image"):
            return u
    return ""


def page_image(url):
    """Image de partage (og:image) de la page de l'article."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "fr-FR,fr;q=0.9"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read(400000).decode("utf-8", "ignore")
    except Exception as e:
        print("[!] Page illisible (" + url[:70] + ") : " + str(e))
        return ""
    patterns = (
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    )
    for pat in patterns:
        m = re.search(pat, raw, re.I)
        if m:
            u = html.unescape(m.group(1)).strip()
            if u.startswith("//"):
                u = "https:" + u
            if u.startswith("http"):
                return u
    return ""


def wiki_image(title):
    """Image de l'article Wikipédia français du sujet."""
    title = clean_text(title)
    if not title:
        return ""
    url = (
        "https://fr.wikipedia.org/w/api.php?action=query&redirects=1&prop=pageimages"
        "&piprop=thumbnail&pithumbsize=800&format=json&titles=" + urllib.parse.quote(title)
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mon-brief/1.0 (usage personnel)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        for p in data["query"]["pages"].values():
            src = (p.get("thumbnail") or {}).get("source", "")
            if src:
                return src
    except Exception as e:
        print("[!] Image Wikipédia indisponible (" + title + ") : " + str(e))
    return ""


def add_images(entries):
    """Complète les infos qui n'ont pas encore d'image avec celle de leur article."""
    for e in entries:
        if e.get("image"):
            continue
        lien = e.get("lien")
        if not lien:
            continue
        if lien not in IMG_CACHE:
            IMG_CACHE[lien] = page_image(lien)
        e["image"] = IMG_CACHE[lien]
    n = sum(1 for e in entries if e.get("image"))
    print("Images : " + str(n) + "/" + str(len(entries)))


# ---------- Actualités (flux RSS) ----------
def fetch_feed(name, url):
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mon-brief)"})
        with urllib.request.urlopen(req, timeout=25) as r:
            root = ET.fromstring(r.read())
        for it in root.iter("item"):
            title = clean_text(it.findtext("title"))
            link = (it.findtext("link") or "").strip()
            desc = clean_text(it.findtext("description"))
            pub = it.findtext("pubDate")
            if not title or not pub:
                continue
            try:
                d = parsedate_to_datetime(pub)
            except Exception:
                continue
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            items.append({
                "titre": title,
                "lien": link,
                "extrait": desc,
                "source": name,
                "date": d.astimezone(PARIS),
                "image": rss_image(it),
            })
    except Exception as e:
        print("[!] Flux ignoré (" + name + ") : " + str(e))
    return items


def collect_items():
    seen = set()
    out = []
    for name, url in FEEDS:
        got = fetch_feed(name, url)
        print(name + " : " + str(len(got)) + " articles")
        for it in got:
            key = re.sub(r"\W+", "", it["titre"].lower())[:60]
            if key in seen:
                continue
            if any(similar(it["titre"], o["titre"]) for o in out):
                continue
            seen.add(key)
            out.append(it)
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


# ---------- Gemini ----------
def gemini(prompt):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": os.environ["GEMINI_API_KEY"],
    }
    # Un essai par modèle, puis un second tour sur les 2 premiers
    plan = MODELS + MODELS[:2]
    last_error = None
    for attempt, model in enumerate(plan):
        is_last = attempt == len(plan) - 1
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
        try:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
