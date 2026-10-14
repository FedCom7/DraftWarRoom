#!/usr/bin/env python3
"""Analisi della stagione fantasy: squadre, reparti, draft e giocatori da ricordare.

Lavora solo sulle giornate concluse, partendo dalle formazioni schierate su ESPN
(chi era titolare, chi in panchina, quanti punti ha fatto) e le incrocia con il
draft e con i movimenti di mercato.

Il risultato si salva anche in data/history/season_{anno}.json e non si cancella
mai: l'anno prossimo la draft room lo legge per ricordare chi ha fatto la
differenza.
"""
import json, math, os, random, statistics
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "data", "history")
POS = ["QB", "RB", "WR", "TE", "K", "DST"]
SLOT_POS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "D/ST": "DST"}
# i posti della formazione: ogni squadra ne ha lo stesso numero, quindi il confronto
# è alla pari anche quando qualcuno mette un RB nel FLEX e qualcun altro un WR
SLOTS = ["QB", "RB", "WR", "TE", "FLEX", "K", "DST"]
SLOT_OF = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "RB/WR": "FLEX", "FLEX": "FLEX",
           "K": "K", "D/ST": "DST"}
LINEUP = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1}      # più un FLEX RB/WR
FLEX_OK = ("RB", "WR")


def _r(v, d=1):
    return None if v is None else round(v, d)


def _q(vals, p):
    """Percentile con interpolazione lineare (p fra 0 e 1)."""
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _cv(vals):
    """Coefficiente di variazione: oscillazione rispetto alla media."""
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    return _r(statistics.pstdev(vals) / m, 3) if m > 0 else None


def optimal(rows, pos):
    """Punti della formazione migliore possibile col senno di poi (IR esclusi):
    i migliori per ogni posto fisso, poi il miglior RB o WR rimasto nel FLEX."""
    pool = defaultdict(list)
    for r in rows:
        if r["slot"] != "IR":
            pool[pos(r)].append(r.get("act") or 0.0)
    total, left = 0.0, []
    for p, n in LINEUP.items():
        v = sorted(pool.get(p, []), reverse=True)
        total += sum(v[:n])
        if p in FLEX_OK:
            left += v[n:]
    return total + (max(left) if left else 0.0)


def completed_weeks(by_week, week_now, game_state):
    """Le giornate chiuse. Quella in corso conta solo se tutte le partite sono finite."""
    weeks = [int(w) for w in by_week if int(w) < week_now]
    states = [s.get("state") for s in (game_state or {}).values()]
    if str(week_now) in by_week and states and all(s == "post" for s in states):
        weeks.append(week_now)
    return sorted(weeks)


