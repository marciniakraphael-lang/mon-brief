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

# ---------- Réglages ----------
MODEL = "gemini-flash-latest"
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
            key = re.sub(r"\W+", "", it["titre"].lower())[:60]
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
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
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
    prompt = (
        "Tu rédiges un brief d'actualité quotidien en français pour quelqu'un qui veut améliorer sa culture générale.\n"
        "Pour chaque article ci-dessous, écris un résumé factuel et neutre de 2 à 3 phrases, en langage simple, "
        "avec le contexte utile si l'extrait le permet. N'invente aucun fait : appuie-toi uniquement sur le titre "
        "et l'extrait fournis. Pas d'opinion.\n"
        'Réponds uniquement en JSON : {"resumes": [{"id": 0, "resume": "..."}]}\n\n'
        "Articles :\n" + json.dumps(payload, ensure_ascii=False)
    )
    res = gemini(prompt)
    resumes = {}
    if isinstance(res, dict):
        for r in res.get("resumes", []):
            try:
                resumes[int(r["id"])] = clean_text(r["resume"])
            except Exception:
                pass
    out = []
    for i, it in enumerate(items):
        out.append({
            "titre": it["titre"],
            "lien": it["lien"],
            "source": it["source"],
            "date": it["date"].isoformat(),
            "resume": resumes.get(i) or it["extrait"][:300],
        })
    return out


def make_culture(seen):
    themes = random.sample(THEMES, 3)
    prompt = (
        "Tu écris 3 fiches de culture générale en français, claires et agréables à lire, pour un adulte curieux. "
        "Une fiche par thème imposé, dans cet ordre : " + json.dumps(themes, ensure_ascii=False) + ".\n"
        "Règles : faits solides et vérifiables uniquement (si tu as un doute, choisis un autre sujet) ; "
        "pas de chiffres précis dont tu n'es pas sûr ; ne répète pas ces sujets déjà présentés : "
        + json.dumps(seen[-80:], ensure_ascii=False) + ".\n"
        "Chaque fiche : un titre court, un texte de 4 à 6 phrases simples qui explique le sujet, "
        "et une phrase 'a_retenir'.\n"
        'Réponds uniquement en JSON : {"culture": [{"theme": "...", "titre": "...", "texte": "...", "a_retenir": "..."}]}'
    )
    res = gemini(prompt)
    out = []
    if isinstance(res, dict):
        for c in res.get("culture", [])[:3]:
            try:
                out.append({
                    "theme": clean_text(c["theme"]),
                    "titre": clean_text(c["titre"]),
                    "texte": clean_text(c["texte"]),
                    "a_retenir": clean_text(c.get("a_retenir", "")),
                })
            except Exception:
                pass
    return out


