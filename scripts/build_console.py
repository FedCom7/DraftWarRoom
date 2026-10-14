#!/usr/bin/env python3
"""Costruisce data/build/console.json, il bundle che alimenta la console.

Tutto viene ricalcolato qui: nessun file derivato di altri progetti entra nel
risultato. Gli ingressi sono solo data/raw/ (scaricato da fetch_sources.py) e
data/vendor/ (la copia una tantum dello storico 2019-2025).

Uso:  python3 scripts/build_console.py [--season 2026]
"""
import argparse, csv, functools, glob, json, os, re, statistics, sys
from collections import defaultdict

import merge_stats as MS
import season_review as SR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
VENDOR = os.path.join(ROOT, "data", "vendor")
BUILD = os.path.join(ROOT, "data", "build")

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
TEAM = {0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
        9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN",
        17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
        25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}
# nflverse usa sigle diverse da ESPN per tre squadre
ABBR = {"LA": "LAR", "WAS": "WSH", "JAC": "JAX", "SD": "LAC", "OAK": "LV", "STL": "LAR"}
INJ = {"ACTIVE": "", "NORMAL": "", "QUESTIONABLE": "Q", "OUT": "O", "INJURY_RESERVE": "IR",
       "DOUBTFUL": "D", "SUSPENSION": "SUS", "PROBABLE": "P"}
# i manager: chiave storica (NFL.com) -> id squadra ESPN 2026
MANAGERS = {"riccardo97com": 1, "lasers": 2, "FedCom": 3, "Capi dei Pianeti": 4}
MY_TEAM = 3

ab = lambda t: ABBR.get(t, t)
norm = lambda s: re.sub(r"[^a-z]", "", re.sub(r"\s(jr|sr|iii|ii|iv)\.?$", "", (s or "").lower()))
nkey = lambda n, p: re.sub(r"[^a-z ]", "", (n or "").lower()).strip() + "|" + p