def build(season, week_now, by_week, pool, picks, tx, game_state, stats=None, ctx=None):
    pos_of = {p["id"]: p["pos"] for p in pool}
    name_of = {p["id"]: p["name"] for p in pool}
    nfl_of = {p["id"]: p["nfl"] for p in pool}
    weeks = completed_weeks(by_week, week_now, game_state)
    teams = sorted({int(t) for w in by_week.values() for t in w})

    def pos(row):
        return pos_of.get(row["id"]) or SLOT_POS.get(row["slot"]) or "?"

    # ---------------------------------------------------------- per squadra
    team_week = {t: {} for t in teams}
    starts = []                                   # titolari: [squadra, giornata, id, ruolo, punti, slot]
    bench_rows = []                               # panchina: [squadra, giornata, id, ruolo, punti]
    owner_week = defaultdict(dict)                # giocatore -> giornata -> (squadra, titolare, punti)
    for w in weeks:
        for t, rows in (by_week.get(str(w)) or {}).items():
            t = int(t)
            by_slot, by_bpos, bench, total = defaultdict(float), defaultdict(float), 0.0, 0.0
            for r in rows:
                pts = r.get("act") or 0.0
                starter = r["starter"] and r["slot"] != "IR"
                owner_week[r["id"]][w] = (t, starter, pts)
                if starter:
                    sl = SLOT_OF.get(r["slot"], r["slot"])
                    total += pts
                    by_slot[sl] += pts
                    starts.append([t, w, r["id"], pos(r), _r(pts), sl])
                elif r["slot"] == "BE":
                    bench += pts
                    by_bpos[pos(r)] += pts
                    bench_rows.append([t, w, r["id"], pos(r), _r(pts)])
            best = optimal(rows, pos)
            team_week[t][str(w)] = {"tot": _r(total), "slot": {k: _r(v) for k, v in by_slot.items()},
                                    "benchPos": {k: _r(v) for k, v in by_bpos.items()},
                                    "bench": _r(bench), "best": _r(best), "left": _r(max(0.0, best - total))}

    team_sum = {}
    for t, wk in team_week.items():
        tots = [v["tot"] for v in wk.values()]
        per_slot, per_bench = {}, {}
        for sl in SLOTS:
            vals = [v["slot"].get(sl, 0.0) for v in wk.values()]
            per_slot[sl] = {"avg": _r(statistics.mean(vals)) if vals else None, "cv": _cv(vals),
                            "min": _r(min(vals)) if vals else None, "max": _r(max(vals)) if vals else None}
        for p in POS:
            vals = [v["benchPos"].get(p, 0.0) for v in wk.values()]
            per_bench[p] = _r(statistics.mean(vals)) if vals else None
        bests = [v["best"] for v in wk.values()]
        team_sum[str(t)] = {
            "avg": _r(statistics.mean(tots)) if tots else None, "sd": _r(statistics.pstdev(tots)) if len(tots) > 1 else None,
            "cv": _cv(tots), "best": _r(max(tots)) if tots else None, "worst": _r(min(tots)) if tots else None,
            "bench": _r(statistics.mean([v["bench"] for v in wk.values()])) if wk else None,
            "left": _r(sum(v["left"] for v in wk.values())),
            "optAvg": _r(statistics.mean(bests)) if bests else None,
            "eff": _r(sum(tots) / sum(bests), 3) if bests and sum(bests) else None,
            "slot": per_slot, "benchPos": per_bench}

    # riferimento di ruolo: com'è andato in media un titolare di quel ruolo
    by_pos_scores = defaultdict(list)
    for t, w, pid, p, pts, _slot in starts:
        by_pos_scores[p].append(pts or 0)
    pos_ref = {p: {"mean": _r(statistics.mean(v)), "p25": _r(_q(v, .25)), "p75": _r(_q(v, .75)),
                   "boom": _r(_q(v, .85)), "bust": _r(_q(v, .15))} for p, v in by_pos_scores.items() if v}

    # --------------------------------------------------------------- draft
    acquired = {}                                 # giocatore -> primo movimento che l'ha portato in una rosa
    dropped = defaultdict(list)
    for m in sorted(tx or [], key=lambda x: x.get("date") or 0):
        for pid in m.get("add") or []:
            acquired.setdefault(pid, {"team": m["team"], "week": m["week"], "type": m["type"]})
        for pid in m.get("drop") or []:
            dropped[pid].append({"team": m["team"], "week": m["week"]})
    draft = []
    for pick, team, pid in picks or []:
        ow = owner_week.get(pid, {})
        mine = [(w, s, p) for w, (t, s, p) in ow.items() if t == team]
        draft.append({"pick": pick, "team": team, "id": pid, "pos": pos_of.get(pid, "?"),
                      "pts": _r(sum(p for _, s, p in mine if s)), "all": _r(sum(p for _, _, p in mine)),
                      "weeks": len(mine), "starts": sum(1 for _, s, _ in mine if s)})
    # rendimento atteso per pick: retta sui logaritmi, il calo tipico fra prime e ultime scelte
    xs = [math.log(d["pick"]) for d in draft]
    ys = [d["pts"] or 0 for d in draft]
    a = b = 0.0
    if len(xs) > 2:
        mx, my = statistics.mean(xs), statistics.mean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
        a = my - b * mx
    for d in draft:
        d["exp"] = _r(a + b * math.log(d["pick"]))
        d["res"] = _r((d["pts"] or 0) - d["exp"])
    draft_team = {}
    for t in teams:
        mine = [d for d in draft if d["team"] == t]
        draft_team[str(t)] = {"res": _r(sum(d["res"] for d in mine)), "pts": _r(sum(d["pts"] or 0 for d in mine)),
                              "kept": sum(1 for d in mine if d["weeks"] == len(weeks))}

    # ---------------------------------------------------- giocatori da ricordare
    pick_of = {d["id"]: d for d in draft}
    # partite davvero giocate (dalle statistiche unite): bye e assenze non contano
    # nella media, altrimenti uno zero da bye pesa come una partita storta
    def played(pid, w):
        sp = (stats or {}).get("players", {}).get(str(pid))
        if not sp:
            return True
        wk = sp["w"].get(str(w))
        return bool(wk and wk["gp"])
    players = []
    for pid, ow in owner_week.items():
        p = pos_of.get(pid, "?")
        ref = pos_ref.get(p) or {}
        st = [(w, pts) for w, (t, s, pts) in ow.items() if s]
        be = [(w, pts) for w, (t, s, pts) in ow.items() if not s]
        if not st and not be:
            continue
        pts_st = sum(x for _, x in st)
        # il rendimento del giocatore conta tutte le partite giocate, titolare o in
        # panchina: per ricordarlo l'anno dopo non importa dove l'ha messo il manager
        prod = [(w, x) for w, (t, s, x) in ow.items() if played(pid, w)]
        avg = statistics.mean(x for _, x in prod) if prod else None
        last_team = ow[max(ow)][0]
        teams_seen = []
        for w in sorted(ow):
            if ow[w][0] not in teams_seen:
                teams_seen.append(ow[w][0])
        booms = sum(1 for _, x in prod if ref.get("boom") is not None and x >= ref["boom"])
        busts = sum(1 for _, x in prod if ref.get("bust") is not None and x <= ref["bust"])
        above = sum(x - (ref.get("mean") or 0) for _, x in prod)
        best = max(ow.items(), key=lambda kv: kv[1][2])
        d = pick_of.get(pid)
        acq = acquired.get(pid)
        if acq and d and acq["week"] is not None and acq["week"] <= 1 and acq["team"] == d["team"]:
            acq = None                            # ripreso subito da chi l'aveva scelto: non è un colpo di mercato
        players.append({
            "id": pid, "name": name_of.get(pid, str(pid)), "pos": p, "nfl": nfl_of.get(pid),
            "team": last_team, "teams": teams_seen,
            "weeks": len(ow), "games": len(prod), "starts": len(st), "pts": _r(pts_st), "avg": _r(avg),
            "bench": _r(sum(x for _, x in be)), "booms": booms, "busts": busts,
            "above": _r(above), "cv": _cv([x for _, x in prod]) if len(prod) >= 3 else None,
            "best": {"w": best[0], "pts": _r(best[1][2])},
            "pick": d["pick"] if d else None, "pickTeam": d["team"] if d else None, "res": d["res"] if d else None,
            "acq": acq, "dropped": dropped.get(pid) or [],
            "byWeek": {str(w): [ow[w][0], 1 if ow[w][1] else 0, _r(ow[w][2])] for w in sorted(ow)},
        })
    # liberi: chi ha segnato tanto senza essere in nessuna rosa
    free = []
    if stats:
        idx = [f[0] for f in stats["fields"]].index("pts")
        for pid_s, sp in stats["players"].items():
            pid = int(pid_s)
            p = pos_of.get(pid)
            if not p or p not in pos_ref or pid in owner_week:       # solo chi non è mai stato in una rosa
                continue
            pts = [(int(w), v["v"][idx]) for w, v in sp["w"].items()
                   if int(w) in weeks and v["gp"] and v["v"][idx] is not None]
            if len(pts) >= 2:
                avg = statistics.mean(x for _, x in pts)
                if avg >= pos_ref[p]["mean"]:
                    free.append({"id": pid, "name": name_of.get(pid, pid_s), "pos": p, "nfl": nfl_of.get(pid),
                                 "games": len(pts), "avg": _r(avg), "pts": _r(sum(x for _, x in pts)),
                                 "above": _r(sum(x - pos_ref[p]["mean"] for _, x in pts))})
        free.sort(key=lambda x: -x["above"])
    tag_players(players, pos_ref, draft, len(weeks))
    for f in free[:12]:
        f["tags"] = ["libero"]

    ctx = ctx or {}
    extra = {
        "luck": luck(team_week, weeks, teams, ctx.get("games") or []),
        "choices": choices(by_week, weeks, teams, pos),
        "stars": stars(starts, teams),
        "tdShare": td_share(starts, teams, stats, ctx.get("tdPts") or {}),
        "market": market(tx, owner_week, teams, stats, weeks, name_of),
        "form": form(team_week, weeks, teams),
        "outlook": outlook(team_week, weeks, teams, ctx, pos_of, week_now),
    }
    return {"season": season, "weeks": weeks, "teams": teams, "teamWeek": {str(k): v for k, v in team_week.items()},
            "teamSum": team_sum, "posRef": pos_ref, "starts": starts, "bench": bench_rows, "draft": draft,
            "draftFit": {"a": _r(a, 3), "b": _r(b, 3)}, "draftTeam": draft_team,
            "players": sorted(players, key=lambda x: -(x["above"] or 0)), "free": free[:12], **extra}


