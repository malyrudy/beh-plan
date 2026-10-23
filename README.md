# Běžecká příprava

Osobní tréninkový plán na půlmaraton / maraton, který skládá a průběžně vyhodnocuje
agent v Claude Code. Stránka je statická (GitHub Pages) a jen zobrazuje `data/*.json`.

Ukázka: `index.html?demo`

## Jak to funguje

```
ty ──► Claude Code (CLAUDE.md = instrukce trenéra)
         │  ptá se na závod, cíl, formu
         │  čte exporty z import/
         ▼
       data/profil.json, plan.json, aktivity.json, hodnoceni.json
         │  git push
         ▼
       GitHub Pages ──► stránka s plánem, tempy, hodnocením
```

1. V Claude Code napiš **`chci nový plán`** – agent se zeptá na závod, datum, cíl a formu a plán vygeneruje.
2. Po bězích hoď exporty do `import/` a napiš **`zhodnoť nové běhy`**.
3. Kdykoli: „příští týden jsem na horách“, „bolí mě holeň“, „chci zrychlit cíl“ – agent upraví plán.

## Export aktivit

**Garmin Connect** (web)
- jedna aktivita: otevři aktivitu → ozubené kolo ⚙ → *Exportovat originál* (.zip s .fit – rozbal) nebo *Exportovat do GPX*
- víc najednou: *Aktivity → Všechny aktivity* → vpravo nahoře *Export CSV* (souhrny bez stopy, stačí na hodnocení)

**Strava** (web)
- jedna aktivita: aktivita → *…* → *Exportovat GPX*
- všechno: *Nastavení → Můj účet → Stáhnout nebo smazat účet → Vyžádat archiv* → z archivu stačí `activities.csv`

Soubory (.fit, .fit.gz, .gpx, .tcx, .csv) dej do `import/`. Pro .fit je potřeba `pip install -r requirements.txt`.
Do repa se ukládá jen souhrn (datum, km, čas, tep). Surové soubory s GPS stopou zůstávají lokálně.

## Lokální náhled

```
python -m http.server 8000
```
a otevři http://localhost:8000 (případně `?demo`, `?dnes=2027-02-04`).

## Zveřejnění na GitHubu

1. Na github.com vytvoř nový repozitář `beh-plan` (bez README).
2. ```
   git remote add origin https://github.com/<uzivatel>/beh-plan.git
   git push -u origin master
   ```
3. Repo → *Settings → Pages → Source: Deploy from a branch → master / (root)*.
   Stránka poběží na `https://<uzivatel>.github.io/beh-plan/`.

Repo je veřejné, takže kdo zná adresu, vidí i tepy a běhy.

## Nástroje

| | |
|---|---|
| `tools/zony.py` | tempa, tepové zóny a předpovědi časů (Daniels VDOT) |
| `tools/kontrola_planu.py` | hlídá pravidla plánu (nárůst objemu, podíl dlouhého běhu, odlehčení…) |
| `tools/import_aktivit.py` | Garmin / Strava → `data/aktivity.json` |
