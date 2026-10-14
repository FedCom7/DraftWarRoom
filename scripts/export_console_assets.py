#!/usr/bin/env python3
"""Traduce data/build/console.json nei file che la pagina della console incorpora.

La console è una singola pagina HTML con i dati dentro: questo script prepara i
pezzi (pool della draft, pool esteso, bundle, storico, calendario) nella forma
che il suo JavaScript si aspetta, così il rebuild della pagina non richiede di
toccare il codice dell'interfaccia.

Uso:  python3 scripts/export_console_assets.py [--out DIR]
"""
import argparse, json, os, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "data", "build")
LEGACY_KEY = {1: "oscurus", 2: "lasers", 3: "sommo", 4: "capi"}   # chiavi usate nella UI


def rnd(v, d=1):
    return None if v is None else round(v, d)


def player_rows(pool, adv_cur, adv_prev, season):
    """Una riga per giocatore, nell'ordine di campi che il JS legge per indice."""
    rows = []
    for p in pool:
        g = p.get("gsis")
        a = adv_cur.get(g) or {}
        b = adv_prev.get(g) or {}
        pc = lambda d, k, mul=1: None if d.get(k) is None else rnd(d[k] * mul)
        rows.append([
            p["id"], p["name"], p["pos"], p["nfl"], p["rank"], p["adpEspn"], p["proj"],
            p["bye"], p["adpSd"], p["inj"], p["age"], p["exp"], p["dc"],
            b.get("gp") or 0, b.get("fpg"), pc(b, "tgtPerGame"), pc(b, "targetShare", 100),
            pc(b, "carriesPerGame"), b.get("recTd") or 0, b.get("rushTd") or 0, pc(b, "snapPct", 100),
            a.get("gp") or 0, a.get("fpg"), pc(a, "tgtPerGame"), pc(a, "targetShare", 100),
            pc(a, "carriesPerGame"), a.get("recTd") or 0, a.get("rushTd") or 0, pc(a, "snapPct", 100),
            p.get("own") or 0, p["pct"], p.get("actPrev"), p.get("act"), p.get("started"),
        ])
    return rows


def draft_rows(rows_full):
    """Il sottoinsieme che serve alla draft demo: i primi 240 per ranking ESPN."""
    out = []
    for r in sorted(rows_full, key=lambda r: r[4])[:240]:
        out.append([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                    r[10], r[11], r[12], r[13], r[14], r[15], r[16],
                    None,                       # wopr: non usato dalla draft demo
                    r[17], r[20], r[31], r[32], r[22],
                    r[23], r[25], r[28], r[29], r[30], r[21]])
    return out