# ------------------------------------------------------- 1. fortuna o bravura
def luck(team_week, weeks, teams, games):
    """Record reale contro record "tutti contro tutti": ogni giornata conta come
    se avessi giocato contro tutte le altre. La differenza è la fortuna del calendario."""
    out = {}
    for t in teams:
        ap_w = ap_l = 0.0
        for w in weeks:
            mine = team_week[t][str(w)]["tot"]
            for o in teams:
                if o == t:
                    continue
                other = team_week[o][str(w)]["tot"]
                ap_w += 1 if mine > other else .5 if mine == other else 0
                ap_l += 1 if mine < other else .5 if mine == other else 0
        real_w = real_l = 0
        pa = []
        for g in games:
            if g["w"] not in weeks or t not in (g["h"], g["a"]):
                continue
            me, op = (g["hp"], g["ap"]) if g["h"] == t else (g["ap"], g["hp"])
            pa.append(op)
            real_w += me > op
            real_l += me < op
        exp_w = ap_w / max(1, len(teams) - 1)       # vittorie attese su una partita a giornata
        out[str(t)] = {"w": real_w, "l": real_l, "apW": _r(ap_w), "apL": _r(ap_l),
                       "apPct": _r(ap_w / (ap_w + ap_l), 3) if ap_w + ap_l else None,
                       "expW": _r(exp_w, 2), "luck": _r(real_w - exp_w, 2),
                       "pa": _r(statistics.mean(pa)) if pa else None}
    return out


