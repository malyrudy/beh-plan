"""Načte exporty z Garminu / Stravy ze složky import/ a doplní je do data/aktivity.json.

Podporované soubory:
  *.fit / *.fit.gz  – „Exportovat originál“ z Garmin Connect, soubory z bulk exportu Stravy
                       (potřebuje `pip install fitparse`)
  *.gpx / *.tcx     – export jedné aktivity z Garminu i Stravy
  *.csv             – seznam aktivit z Garmin Connect (Activities.csv, CZ i EN)
                       nebo activities.csv z bulk exportu Stravy

Do repa se ukládá jen souhrn (datum, sport, km, čas, tep, převýšení). Surové soubory
s GPS stopou zůstávají v import/ (je v .gitignore) – start stopy by jinak prozradil, kde bydlíš.
Zpracované soubory se přesunou do import/zpracovano/.

Použití:
    python tools/import_aktivit.py            # zpracuje import/ a vypíše nové aktivity
    python tools/import_aktivit.py --nechat   # soubory nepřesouvat
"""
import argparse
import csv
import gzip
import io
import json
import math
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

KOREN = Path(__file__).resolve().parent.parent
IMPORT = KOREN / "import"
AKTIVITY = KOREN / "data" / "aktivity.json"


# ---------- společné pomocné funkce ----------

def sport(text):
    """Sjednotí názvy sportů z různých zdrojů na pár kategorií, se kterými pracuje stránka."""
    t = (text or "").lower()
    if re.search(r"run|běh|beh|trail|treadmill|pás", t):
        return "beh"
    if re.search(r"swim|plav", t):
        return "plavani"
    if re.search(r"bike|cycl|ride|kol[oea]|cyklist|spinning", t):
        return "kolo"
    if re.search(r"walk|hik|chůz|chuz|turist|pěší", t):
        return "chuze"
    if re.search(r"yoga|jóga|joga|pilates|stretch|protah", t):
        return "joga"
    if re.search(r"strength|weight|síl|sil|posil|fitness|training|hiit|cardio|kardio", t):
        return "posilovna"
    return "jine"