def make_quiz(items, culture):
    if not items and not culture:
        return []
    articles = [
        {"id": i, "titre": it["titre"], "resume": it["resume"]} for i, it in enumerate(items)
    ]
    fiches = [{"titre": c["titre"], "texte": c["texte"]} for c in culture]
    prompt = (
        "Crée des questions de quiz à choix multiples (4 choix, une seule bonne réponse) en français.\n"
        "1) Jusqu'à 5 questions sur les articles d'actualité du jour ci-dessous (type 'actu'), "
        "avec l'id de l'article concerné.\n"
        "2) Jusqu'à 2 questions sur les fiches de culture générale ci-dessous (type 'culture').\n"
        "Règles : questions claires qui se comprennent sans avoir lu l'article ; réponse vérifiable dans le texte "
        "fourni ; mauvaises réponses plausibles ; une explication courte pour chaque réponse.\n"
        'Réponds uniquement en JSON : {"questions": [{"type": "actu", "id_article": 0, "question": "...", '
        '"choix": ["A", "B", "C", "D"], "reponse": 0, "explication": "..."}]}\n'
        "('reponse' est l'index de 0 à 3 de la bonne réponse ; id_article vaut null pour le type culture.)\n\n"
        "Articles :\n" + json.dumps(articles, ensure_ascii=False) +
        "\n\nFiches culture :\n" + json.dumps(fiches, ensure_ascii=False)
    )
    res = gemini(prompt)
    out = []
    if not isinstance(res, dict):
        return out
    for q in res.get("questions", []):
        try:
            choix = [clean_text(str(c)) for c in q["choix"]]
            rep = int(q["reponse"])
            if len(choix) != 4 or not 0 <= rep <= 3:
                continue
            bonne = choix[rep]
            random.shuffle(choix)
            lien = ""
            ida = q.get("id_article")
            if isinstance(ida, str) and ida.isdigit():
                ida = int(ida)
            if q.get("type") == "actu" and isinstance(ida, int) and 0 <= ida < len(items):
                lien = items[ida]["lien"]
            question = clean_text(q["question"])
            qid = hashlib.md5(question.lower().encode("utf-8")).hexdigest()[:10]
            out.append({
                "id": qid,
                "date": TODAY,
                "type": "actu" if q.get("type") == "actu" else "culture",
                "question": question,
                "choix": choix,
                "reponse": choix.index(bonne),
                "explication": clean_text(q.get("explication", "")),
                "lien": lien,
            })
        except Exception:
            continue
    return out


# ---------- Programme principal ----------
def main():
    print("Mode : " + MODE + " | " + NOW.isoformat())
    items = collect_items()
    if not items:
        raise SystemExit("Aucune actualité récupérée : vérifie les flux RSS.")

    history = load_json(HISTORY, {})
    history.setdefault("days", {})
    history.setdefault("culture_seen", [])
    latest = load_json(LATEST, {})
    bank = load_json(BANK, {})
    bank.setdefault("questions", [])

    if MODE == "morning":
        prev = history["days"].get(YESTERDAY, {})
        try:
            start = datetime.fromisoformat(prev["morning_run"])
        except Exception:
            start = MIDNIGHT - timedelta(hours=18)
        deja = prev.get("morning_items", [])
        depuis_src = [it for it in items if start <= it["date"] < MIDNIGHT][:8]
        auj_src = [it for it in items if it["date"] >= MIDNIGHT][:8]
        summarized = summarize(depuis_src + auj_src)
        depuis = summarized[:len(depuis_src)]
        auj = summarized[len(depuis_src):]
        culture = make_culture(history["culture_seen"])
        history["culture_seen"] += [c["titre"] for c in culture]
        history["culture_seen"] = history["culture_seen"][-200:]
        history["days"][TODAY] = {"morning_run": NOW.isoformat(), "morning_items": auj}
        quiz = []
    else:
        same_day = latest.get("date") == TODAY
        auj_src = [it for it in items if it["date"] >= MIDNIGHT][:10]
        auj = summarize(auj_src)
        deja = latest.get("deja_presente", []) if same_day else []
        depuis = latest.get("depuis_hier", []) if same_day else []
        culture = latest.get("culture", []) if same_day else []
        quiz = make_quiz(auj, culture)
        known = {q["id"] for q in bank["questions"]}
        for q in quiz:
            if q["id"] not in known:
                bank["questions"].append(q)
        bank["questions"] = bank["questions"][-600:]

    state = {
        "date": TODAY,
        "mode": MODE,
        "updated": NOW.isoformat(),
        "deja_presente": deja,
        "depuis_hier": depuis,
        "aujourdhui": auj,
        "culture": culture,
        "quiz_jour": quiz,
    }

    keep = sorted(history["days"].keys())[-40:]
    history["days"] = {k: history["days"][k] for k in keep}

    save_json(LATEST, state)
    save_json(HISTORY, history)
    save_json(BANK, bank)
    print("OK : " + str(len(depuis)) + " depuis hier, " + str(len(auj)) + " aujourd'hui, "
          + str(len(culture)) + " culture, " + str(len(quiz)) + " questions.")


if __name__ == "__main__":
    main()