# --------------------------------------------- 2. proiezioni contro realtà e scelte
def choices(by_week, weeks, teams, pos):
    """Quanto i titolari hanno fatto rispetto alle proiezioni ESPN, e quanto il
    manager ha scelto meglio (o peggio) della formazione che le proiezioni suggerivano."""
    out = {}
    for t in teams:
        act = proj = by_proj = 0.0
        swaps = []
        for w in weeks:
            rows = (by_week.get(str(w)) or {}).get(str(t)) or []
            st = [r for r in rows if r["starter"] and r["slot"] != "IR"]
            act += sum(r.get("act") or 0 for r in st)
            proj += sum(r.get("proj") or 0 for r in st)
            chosen = pick_lineup(rows, pos, "proj")
            by_proj += sum(r.get("act") or 0 for r in chosen)
            ids = {r["id"] for r in st}
            for r in chosen:                         # dove il manager si è discostato dalla proiezione
                if r["id"] not in ids:
                    swaps.append(w)
        n = len(weeks) or 1
        out[str(t)] = {"act": _r(act / n), "proj": _r(proj / n), "vsProj": _r((act - proj) / n),
                       "byProj": _r(by_proj / n), "decisions": _r((act - by_proj) / n),
                       "swaps": len(swaps)}
    return out


def pick_lineup(rows, pos, key):
    """La formazione che si ottiene scegliendo per `key` (proiezione o punti veri)."""
    pool = defaultdict(list)
    for r in rows:
        if r["slot"] != "IR":
            pool[pos(r)].append(r)
    chosen, rest = [], []
    for p, n in LINEUP.items():
        v = sorted(pool.get(p, []), key=lambda r: -(r.get(key) or 0))
        chosen += v[:n]
        if p in FLEX_OK:
            rest += v[n:]
    if rest:
        chosen.append(max(rest, key=lambda r: r.get(key) or 0))
    return chosen