def lokalni(dt):
    """UTC → místní čas počítače (zoneinfo na Windows bez tzdata nefunguje, tohle ano)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)


def cislo(s):
    """'10,02' / '10.02' / '1,500' / '' → float nebo None."""
    s = str(s or "").strip().replace("\xa0", "").replace(" ", "")
    if s in ("", "--"):
        return None
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):   # anglické tisíce: 1,500.5
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def cas_s(s):
    """'00:45:12' / '45:12' / '00:45:12.3' / '2712' → sekundy."""
    s = str(s or "").strip()
    if not s or s == "--":
        return None
    if ":" not in s:
        return cislo(s)
    v = 0.0
    for p in s.split(":"):
        v = v * 60 + float(p.replace(",", "."))
    return v


def haversine(a, b):
    r = 6371000
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def zaznam(zdroj, start, typ, nazev, metry, sekundy, tep_prum=None, tep_max=None, prevyseni=None):
    start = start.replace(microsecond=0)
    z = {
        "id": f"{start:%Y%m%d-%H%M}-{typ}",
        "zdroj": zdroj,
        "datum": start.isoformat(),
        "typ": typ,
        "nazev": nazev or "",
        "km": round(metry / 1000, 2) if metry else 0,
        "cas_s": round(sekundy) if sekundy else None,
        "tep_prum": round(tep_prum) if tep_prum else None,
        "tep_max": round(tep_max) if tep_max else None,
        "prevyseni": round(prevyseni) if prevyseni else None,
    }
    if typ == "beh" and z["km"] and z["cas_s"]:
        z["tempo_s"] = round(z["cas_s"] / z["km"])
    return z


def bez_ns(tag):
    return tag.split("}", 1)[-1]


def otevri(p):
    return gzip.open(p, "rb") if p.suffix == ".gz" else open(p, "rb")


# ---------- jednotlivé formáty ----------

def nacti_gpx(p):
    root = ET.parse(otevri(p)).getroot()
    nazev, typ, body = "", "", []
    for el in root.iter():
        t = bez_ns(el.tag)
        if t == "name" and not nazev:
            nazev = el.text or ""
        elif t == "type" and not typ:
            typ = el.text or ""
        elif t == "trkpt":
            bod = {"ll": (float(el.get("lat")), float(el.get("lon")))}
            for c in el.iter():
                ct = bez_ns(c.tag)
                if ct == "time":
                    bod["t"] = datetime.fromisoformat(c.text.replace("Z", "+00:00"))
                elif ct == "ele":
                    bod["ele"] = float(c.text)
                elif ct == "hr":
                    bod["hr"] = float(c.text)
            body.append(bod)
    body = [b for b in body if "t" in b]
    if len(body) < 2:
        return []
    metry = sum(haversine(a["ll"], b["ll"]) for a, b in zip(body, body[1:]))
    tepy = [b["hr"] for b in body if "hr" in b]
    vyska = [b["ele"] for b in body if "ele" in b]
    stoupani = sum(max(0, b - a) for a, b in zip(vyska, vyska[1:])) if vyska else None
    return [zaznam("gpx", lokalni(body[0]["t"]), sport(typ or nazev or "run"), nazev, metry,
                   (body[-1]["t"] - body[0]["t"]).total_seconds(),
                   sum(tepy) / len(tepy) if tepy else None, max(tepy) if tepy else None, stoupani)]


def nacti_tcx(p):
    root = ET.parse(otevri(p)).getroot()
    out = []
    for akt in (e for e in root.iter() if bez_ns(e.tag) == "Activity"):
        start, metry, sek, tepy, tmax = None, 0.0, 0.0, [], None
        for el in akt.iter():
            t = bez_ns(el.tag)
            if t == "Id" and el.text:
                start = datetime.fromisoformat(el.text.strip().replace("Z", "+00:00"))
            elif t == "Lap":
                for c in el:
                    ct = bez_ns(c.tag)
                    if ct == "TotalTimeSeconds":
                        sek += float(c.text)
                    elif ct == "DistanceMeters":
                        metry += float(c.text)
            elif t == "HeartRateBpm" and el.find("./*") is not None:
                tepy.append(float(el.find("./*").text))
        if start:
            tmax = max(tepy) if tepy else None
            out.append(zaznam("tcx", lokalni(start), sport(akt.get("Sport")), "", metry, sek,
                              sum(tepy) / len(tepy) if tepy else None, tmax))
    return out


def nacti_fit(p):
    try:
        import fitparse
    except ImportError:
        print(f"  ! {p.name}: pro .fit soubory nainstaluj `pip install fitparse` (nebo exportuj GPX)")
        return None
    with otevri(p) as f:
        fit = fitparse.FitFile(io.BytesIO(f.read()))
    out = []
    for s in fit.get_messages("session"):
        v = s.get_values()
        if not v.get("start_time"):
            continue
        sp = f"{v.get('sport', '')} {v.get('sub_sport', '')}"
        out.append(zaznam("fit", lokalni(v["start_time"]), sport(sp), "", v.get("total_distance"),
                          v.get("total_timer_time"), v.get("avg_heart_rate"), v.get("max_heart_rate"),
                          v.get("total_ascent")))
    return out


# Hlavičky Garmin CSV v angličtině i češtině (první nalezený sloupec vyhrává).
GARMIN = {
    "typ": ["Activity Type", "Typ aktivity"],
    "datum": ["Date", "Datum"],
    "nazev": ["Title", "Název"],
    "km": ["Distance", "Vzdálenost"],
    "cas": ["Time", "Čas", "Moving Time", "Celkový čas"],
    "tep": ["Avg HR", "Průměrný ST", "Prům. TF", "Průměrná TF"],
    "tep_max": ["Max HR", "Maximální ST", "Max. TF", "Maximální TF"],
    "stoupani": ["Total Ascent", "Celkový výstup", "Celkové stoupání"],
}


def nacti_csv(p):
    text = p.read_text(encoding="utf-8-sig")
    radky = list(csv.reader(io.StringIO(text)))
    if not radky:
        return []
    hlavicka = radky[0]

    def idx(*nazvy):
        for n in nazvy:
            if n in hlavicka:
                return hlavicka.index(n)   # index() vrací první výskyt – u Stravy je to ten správný
        return None

    out = []
    if "Activity ID" in hlavicka:   # Strava bulk export
        i = dict(datum=idx("Activity Date"), nazev=idx("Activity Name"), typ=idx("Activity Type"),
                 cas=idx("Moving Time"), cas2=idx("Elapsed Time"), km=idx("Distance"),
                 tep=idx("Average Heart Rate"), tep_max=idx("Max Heart Rate"), stoupani=idx("Elevation Gain"))
        for r in radky[1:]:
            if not r or not r[i["datum"]]:
                continue
            start = datetime.strptime(r[i["datum"]], "%b %d, %Y, %I:%M:%S %p")
            g = lambda k: r[i[k]] if i[k] is not None and i[k] < len(r) else ""
            km = cislo(g("km")) or 0
            out.append(zaznam("strava", lokalni(start), sport(g("typ")), g("nazev"), km * 1000,
                              cislo(g("cas")) or cislo(g("cas2")), cislo(g("tep")), cislo(g("tep_max")),
                              cislo(g("stoupani"))))
        return out

    i = {k: idx(*v) for k, v in GARMIN.items()}
    if i["datum"] is None or i["typ"] is None:
        print(f"  ! {p.name}: neznámý formát CSV (hlavička {hlavicka[:6]}…)")
        return None
    for r in radky[1:]:
        if not r:
            continue
        g = lambda k: r[i[k]] if i[k] is not None and i[k] < len(r) else ""
        start = datetime.fromisoformat(g("datum").strip()[:19])   # Garmin CSV je už v místním čase
        typ = sport(g("typ"))
        km = cislo(g("km")) or 0
        # Plavání má Garmin v metrech, ostatní v km.
        metry = km if typ == "plavani" and km > 50 else km * 1000
        out.append(zaznam("garmin", start, typ, g("nazev"), metry, cas_s(g("cas")),
                          cislo(g("tep")), cislo(g("tep_max")), cislo(g("stoupani"))))
    return out


CTECKY = {".gpx": nacti_gpx, ".tcx": nacti_tcx, ".fit": nacti_fit, ".csv": nacti_csv}


def ctecka(p):
    pripona = "".join(p.suffixes[-2:]) if p.suffix == ".gz" else p.suffix
    return CTECKY.get(pripona.replace(".gz", "").lower())


# ---------- sloučení ----------

def klic(z):
    """Stejná aktivita z Garminu i Stravy se liší o sekundy – porovnává se na 3 minuty."""
    t = datetime.fromisoformat(z["datum"])
    return z["typ"], round(t.timestamp() / 180)


def slouc(stare, nove):
    """Doplní nové aktivity; u duplicit si nechá údaje, které ve starém záznamu chybí."""
    podle = {klic(z): z for z in stare}
    pridane = []
    for z in nove:
        k = klic(z)
        if k in podle:
            puvodni = podle[k]
            for pole, hodnota in z.items():
                if puvodni.get(pole) in (None, "", 0) and hodnota not in (None, "", 0):
                    puvodni[pole] = hodnota
        else:
            podle[k] = z
            pridane.append(z)
    return sorted(podle.values(), key=lambda z: z["datum"]), pridane


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nechat", action="store_true", help="zpracované soubory nepřesouvat")
    a = ap.parse_args()

    stare = json.loads(AKTIVITY.read_text(encoding="utf-8")) if AKTIVITY.exists() else []
    soubory = [p for p in sorted(IMPORT.glob("*")) if p.is_file() and ctecka(p)]
    if not soubory:
        print("Ve složce import/ nejsou žádné soubory (.fit, .gpx, .tcx, .csv).")
        return

    nove = []
    for p in soubory:
        try:
            z = ctecka(p)(p)
        except Exception as e:   # jeden rozbitý soubor nesmí shodit celý import
            print(f"  ! {p.name}: {e}")
            continue
        if z is None:
            continue
        print(f"  {p.name}: {len(z)} aktivit")
        nove += z
        if not a.nechat:
            (IMPORT / "zpracovano").mkdir(exist_ok=True)
            shutil.move(str(p), IMPORT / "zpracovano" / p.name)

    vse, pridane = slouc(stare, nove)
    AKTIVITY.parent.mkdir(exist_ok=True)
    AKTIVITY.write_text(json.dumps(vse, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nNových aktivit: {len(pridane)} (celkem {len(vse)})")
    for z in pridane:
        tempo = f" {z['tempo_s'] // 60}:{z['tempo_s'] % 60:02d}/km" if z.get("tempo_s") else ""
        tep = f" ♥{z['tep_prum']}/{z['tep_max']}" if z.get("tep_prum") else ""
        print(f"  {z['id']}  {z['km']} km{tempo}{tep}  {z['nazev']}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
