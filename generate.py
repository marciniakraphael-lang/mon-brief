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

MODEL = "gemini-flash-latest"
PARIS = ZoneInfo("Europe/Paris")
DATA_DIR = "data"
LATEST = os.path.join(DATA_DIR, "latest.json")
HISTORY = os.path.join(DATA_DIR, "history.json")
BANK = os.path.join(DATA_DIR, "quiz_bank.json")
APP_URL = (
    "https://marciniakraphael-lang"
    ".github.io/mon-brief/"
)
CHANCE_TUTO = 0.4

FEEDS = [
    ("franceinfo",
     "https://www.francetvinfo.fr/titres.rss"),
    ("franceinfo Monde",
     "https://www.francetvinfo.fr/monde.rss"),
    ("France 24",
     "https://www.france24.com/fr/rss"),
    ("Le Monde",
     "https://www.lemonde.fr/rss/une.xml"),
]

THEMES = [
    "science",
    "sport",
    "santé et corps humain",
    "mythologie grecque",
    "vie courante (argent, droit, logement, cuisine)",
    "histoire",
    "géographie et pays du monde",
    "origine des grands événements ou conflits actuels",
    "nature et animaux",
    "technologie",
    "arts et littérature",
    "économie",
]

TUTOS = [
    "appliquer de l'enduit sur un trou ou une fissure",
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
        data = {
            "topic": topic,
            "title": title,
            "message": message,
            "click": APP_URL,
        }
        body = json.dumps(data, ensure_ascii=False)
        req = urllib.request.Request(
            "https://ntfy.sh",
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=20).read()
        print("Notification envoyée : " + title)
    except Exception as e:
        print("[!] Notification impossible : " + str(e))


def fetch_feed(name, url):
    items = []
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (mon-brief)"},
        )
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


def gemini(prompt):
    url = (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/" + MODEL + ":generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": os.environ["GEMINI_API_KEY"],
    }
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(
                p.get("text", "")
                for p in parts
                if not p.get("thought")
            )
            pat = "^" + FENCE + r"(?:json)?\s*"
            pat += "|" + r"\s*" + FENCE + "$"
            text = re.sub(pat, "", text.strip())
            return json.loads(text)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:500]
            print("[!] Erreur Gemini " + str(e.code))
            print(detail)
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
    payload = []
    for i, it in enumerate(items):
        payload.append({
            "id": i,
            "titre": it["titre"],
            "extrait": it["extrait"][:500],
            "source": it["source"],
        })
    fmt = (
        'Réponds uniquement en JSON : {"resumes": '
        '[{"id": 0, "resume": "...", '
        '"contexte": "...", "important": false}]}'
    )
    prompt = NL.join([
        "Tu rédiges un brief d'actualité en français",
        "pour quelqu'un qui veut améliorer sa culture générale.",
        "Pour chaque article ci-dessous :",
        "- resume : résumé factuel et neutre de 2 à 3 phrases,",
        "en langage simple. N'invente aucun fait :",
        "appuie-toi uniquement sur le titre et l'extrait.",
        "Pas d'opinion.",
        "- contexte : 1 à 2 phrases qui expliquent pourquoi",
        "c'est important (causes, enjeux, historique),",
        "avec des connaissances générales solides.",
        "Si tu n'es pas sûr, laisse vide.",
        "- important : true uniquement pour une très grande",
        "nouvelle (catastrophe majeure, attentat, événement",
        "politique ou international de premier plan).",
        "Dans la grande majorité des cas, false.",
        fmt,
        "",
        "Articles :",
        json.dumps(payload, ensure_ascii=False),
    ])
    res = gemini(prompt)
    resumes = {}
    if isinstance(res, dict):
        for r in res.get("resumes", []):
            try:
                resumes[int(r["id"])] = (
                    clean_text(r["resume"]),
                    clean_text(r.get("contexte", "")),
                    r.get("important") is True,
                )
            except Exception:
                pass
    out = []
    for i, it in enumerate(items):
        resume, contexte, important = resumes.get(
            i, ("", "", False)
        )
        out.append({
            "titre": it["titre"],
            "lien": it["lien"],
            "source": it["source"],
            "date": it["date"].isoformat(),
            "resume": resume or it["extrait"][:300],
            "contexte": contexte,
            "important": important,
        })
    return out