def traits_as_profiles(traits, lineups):
    """I tratti dei manager con lo z-score calcolato fra i quattro della lega.

    Non è un test statistico: con quattro manager e sette draft lo z dice solo
    quanto uno si stacca dagli altri tre, ed è così che va letto.
    """
    metrics = [
        ("reach", "Anticipo sul mercato", "market", "anticipa il mercato", lambda t, l: t.get("reach")),
        ("erratic", "Imprevedibilità", "market", "sceglie in modo meno prevedibile", lambda t, l: t.get("reachSd")),
        ("firstQB", "Giro del primo QB", "structure", "aspetta di più sul QB", lambda t, l: (t.get("first") or {}).get("QB")),
        ("firstTE", "Giro del primo TE", "structure", "aspetta di più sul TE", lambda t, l: (t.get("first") or {}).get("TE")),
        ("repeat", "Ridrafta i propri (%)", "loyalty", "torna spesso sugli stessi nomi", lambda t, l: t.get("repeatRate")),
        ("streamQB", "QB diversi per stagione", "inseason", "cambia spesso QB", lambda t, l: (l.get("distinct") or {}).get("QB")),
        ("streamDST", "D/ST diverse per stagione", "inseason", "streama la difesa", lambda t, l: (l.get("distinct") or {}).get("DST")),
        ("shareRB", "Quota punti dai RB (%)", "market", "costruisce sui RB", lambda t, l: (l.get("share") or {}).get("RB")),
        ("shareWR", "Quota punti dai WR (%)", "market", "costruisce sui WR", lambda t, l: (l.get("share") or {}).get("WR")),
    ]
    ids = sorted(traits)
    meta, managers = [], {}
    for key, label, group, hi, fn in metrics:
        vals = {i: fn(traits[i], lineups.get(i, {})) for i in ids}
        good = [v for v in vals.values() if v is not None]
        if len(good) < 2:
            continue
        mean = statistics.mean(good)
        sd = statistics.pstdev(good) or 1
        meta.append({"id": key, "label": label, "g": group, "hi": hi, "tier": "signature", "q": None})
        for i in ids:
            v = vals[i]
            z = None if v is None else (v - mean) / sd
            m = managers.setdefault(LEGACY_KEY[int(i)], {"nPicks": traits[i]["picks"],
                                                         "nSeasons": len(traits[i]["seasons"]),
                                                         "traits": {}})
            if z is not None:
                m["traits"][key] = {"raw": rnd(v, 2), "z": rnd(z, 2),
                                    "tier": "signature" if abs(z) >= 1 else "differs" if abs(z) >= 0.6 else "noise"}
    return {"seasons": [str(y) for y in traits[ids[0]]["seasons"]],
            "groups": {"market": "Il mercato al draft", "structure": "Struttura del draft",
                       "loyalty": "Fedeltà", "inseason": "Durante la stagione"},
            "traits": meta, "managers": managers}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(BUILD, "console-assets"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(BUILD, "console.json"), encoding="utf-8") as f:
        d = json.load(f)
    season = d["season"]
    adv_cur = d["adv"][str(season)]
    adv_prev = d["adv"][str(season - 1)]

    rows_full = player_rows(d["pool"], adv_cur, adv_prev, season)
    rows_draft = draft_rows(rows_full)

    # mappa id ESPN -> id nflverse, serve alla scheda giocatore
    id_map = {str(p["id"]): p["gsis"] for p in d["pool"] if p.get("gsis")}

    def adv_export(src):
        out = {}
        for gsis, v in src.items():
            out[gsis] = {k: v[k] for k in ("n", "pos", "t", "gp", "fpg", "targetShare", "rushShare",
                                           "airYardsShare", "wopr", "racr", "tgtPerGame",
                                           "carriesPerGame", "ydsPerTgt", "ydsPerCarry",
                                           "epaPerGame", "catchRate", "snapPct", "stPct", "wk",
                                           "sep", "cushion", "yacOE", "aySharePct", "intendedAirYd",
                                           "ryoePerAtt", "rushEff", "timeToLos", "pctAtt8Def",
                                           "cpoe", "timeToThrow", "aggressiveness", "expComplPct",
                                           "airYdToSticks") if v.get(k) is not None}
        return out

    bundle = {
        "generatedAt": d["generatedAt"],
        "season": d["season"],
        "week": d["league"].get("week"),
        "matchupPeriod": d["league"].get("matchupPeriod"),
        "teams": d["teams"],
        "fpa25": d["fpaPrev"],
        "adv26": adv_export(adv_cur),
        "adv25": adv_export(adv_prev),
        "inj": d["inj"],
        "map": id_map,
        "drafts": {LEGACY_KEY[int(k)]: v for k, v in d["drafts"].items()},
        "dna": traits_as_profiles(d["traits"], d["lineups"]),
        "lg": d["lg"],
        "curves": d.get("curves", {}),
        "gameState": d.get("gameState", {}),
        "games": d.get("games", {}),
        "transactions": d.get("transactions", []),
        "trending": d.get("trending", {}),
        "projWeeks": d.get("projWeeks", {}),
        "weekly": d.get("weekly", {}),
        "stats": d.get("stats", {}),
        "review": d.get("review", {}),
        "reviewHist": d.get("reviewHist", {}),
        "notes": d.get("notes", {}),
        "kickers": d.get("kickers", {}),
        "defense": d.get("defense", {}),
        "frailty": d.get("frailty", {}),
        "hist": {"seasons": {y: {LEGACY_KEY[int(t)]: v for t, v in tab.items()}
                             for y, tab in d["hist"]["seasons"].items()},
                 "h2h": [{"a": LEGACY_KEY[h["a"]], "b": LEGACY_KEY[h["b"]], "aw": h["aw"], "bw": h["bw"]}
                         for h in d["hist"]["h2h"]]},
        "histWeekly": {LEGACY_KEY[int(k)]: v for k, v in d["histWeekly"].items()},
    }

    hist_cards = {}
    for tid_str, l in d["lineups"].items():
        tid = int(tid_str)
        seasons = []
        for y, used in (l.get("perSeason") or {}).items():
            seasons.append({"y": int(y), "used": used,
                            "pts": {p: round((l.get("share") or {}).get(p, 0)) for p in used}, "w1": []})
        hist_cards[tid] = {"name": (d["league"]["teams"].get(str(tid)) or {}).get("name", str(tid)),
                           "seasons": sorted(seasons, key=lambda s: s["y"]),
                           "top": l.get("top", []), "share": l.get("share", {}),
                           "distinct": l.get("distinct", {})}

    files = {
        "seed_pool.json": rows_full,
        "seed_draft.json": rows_draft,
        "bundle.json": bundle,
        "history_cards.json": hist_cards,
        "sched.json": d["sched"],
        "picks.json": d["picks"],
        "teamctx.json": {k: {"epa": v.get("epa"), "td": v.get("td"), "pass": int((v.get("pass") or 0) * 100),
                             "ydspg": v.get("ypp"), "g26": v.get("g")} for k, v in d["teams"].items()},
    }
    for name, payload in files.items():
        path = os.path.join(a.out, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
        print(f"  {name}: {os.path.getsize(path)/1024:.0f} KB")
    print(f"pronti in {a.out}")


if __name__ == "__main__":
    sys.exit(main())
