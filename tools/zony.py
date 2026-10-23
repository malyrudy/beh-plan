"""Tréninková tempa, tepové zóny a předpovědi časů z jednoho referenčního výkonu.

Počítá se podle vzorců Jacka Danielse (VDOT). Agent to používá při tvorbě plánu,
aby tempa v plan.json nebyla odhadnutá „od oka“, ale konzistentní s tvým výkonem.

Použití:
    python tools/zony.py --vzdalenost 10 --cas 49:30 --maxtep 190
    python tools/zony.py --vzdalenost 21.0975 --cas 1:49:54 --maxtep 188 --json
"""
import argparse
import json
import math

ZAVODY = {"5 km": 5.0, "10 km": 10.0, "půlmaraton": 21.0975, "maraton": 42.195}

# Podíl VDOT, na kterém se dané tempo běhá (kalibrováno na Danielsovy tabulky).
TEMPA = [
    # klíč, název, podíl VDOT (pomalý konec, rychlý konec), tep v % maxima, popis
    ("lehky", "Lehký / dlouhý běh", (0.62, 0.70), (0.65, 0.78),
     "Dá se mluvit v celých větách. Většina objemu."),
    ("prah", "Tempo běh (práh)", (0.86, 0.89), (0.86, 0.91),
     "„Komfortně těžké“, 20–40 min souvisle nebo v úsecích."),
    ("intervaly", "Intervaly (VO2max)", (0.96, 0.99), (0.92, 0.97),
     "Těžké, ale technicky čisté. Úseky 2–5 min."),
]


def vo2(v):
    """Kyslíková spotřeba při rychlosti v (m/min)."""
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def podil_max(t_min):
    """Jaký podíl VO2max se udrží po dobu t minut."""
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot(dist_km, t_s):
    t_min = t_s / 60
    return vo2(dist_km * 1000 / t_min) / podil_max(t_min)


def predikce(vd, dist_km):
    """Čas (s) na vzdálenost při daném VDOT – bisekce, VDOT s časem klesá."""
    lo, hi = dist_km * 1000 / 500 * 60, dist_km * 1000 / 50 * 60
    for _ in range(100):
        mid = (lo + hi) / 2
        if vdot(dist_km, mid) > vd:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def tempo_pro_podil(vd, podil):
    """Tempo (s/km) pro zadaný podíl VDOT – inverze vzorce vo2()."""
    a, b, c = 0.000104, 0.182258, -4.60 - podil * vd
    v = (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)
    return 60000 / v


def cas2s(t):
    s = 0
    for p in t.split(":"):
        s = s * 60 + float(p)
    return s


def s2cas(s):
    s = round(s)
    h, m, x = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


def spocitej(dist_km, cas, maxtep):
    vd = vdot(dist_km, cas2s(cas))
    out = {"vdot": round(vd, 1), "predikce": {}, "tempa": []}
    for nazev, d in ZAVODY.items():
        t = predikce(vd, d)
        out["predikce"][nazev] = {"cas": s2cas(t), "tempo": s2cas(t / d)}
    # Riegel jako druhý názor – u prvního maratonu bývá Daniels/Riegel optimistický o 1–4 %.
    out["riegel_maraton"] = s2cas(cas2s(cas) * (42.195 / dist_km) ** 1.06)

    for klic, nazev, (p1, p2), (h1, h2), popis in TEMPA:
        out["tempa"].append({
            "klic": klic, "nazev": nazev,
            "od": s2cas(tempo_pro_podil(vd, p1)), "do": s2cas(tempo_pro_podil(vd, p2)),
            "tep": f"{round(h1 * maxtep)}–{round(h2 * maxtep)}" if maxtep else None,
            "popis": popis,
        })
    # Závodní tempa se berou přímo z předpovědí (přesnější než podíl VDOT).
    for nazev, h in (("půlmaraton", (0.85, 0.90)), ("maraton", (0.80, 0.86))):
        t = predikce(vd, ZAVODY[nazev]) / ZAVODY[nazev]
        out["tempa"].append({
            "klic": "hm" if nazev == "půlmaraton" else "mp",
            "nazev": f"Tempo na {nazev}",
            "od": s2cas(t + 5), "do": s2cas(t - 5),
            "tep": f"{round(h[0] * maxtep)}–{round(h[1] * maxtep)}" if maxtep else None,
            "popis": "Kontrolované, závodní úsilí.",
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vzdalenost", type=float, required=True, help="km referenčního výkonu")
    ap.add_argument("--cas", required=True, help="čas, např. 49:30 nebo 1:49:54")
    ap.add_argument("--maxtep", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = spocitej(a.vzdalenost, a.cas, a.maxtep)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    print(f"VDOT {r['vdot']}")
    print("\nPředpovědi:")
    for n, p in r["predikce"].items():
        print(f"  {n:<11} {p['cas']:>8}  ({p['tempo']}/km)")
    print(f"  maraton dle Riegela {r['riegel_maraton']}")
    print("\nTempa (min/km, pomalý – rychlý konec):")
    for t in r["tempa"]:
        tep = f"   ♥ {t['tep']}" if t["tep"] else ""
        print(f"  {t['nazev']:<22} {t['od']}–{t['do']}{tep}")


if __name__ == "__main__":
    main()