def make_culture(seen):
    tuto = random.random() < CHANCE_TUTO
    themes = random.sample(THEMES, 2 if tuto else 3)
    lines = [
        "Tu écris des fiches en français, claires et",
        "agréables à lire, pour un adulte curieux.",
        "Une fiche par thème imposé, dans cet ordre : "
        + json.dumps(themes, ensure_ascii=False),
    ]
    if tuto:
        idees = random.sample(TUTOS, 5)
        lines += [
            "Ajoute en dernière position une fiche de type",
            "tuto : un mini-tuto pratique et utile pour la",
            "vie de tous les jours, sans danger (rien sur",
            "l'électricité sous tension, le gaz ou la santé",
            "grave). Sujets possibles : "
            + json.dumps(idees, ensure_ascii=False),
            "Choisis-en un, ou un autre du même esprit.",
            "Pour le tuto : theme = Tuto pratique,",
            "texte = une phrase d'introduction,",
            "etapes = 4 à 7 étapes courtes et concrètes",
            "(le matériel nécessaire dans la première),",
            "erreurs = 2 à 3 erreurs courantes à éviter,",
            "a_retenir = le conseil clé.",
        ]
    lines += [
        "Fiches de culture générale (type culture) :",
        "un titre court, un texte de 4 à 6 phrases simples",
        "qui explique le sujet, et une phrase a_retenir.",
        "Règles : faits solides et vérifiables uniquement",
        "(en cas de doute, choisis un autre sujet) ;",
        "pas de chiffres précis dont tu n'es pas sûr ;",
        "ne répète pas ces sujets déjà présentés : "
        + json.dumps(seen[-80:], ensure_ascii=False),
        'Réponds uniquement en JSON : {"culture": [',
        '{"type": "culture", "theme": "...",',
        '"titre": "...", "texte": "...",',
        '"a_retenir": "..."},',
        '{"type": "tuto", "theme": "Tuto pratique",',
        '"titre": "...", "texte": "...",',
        '"etapes": ["..."], "erreurs": ["..."],',
        '"a_retenir": "..."}]}',
    ]
    res = gemini(NL.join(lines))
    out = []
    if isinstance(res, dict):
        for c in res.get("culture", [])[:3]:
            try:
                fiche = {
                    "type": "culture",
                    "theme": clean_text(c["theme"]),
                    "titre": clean_text(c["titre"]),
                    "texte": clean_text(c["texte"]),
                    "a_retenir": clean_text(
                        c.get("a_retenir", "")
                    ),
                }
                etapes = []
                for e in c.get("etapes", []):
                    e = clean_text(str(e))
                    if e:
                        etapes.append(e)
                etapes = etapes[:8]
                if (tuto and c.get("type") == "tuto"
                        and len(etapes) >= 3):
                    erreurs = []
                    for e in c.get("erreurs", []):
                        e = clean_text(str(e))
                        if e:
                            erreurs.append(e)
                    fiche["type"] = "tuto"
                    fiche["etapes"] = etapes
                    fiche["erreurs"] = erreurs[:4]
                out.append(fiche)
            except Exception:
                pass
    return out


def make_quiz(items, culture):
    if not items and not culture:
        return []
    articles = []
    for i, it in enumerate(items):
        articles.append({
            "id": i,
            "titre": it["titre"],
            "resume": it["resume"],
        })
    fiches = []
    for c in culture:
        txt = c["texte"] + " " + " ".join(c.get("etapes", []))
        fiches.append({"titre": c["titre"], "texte": txt})
    fmt = (
        'Réponds uniquement en JSON : {"questions": ['
        '{"type": "actu", "id_article": 0, '
        '"question": "...", '
        '"choix": ["A", "B", "C", "D"], '
        '"reponse": 0, "explication": "..."}]}'
    )
    prompt = NL.join([
        "Crée des questions de quiz à choix multiples",
        "(4 choix, une seule bonne réponse) en français.",
        "1) Jusqu'à 5 questions sur les articles du jour",
        "ci-dessous (type actu), avec l'id de l'article.",
        "2) Jusqu'à 2 questions sur les fiches de culture",
        "générale ci-dessous (type culture).",
        "Règles : questions claires qui se comprennent",
        "sans avoir lu l'article ; réponse vérifiable dans",
        "le texte fourni ; mauvaises réponses plausibles ;",
        "une explication courte pour chaque réponse.",
        fmt,
        "reponse est l'index de 0 à 3 de la bonne réponse.",
        "id_article vaut null pour le type culture.",
        "",
        "Articles :",
        json.dumps(articles, ensure_ascii=False),
        "",
        "Fiches culture :",
        json.dumps(fiches, ensure_ascii=False),
    ])
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
            is_actu = q.get("type") == "actu"
            if is_actu and isinstance(ida, int):
                if 0 <= ida < len(items):
                    lien = items[ida]["lien"]
            question = clean_text(q["question"])
            raw = question.lower().encode("utf-8")
            qid = hashlib.md5(raw).hexdigest()[:10]
            out.append({
                "id": qid,
                "date": TODAY,
                "type": "actu" if is_actu else "culture",
                "question": question,
                "choix": choix,
                "reponse": choix.index(bonne),
                "explication": clean_text(
                    q.get("explication", "")
                ),
                "lien": lien,
            })
        except Exception:
            continue
    return out


