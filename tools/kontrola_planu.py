"""Kontrola data/plan.json proti pravidlům, která si plán sám dává.

Agent ji spouští po každé změně plánu. CHYBA = plán je rozbitý (stránka by ho
zobrazila špatně), VAROVÁNÍ = porušené tréninkové pravidlo – buď opravit,
nebo v poznámce týdne vysvětlit, proč je výjimka v pořádku.

Použití:
    python tools/kontrola_planu.py            # data/
    python tools/kontrola_planu.py demo       # jiná složka s daty
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

DNY = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
TYPY = {"lehky", "dlouhy", "kvalita", "zavod", "posilovna", "plavani", "kolo", "volno"}
BEZECKE = {"lehky", "dlouhy", "kvalita", "zavod"}

MAX_NARUST = 0.10          # týdenní nárůst objemu
TOLERANCE_KM = 3           # u malých objemů je 10 % pár set metrů – drobné skoky nevadí
MAX_PODIL_DLOUHEHO = 0.40  # dlouhý běh / týdenní objem
MAX_BEZ_ODLEHCENI = 3      # po kolika týdnech v řadě má přijít odlehčení


def main():
    slozka = Path(__file__).resolve().parent.parent / (sys.argv[1] if len(sys.argv) > 1 else "data")
    plan = json.loads((slozka / "plan.json").read_text(encoding="utf-8"))
    profil = json.loads((slozka / "profil.json").read_text(encoding="utf-8"))
    chyby, varovani = [], []

    zavod = date.fromisoformat(profil["zavod"]["datum"])
    start = date.fromisoformat(profil["start_pripravy"])
    tydny = plan["tydny"]

    if start.weekday() != 0:
        chyby.append(f"start_pripravy {start} není pondělí")

    # --- struktura ---
    for i, t in enumerate(tydny):
        od = date.fromisoformat(t["od"])
        if t.get("cislo") != i + 1:
            chyby.append(f"týden na pozici {i + 1} má číslo {t.get('cislo')}")
        if od != start + timedelta(weeks=i):
            chyby.append(f"T{i + 1}: začíná {od}, čekal jsem {start + timedelta(weeks=i)}")
        if [d["den"] for d in t["dny"]] != DNY:
            chyby.append(f"T{i + 1}: dny musí být přesně Po–Ne v tomto pořadí")
        for d in t["dny"]:
            if d["typ"] not in TYPY:
                chyby.append(f"T{i + 1} {d['den']}: neznámý typ '{d['typ']}'")
            if d["typ"] in BEZECKE and not d.get("km"):
                chyby.append(f"T{i + 1} {d['den']}: běh bez km")

    posledni = date.fromisoformat(tydny[-1]["od"])
    if not posledni <= zavod <= posledni + timedelta(days=6):
        chyby.append(f"závod {zavod} neleží v posledním týdnu plánu ({posledni})")
    else:
        den_zavodu = tydny[-1]["dny"][(zavod - posledni).days]
        if den_zavodu["typ"] != "zavod":
            chyby.append(f"v den závodu ({den_zavodu['den']}) není typ 'zavod'")

    faze = {f["nazev"] for f in plan.get("faze", [])}
    for t in tydny:
        if t["faze"] not in faze:
            chyby.append(f"T{t['cislo']}: fáze '{t['faze']}' není v seznamu fází")

    # --- tréninková pravidla ---
    def objem(t):
        # závod se do objemu nepočítá, jinak by poslední týden vypadal jako skok
        return sum(d.get("km", 0) for d in t["dny"] if d["typ"] in BEZECKE - {"zavod"})

    def dlouhy(t):
        return max((d["km"] for d in t["dny"] if d["typ"] == "dlouhy"), default=0)

    vrchol = max(objem(t) for t in tydny)
    bez_odlehceni = 0
    for i, t in enumerate(tydny):
        km, dl = objem(t), dlouhy(t)
        tapering = t["faze"].lower().startswith("taper")
        vyjimka = " (poznámka vysvětluje?)" if t.get("poznamka") else ""

        if dl and km and dl / km > MAX_PODIL_DLOUHEHO and km >= 25:
            varovani.append(f"T{t['cislo']}: dlouhý běh {dl} km = {dl / km:.0%} z {km:g} km "
                            f"(max {MAX_PODIL_DLOUHEHO:.0%}) – přesuň objem do týdne")

        if i:
            # srovnává se s posledním plnohodnotným týdnem, ne s odlehčovacím
            ref = next((objem(p) for p in reversed(tydny[:i]) if not p.get("odlehceni")), objem(tydny[i - 1]))
            if km > ref * (1 + MAX_NARUST) and km - ref > TOLERANCE_KM:
                varovani.append(f"T{t['cislo']}: {ref:g} → {km:g} km (+{km / ref - 1:.0%}){vyjimka}")
            prev_dl = dlouhy(tydny[i - 1])
            if dl and prev_dl and dl - prev_dl > 3:
                varovani.append(f"T{t['cislo']}: dlouhý běh {prev_dl} → {dl} km (skok > 3 km){vyjimka}")

        bez_odlehceni = 0 if t.get("odlehceni") or tapering else bez_odlehceni + 1
        if bez_odlehceni > MAX_BEZ_ODLEHCENI:
            varovani.append(f"T{t['cislo']}: {bez_odlehceni}. týden v řadě bez odlehčení")

        kvalita = sum(d["typ"] == "kvalita" for d in t["dny"])
        if kvalita > 2:
            varovani.append(f"T{t['cislo']}: {kvalita} kvalitní tréninky – víc než 2 týdně je moc")

    # --- Den D ---
    den_d = plan.get("den_d", {})
    if den_d.get("tempo") and profil["zavod"].get("cil"):
        def s(x):
            v = 0
            for p in x.split(":"):
                v = v * 60 + int(p)
            return v
        cil = s(profil["zavod"]["cil"])
        dle_tempa = s(den_d["tempo"]) * profil["zavod"]["vzdalenost_km"]
        if abs(dle_tempa - cil) > 120:
            varovani.append(f"Den D: tempo {den_d['tempo']} dává {int(dle_tempa // 3600)}:{int(dle_tempa % 3600 // 60):02d}, "
                            f"cíl je {profil['zavod']['cil']}")

    print(f"Plán: {len(tydny)} týdnů, {start} → {zavod}, vrchol {vrchol:g} km/týden")
    for c in chyby:
        print("CHYBA     ", c)
    for v in varovani:
        print("VAROVÁNÍ  ", v)
    if not chyby and not varovani:
        print("OK – plán drží všechna pravidla.")
    sys.exit(1 if chyby else 0)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
