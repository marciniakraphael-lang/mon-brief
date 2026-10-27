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
            result = json.loads(text)
            print("Gemini OK avec " + model)
            return result
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            print("[!] Erreur Gemini " + str(e.code) + " (" + model + ") : " + detail)
            last_error = e
            if e.code in (400, 404, 429, 500, 503, 504) and not is_last:
                time.sleep(3 if e.code in (400, 404) else 15)
                continue
            raise
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print("[!] Réponse Gemini illisible (" + model + ") : " + str(e))
            last_error = e
            if not is_last:
                time.sleep(3)
                continue
            raise
        except (TimeoutError, OSError) as e:
            print("[!] Gemini ne répond pas (" + model + ") : " + str(e))
            last_error = e
            if not is_last:
                time.sleep(5)
                continue
            raise
    raise last_error


def raw_entry(it):
    return {
        "titre": it["titre"],
        "lien": it["lien"],
        "source": it["source"],
        "date": it["date"].isoformat(),
        "resume": it["extrait"][:300],
        "contexte": "",
    }


def summarize(items, avoid=None):
    if not items:
        return []
    payload = [
        {"id": i, "titre": it["titre"], "extrait": it["extrait"][:800], "source": it["source"]}
        for i, it in enumerate(items)
    ]
    avoid_txt = ""
    if avoid:
        avoid_txt = (
            "Sujets déjà présentés hier (ne les reprends pas, sauf s'il y a un fait réellement nouveau) : "
            + json.dumps(avoid[:40], ensure_ascii=False) + ".\n"
        )
    prompt = (
        "Tu rédiges un brief d'actualité quotidien en français pour quelqu'un qui veut comprendre le monde "
        "et améliorer sa culture générale.\n"
        "ÉTAPE 1 : regroupe en UNE SEULE histoire tous les articles qui parlent du même événement ou du même sujet, "
        "même s'ils sont formulés différemment ou viennent de médias différents. Tu ne dois JAMAIS produire deux "
        "histoires sur le même sujet. Les articles qui n'ont aucun doublon forment chacun leur histoire.\n"
        + avoid_txt +
        "ÉTAPE 2 : pour chaque histoire, écris :\n"
        "- 'ids' : la liste des ids des articles regroupés (le premier est le plus important).\n"
        "- 'resume' : 3 à 4 phrases factuelles et neutres qui disent clairement CE QUI S'EST PASSÉ "
        "(qui, quoi, quand, où, chiffres cités dans les extraits), en combinant les infos de tous les articles du groupe. "
        "Appuie-toi uniquement sur les titres et extraits fournis.\n"
        "- 'contexte' : 2 à 4 phrases qui expliquent POURQUOI c'est arrivé et ce que cela change : les raisons, "
        "les enjeux, le contexte utile et les conséquences possibles. Tu peux t'appuyer sur tes connaissances générales "
        "solides pour ce contexte, mais n'invente aucun fait précis (chiffre, date, citation, motif prêté à une personne). "
        "Quand une raison n'est pas confirmée par l'article, formule-la comme une explication courante "
        "('l'objectif est généralement de...', 'cela s'explique souvent par...') ou dis que les motifs n'ont pas été précisés.\n"
        "Langage simple, pas d'opinion.\n"
        'Réponds uniquement en JSON : {"histoires": [{"ids": [0, 3], "resume": "...", "contexte": "..."}]}\n\n'
        "Articles :\n" + json.dumps(payload, ensure_ascii=False)
    )
    res = gemini(prompt)

    out = []
    used = set()
    if isinstance(res, dict):
        for h in res.get("histoires", []):
            try:
                ids = []
                for x in h.get("ids", []):
                    x = int(x)
                    if 0 <= x < len(items) and x not in used:
                        ids.append(x)
                if not ids:
                    continue
                used.update(ids)
                main_item = items[ids[0]]
                sources = []
                for x in ids:
                    s = items[x]["source"]
                    if s not in sources:
                        sources.append(s)
                newest = max(items[x]["date"] for x in ids)
                out.append({
                    "titre": main_item["titre"],
                    "lien": main_item["lien"],
                    "source": " · ".join(sources),
                    "date": newest.isoformat(),
                    "resume": clean_text(h.get("resume", "")) or main_item["extrait"][:300],
                    "contexte": clean_text(h.get("contexte", "")),
                })
            except Exception:
                continue

    if not out:
        print("[!] Regroupement indisponible : articles gardés tels quels.")
        return [raw_entry(it) for it in items]

    out.sort(key=lambda e: e["date"], reverse=True)
    print("Regroupement : " + str(len(items)) + " articles -> " + str(len(out)) + " sujets.")
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


def is_today(entry):
    try:
        return datetime.fromisoformat(entry["date"]) >= MIDNIGHT
    except Exception:
        return True


# ---------- Programme principal ----------
def main():
    print("Mode : " + MODE + " | " + NOW.isoformat())
    items = collect_items()
    if not items:
        raise SystemExit("Aucune actualité récupérée : vérifie les flux RSS.")
    print("Après filtrage des doublons évidents : " + str(len(items)) + " articles.")

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
        depuis_src = [it for it in items if start <= it["date"] < MIDNIGHT][:10]
        auj_src = [it for it in items if it["date"] >= MIDNIGHT][:10]
        summarized = summarize(depuis_src + auj_src, [d["titre"] for d in deja])
        auj = [s for s in summarized if is_today(s)]
        depuis = [s for s in summarized if not is_today(s)]
        culture = make_culture(history["culture_seen"])
        history["culture_seen"] += [c["titre"] for c in culture]
        history["culture_seen"] = history["culture_seen"][-200:]
        history["days"][TODAY] = {"morning_run": NOW.isoformat(), "morning_items": auj}
        quiz = []
    else:
        same_day = latest.get("date") == TODAY
        deja = latest.get("deja_presente", []) if same_day else []
        depuis = latest.get("depuis_hier", []) if same_day else []
        culture = latest.get("culture", []) if same_day else []
        auj_src = [it for it in items if it["date"] >= MIDNIGHT][:12]
        auj = summarize(auj_src, [d["titre"] for d in (deja + depuis)])
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
