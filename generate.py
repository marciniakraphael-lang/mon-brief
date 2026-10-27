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
MODEL_FAST = "gemini-flash-lite-latest"
TIMEOUT = 150
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
    "vie courante (argent, droit, logement)",
    "histoire",
    "géographie et pays du monde",
    "origine des conflits actuels",
    "nature et animaux",
    "technologie",
    "arts et littérature",
    "économie",
]

TUTOS = [
    "appliquer de l'enduit sur un trou",
    "reboucher un trou de cheville",
    "changer un joint de robinet",
    "déboucher un évier sans produit agressif",
    "détartrer une bouilloire",
    "changer une roue de voiture",
    "lire sa fiche de paie",
    "faire un budget mensuel simple",
    "rédiger une lettre de résiliation",
    "faire un nœud de cravate",
    "poser une étagère avec des chevilles",
    "affûter un couteau de cuisine",
    "enlever une tache sur un vêtement",
    "faire cuire parfaitement du riz",
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
YEST = NOW - timedelta(days=1)
YESTERDAY = YEST.strftime("%Y-%m-%d")
MIDNIGHT = NOW.replace(
    hour=0, minute=0, second=0, microsecond=0
)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clean_text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def norm(t):
    t = (t or "").lower()
    return re.sub(r"\W+", "", t)[:60]


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


def call_gemini(model, prompt):
    url = (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/" + model + ":generateContent"
    )
    config = {
        "responseMimeType": "application/json",
        "temperature": 0.7,
        "thinkingConfig": {"thinkingBudget": 0},
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": config,
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": os.environ["GEMINI_API_KEY"],
    }
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8"))
    parts = data["candidates"][0]["content"]["parts"]
    text = ""
    for p in parts:
        if not p.get("thought"):
            text += p.get("text", "")
    pat = "^" + FENCE + r"(?:json)?\s*"
    pat += "|" + r"\s*" + FENCE + "$"
    text = re.sub(pat, "", text.strip())
    return json.loads(text)


def gemini(prompt):
    plan = [MODEL, MODEL, MODEL_FAST, MODEL_FAST]
    last_error = None
    for i, model in enumerate(plan):
        try:
            print("Gemini : " + model)
            return call_gemini(model, prompt)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            print("[!] Erreur Gemini " + str(e.code))
            print(detail[:300])
            last_error = e
            time.sleep(15 * (i + 1))
        except (TimeoutError, OSError) as e:
            print("[!] Délai dépassé : " + str(e))
            last_error = e
            time.sleep(5)
        except (json.JSONDecodeError, KeyError) as e:
            print("[!] Réponse illisible : " + str(e))
            last_error = e
            time.sleep(5)
        except IndexError as e:
            print("[!] Réponse vide : " + str(e))
            last_error = e
            time.sleep(5)
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
        "pour quelqu'un qui veut améliorer sa culture.",
        "Pour chaque article ci-dessous :",
        "- resume : résumé factuel et neutre de 2 à 3",
        "phrases, en langage simple. N'invente aucun",
        "fait : appuie-toi uniquement sur le titre et",
        "l'extrait. Pas d'opinion.",
        "- contexte : 1 à 2 phrases qui expliquent",
        "pourquoi c'est important (causes, enjeux,",
        "historique), avec des connaissances solides.",
        "Si tu n'es pas sûr, laisse vide.",
        "- important : true uniquement pour une très",
        "grande nouvelle (catastrophe majeure, attentat,",
        "événement politique ou international de premier",
        "plan). Dans la grande majorité des cas, false.",
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
                key = int(r["id"])
                resumes[key] = (
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


def clean_list(values, limit):
    out = []
    for v in values:
        v = clean_text(str(v))
        if v:
            out.append(v)
    return out[:limit]


def make_culture(seen):
    tuto = random.random() < CHANCE_TUTO
    nb = 2 if tuto else 3
    themes = random.sample(THEMES, nb)
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
            "l'électricité sous tension, le gaz ou la",
            "santé grave). Sujets possibles : "
            + json.dumps(idees, ensure_ascii=False),
            "Choisis-en un, ou un autre du même esprit.",
            "Pour le tuto : theme = Tuto pratique,",
            "texte = une phrase d'introduction,",
            "etapes = 4 à 7 étapes courtes et concrètes",
            "(le matériel nécessaire dans la première),",
            "erreurs = 2 à 3 erreurs courantes à éviter,",
            "a_retenir = le conseil clé.",
        ]
    vus = json.dumps(seen[-80:], ensure_ascii=False)
    lines += [
        "Fiches de culture générale (type culture) :",
        "un titre court, un texte de 4 à 6 phrases",
        "simples qui explique le sujet, et une phrase",
        "a_retenir.",
        "Règles : faits solides et vérifiables",
        "uniquement (en cas de doute, change de sujet) ;",
        "pas de chiffres précis dont tu n'es pas sûr ;",
        "ne répète pas ces sujets déjà présentés : " + vus,
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
    if not isinstance(res, dict):
        return out
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
            etapes = clean_list(c.get("etapes", []), 8)
            is_tuto = tuto and c.get("type") == "tuto"
            if is_tuto and len(etapes) >= 3:
                erreurs = clean_list(
                    c.get("erreurs", []), 4
                )
                fiche["type"] = "tuto"
                fiche["etapes"] = etapes
                fiche["erreurs"] = erreurs
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
        steps = " ".join(c.get("etapes", []))
        txt = c["texte"] + " " + steps
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
        "ci-dessous (type culture).",
        "Règles : questions claires qui se comprennent",
        "sans avoir lu l'article ; réponse vérifiable",
        "dans le texte fourni ; mauvaises réponses",
        "plausibles ; une explication courte par réponse.",
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
            choix = []
            for c in q["choix"]:
                choix.append(clean_text(str(c)))
            rep = int(q["reponse"])
            if len(choix) != 4:
                continue
            if rep < 0 or rep > 3:
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
            expl = clean_text(q.get("explication", ""))
            out.append({
                "id": qid,
                "date": TODAY,
                "type": "actu" if is_actu else "culture",
                "question": question,
                "choix": choix,
                "reponse": choix.index(bonne),
                "explication": expl,
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
            start = datetime.fromisoformat(
                prev["morning_run"]
            )
        except Exception:
            start = MIDNIGHT - timedelta(hours=18)
        deja = prev.get("morning_items", [])
        depuis_src = []
        auj_src = []
        for it in items:
            if start <= it["date"] < MIDNIGHT:
                depuis_src.append(it)
            elif it["date"] >= MIDNIGHT:
                auj_src.append(it)
        depuis_src = depuis_src[:8]
        auj_src = auj_src[:8]
        summarized = summarize(depuis_src + auj_src)
        cut = len(depuis_src)
        depuis = summarized[:cut]
        auj = summarized[cut:]
        seen = history["culture_seen"]
        culture = make_culture(seen)
        for c in culture:
            seen.append(c["titre"])
        history["culture_seen"] = seen[-200:]
        quiz = []
    else:
        same_day = latest.get("date") == TODAY
        old = []
        deja = []
        depuis = []
        culture = []
        quiz = []
        if same_day:
            old = latest.get("aujourdhui", [])
            deja = latest.get("deja_presente", [])
            depuis = latest.get("depuis_hier", [])
            culture = latest.get("culture", [])
            quiz = latest.get("quiz_jour", [])
        have = set()
        for a in old + depuis + deja:
            have.add(norm(a["titre"]))
        fresh = []
        for it in items:
            if it["date"] < MIDNIGHT:
                continue
            if norm(it["titre"]) in have:
                continue
            fresh.append(it)
        new = summarize(fresh[:8])
        auj = (new + old)[:30]
        if mode == "evening":
            quiz = make_quiz(auj[:10], culture)
            known = set()
            for q in bank["questions"]:
                known.add(q["id"])
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
    days = {}
    for k in keep:
        days[k] = history["days"][k]
    history["days"] = days

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
        has_tuto = False
        for c in culture:
            if c.get("type") == "tuto":
                has_tuto = True
        total = len(auj) + len(depuis)
        msg = str(total) + " actus et "
        msg += str(len(culture)) + " fiches"
        msg += " dont un tuto." if has_tuto else "."
        notify("Ton brief du matin est prêt", msg)
    elif mode == "evening":
        n = 0
        for q in quiz:
            if q.get("type") == "actu":
                n += 1
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
