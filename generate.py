import os
import re
import json
import time
import random
import hashlib
import html
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

NL = chr(10)
FENCE = chr(96) * 3

# ---------- Réglages ----------
MODEL = "gemini-flash-latest"
PARIS = ZoneInfo("Europe/Paris")
DATA_DIR = "data"
LATEST = os.path.join(DATA_DIR, "latest.json")
HISTORY = os.path.join(DATA_DIR, "history.json")
BANK = os.path.join(DATA_DIR, "quiz_bank.json")
APP_URL = "https://marciniakraphael-lang.github.io/mon-brief/"
CHANCE_TUTO = 0.4

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

TUTOS = [
    "appliquer de l'enduit sur un trou ou une fissure au mur",
    "reboucher un trou de cheville",
    "changer un joint de robinet",
    "déboucher un évier sans produit agressif",
    "détartrer une bouilloire ou une machine à café",
    "changer une roue de voiture",
    "lire sa fiche de paie",
    "faire un budget mensuel simple",
    "rédiger une bonne lettre de résiliation",
    "faire un nœud de cravate",
    "poser une étagère avec des chevilles adaptées",
    "entretenir et affûter un couteau de cuisine",
    "enlever une tache courante sur un vêtement",
    "faire cuire parfaitement du riz ou des pâtes",
    "organiser son CV sur une page",
    "peindre un mur proprement",
    "nettoyer le filtre d'une machine à laver",
    "préparer une négociation de salaire",
]

NOW = datetime.now(PARIS)
MODE = os.environ.get("MODE", "").strip()
if MODE not in ("morning", "evening", "update"):
    MODE = "morning" if NOW.hour < 12 else "evening"
TODAY = NOW.strftime("%Y-%m-%d")
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
MIDNIGHT = NOW.replace(hour=0, minute=0, second=0, microsecond=0)


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


def norm(t):
    return re.sub(r"\W+", "", (t or "").lower())[:60]


def notify(title, message):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    try:
        body = json.dumps(
            {"topic": topic, "title": title, "message": message, "click": APP_URL},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://ntfy.sh", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(req, timeout=20).read()
        print("Notification envoyée : " + title)
    except Exception as e:
        print("[!] Notification impossible : " + str(e))


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
            key = norm(it["titre"])
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


# ---------- Gemini ----------
def gemini(prompt):
    url = "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL + ":generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": os.environ["GEMINI_API_KEY"],
    }
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            text = re.sub("^" + FENCE + r"(?:json)?\s*|\s*" + FENCE + "$", "", text.strip())
            return json.loads(text)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:500]
            print("[!] Erreur Gemini " + str(e.code) + " : " + detail)
            last_error = e
            if e.code in (429, 500, 503) and attempt < 2:
                time.sleep(25 * (attempt + 1))
                continue
            raise
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print("[!] Réponse Gemini illisible : " + str(e))
            last_error = e
            if attempt < 2:
                time.sleep(5)
                continue
            raise
    raise last_error


def summarize(items):
    if not items:
        return []
    payload = [
        {"id": i, "titre": it["titre"], "extrait": it["extrait"][:500], "source": it["source"]}
        for i, it in enumerate(items)
    ]
    prompt = NL.join([
        "Tu rédiges un brief d'actualité quotidien en français pour quelqu'un qui veut améliorer sa culture générale.",
        "Pour chaque article ci-dessous :",
        "- 'resume' : un résumé factuel et neutre de 2 à 3 phrases, en langage simple. N'invente aucun fait : "
        "appuie-toi uniquement sur le titre et l'extrait fourn