def main():
    items = collect_items()
    if not items:
        raise SystemExit("Aucune actualité récupérée.")

    history = load_json(HISTORY, {})
    history.setdefault("days", {})
    history.setdefault("culture_seen", [])
    latest = load_json(LATEST, {})
    bank = load_json(BANK, {})
    bank.setdefault("questions", [])

    mode = MODE
    if mode == "update" and latest.get("date") != TODAY:
        mode = "morning"
    print("Mode : " + mode + " | " + NOW.isoformat())

    new = []
    if mode == "morning":
        prev = history["days"].get(YESTERDAY, {})
        try:
            start = datetime.fromisoformat(prev["morning_run"])
        except Exception:
            start = MIDNIGHT - timedelta(hours=18)
        deja = prev.get("morning_items", [])
        depuis_src = [
            it for it in items
            if start <= it["date"] < MIDNIGHT
        ][:8]
        auj_src = [
            it for it in items if it["date"] >= MIDNIGHT
        ][:8]
        summarized = summarize(depuis_src + auj_src)
        depuis = summarized[:len(depuis_src)]
        auj = summarized[len(depuis_src):]
        culture = make_culture(history["culture_seen"])
        history["culture_seen"] += [c["titre"] for c in culture]
        history["culture_seen"] = history["culture_seen"][-200:]
        quiz = []
    else:
        same_day = latest.get("date") == TODAY
        old = latest.get("aujourdhui", []) if same_day else []
        deja = latest.get("deja_presente", []) if same_day else []
        depuis = latest.get("depuis_hier", []) if same_day else []
        culture = latest.get("culture", []) if same_day else []
        quiz = latest.get("quiz_jour", []) if same_day else []
        have = {norm(a["titre"]) for a in old + depuis + deja}
        today_src = [it for it in items if it["date"] >= MIDNIGHT]
        fresh = [
            it for it in today_src
            if norm(it["titre"]) not in have
        ][:8]
        new = summarize(fresh)
        auj = (new + old)[:30]
        if mode == "evening":
            quiz = make_quiz(auj[:10], culture)
            known = {q["id"] for q in bank["questions"]}
            for q in quiz:
                if q["id"] not in known:
                    bank["questions"].append(q)
            bank["questions"] = bank["questions"][-600:]

    history["days"][TODAY] = {
        "morning_run": NOW.isoformat(),
        "morning_items": auj,
    }

    state = {
        "date": TODAY,
        "mode": mode,
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
    print(
        "OK : " + str(len(depuis)) + " depuis hier, "
        + str(len(auj)) + " aujourd'hui, "
        + str(len(culture)) + " culture, "
        + str(len(quiz)) + " questions."
    )

    if mode == "morning":
        has_tuto = any(c.get("type") == "tuto" for c in culture)
        msg = (
            str(len(auj) + len(depuis)) + " actus et "
            + str(len(culture)) + " fiches"
        )
        msg += " dont un tuto." if has_tuto else "."
        notify("Ton brief du matin est prêt", msg)
    elif mode == "evening":
        n = len([q for q in quiz if q.get("type") == "actu"])
        notify(
            "Ton quiz du jour est prêt",
            str(n) + " questions sur les infos du jour.",
        )
    else:
        imp = [a for a in new if a.get("important")]
        for a in imp[:2]:
            notify("À la une", a["titre"])


if __name__ == "__main__":
    main()