# ------------------------------------------------- 3. dipendenza dalle stelle
def stars(starts, teams):
    """Quota dei punti da titolare che arriva dal primo e dai primi tre giocatori."""
    out = {}
    for t in teams:
        by = defaultdict(float)
        for tt, w, pid, p, pts, sl in starts:
            if tt == t:
                by[pid] += pts or 0
        tot = sum(by.values()) or 1
        top = sorted(by.items(), key=lambda kv: -kv[1])
        out[str(t)] = {"top1": _r(top[0][1] / tot, 3) if top else None,
                       "top3": _r(sum(v for _, v in top[:3]) / tot, 3) if top else None,
                       "list": [[pid, _r(v), _r(v / tot, 3)] for pid, v in top[:5]],
                       "players": len(top)}
    return out


# --------------------------------------------------- 4. volume contro touchdown
def td_share(starts, teams, stats, td_pts):
    """Quanti punti dei titolari arrivano dai touchdown (variabili) e quanti dal
    volume: ricezioni, yard, calci e difese (più ripetibili)."""
    if not stats:
        return {}
    keys = [f[0] for f in stats["fields"]]
    ix = {k: keys.index(k) for k in ("passTd", "rushTd", "recTd", "stTd") if k in keys}
    pass_td, other_td = td_pts.get("pass", 4.0), td_pts.get("rush", 6.0)
    out = {}
    for t in teams:
        td = tot = 0.0
        by_slot = defaultdict(lambda: [0.0, 0.0])
        for tt, w, pid, p, pts, sl in starts:
            if tt != t:
                continue
            wk = ((stats["players"].get(str(pid)) or {}).get("w") or {}).get(str(w))
            v = (wk or {}).get("v") or []
            g = lambda k: (v[ix[k]] or 0) if k in ix and len(v) > ix[k] else 0
            tdp = g("passTd") * pass_td + (g("rushTd") + g("recTd") + g("stTd")) * other_td
            if p in ("K", "DST"):
                tdp = 0.0                             # per K e D/ST i TD non sono la misura giusta
            tdp = min(tdp, max(0.0, pts or 0))
            td += tdp
            tot += pts or 0
            by_slot[sl][0] += tdp
            by_slot[sl][1] += pts or 0
        out[str(t)] = {"td": _r(td), "tot": _r(tot), "share": _r(td / tot, 3) if tot else None,
                       "slot": {k: _r(a / b, 3) if b else None for k, (a, b) in by_slot.items()}}
    return out