def jload(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return json.load(f)


def rows(path):
    if path.endswith(".gz"):
        import gzip
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(r, k):
    v = (r or {}).get(k)
    if v in (None, "", "NA"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def rnd(v, d=1):
    return None if v is None else round(v, d)


def pctl(vals, p):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    i = (len(v) - 1) * p
    lo, hi = int(i), min(int(i) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


# ---------------------------------------------------------------- crosswalk
def crosswalk():
    """espn_id -> {gsis, sleeper, pfr}, dal database aperto di DynastyProcess."""
    out = {}
    for r in rows(os.path.join(RAW, "dp_playerids.csv")):
        e = r.get("espn_id")
        if e and e != "NA":
            out[e] = {k: (r.get(f"{k}_id") if r.get(f"{k}_id") not in ("NA", "") else None)
                      for k in ("gsis", "sleeper", "pfr")}
    return out


# ------------------------------------------------------- squadre NFL e difese
def nfl_context(season):
    """Attacco, difesa, calendario e bye di ogni squadra NFL."""
    pro = jload(RAW, "espn_proteams.json")["settings"]["proTeams"]
    sched, teams = {}, {}
    for t in pro:
        if t["id"] == 0:
            continue
        a = t["abbrev"].upper()
        opp = {}
        for wk, games in (t.get("proGamesByScoringPeriod") or {}).items():
            for g in games:
                other = g["awayProTeamId"] if g["homeProTeamId"] == t["id"] else g["homeProTeamId"]
                opp[int(wk)] = ("@" if g["awayProTeamId"] == t["id"] else "") + TEAM.get(other, "?")
        sched[a] = {"bye": t.get("byeWeek"), "opp": opp}

    # punti segnati e subiti: dai risultati reali delle partite
    pf, pa, gp = defaultdict(float), defaultdict(float), defaultdict(int)
    for g in rows(os.path.join(RAW, "nflverse", "games.csv")):
        if int(g["season"] or 0) != season or (g.get("game_type") or "REG") != "REG":
            continue
        hs, as_ = num(g, "home_score"), num(g, "away_score")
        if hs is None or as_ is None:
            continue
        h, a = ab(g["home_team"]), ab(g["away_team"])
        pf[h] += hs; pa[h] += as_; gp[h] += 1
        pf[a] += as_; pa[a] += hs; gp[a] += 1

    def team_rows(y):
        return {ab(r["team"]): r for r in rows(os.path.join(RAW, "nflverse", f"stats_team_reg_{y}.csv"))
                if (r.get("season_type") or "REG") == "REG"}

    cur, prv = team_rows(season), team_rows(season - 1)
    for a, s in sched.items():
        c, p = cur.get(a), prv.get(a)
        g_cur = num(c, "games") or 0
        w = min(0.5, g_cur * 0.22)          # con due giornate il 2026 pesa poco
        def blend(key, per_game=True):
            def val(r):
                if not r:
                    return 0.0
                g = num(r, "games") or 1
                return (num(r, key) or 0) / (g if per_game else 1)
            return (1 - w) * val(p) + w * val(c)
        att = blend("attempts"); car = blend("carries")
        teams[a] = {
            "g": int(g_cur),
            "ppg": rnd(pf[a] / gp[a], 0) if gp[a] else None,
            "papg": rnd(pa[a] / gp[a], 0) if gp[a] else None,
            "pass": rnd(att / (att + car), 2) if (att + car) else None,
            "ypp": rnd(blend("passing_yards") + blend("rushing_yards"), 0),
            "epa": rnd(blend("passing_epa") + blend("rushing_epa"), 2),
            "td": rnd(blend("passing_tds") + blend("rushing_tds"), 2),
            "bye": s["bye"], "sch": [{"w": w_, "o": o} for w_, o in sorted(s["opp"].items())],
        }
    # rank d'attacco e di difesa sui punti
    for key, field, rev in (("oRank", "ppg", True), ("dRank", "papg", False)):
        order = sorted([a for a in teams if teams[a][field] is not None],
                       key=lambda a: teams[a][field], reverse=rev)
        for i, a in enumerate(order):
            teams[a][key] = i + 1
    return sched, teams


def fantasy_allowed(season):
    """Punti PPR concessi da ogni difesa per reparto, come rapporto sulla media."""
    per_game = defaultdict(lambda: defaultdict(float))
    for r in rows(os.path.join(RAW, "nflverse", f"stats_player_week_{season}.csv")):
        pos, opp = r.get("position"), r.get("opponent_team")
        if pos not in ("QB", "RB", "WR", "TE") or not opp:
            continue
        per_game[(ab(opp), int(r["week"]))][pos] += num(r, "fantasy_points_ppr") or 0
    agg = defaultdict(lambda: defaultdict(list))
    for (opp, _), d in per_game.items():
        for pos, v in d.items():
            agg[opp][pos].append(v)
    league = {}
    for pos in ("QB", "RB", "WR", "TE"):
        vals = [statistics.mean(v[pos]) for v in agg.values() if v.get(pos)]
        league[pos] = statistics.mean(vals) if vals else 1
    out = {}
    for opp, v in agg.items():
        out[opp] = {pos: {"v": rnd(statistics.mean(v[pos]), 2),
                          "r": None} for pos in ("QB", "RB", "WR", "TE") if v.get(pos)}
    for pos in ("QB", "RB", "WR", "TE"):
        order = sorted([t for t in out if pos in out[t]], key=lambda t: out[t][pos]["v"])
        for i, t in enumerate(order):                 # rank 1 = difesa più dura
            out[t][pos]["r"] = i + 1
            out[t][pos]["ratio"] = rnd(out[t][pos]["v"] / league[pos], 3)
    return out, {k: rnd(v, 1) for k, v in league.items()}


# -------------------------------------------------------- metriche giocatore
def advanced(season, ids_by_gsis):
    """Utilizzo, quote di reparto, snap e tabellino settimana per settimana."""
    out = {}
    for r in rows(os.path.join(RAW, "nflverse", f"stats_player_reg_{season}.csv")):
        g = num(r, "games") or 0
        if not g or r["player_id"] not in ids_by_gsis:
            continue
        rec_tgt = num(r, "targets") or 0
        out[r["player_id"]] = {
            "n": r.get("player_display_name") or r.get("player_name"),
            "pos": r.get("position"), "t": ab(r.get("recent_team") or ""),
            "gp": int(g),
            "fpg": rnd((num(r, "fantasy_points_ppr") or 0) / g),
            "targetShare": rnd(num(r, "target_share") or 0, 3),
            "airYardsShare": rnd(num(r, "air_yards_share") or 0, 3),
            "wopr": rnd(num(r, "wopr") or 0, 3),
            "racr": rnd(num(r, "racr"), 2),
            "tgtPerGame": rnd(rec_tgt / g),
            "carriesPerGame": rnd((num(r, "carries") or 0) / g),
            "recTd": int(num(r, "receiving_tds") or 0),
            "rushTd": int(num(r, "rushing_tds") or 0),
            "ydsPerTgt": rnd((num(r, "receiving_yards") or 0) / rec_tgt) if rec_tgt else None,
            "ydsPerCarry": rnd((num(r, "rushing_yards") or 0) / (num(r, "carries") or 1)) if num(r, "carries") else None,
            "epaPerGame": rnd(((num(r, "receiving_epa") or 0) + (num(r, "rushing_epa") or 0) +
                               (num(r, "passing_epa") or 0)) / g, 2),
            "catchRate": rnd((num(r, "receptions") or 0) / rec_tgt, 2) if rec_tgt else None,
        }
    # quota corse della squadra: il dato non esiste nel file, si calcola
    team_car = defaultdict(float)
    for gsis, p in out.items():
        team_car[p["t"]] += (p["carriesPerGame"] or 0) * p["gp"]
    for gsis, p in out.items():
        tot = team_car[p["t"]]
        p["rushShare"] = rnd(((p["carriesPerGame"] or 0) * p["gp"]) / tot, 3) if tot else None
    # snap%
    snaps, st_snaps = defaultdict(list), defaultdict(list)
    for r in rows(os.path.join(RAW, "nflverse", f"snap_counts_{season}.csv")):
        v = num(r, "offense_pct")
        if v is not None:
            snaps[r.get("pfr_player_id")].append(v)
        sv = num(r, "st_pct")
        if sv is not None:
            st_snaps[r.get("pfr_player_id")].append(sv)
    # tabellino settimanale
    weekly = defaultdict(dict)
    for r in rows(os.path.join(RAW, "nflverse", f"stats_player_week_{season}.csv")):
        if r["player_id"] in out:
            weekly[r["player_id"]][int(r["week"])] = rnd(num(r, "fantasy_points_ppr") or 0)
    for gsis, p in out.items():
        pfr = (ids_by_gsis.get(gsis) or {}).get("pfr")
        p["snapPct"] = rnd(statistics.mean(snaps[pfr]), 3) if pfr and snaps.get(pfr) else None
        p["stPct"] = rnd(statistics.mean(st_snaps[pfr]), 3) if pfr and st_snaps.get(pfr) else None
        wk = weekly.get(gsis) or {}
        p["wk"] = [wk[k] for k in sorted(wk)]
    return out


def nextgen(season):
    """Next Gen Stats di stagione (week 0 = aggregato), per giocatore gsis.

    Separazione, cushion e YAC oltre l'atteso per i ricevitori; RYOE ed
    efficienza per i corridori; CPOE, tempo di lancio e aggressività per i QB.
    """
    out = defaultdict(dict)
    want = {
        "receiving": {"avg_separation": "sep", "avg_cushion": "cushion",
                      "avg_yac_above_expectation": "yacOE",
                      "percent_share_of_intended_air_yards": "aySharePct",
                      "avg_intended_air_yards": "intendedAirYd"},
        "rushing": {"rush_yards_over_expected_per_att": "ryoePerAtt", "efficiency": "rushEff",
                    "avg_time_to_los": "timeToLos",
                    "percent_attempts_gte_eight_defenders": "pctAtt8Def"},
        "passing": {"completion_percentage_above_expectation": "cpoe",
                    "avg_time_to_throw": "timeToThrow", "aggressiveness": "aggressiveness",
                    "expected_completion_percentage": "expComplPct",
                    "avg_air_yards_to_sticks": "airYdToSticks"},
    }
    for kind, cols in want.items():
        path = os.path.join(RAW, "nflverse", f"ngs_{kind}.csv.gz")
        if not os.path.exists(path):
            continue
        for r in rows(path):
            if int(r.get("season") or 0) != season or int(r.get("week") or -1) != 0:
                continue                       # week 0 = riga di stagione
            gsis = r.get("player_gsis_id")
            if not gsis:
                continue
            for src, dst in cols.items():
                v = num(r, src)
                if v is not None:
                    out[gsis][dst] = rnd(v, 2)
    return out


def week_games(season, week):
    """Partite della giornata e delle tre successive: quote, meteo, campo, orario.

    Il totale implicito (quanto ci si aspetta che segni una squadra) è il
    segnale più diretto che il mercato dà al fantasy: totale/2 meno mezzo spread.
    """
    out = defaultdict(dict)
    for wk in range(week, week + 4):
        path = os.path.join(RAW, "espn_scoreboard.json" if wk == week else f"espn_scoreboard_{wk}.json")
        if not os.path.exists(path):
            continue
        for e in (jload(path).get("events") or []):
            comp = (e.get("competitions") or [{}])[0]
            odds = (comp.get("odds") or [{}])[0] if comp.get("odds") else {}
            total = odds.get("overUnder")
            venue = comp.get("venue") or {}
            wx = e.get("weather") or {}
            comps = comp.get("competitors") or []
            for c in comps:
                t = ab(((c.get("team") or {}).get("abbreviation")) or "")
                other = next((ab(((x.get("team") or {}).get("abbreviation")) or "") for x in comps if x is not c), None)
                if not t:
                    continue
                fav = (odds.get("details") or "").split(" ")[0] if odds.get("details") else None
                spread = odds.get("spread")
                mine = None
                if spread is not None and fav:
                    mine = spread if fav == t else -spread     # spread dal punto di vista della squadra
                implied = None
                if total is not None and mine is not None:
                    implied = round(total / 2 - mine / 2, 1)
                out[t][str(wk)] = {
                    "opp": other, "home": c.get("homeAway") == "home", "kick": e.get("date"),
                    "total": total, "spread": mine, "implied": implied,
                    "venue": venue.get("fullName"), "indoor": venue.get("indoor"),
                    "temp": wx.get("temperature"), "sky": wx.get("displayValue") or wx.get("conditionId"),
                }
    return {k: v for k, v in out.items()}


# id delle statistiche nel formato ESPN
ESPN_STAT = {"patt": 0, "cmp": 1, "pyds": 3, "ptd": 4, "int": 20,
             "ratt": 23, "ryds": 24, "rtd": 25,
             "rec": 53, "rec2": 41, "recyds": 42, "rectd": 43, "tgt": 58}


@functools.lru_cache(maxsize=None)
def red_zone(season, week_now):
    """Bersagli e portate dentro le 20 yard, giornata per giornata.

    Dal play-by-play: nflverse per le giornate concluse, ESPN per quella in corso
    (le sue giocate portano `yardsToEndzone`).
    """
    rz = defaultdict(lambda: defaultdict(lambda: {"tgt": 0, "car": 0, "in10": 0}))
    path = os.path.join(RAW, "nflverse", f"pbp_{season}.csv.gz")
    gsis_seen = set()
    if os.path.exists(path):
        for r in rows(path):
            y = num(r, "yardline_100")
            if y is None or y > 20:
                continue
            wk = str(int(num(r, "week") or 0))
            for key, pid in (("tgt", r.get("receiver_player_id")), ("car", r.get("rusher_player_id"))):
                if not pid:
                    continue
                rz[pid][wk][key] += 1
                if y <= 10:
                    rz[pid][wk]["in10"] += 1
                gsis_seen.add(pid)
    # giornata in corso: le giocate ESPN, con gli id già in formato ESPN
    espn_rz = defaultdict(lambda: {"tgt": 0, "car": 0, "in10": 0})
    folder = os.path.join(RAW, "espn_plays")
    if os.path.isdir(folder):
        for f in glob.glob(os.path.join(folder, "*.json")):
            for pl in (jload(f).get("items") or []):
                dist = ((pl.get("start") or {}).get("yardsToEndzone"))
                if dist is None or dist > 20:
                    continue
                for part in pl.get("participants") or []:
                    typ = part.get("type")
                    if typ not in ("receiver", "rusher"):
                        continue
                    m = re.search(r"/athletes/(\d+)", ((part.get("athlete") or {}).get("$ref") or ""))
                    if not m:
                        continue
                    e = espn_rz[int(m.group(1))]
                    e["tgt" if typ == "receiver" else "car"] += 1
                    if dist <= 10:
                        e["in10"] += 1
    return rz, espn_rz


def lineups_by_week(week_now):
    """Formazioni e punti di ogni giornata, per poter tornare indietro."""
    out = {}
    for wk in range(1, week_now + 1):
        path = os.path.join(RAW, f"espn_box_{wk}.json")
        if not os.path.exists(path):
            continue
        teams = {}
        for m in (jload(path).get("schedule") or []):
            if m.get("matchupPeriodId") != wk:
                continue
            for side in ("home", "away"):
                t = m.get(side) or {}
                tid = t.get("teamId")
                roster = (t.get("rosterForCurrentScoringPeriod") or t.get("rosterForMatchupPeriod") or {})
                rows_ = []
                for e in (roster.get("entries") or []):
                    pp = e.get("playerPoolEntry") or {}
                    pl = pp.get("player") or {}
                    stats = pl.get("stats") or []
                    proj = next((s_.get("appliedTotal") for s_ in stats
                                 if s_.get("scoringPeriodId") == wk and s_.get("statSourceId") == 1), None)
                    rows_.append({"id": e["playerId"],
                                  "slot": SLOT.get(e.get("lineupSlotId"), "?"),
                                  "starter": e.get("lineupSlotId") not in (20, 21),
                                  "inj": INJ.get(pl.get("injuryStatus") or "ACTIVE", "?"),
                                  "act": rnd(pp.get("appliedStatTotal")), "proj": rnd(proj)})
                order = {"QB": 0, "RB": 1, "RB/WR": 2, "FLEX": 2, "WR": 3, "TE": 4,
                         "D/ST": 5, "K": 6, "BE": 7, "IR": 8}
                if tid is not None and rows_:
                    teams[str(tid)] = sorted(rows_, key=lambda r: (order.get(r["slot"], 9), -(r["proj"] or 0)))
        if teams:
            out[str(wk)] = teams
    return out


def apply_merged(stats, pool, adv_cur, weekly, kick_cur, dst_cur, gsis_to_espn):
    """Riporta le statistiche unite (ESPN → Sleeper → nflverse) nelle strutture
    che le pagine già leggono, così ogni numero segue la stessa priorità."""
    I = MS.IDX
    by_id = {p["id"]: p for p in pool}
    # utilizzo di stagione
    for p in pool:
        o = MS.adv_overrides(stats, p["id"])
        if not o:
            continue
        g = p.get("gsis")
        if not g:
            continue
        adv_cur.setdefault(g, {"n": p["name"], "pos": p["pos"], "t": p["nfl"]}).update(o)
    team_car = defaultdict(float)                 # quota corse ricalcolata sui totali nuovi
    for a in adv_cur.values():
        team_car[a.get("t")] += (a.get("carriesPerGame") or 0) * (a.get("gp") or 0)
    for a in adv_cur.values():
        tot = team_car[a.get("t")]
        a["rushShare"] = rnd(((a.get("carriesPerGame") or 0) * (a.get("gp") or 0)) / tot, 3) if tot else None
    # tabellino giornata per giornata
    cols = {3: "tgt", 4: "rec", 5: "recYds", 6: "recTd", 7: "rushAtt", 8: "rushYds", 9: "rushTd",
            10: "passYds", 11: "passTd", 12: "passInt", 15: "recRz", 16: "rushRz"}
    for pid, rows_ in weekly.items():
        sp = stats["players"].get(pid)
        if not sp:
            continue
        for row in rows_:
            w = sp["w"].get(str(row[0]))
            if not w:
                continue
            for i, k in cols.items():
                if w["v"][I[k]] is not None:
                    row[i] = w["v"][I[k]]
            if w["v"][I["snapPct"]] is not None:
                row[13] = rnd(w["v"][I["snapPct"]] * 100)
            if w["v"][I["tgtShare"]] is not None:
                row[14] = rnd(w["v"][I["tgtShare"]] * 100)
    # kicker e difese
    for p in pool:
        sp = stats["players"].get(str(p["id"]))
        if not sp or not sp["gp"]:
            continue
        v = lambda k: sp["season"][I[k]]
        if p["pos"] == "K" and p.get("gsis"):
            att, made = v("fga") or 0, v("fgm") or 0
            kick_cur[p["gsis"]] = {
                "fgMade": int(made), "fgAtt": int(att),
                "fgPct": rnd(made / att * 100) if att else None,
                "long": int(v("fgLng") or 0),
                "from40": int((v("fgm40") or 0) + (v("fgm50") or 0)),
                "patMade": int(v("xpm") or 0), "patAtt": int(v("xpa") or 0), "gp": sp["gp"]}
        elif p["pos"] == "DST" and p["id"] < 0:
            team = TEAM.get(-p["id"] - 16000)
            if team:
                g = sp["gp"]
                dst_cur[team] = {"sacks": rnd((v("dSack") or 0) / g, 2), "int": rnd((v("dInt") or 0) / g, 2),
                                 "ff": rnd((v("dFf") or 0) / g, 2), "td": int(v("dTd") or 0), "gp": g,
                                 "fumRec": int(v("dFumRec") or 0), "pa": rnd((v("dPa") or 0) / g),
                                 "ya": rnd((v("dYa") or 0) / g)}


def weekly_lines(season, week_now, ids, sched):
    """Il tabellino di ogni giornata: punti e statistiche vere, non solo il totale."""
    # ESPN spezza le statistiche fra più payload: si uniscono tutti
    pool = {}
    sources = ([os.path.join(RAW, "espn_players.json")]
               + sorted(glob.glob(os.path.join(RAW, "espn_week_*.json")))
               + sorted(glob.glob(os.path.join(RAW, "espn_proj_w*.json"))))
    for path in sources:
        for e in (jload(path).get("players") or []):
            p_ = e.get("player") or {}
            cur = pool.setdefault(p_["id"], {"player": {**p_, "stats": []}})
            seen = {(s_.get("scoringPeriodId"), s_.get("statSourceId")) for s_ in cur["player"]["stats"]}
            for s_ in p_.get("stats", []):
                if (s_.get("scoringPeriodId"), s_.get("statSourceId")) not in seen:
                    cur["player"]["stats"].append(s_)
    pool = list(pool.values())
    # utilizzo settimanale da nflverse (quota target) e snap
    tsh, snap = defaultdict(dict), defaultdict(dict)
    wpath = os.path.join(RAW, "nflverse", f"stats_player_week_{season}.csv")
    if os.path.exists(wpath):
        for r in rows(wpath):
            v = num(r, "target_share")
            if v is not None:
                tsh[r["player_id"]][str(int(num(r, "week") or 0))] = rnd(v * 100)
    spath = os.path.join(RAW, "nflverse", f"snap_counts_{season}.csv")
    if os.path.exists(spath):
        for r in rows(spath):
            v = num(r, "offense_pct")
            if v is not None:
                snap[r.get("pfr_player_id")][str(int(num(r, "week") or 0))] = rnd(v * 100)
    rz_gsis, rz_espn = red_zone(season, week_now)
    nfl_week = defaultdict(dict)
    if os.path.exists(wpath):
        for r in rows(wpath):
            wk = str(int(num(r, "week") or 0))
            nfl_week[r["player_id"]][wk] = r

    out = {}
    for e in pool:
        p = e.get("player") or {}
        pid = p.get("id")
        x = ids.get(str(pid)) or {}
        gsis, pfr = x.get("gsis"), x.get("pfr")
        team = TEAM.get(p.get("proTeamId"), "FA")
        weeks = []
        for st in p.get("stats", []):
            if st.get("statSourceId") != 0 or not st.get("scoringPeriodId"):
                continue
            wk = st["scoringPeriodId"]
            raw = {int(k): v for k, v in (st.get("stats") or {}).items()}
            g = lambda key: raw.get(ESPN_STAT[key])
            rec = g("rec") if g("rec") is not None else g("rec2")
            z = (rz_gsis.get(gsis, {}) or {}).get(str(wk)) or (rz_espn.get(pid) if wk == week_now else None) or {}
            opp = ((sched.get(team) or {}).get("opp") or {}).get(wk)
            nf = (nfl_week.get(gsis) or {}).get(str(wk)) or {}
            fill = lambda v, col: v if v is not None else num(nf, col)
            weeks.append([
                wk, rnd(st.get("appliedTotal")), opp,
                fill(g("tgt"), "targets"), fill(rec, "receptions"),
                fill(g("recyds"), "receiving_yards"), fill(g("rectd"), "receiving_tds"),
                fill(g("ratt"), "carries"), fill(g("ryds"), "rushing_yards"), fill(g("rtd"), "rushing_tds"),
                fill(g("pyds"), "passing_yards"), fill(g("ptd"), "passing_tds"), fill(g("int"), "passing_interceptions"),
                (snap.get(pfr) or {}).get(str(wk)),
                (tsh.get(gsis) or {}).get(str(wk)),
                z.get("tgt") or None, z.get("car") or None, z.get("in10") or None,
            ])
        if weeks:
            out[str(pid)] = sorted(weeks, key=lambda w: w[0])
    return out


def weekly_projections(week):
    """Proiezioni ufficiali ESPN per le prossime giornate, una richiesta per settimana."""
    out = defaultdict(dict)
    for wk in range(week, week + 4):
        path = os.path.join(RAW, f"espn_proj_w{wk}.json")
        if not os.path.exists(path):
            continue
        for e in (jload(path).get("players") or []):
            p = e.get("player") or {}
            v = next((s_.get("appliedTotal") for s_ in p.get("stats", [])
                      if s_.get("scoringPeriodId") == wk and s_.get("statSourceId") == 1), None)
            if v is not None:
                out[str(p["id"])][str(wk)] = rnd(v)
    return out


def transactions(season):
    """Movimenti della lega andati a buon fine: waiver, svincolati e scambi.

    ESPN li dà una giornata alla volta (espn_tx_{giornata}.json). Le scelte del
    draft, i cambi di formazione e i waiver falliti non sono movimenti di mercato.
    """
    out, seen = [], set()
    for path in sorted(glob.glob(os.path.join(RAW, "espn_tx_*.json"))):
        for t in (jload(path).get("transactions") or []):
            if t.get("status") != "EXECUTED" or t.get("type") not in ("WAIVER", "FREEAGENT", "TRADE_ACCEPT", "TRADE"):
                continue
            if t.get("id") in seen:
                continue
            seen.add(t.get("id"))
            adds = [i["playerId"] for i in t.get("items", []) if i.get("type") == "ADD"]
            drops = [i["playerId"] for i in t.get("items", []) if i.get("type") == "DROP"]
            trade = [{"p": i["playerId"], "from": i.get("fromTeamId"), "to": i.get("toTeamId")}
                     for i in t.get("items", []) if i.get("type") == "TRADE"]
            if not adds and not drops and not trade:
                continue
            out.append({"team": t.get("teamId"), "date": t.get("proposedDate"), "week": t.get("scoringPeriodId"),
                        "type": t.get("type"), "bid": t.get("bidAmount") or 0, "add": adds, "drop": drops,
                        "trade": trade})
    out.sort(key=lambda x: x["date"] or 0, reverse=True)
    return out


def trending(ids_by_sleeper):
    """Aggiunte e rilasci nelle ultime 24 ore su Sleeper, tradotti in id ESPN."""
    out = {}
    for kind in ("add", "drop"):
        path = os.path.join(RAW, f"sleeper_trending_{kind}.json")
        if not os.path.exists(path):
            continue
        for row in jload(path):
            espn = ids_by_sleeper.get(str(row.get("player_id")))
            if espn:
                out.setdefault(str(espn), {})[kind] = row.get("count")
    return out


def play_context(event_id):
    """Per ogni giocata: il drive da cui nasce e la probabilità di vittoria in quel momento."""
    drives, probs = {}, {}
    dpath = os.path.join(RAW, "espn_drives", f"{event_id}.json")
    if os.path.exists(dpath):
        for d in (jload(dpath).get("items") or []):
            start = (d.get("start") or {})
            info = {"desc": d.get("description"), "from": (start.get("text") or None),
                    "res": d.get("shortDisplayResult") or d.get("result")}
            for pl in ((d.get("plays") or {}).get("items") or []):
                probs.setdefault("_", None)
                drives[str(pl.get("id"))] = info
            drives[str(d.get("id"))] = info      # riserva: id del drive
    ppath = os.path.join(RAW, "espn_probabilities", f"{event_id}.json")
    if os.path.exists(ppath):
        for it in (jload(ppath).get("items") or []):
            ref = ((it.get("play") or {}).get("$ref") or "")
            m = re.search(r"/plays/(\d+)", ref)
            key = m.group(1) if m else str(it.get("sequenceNumber") or "")
            if key:
                probs[key] = {"home": it.get("homeWinPercentage"), "away": it.get("awayWinPercentage")}
    return drives, probs


def espn_curves(week):
    """Curve dei punti dal play-by-play ESPN: è l'unica fonte viva a partita in corso.

    Ogni giocata porta il ruolo di chi l'ha fatta (passer, receiver, rusher…) e
    l'id ESPN del giocatore, quindi non serve nessuna tabella di conversione.
    Il punteggio applicato è quello della lega.
    """
    folder = os.path.join(RAW, "espn_plays")
    if not os.path.isdir(folder):
        return {}, {}
    events = defaultdict(list)
    meta = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        event_id = os.path.splitext(os.path.basename(path))[0]
        drives, probs = play_context(event_id)
        with open(path, encoding="utf-8") as f:
            items = (json.load(f) or {}).get("items") or []
        for pl in items:
            per = ((pl.get("period") or {}).get("number")) or 1
            clock = (pl.get("clock") or {}).get("value")
            if clock is None:
                continue
            elapsed = int((per - 1) * 900 + (900 - clock))
            parts = {}
            for part in pl.get("participants") or []:
                m = re.search(r"/athletes/(\d+)", ((part.get("athlete") or {}).get("$ref") or ""))
                if m:
                    parts.setdefault(part.get("type"), []).append(int(m.group(1)))
            if not parts:
                continue
            yards = pl.get("statYardage") or 0
            text = pl.get("text") or ""
            td = bool(pl.get("scoringPlay")) and (pl.get("scoringType") or {}).get("abbreviation") == "TD"
            add = defaultdict(float)
            rec = (parts.get("receiver") or [None])[0]
            rush = (parts.get("rusher") or [None])[0]
            pas = (parts.get("passer") or [None])[0]
            completed = rec is not None and "INTERCEPT" not in text.upper() and "incomplete" not in text.lower()
            if completed:
                add[rec] += 1 + yards * 0.1
                if pas is not None:
                    add[pas] += yards * 0.04
            if rush is not None:
                add[rush] += yards * 0.1
            if "INTERCEPT" in text.upper() and pas is not None:
                add[pas] -= 2
            if td:
                scorer = (parts.get("scorer") or [None])[0] or rec or rush
                if scorer is not None:
                    add[scorer] += 6
                if pas is not None and scorer == rec and rec is not None:
                    add[pas] += 4
            if pl.get("isTurnover") and parts.get("fumbler"):
                add[parts["fumbler"][0]] -= 2
            ctx = None
            if td or abs(sum(add.values())) >= 4:
                dr = drives.get(str(pl.get("id"))) or {}
                pr = probs.get(str(pl.get("id"))) or probs.get(str(pl.get("sequenceNumber")) or "") or {}
                bits = []
                if dr.get("desc"):
                    bits.append(dr["desc"].replace("plays", "giocate").replace("yards", "yard"))
                if dr.get("from"):
                    bits.append("partiti da " + dr["from"])
                if pr.get("home") is not None:
                    bits.append(f"vittoria casa {round(pr['home'] * 100)}%")
                ctx = " · ".join(bits) or None
            for pid, pts in add.items():
                if abs(pts) >= 0.05:
                    row_ = [elapsed, round(pts, 2)]
                    if abs(pts) >= 4:
                        row_.append(text[:90])
                        if ctx:
                            row_.append(ctx)
                    events[pid].append(row_)
    curves = {}
    for pid, evs in events.items():
        evs.sort(key=lambda e: e[0])
        tot, out = 0.0, []
        for ev in evs:
            sec, val = ev[0], ev[1]
            tot += val
            row_ = [sec, round(tot, 1)]
            if len(ev) > 2 and ev[2]:
                row_.append(ev[2])
                if len(ev) > 3 and ev[3]:
                    row_.append(ev[3])
            out.append(row_)
        curves[str(pid)] = {str(week): out}
    return curves, meta


def week_game_state(season, week):
    """Stato della partita NFL di ogni squadra: prima ESPN (sa anche il live), poi nflverse."""
    out = {}
    sb_path = os.path.join(RAW, "espn_scoreboard.json")
    if os.path.exists(sb_path):
        for e in (jload(sb_path).get("events") or []):
            comp = (e.get("competitions") or [{}])[0]
            st = ((comp.get("status") or {}).get("type") or {})
            teams = [(c.get("team") or {}).get("abbreviation") for c in (comp.get("competitors") or [])]
            for i, t in enumerate(teams):
                if not t:
                    continue
                # minuto di gioco, per fermare le curve delle partite in corso
                elapsed = None
                if st.get("state") == "in":
                    per = (comp.get("status") or {}).get("period") or 1
                    clock = (comp.get("status") or {}).get("displayClock") or "0:00"
                    try:
                        mm, ss = clock.split(":")
                        elapsed = int((per - 1) * 900 + (900 - (int(mm) * 60 + int(ss))))
                    except ValueError:
                        elapsed = None
                out[ab(t)] = {"state": st.get("state"), "detail": st.get("shortDetail"),
                              "el": elapsed, "opp": ab(teams[1 - i] or ""), "kick": e.get("date")}
        if out:
            return out
    for g in rows(os.path.join(RAW, "nflverse", "games.csv")):
        if int(g.get("season") or 0) != season or int(g.get("week") or 0) != week:
            continue
        played = num(g, "home_score") is not None and num(g, "away_score") is not None
        for t, opp in ((ab(g["home_team"]), ab(g["away_team"])), (ab(g["away_team"]), ab(g["home_team"]))):
            out[t] = {"state": "post" if played else "pre", "opp": opp,
                      "kick": (g.get("gameday") or "") + " " + (g.get("gametime") or "")}
    return out


def scoring_curves(season, gsis_to_espn):
    """Punti fantasy azione per azione, per ricostruire la curva di una partita.

    Il play-by-play di nflverse porta il cronometro di ogni giocata: da lì si
    ricava quando un giocatore ha fatto i suoi punti, non solo quanti.
    Punteggio della lega: ricezione 1, yard 0,1, yard su passaggio 0,04,
    TD 6 (4 se di passaggio), intercetto e fumble persi -2.
    """
    path = os.path.join(RAW, "nflverse", f"pbp_{season}.csv.gz")
    if not os.path.exists(path):
        return {}
    events = defaultdict(list)
    for r in rows(path):
        secs = num(r, "game_seconds_remaining")
        if secs is None:
            continue
        elapsed = int(max(0, 3600 - secs))
        week = int(num(r, "week") or 0)
        td_id = r.get("td_player_id") or ""
        add = defaultdict(float)
        rec_id, rush_id, pass_id = r.get("receiver_player_id"), r.get("rusher_player_id"), r.get("passer_player_id")
        if rec_id and r.get("complete_pass") == "1":
            add[rec_id] += 1 + (num(r, "receiving_yards") or 0) * 0.1
        if rush_id:
            add[rush_id] += (num(r, "rushing_yards") or 0) * 0.1
        if pass_id and r.get("complete_pass") == "1":
            add[pass_id] += (num(r, "passing_yards") or 0) * 0.04
        if r.get("interception") == "1" and pass_id:
            add[pass_id] -= 2
        if r.get("fumble_lost") == "1":
            fum = r.get("fumbled_1_player_id")
            if fum:
                add[fum] -= 2
        if r.get("touchdown") == "1" and td_id:
            add[td_id] += 6
            if pass_id and td_id != pass_id and r.get("pass") == "1":
                add[pass_id] += 4
        if r.get("two_point_conv_result") == "success":
            for pid in (rec_id, rush_id):
                if pid:
                    add[pid] += 2
        for pid, pts in add.items():
            if abs(pts) < 0.05 or pid not in gsis_to_espn:
                continue
            desc = (r.get("desc") or "")[:90] if abs(pts) >= 4 else None
            events[(gsis_to_espn[pid], week)].append([elapsed, round(pts, 2), desc])
    curves = defaultdict(dict)
    for (espn_id, week), evs in events.items():
        evs.sort(key=lambda e: e[0])
        tot, pts = 0.0, []
        for sec, val, desc in evs:
            tot += val
            row_ = [sec, round(tot, 1)]
            if desc:
                row_.append(desc)
            pts.append(row_)
        curves[str(espn_id)][str(week)] = pts
    return curves


def kickers_and_defense(season):
    """Numeri di supporto per i due reparti che non hanno utilizzo: K e D/ST."""
    kick = {}
    for r in rows(os.path.join(RAW, "nflverse", f"stats_player_reg_{season}.csv")):
        if (r.get("position") or "") != "K":
            continue
        att, made = num(r, "fg_att") or 0, num(r, "fg_made") or 0
        if not att and not num(r, "pat_att"):
            continue
        kick[r["player_id"]] = {
            "fgMade": int(made), "fgAtt": int(att),
            "fgPct": rnd(made / att * 100) if att else None,
            "long": int(num(r, "fg_long") or 0),
            "from40": int((num(r, "fg_made_40_49") or 0) + (num(r, "fg_made_50_59") or 0) + (num(r, "fg_made_60_") or 0)),
            "patMade": int(num(r, "pat_made") or 0), "patAtt": int(num(r, "pat_att") or 0),
            "gp": int(num(r, "games") or 0),
        }
    dst = {}
    for r in rows(os.path.join(RAW, "nflverse", f"stats_team_reg_{season}.csv")):
        if (r.get("season_type") or "REG") != "REG":
            continue
        g = num(r, "games") or 1
        dst[ab(r["team"])] = {
            "sacks": rnd((num(r, "def_sacks") or 0) / g, 2),
            "int": rnd((num(r, "def_interceptions") or 0) / g, 2),
            "ff": rnd((num(r, "def_fumbles_forced") or 0) / g, 2),
            "td": int(num(r, "def_tds") or 0),
            "gp": int(g),
        }
    return kick, dst


def injury_history(seasons):
    """Indice di fragilità: quante settimane ogni giocatore è stato fuori o limitato."""
    out = defaultdict(lambda: {"out": 0, "dnp": 0, "limited": 0, "weeks": 0, "list": []})
    for season in seasons:
        path = os.path.join(RAW, "nflverse", f"injuries_{season}.csv")
        if not os.path.exists(path):
            continue
        for r in rows(path):
            gsis = r.get("gsis_id")
            if not gsis:
                continue
            e = out[gsis]
            e["weeks"] += 1
            status = (r.get("report_status") or "").strip()
            practice = (r.get("practice_status") or "").strip()
            if status == "Out":
                e["out"] += 1
            if practice.startswith("Did Not"):
                e["dnp"] += 1
            elif practice.startswith("Limited"):
                e["limited"] += 1
            inj = (r.get("report_primary_injury") or r.get("practice_primary_injury") or "").strip()
            if inj and inj not in e["list"]:
                e["list"].append(inj)
    return {k: {**v, "list": v["list"][:6]} for k, v in out.items() if v["weeks"]}


def injuries(season):
    """Ultimo bollettino utile per ogni giocatore."""
    latest = {}
    for r in rows(os.path.join(RAW, "nflverse", f"injuries_{season}.csv")):
        gsis = r.get("gsis_id")
        if not gsis:
            continue
        status = (r.get("report_status") or "").strip()
        practice = (r.get("practice_status") or "").strip()
        if not status and not practice:
            continue
        wk = int(num(r, "week") or 0)
        if gsis not in latest or wk >= latest[gsis]["w"]:
            latest[gsis] = {"n": r.get("full_name"), "t": ab(r.get("team") or ""), "w": wk,
                            "s": {"Out": "O", "Doubtful": "D", "Questionable": "Q"}.get(status) or (status or None),
                            "i": (r.get("report_primary_injury") or r.get("practice_primary_injury") or None),
                            "pr": practice or None}
    return latest


# ------------------------------------------------------------- lega e mercato
SLOT = {0: "QB", 2: "RB", 3: "RB/WR", 4: "WR", 6: "TE", 16: "D/ST", 17: "K",
        20: "BE", 21: "IR", 23: "FLEX"}


def league_data(season):
    lg = jload(RAW, "espn_league.json")
    week = lg.get("scoringPeriodId") or (lg.get("status") or {}).get("latestScoringPeriod")
    roster = {}
    lineups = {}
    for t in lg["teams"]:
        rows_ = []
        for e in (t.get("roster") or {}).get("entries") or []:
            roster[e["playerId"]] = t["id"]
            pl = ((e.get("playerPoolEntry") or {}).get("player") or {})
            stats = pl.get("stats") or []
            def week_stat(src):
                return next((s.get("appliedTotal") for s in stats
                             if s.get("scoringPeriodId") == week and s.get("statSourceId") == src), None)
            rows_.append({
                "id": e["playerId"],
                "slot": SLOT.get(e.get("lineupSlotId"), str(e.get("lineupSlotId"))),
                "starter": e.get("lineupSlotId") not in (20, 21),
                "inj": INJ.get(pl.get("injuryStatus") or e.get("injuryStatus") or "ACTIVE", "?"),
                "proj": rnd(week_stat(1)), "act": rnd(week_stat(0)),
            })
        order = {"QB": 0, "RB": 1, "RB/WR": 2, "FLEX": 2, "WR": 3, "TE": 4, "D/ST": 5, "K": 6, "BE": 7, "IR": 8}
        lineups[t["id"]] = sorted(rows_, key=lambda r: (order.get(r["slot"], 9), -(r["proj"] or 0)))
    rec = {t["id"]: {"w": (t.get("record") or {}).get("overall", {}).get("wins"),
                     "l": (t.get("record") or {}).get("overall", {}).get("losses"),
                     "pf": rnd((t.get("record") or {}).get("overall", {}).get("pointsFor")),
                     "pa": rnd((t.get("record") or {}).get("overall", {}).get("pointsAgainst"))}
           for t in lg["teams"]}
    sch = jload(RAW, "espn_schedule.json")
    games, weekly = [], defaultdict(dict)
    for m in sch.get("schedule", []):
        h, a = m.get("home") or {}, m.get("away") or {}
        games.append({"w": m.get("matchupPeriodId"), "h": h.get("teamId"), "a": a.get("teamId"),
                      "hp": rnd(h.get("totalPoints") or 0), "ap": rnd(a.get("totalPoints") or 0)})
        for side in (h, a):
            for w, v in (side.get("pointsByScoringPeriod") or {}).items():
                weekly[str(side.get("teamId"))][w] = rnd(v)
    draft = lg.get("draftDetail") or {}
    picks = [[p["overallPickNumber"], p["teamId"], p["playerId"]]
             for p in draft.get("picks", []) if p.get("playerId")]
    st = lg.get("status") or {}
    meta = {
        "id": lg["id"], "season": season,
        # settimana in corso secondo ESPN: avanza il martedì, quindi è anche
        # quella su cui ha senso consigliare la formazione.
        "week": lg.get("scoringPeriodId") or st.get("latestScoringPeriod"),
        "matchupPeriod": st.get("currentMatchupPeriod"),
        "name": lg["settings"].get("name"),
        "teams": {t["id"]: {"name": t.get("name"), "abbrev": t.get("abbrev")} for t in lg["teams"]},
        "draft": lg["settings"]["draftSettings"],
        "slots": {k: v for k, v in lg["settings"]["rosterSettings"]["lineupSlotCounts"].items() if v},
        "scoring": lg["settings"]["scoringSettings"].get("playerRankType"),
        "myTeam": MY_TEAM,
    }
    return meta, roster, rec, games, dict(weekly), picks, lineups


def adp_index(season):
    """ADP di FFC indicizzato per nome+ruolo (l'API restituisce una lista)."""
    try:
        data = jload(RAW, "ffc", f"adp_{season}.json").get("players") or []
    except FileNotFoundError:
        return {}
    if isinstance(data, dict):                    # formato già indicizzato
        return data
    out = {}
    for p in data:
        pos = p.get("position") or p.get("pos") or ""
        out[nkey(p.get("name"), pos)] = {"adp": p.get("adp"), "stdev": p.get("stdev"),
                                         "bye": p.get("bye"), "team": p.get("team")}
    return out


def player_pool(season, ids, sched):
    """Il pool ESPN arricchito con ADP, età e anagrafica."""
    pool = jload(RAW, "espn_players.json")["players"]
    ffc_by = adp_index(season)
    sleeper = {}
    for k, v in jload(RAW, "sleeper_players.json").items():
        sleeper[k] = {"age": v.get("age"), "exp": v.get("years_exp"), "dc": v.get("depth_chart_order")}
    out = []
    for e in pool:
        p = e["player"]
        pos = POS.get(p["defaultPositionId"])
        if not pos:
            continue
        x = ids.get(str(p["id"])) or {}
        sl = sleeper.get(x.get("sleeper") or "") or {}
        team = TEAM.get(p.get("proTeamId"), "FA")
        stats = p.get("stats", [])
        pick = lambda src, split=0, y=season: next(
            (s.get("appliedTotal") for s in stats if s.get("seasonId") == y and s.get("scoringPeriodId") == 0
             and s.get("statSourceId") == src and s.get("statSplitTypeId") == split), None)
        adp = ffc_by.get(nkey(p["fullName"], pos)) or {}
        out.append({
            "id": p["id"], "name": p["fullName"], "pos": pos, "nfl": team,
            "rank": (p.get("draftRanksByRankType", {}).get("PPR") or {}).get("rank") or 999,
            "adpEspn": rnd(p.get("ownership", {}).get("averageDraftPosition") or 0),
            "adp": rnd(adp.get("adp")), "adpSd": rnd(adp.get("stdev")),
            "proj": rnd(pick(1) or 0), "act": rnd(pick(0)), "actPrev": rnd(pick(0, y=season - 1)),
            "bye": (sched.get(team) or {}).get("bye"),
            "inj": INJ.get(p.get("injuryStatus") or "ACTIVE", "?"),
            "pct": rnd(p.get("ownership", {}).get("percentOwned") or 0),
            "started": rnd(p.get("ownership", {}).get("percentStarted") or 0),
            "age": sl.get("age"), "exp": sl.get("exp"), "dc": sl.get("dc"),
            "gsis": x.get("gsis"),
        })
    return out


# ------------------------------------------------- storico e tratti dei manager
def history():
    """Classifiche, scontri diretti e punteggi settimanali dall'archivio 2019-2025."""
    seasons, h2h, weekly = {}, {}, defaultdict(lambda: defaultdict(dict))
    for f in sorted(glob.glob(os.path.join(VENDOR, "archive", "fantasy_data_*.json"))):
        d = jload(f)
        y = int(d["season"])
        tab = {}
        for wk, w in sorted(d["weeks"].items(), key=lambda kv: int(kv[0])):
            wn, playoff = int(wk), int(wk) > 15
            for m in w["matchups"]:
                t1, t2 = m.get("team1") or {}, m.get("team2") or {}
                k1, k2 = MANAGERS.get(t1.get("name")), MANAGERS.get(t2.get("name"))
                if not k1 or not k2:
                    continue
                try:
                    s1, s2 = float(t1.get("score") or 0), float(t2.get("score") or 0)
                except ValueError:
                    continue
                if not s1 and not s2:
                    continue
                for k, s, o in ((k1, s1, s2), (k2, s2, s1)):
                    e = tab.setdefault(k, {"w": 0, "l": 0, "pf": 0.0, "pa": 0.0, "g": 0,
                                           "best": 0.0, "pw": 0, "pl": 0})
                    if playoff:
                        e["pw" if s > o else "pl"] += 1
                    else:
                        e["w" if s > o else "l"] += 1
                        e["pf"] += s; e["pa"] += o; e["g"] += 1
                        e["best"] = max(e["best"], s)
                        weekly[k][str(y)][str(wn)] = rnd(s)
                if not playoff:
                    a, b = min(k1, k2), max(k1, k2)
                    e = h2h.setdefault((a, b), {"a": a, "b": b, "aw": 0, "bw": 0})
                    e["aw" if (k1 if s1 > s2 else k2) == a else "bw"] += 1
        for e in tab.values():
            e["pf"], e["pa"] = rnd(e["pf"]), rnd(e["pa"])
            e["ppg"] = rnd(e["pf"] / max(1, e["g"]))
            e["best"] = rnd(e["best"])
        seasons[y] = tab
    return {"seasons": seasons, "h2h": list(h2h.values())}, {k: dict(v) for k, v in weekly.items()}


def drafts_and_traits(season, picks26):
    """Le draft storiche e i tratti che servono al mock draft, calcolati qui."""
    drafts = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(VENDOR, "drafts", "draft_data_*.json"))):
        d = jload(f)
        y = int(d["season"])
        adp = adp_index(y)
        for tname, plist in d["teams"].items():
            tid = MANAGERS.get(tname)
            if not tid:
                continue
            for p in plist:
                a = adp.get(nkey(p["name"], p["position"]))
                drafts[tid].append({"y": y, "p": p["pick"], "n": p["name"], "pos": p["position"],
                                    "t": p.get("nfl_team"), "adp": (a or {}).get("adp")})
    # posto atteso dal mercato DENTRO la stessa draft: con 4 squadre il numero di
    # pick non è confrontabile con un ADP calcolato su leghe da 12.
    by_year = defaultdict(list)
    for tid, rws in drafts.items():
        for r in rws:
            by_year[r["y"]].append(r)
    for y, rws in by_year.items():
        for i, r in enumerate(sorted([r for r in rws if r.get("adp")], key=lambda r: r["adp"])):
            r["ar"] = i + 1

    traits = {}
    n_teams = 4
    for tid, rws in drafts.items():
        with_ar = [r for r in rws if r.get("ar")]
        reach = [r["ar"] - r["p"] for r in with_ar]
        by_round = defaultdict(lambda: defaultdict(int))
        counts = defaultdict(int)
        for r in rws:
            rd = -(-r["p"] // n_teams)
            by_round[rd][r["pos"]] += 1
            counts[rd] += 1
        firsts = {}
        for pos in ("QB", "RB", "WR", "TE"):
            per_year = {}
            for r in rws:
                if r["pos"] == pos:
                    per_year[r["y"]] = min(per_year.get(r["y"], 99), -(-r["p"] // n_teams))
            firsts[pos] = rnd(statistics.mean(per_year.values())) if per_year else None
        # fedeltà: quante volte ha ridraftato un giocatore che aveva già preso
        seen, repeat = set(), 0
        for r in sorted(rws, key=lambda r: (r["y"], r["p"])):
            key = norm(r["n"])
            if key in seen:
                repeat += 1
            seen.add(key)
        traits[tid] = {
            "picks": len(rws), "seasons": sorted({r["y"] for r in rws}),
            "reach": rnd(statistics.mean(reach), 2) if reach else None,
            "reachSd": rnd(statistics.pstdev(reach), 2) if len(reach) > 1 else None,
            "first": firsts,
            "byRound": {str(rd): {p: rnd(c / counts[rd], 3) for p, c in d.items()}
                        for rd, d in by_round.items()},
            "repeatRate": rnd(repeat / max(1, len(rws)) * 100),
            "own26": sorted({p[2] for p in picks26 if p[1] == tid}),
        }
    return {str(k): v for k, v in drafts.items()}, {str(k): v for k, v in traits.items()}


def streaming(hist_weekly):
    """Quanti giocatori diversi ha schierato ogni manager per ruolo, per stagione."""
    used = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    points = defaultdict(lambda: defaultdict(float))
    starts = defaultdict(lambda: defaultdict(int))     # quante volte ha schierato quel giocatore
    for f in sorted(glob.glob(os.path.join(VENDOR, "archive", "fantasy_data_*.json"))):
        d = jload(f)
        y = int(d["season"])
        for wk, w in d["weeks"].items():
            for m in w["matchups"]:
                for side in ("team1", "team2"):
                    t = m.get(side) or {}
                    tid = MANAGERS.get(t.get("name"))
                    if not tid:
                        continue
                    for s in t.get("starters") or []:
                        pos = (s.get("position") or "").upper().replace("D/ST", "DST").replace("DEF", "DST")
                        if pos not in ("QB", "RB", "WR", "TE", "K", "DST"):
                            continue
                        used[tid][y][pos].add(s.get("name"))
                        starts[tid][(s.get("name"), pos)] += 1
                        try:
                            points[tid][pos] += float(s.get("fantasy_points") or 0)
                        except ValueError:
                            pass
    out = {}
    for tid, years in used.items():
        per_pos, per_season = {}, {}
        for pos in ("QB", "RB", "WR", "TE", "K", "DST"):
            vals = [len(years[y][pos]) for y in years if years[y].get(pos)]
            per_pos[pos] = rnd(statistics.mean(vals)) if vals else None
        for y in sorted(years):
            per_season[str(y)] = {p: len(v) for p, v in years[y].items()}
        tot = sum(points[tid].values()) or 1
        out[str(tid)] = {"distinct": per_pos, "perSeason": per_season,
                         "share": {p: rnd(v / tot * 100) for p, v in points[tid].items()},
                         "top": [[n, p, c] for (n, p), c in
                                 sorted(starts[tid].items(), key=lambda kv: -kv[1])[:14]]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=int(os.environ.get("SEASON", 2026)))
    a = ap.parse_args()
    y = a.season
    os.makedirs(BUILD, exist_ok=True)

    ids = crosswalk()
    by_gsis = {v["gsis"]: v for v in ids.values() if v.get("gsis")}
    sched, teams = nfl_context(y)
    fpa_cur, lg_cur = fantasy_allowed(y)
    fpa_prev, lg_prev = fantasy_allowed(y - 1)
    meta, roster, rec, games, weekly, picks26, lineups_now = league_data(y)
    pool = player_pool(y, ids, sched)

    # utilizzo: solo i giocatori del pool, per non portarsi dietro l'intera NFL
    wanted = {p["gsis"] for p in pool if p.get("gsis")}
    keep = {g: by_gsis[g] for g in wanted if g in by_gsis}
    adv_cur, adv_prev = advanced(y, keep), advanced(y - 1, keep)
    for season, target in ((y, adv_cur), (y - 1, adv_prev)):
        for gsis, extra in nextgen(season).items():
            if gsis in target:
                target[gsis].update(extra)
    inj = {k: v for k, v in injuries(y).items() if k in wanted}

    for p in pool:
        p["own"] = roster.get(p["id"], 0)

    gsis_to_espn = {p["gsis"]: p["id"] for p in pool if p.get("gsis")}
    week_now = meta.get("week") or 1
    curves = scoring_curves(y, gsis_to_espn)          # nflverse: settimane concluse
    live, _ = espn_curves(week_now)                   # ESPN: anche partite in corso
    for pid, weeks in live.items():
        curves.setdefault(pid, {}).update(weeks)      # la settimana viva arriva da ESPN
    game_state = week_game_state(y, week_now)
    games_info = week_games(y, week_now)
    tx = transactions(y)
    sleeper_to_espn = {}
    for espn_id, x in ids.items():
        if x.get("sleeper"):
            sleeper_to_espn[str(x["sleeper"])] = int(espn_id)
    trend = trending(sleeper_to_espn)
    proj_weeks = weekly_projections(week_now)
    weekly = weekly_lines(y, week_now, ids, sched)
    kick_cur, dst_cur = kickers_and_defense(y)
    # statistiche unite: ESPN prima, poi Sleeper, poi nflverse
    rz_g, rz_e = red_zone(y, week_now)
    rz_extra = defaultdict(dict)
    for g, wks in rz_g.items():
        if g in gsis_to_espn:
            rz_extra[gsis_to_espn[g]] = {k: dict(v) for k, v in wks.items()}
    for pid, z in rz_e.items():
        rz_extra[pid].setdefault(str(week_now), dict(z))
    stats = MS.build(y, week_now, ids, pool, rows, ab, TEAM, rz_extra)
    apply_merged(stats, pool, adv_cur, weekly, kick_cur, dst_cur, gsis_to_espn)
    kick_prev, dst_prev = kickers_and_defense(y - 1)
    frailty = {g: v for g, v in injury_history((y, y - 1)).items() if g in wanted}
    hist, hist_weekly = history()
    drafts, traits = drafts_and_traits(y, picks26)
    lineups = streaming(hist_weekly)

    # analisi di stagione e giocatori da ricordare, archiviati per la draft room dell'anno prossimo
    by_week = lineups_by_week(week_now)
    sset = (jload(RAW, "espn_league.json").get("settings") or {})
    items = {i["statId"]: i["points"] for i in (sset.get("scoringSettings") or {}).get("scoringItems", [])}
    ss = sset.get("scheduleSettings") or {}
    review = SR.build(y, week_now, by_week, pool, picks26, tx, game_state, stats, ctx={
        "games": games, "lineups": lineups_now, "sched": {k: {"bye": v["bye"], "opp": {str(w): o for w, o in v["opp"].items()}}
                                                          for k, v in sched.items()},
        "fpa": fpa_cur, "nfl": {p["id"]: p["nfl"] for p in pool},
        "tdPts": {"pass": items.get(4, 4.0), "rush": items.get(25, 6.0), "rec": items.get(43, 6.0)},
        "regWeeks": ss.get("matchupPeriodCount") or 15, "playoffTeams": ss.get("playoffTeamCount") or 4})
    SR.save(review)

    bundle = {
        "generatedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "season": y,
        "league": meta,
        "pool": pool,
        "teams": teams,
        "sched": {k: {"bye": v["bye"], "opp": {str(w): o for w, o in v["opp"].items()}}
                  for k, v in sched.items()},
        "fpa": fpa_cur, "fpaPrev": fpa_prev, "fpaLeague": {"cur": lg_cur, "prev": lg_prev},
        "adv": {str(y): adv_cur, str(y - 1): adv_prev},
        "inj": inj,
        "stats": stats,
        "lg": {"games": games, "rec": rec, "weekly": weekly, "lineups": lineups_now,
               "byWeek": by_week},
        "curves": curves,
        "gameState": game_state,
        "games": games_info,
        "transactions": tx,
        "review": review,
        "reviewHist": SR.load_history(y),
        "notes": SR.load_notes(y),
        "trending": trend,
        "projWeeks": proj_weeks,
        "weekly": weekly,
        "kickers": {"cur": kick_cur, "prev": kick_prev},
        "defense": {"cur": dst_cur, "prev": dst_prev},
        "frailty": frailty,
        "picks": picks26,
        "drafts": drafts, "traits": traits, "lineups": lineups,
        "hist": hist, "histWeekly": hist_weekly,
    }
    out = os.path.join(BUILD, "console.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, separators=(",", ":"), ensure_ascii=False)
    print(f"scritto {out}: {os.path.getsize(out)/1024:.0f} KB")
    print(f"  pool {len(pool)} giocatori · utilizzo {len(adv_cur)}/{len(adv_prev)} · infortuni {len(inj)}")
    print(f"  squadre NFL {len(teams)} · difese {len(fpa_prev)} · draft storiche {sum(len(v) for v in drafts.values())} pick")
    print(f"  stagioni storiche {sorted(hist['seasons'])}")


if __name__ == "__main__":
    sys.exit(main())