# ------------------------------------------------------------------ 6. mercato
def market(tx, owner_week, teams, stats, weeks, name_of):
    """Saldo del mercato di ogni squadra: punti da titolare portati da chi è
    arrivato, contro i punti fatti (ovunque) da chi è stato tagliato."""
    pts_idx = [f[0] for f in stats["fields"]].index("pts") if stats else None

    def real_pts(pid, after):
        sp = (stats or {}).get("players", {}).get(str(pid))
        if not sp:
            return 0.0
        return sum((v["v"][pts_idx] or 0) for w, v in sp["w"].items()
                   if int(w) > after and int(w) in weeks and v["gp"])
    out = {}
    for t in teams:
        adds, drops = [], []
        for m in tx or []:
            if m.get("team") != t:
                continue
            wk = m.get("week") or 0
            for pid in m.get("add") or []:
                got = sum(p for w, (tt, s, p) in owner_week.get(pid, {}).items() if tt == t and s and w >= wk)
                adds.append({"id": pid, "name": name_of.get(pid, str(pid)), "week": wk, "type": m.get("type"),
                             "pts": _r(got)})
            for pid in m.get("drop") or []:
                drops.append({"id": pid, "name": name_of.get(pid, str(pid)), "week": wk,
                              "after": _r(real_pts(pid, wk))})
        gain, lost = sum(a["pts"] or 0 for a in adds), sum(d["after"] or 0 for d in drops)
        out[str(t)] = {"moves": len(adds) + len(drops), "gain": _r(gain), "lost": _r(lost), "net": _r(gain - lost),
                       "adds": sorted(adds, key=lambda x: -(x["pts"] or 0))[:6],
                       "drops": sorted(drops, key=lambda x: -(x["after"] or 0))[:6]}
    return out


# ------------------------------------------------------------- 7. andamento
def form(team_week, weeks, teams):
    """Media delle ultime tre giornate contro la stagione, totale e posto per posto."""
    out = {}
    last = weeks[-3:]
    for t in teams:
        tw = team_week[t]
        tot = [tw[str(w)]["tot"] for w in weeks]
        roll = [_r(statistics.mean(tot[max(0, i - 2):i + 1])) for i in range(len(tot))]
        slot = {}
        for sl in SLOTS:
            allv = [tw[str(w)]["slot"].get(sl, 0) for w in weeks]
            lv = [tw[str(w)]["slot"].get(sl, 0) for w in last]
            slot[sl] = {"season": _r(statistics.mean(allv)) if allv else None,
                        "last3": _r(statistics.mean(lv)) if lv else None}
        out[str(t)] = {"roll": roll, "season": _r(statistics.mean(tot)) if tot else None,
                       "last3": _r(statistics.mean([tw[str(w)]["tot"] for w in last])) if last else None, "slot": slot}
    return out


# --------------------------------------------- 5. resto della stagione e playoff
def outlook(team_week, weeks, teams, ctx, pos_of, week_now, sims=20000):
    """Simula le giornate che mancano e i playoff, e misura il calendario che
    attende ogni rosa (difese avversarie e bye).

    Modello: il punteggio di una squadra in una giornata è una normale con media
    pari alla sua media stagionale avvicinata a quella della lega (poche giornate
    giocate = molto rumore) e scarto tipico di una giornata fantasy. In ogni
    stagione simulata anche la forza di ogni squadra è estratta a caso, per tenere
    conto di quanto poco sappiamo dopo poche giornate. Le partite vengono dal
    calendario ESPN, i playoff dalle regole della lega (seed per record)."""
    games = ctx.get("games") or []
    reg_weeks = ctx.get("regWeeks") or 15
    n_po = ctx.get("playoffTeams") or 4
    if not weeks:
        return {}
    tots = {t: [team_week[t][str(w)]["tot"] for w in weeks] for t in teams}
    lg_mean = statistics.mean([x for v in tots.values() for x in v])
    # scarto di una giornata: quello misurato con poche giornate è troppo basso,
    # quindi non si scende sotto il 17% della media (tipico di una giornata fantasy)
    sd = max(statistics.pstdev([x - statistics.mean(v) for v in tots.values() for x in v]), 0.17 * lg_mean)
    k = 5.0                                          # quante giornate "vale" la media della lega
    mu = {t: (sum(v) + k * lg_mean) / (len(v) + k) for t, v in tots.items()}
    # quanto siamo incerti sulla forza vera di ogni squadra
    mu_sd = {t: sd / math.sqrt(len(v) + k) for t, v in tots.items()}
    done = set(weeks)
    rec0 = {t: [0, 0, 0.0] for t in teams}           # vittorie, sconfitte, punti fatti
    left = []
    for g in games:
        if g["w"] > reg_weeks:
            continue
        if g["w"] in done:
            h, a = g["h"], g["a"]
            rec0[h][0 if g["hp"] > g["ap"] else 1] += 1
            rec0[a][0 if g["ap"] > g["hp"] else 1] += 1
            rec0[h][2] += g["hp"]
            rec0[a][2] += g["ap"]
        else:
            left.append((g["h"], g["a"]))
    rng = random.Random(2026)
    seed_n = {t: [0] * len(teams) for t in teams}
    title = {t: 0 for t in teams}
    final = {t: 0 for t in teams}
    wins = {t: 0.0 for t in teams}
    for _ in range(sims):
        m = {t: rng.gauss(mu[t], mu_sd[t]) for t in teams}    # la forza di ognuno in questa stagione simulata
        rec = {t: list(v) for t, v in rec0.items()}
        for h, a in left:
            sh, sa = rng.gauss(m[h], sd), rng.gauss(m[a], sd)
            rec[h][0 if sh > sa else 1] += 1
            rec[a][0 if sa > sh else 1] += 1
            rec[h][2] += sh
            rec[a][2] += sa
        order = sorted(teams, key=lambda t: (-rec[t][0], -rec[t][2]))
        for i, t in enumerate(order):
            seed_n[t][i] += 1
            wins[t] += rec[t][0]
        seeds = order[:n_po]
        if len(seeds) >= 4:
            semi = [(seeds[0], seeds[3]), (seeds[1], seeds[2])]
            fin = [x if rng.gauss(m[x], sd) > rng.gauss(m[y], sd) else y for x, y in semi]
        else:
            fin = seeds[:2]
        for t in fin:
            final[t] += 1
        champ = fin[0] if rng.gauss(m[fin[0]], sd) > rng.gauss(m[fin[1]], sd) else fin[1]
        title[champ] += 1
    sim = {str(t): {"mu": _r(mu[t]), "expW": _r(wins[t] / sims, 1), "seed": [_r(c / sims, 3) for c in seed_n[t]],
                    "final": _r(final[t] / sims, 3), "title": _r(title[t] / sims, 3),
                    "w": rec0[t][0], "l": rec0[t][1]} for t in teams}

    # calendario che attende ogni rosa: difese avversarie posto per posto e bye
    sched, fpa = ctx.get("sched") or {}, ctx.get("fpa") or {}
    lineups, nfl_of = ctx.get("lineups") or {}, ctx.get("nfl") or {}
    first = (max(weeks) + 1) if weeks else week_now
    po_weeks = [reg_weeks + i for i in range(1, 3)]
    rest = list(range(first, reg_weeks + 1))
    sos = {}
    for t in teams:
        rows = [r for r in (lineups.get(str(t)) or lineups.get(t) or []) if r["slot"] not in ("IR",)]
        st = [r for r in rows if r["starter"]]
        def ease(wks, rr):
            vals = []
            for r in rr:
                p, team = pos_of.get(r["id"]), nfl_of.get(r["id"])
                if p not in ("QB", "RB", "WR", "TE") or not team:
                    continue
                for w in wks:
                    opp = ((sched.get(team) or {}).get("opp") or {}).get(str(w))
                    if not opp:
                        continue
                    ratio = ((fpa.get(opp.lstrip("@")) or {}).get(p) or {}).get("ratio")
                    if ratio:
                        vals.append(ratio)
            return _r(statistics.mean(vals), 3) if vals else None
        byes = defaultdict(list)
        for r in st:
            team = nfl_of.get(r["id"])
            b = (sched.get(team) or {}).get("bye")
            if b and first <= b <= reg_weeks:
                byes[b].append(r["id"])
        sos[str(t)] = {"rest": ease(rest, st), "playoff": ease(po_weeks, st), "next3": ease(rest[:3], st),
                       "byes": {str(w): ids for w, ids in sorted(byes.items())}}
    return {"sims": sims, "mu": _r(lg_mean), "sd": _r(sd), "left": len(left), "firstWeek": first,
            "regWeeks": reg_weeks, "poWeeks": po_weeks, "sim": sim, "sos": sos}



def tag_players(players, pos_ref, draft, n_weeks):
    """Etichette da analista: chi ha fatto la differenza, e perché."""
    early = [d for d in draft if d["pick"] <= 24]
    worst_early = {d["id"] for d in sorted(early, key=lambda d: d["res"])[:5]}
    steals = {d["id"] for d in sorted(draft, key=lambda d: -d["res"])[:6] if d["res"] > 0}
    by_pos = defaultdict(list)
    for p in players:
        if p["games"] >= 2 and p["avg"] is not None:
            by_pos[p["pos"]].append(p)
    stars = set()
    for pos, lst in by_pos.items():
        ref = (pos_ref.get(pos) or {}).get("mean") or 0
        for p in sorted(lst, key=lambda x: -x["avg"])[:2]:
            if p["avg"] >= ref * 1.3:
                stars.add(p["id"])
    top_bench = {p["id"] for p in sorted(players, key=lambda x: -(x["bench"] or 0))[:6] if (p["bench"] or 0) >= 25}
    for p in players:
        ref = (pos_ref.get(p["pos"]) or {}).get("mean") or 0
        t = []
        if p["id"] in stars:
            t.append("fuoriclasse")
        if p["booms"] >= 2:
            t.append("esplosivo")
        if p["cv"] is not None and p["cv"] <= 0.25 and (p["avg"] or 0) >= ref:
            t.append("costante")
        if p["acq"] and p["starts"] >= 2 and (p["avg"] or 0) >= ref:
            t.append("waiver")
        if p["id"] in steals:
            t.append("furto")
        if p["id"] in worst_early:
            t.append("delusione")
        if p["id"] in top_bench:
            t.append("panchina")
        later = [w for w, v in p["byWeek"].items() if v[0] != (p["teams"][0] if p["teams"] else None)]
        if p["dropped"] and later and sum(v[2] or 0 for w, v in p["byWeek"].items() if w in later and v[1]) >= 20:
            t.append("scartato")
        p["tags"] = t


def save(review):
    """Archivio della stagione: si aggiorna durante l'anno e resta per i successivi."""
    os.makedirs(HISTORY, exist_ok=True)
    path = os.path.join(HISTORY, f"season_{review['season']}.json")
    keep = {k: review[k] for k in ("season", "weeks", "teamSum", "posRef", "draft", "draftTeam", "players", "free")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, separators=(",", ":"))
    return path


def load_history(before):
    """Le stagioni archiviate prima di `before`, per la draft room."""
    out = {}
    if not os.path.isdir(HISTORY):
        return out
    for name in sorted(os.listdir(HISTORY)):
        if name.startswith("season_") and name.endswith(".json"):
            y = int(name[7:11])
            if y < before:
                with open(os.path.join(HISTORY, name), encoding="utf-8") as f:
                    out[str(y)] = json.load(f)
                out[str(y)]["notes"] = load_notes(y)      # stelle e appunti di quella stagione
    return out


def load_notes(season):
    path = os.path.join(HISTORY, f"notes_{season}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)
