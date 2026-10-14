#!/usr/bin/env python3
"""Statistiche della stagione in corso, unite dalle quattro fonti.

La regola è una sola: per ogni campo vince ESPN se lo fornisce, poi Sleeper,
poi nflverse. FFC dà solo l'ADP e DynastyProcess solo la tabella degli id,
quindi qui non compaiono.

Ogni valore porta la sua fonte (E, S, N), giornata per giornata, così la
scheda del giocatore può dire da dove arriva ogni numero.

Corrispondenza dei codici ESPN: ricavata confrontando i valori sulle stesse
partite con nflverse e con Sleeper (vedi README). Sono usati solo i codici che
coincidono almeno nel 99% dei casi; quelli che ESPN usa come soglie di
punteggio (bonus 40+ yard, "ogni 5 completi" e simili) sono esclusi.
"""
import glob, json, os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")

# chiave, etichetta, gruppo, codice ESPN, campo Sleeper, colonna nflverse, tipo
#   tipo: sum = si somma sulla stagione · max = il massimo · rate = rapporto,
#   non si somma (il valore di stagione arriva dal file stagionale o si ricalcola)
#   La colonna nflverse "snap:" legge snap_counts, "ngs:" i Next Gen Stats.
FIELDS = [
    ("pts", "Punti fantasy", "Fantasy", "PTS", "pts_ppr", "fantasy_points_ppr", "sum"),
    ("posRank", "Posizione nel ruolo", "Fantasy", None, "pos_rank_ppr", None, "rate"),

    ("passAtt", "Tentativi", "Passaggi", 0, "pass_att", "attempts", "sum"),
    ("passCmp", "Completi", "Passaggi", 1, "pass_cmp", "completions", "sum"),
    ("passInc", "Incompleti", "Passaggi", 2, "pass_inc", None, "sum"),
    ("passYds", "Yard", "Passaggi", 3, "pass_yd", "passing_yards", "sum"),
    ("passTd", "Touchdown", "Passaggi", 4, "pass_td", "passing_tds", "sum"),
    ("passInt", "Intercetti", "Passaggi", 20, "pass_int", "passing_interceptions", "sum"),
    ("pass2pt", "Conversioni da 2", "Passaggi", 19, "pass_2pt", "passing_2pt_conversions", "sum"),
    ("passSack", "Sack subiti", "Passaggi", 64, "pass_sack", "sacks_suffered", "sum"),
    ("passSackYds", "Yard perse nei sack", "Passaggi", None, "pass_sack_yds", "sack_yards_lost", "sum"),
    ("passFd", "Primi down", "Passaggi", 211, None, "passing_first_downs", "sum"),
    ("passAir", "Air yards", "Passaggi", None, "pass_air_yd", "passing_air_yards", "sum"),
    ("passYacT", "Yard dopo la ricezione dei compagni", "Passaggi", None, None, "passing_yards_after_catch", "sum"),
    ("passRzAtt", "Tentativi in red zone", "Passaggi", None, "pass_rz_att", None, "sum"),
    ("passLng", "Passaggio più lungo", "Passaggi", None, "pass_lng", None, "max"),
    ("passTd40", "TD da 40+ yard", "Passaggi", None, "pass_td_40p", None, "sum"),
    ("passRtg", "Passer rating", "Passaggi", None, "pass_rtg", None, "rate"),
    ("passEpa", "EPA sui passaggi", "Passaggi", None, None, "passing_epa", "sum"),
    ("passCpoe", "CPOE", "Passaggi", None, None, "passing_cpoe", "rate"),
    ("pacr", "PACR", "Passaggi", None, None, "pacr", "rate"),
    ("dakota", "DAKOTA", "Passaggi", None, None, "dakota", "rate"),

    ("rushAtt", "Corse", "Corse", 23, "rush_att", "carries", "sum"),
    ("rushYds", "Yard", "Corse", 24, "rush_yd", "rushing_yards", "sum"),
    ("rushTd", "Touchdown", "Corse", 25, "rush_td", "rushing_tds", "sum"),
    ("rush2pt", "Conversioni da 2", "Corse", None, "rush_2pt", "rushing_2pt_conversions", "sum"),
    ("rushFd", "Primi down", "Corse", 212, None, "rushing_first_downs", "sum"),
    ("rushRz", "Corse in red zone", "Corse", None, "rush_rz_att", None, "sum"),
    ("rushYac", "Yard dopo il contatto", "Corse", None, "rush_yac", None, "sum"),
    ("rushBtkl", "Placcaggi evitati", "Corse", None, "rush_btkl", None, "sum"),
    ("rushTfl", "Corse chiuse in perdita", "Corse", None, "rush_tkl_loss", None, "sum"),
    ("rushLng", "Corsa più lunga", "Corse", None, "rush_lng", None, "max"),
    ("rush40", "Corse da 40+ yard", "Corse", None, "rush_40p", "rushing_40", "sum"),
    ("rushEpa", "EPA sulle corse", "Corse", None, None, "rushing_epa", "sum"),

    ("tgt", "Target", "Ricezioni", 58, "rec_tgt", "targets", "sum"),
    ("rec", "Ricezioni", "Ricezioni", 53, "rec", "receptions", "sum"),
    ("recYds", "Yard", "Ricezioni", 42, "rec_yd", "receiving_yards", "sum"),
    ("recTd", "Touchdown", "Ricezioni", 43, "rec_td", "receiving_tds", "sum"),
    ("rec2pt", "Conversioni da 2", "Ricezioni", 44, "rec_2pt", "receiving_2pt_conversions", "sum"),
    ("recFd", "Primi down", "Ricezioni", 213, None, "receiving_first_downs", "sum"),
    ("recYac", "Yard dopo la ricezione", "Ricezioni", 59, "rec_yar", "receiving_yards_after_catch", "sum"),
    ("recAir", "Air yards", "Ricezioni", None, "rec_air_yd", "receiving_air_yards", "sum"),
    ("recRz", "Target in red zone", "Ricezioni", None, "rec_rz_tgt", None, "sum"),
    ("recDrop", "Palloni persi (drop)", "Ricezioni", None, "rec_drop", None, "sum"),
    ("recLng", "Ricezione più lunga", "Ricezioni", None, "rec_lng", None, "max"),
    ("rec0", "Ricezioni da 0-4 yard", "Ricezioni", None, "rec_0_4", None, "sum"),
    ("rec5", "Ricezioni da 5-9 yard", "Ricezioni", None, "rec_5_9", None, "sum"),
    ("rec10", "Ricezioni da 10-19 yard", "Ricezioni", None, "rec_10_19", None, "sum"),
    ("rec20", "Ricezioni da 20-29 yard", "Ricezioni", None, "rec_20_29", None, "sum"),
    ("rec30", "Ricezioni da 30-39 yard", "Ricezioni", None, "rec_30_39", None, "sum"),
    ("rec40", "Ricezioni da 40+ yard", "Ricezioni", None, "rec_40p", "receiving_40", "sum"),
    ("tgtShare", "Quota target", "Ricezioni", None, None, "target_share", "rate"),
    ("airShare", "Quota air yards", "Ricezioni", None, None, "air_yards_share", "rate"),
    ("wopr", "WOPR", "Ricezioni", None, None, "wopr", "rate"),
    ("racr", "RACR", "Ricezioni", None, None, "racr", "rate"),
    ("recEpa", "EPA sulle ricezioni", "Ricezioni", None, None, "receiving_epa", "sum"),

    ("offSnp", "Snap in attacco", "Utilizzo", None, "off_snp", "snap:offense_snaps", "sum"),
    ("tmOffSnp", "Snap d'attacco della squadra", "Utilizzo", None, "tm_off_snp", None, "sum"),
    ("snapPct", "Quota snap in attacco", "Utilizzo", None, None, "snap:offense_pct", "rate"),
    ("stSnp", "Snap negli special team", "Utilizzo", None, "st_snp", "snap:st_snaps", "sum"),
    ("h1Yds", "Yard nel primo tempo", "Utilizzo", None, None, None, "sum"),

    ("fum", "Fumble", "Palla persa e ritorni", 68, "fum", "fumbles_total", "sum"),
    ("fumLost", "Fumble persi", "Palla persa e ritorni", 72, "fum_lost", "fumbles_lost_total", "sum"),
    ("krYds", "Yard su ritorni di kickoff", "Palla persa e ritorni", 114, "kr_yd", "kickoff_return_yards", "sum"),
    ("prYds", "Yard su ritorni di punt", "Palla persa e ritorni", 115, "pr_yd", "punt_return_yards", "sum"),
    ("stTd", "TD negli special team", "Palla persa e ritorni", None, None, "special_teams_tds", "sum"),

    ("fgm", "Field goal segnati", "Kicker", 83, "fgm", "fg_made", "sum"),
    ("fga", "Field goal tentati", "Kicker", 84, "fga", "fg_att", "sum"),
    ("fgMiss", "Field goal sbagliati", "Kicker", 85, "fgmiss", "fg_missed", "sum"),
    ("fgm20", "Segnati da 20-29", "Kicker", None, "fgm_20_29", "fg_made_20_29", "sum"),
    ("fgm30", "Segnati da 30-39", "Kicker", None, "fgm_30_39", "fg_made_30_39", "sum"),
    ("fgm40", "Segnati da 40-49", "Kicker", 77, "fgm_40_49", "fg_made_40_49", "sum"),
    ("fgm50", "Segnati da 50+", "Kicker", 74, "fgm_50p", None, "sum"),
    ("fgMiss50", "Sbagliati da 50+", "Kicker", 76, "fgmiss_50p", None, "sum"),
    ("fgLng", "Field goal più lungo", "Kicker", None, "fgm_lng", "fg_long", "max"),
    ("fgYds", "Yard dei field goal segnati", "Kicker", 214, "fgm_yds", None, "sum"),
    ("xpm", "Extra point segnati", "Kicker", 86, "xpm", "pat_made", "sum"),
    ("xpa", "Extra point tentati", "Kicker", 87, "xpa", "pat_att", "sum"),

    ("dSack", "Sack", "Difesa", 99, "sack", None, "sum"),
    ("dInt", "Intercetti", "Difesa", 95, "int", None, "sum"),
    ("dFumRec", "Fumble recuperati", "Difesa", None, "fum_rec", None, "sum"),
    ("dFf", "Fumble forzati", "Difesa", None, "ff", None, "sum"),
    ("dTd", "Touchdown difensivi", "Difesa", 94, "def_td", None, "sum"),
    ("dBlk", "Calci bloccati", "Difesa", 97, "blk_kick", None, "sum"),
    ("dPd", "Passaggi deviati", "Difesa", 113, "def_pass_def", None, "sum"),
    ("dQbHit", "Colpi sul QB", "Difesa", None, "qb_hit", None, "sum"),
    ("dTfl", "Placcaggi in perdita", "Difesa", None, "tkl_loss", None, "sum"),
    ("dPa", "Punti concessi", "Difesa", 120, "pts_allow", None, "sum"),
    ("dYa", "Yard concesse", "Difesa", 127, "yds_allow", None, "sum"),
    ("d3out", "Tre-e-fuori forzati", "Difesa", None, "def_3_and_out", None, "sum"),
]

# Next Gen Stats: solo nflverse le ha, e sono già medie (non si sommano)
NGS = {
    "receiving": [("ngsSep", "Separazione media (yard)", "avg_separation"),
                  ("ngsCush", "Cushion medio (yard)", "avg_cushion"),
                  ("ngsIay", "Profondità media dei target", "avg_intended_air_yards"),
                  ("ngsYacOe", "YAC oltre l'atteso", "avg_yac_above_expectation"),
                  ("ngsAyShare", "Quota air yards intenzionali", "percent_share_of_intended_air_yards")],
    "rushing": [("ngsRyoe", "Yard oltre l'atteso per corsa", "rush_yards_over_expected_per_att"),
                ("ngsEff", "Efficienza (yard percorse per yard guadagnata)", "efficiency"),
                ("ngsBox8", "Corse contro 8+ in box (%)", "percent_attempts_gte_eight_defenders"),
                ("ngsTlos", "Tempo alla linea (s)", "avg_time_to_los")],
    "passing": [("ngsTtt", "Tempo di lancio (s)", "avg_time_to_throw"),
                ("ngsAgg", "Aggressività (%)", "aggressiveness"),
                ("ngsCpoe", "Completi oltre l'atteso (%)", "completion_percentage_above_expectation"),
                ("ngsCay", "Air yards per completo", "avg_completed_air_yards")],
}
for kind, lst in NGS.items():
    for key, label, _ in lst:
        FIELDS.append((key, label, "Next Gen Stats", None, None, f"ngs:{kind}", "rate"))

KEYS = [f[0] for f in FIELDS]
IDX = {k: i for i, k in enumerate(KEYS)}


def _jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _num(v):
    if v in (None, "", "NA"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _round(v):
    if v is None:
        return None
    return round(v, 3) if abs(v) < 10 else round(v, 1)


# ------------------------------------------------------------- lettura fonti
def espn_weeks():
    """ESPN: {(id, giornata): (punti, {codice: valore})} dai payload del pool."""
    out = {}
    paths = [os.path.join(RAW, "espn_players.json")] + sorted(glob.glob(os.path.join(RAW, "espn_week_*.json")))
    for path in paths:
        if not os.path.exists(path):
            continue
        for e in (_jload(path).get("players") or []):
            p = e.get("player") or {}
            for s in p.get("stats") or []:
                if s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 1 and s.get("scoringPeriodId"):
                    out[(p["id"], s["scoringPeriodId"])] = (
                        s.get("appliedTotal"), {int(k): v for k, v in (s.get("stats") or {}).items()})
    return out


def sleeper_weeks(season, sleeper_to_espn, abbr_to_dst):
    """Sleeper: {(id ESPN, giornata): {campo: valore}}. Le difese hanno per id la sigla."""
    out = {}
    for path in sorted(glob.glob(os.path.join(RAW, "sleeper", f"stats_{season}_w*.json"))):
        wk = int(path.rsplit("_w", 1)[1].split(".")[0])
        for e in _jload(path):
            sid = str(e.get("player_id"))
            eid = sleeper_to_espn.get(sid) or abbr_to_dst.get(sid)
            if eid is not None and e.get("stats"):
                out[(eid, wk)] = e["stats"]
    return out


def nflverse_weeks(season, gsis_to_espn, pfr_to_espn, rows, ab):
    """nflverse: tabellino, snap e Next Gen Stats per (id ESPN, giornata)."""
    out = defaultdict(dict)
    path = os.path.join(RAW, "nflverse", f"stats_player_week_{season}.csv")
    if os.path.exists(path):
        for r in rows(path):
            eid = gsis_to_espn.get(r.get("player_id"))
            if eid is not None and (r.get("season_type") or "REG") == "REG":
                out[(eid, int(r["week"]))].update(r)
    path = os.path.join(RAW, "nflverse", f"snap_counts_{season}.csv")
    if os.path.exists(path):
        for r in rows(path):
            eid = pfr_to_espn.get(r.get("pfr_player_id"))
            if eid is not None and (r.get("game_type") or "REG") == "REG":
                d = out[(eid, int(r["week"]))]
                d["snap:offense_snaps"] = r.get("offense_snaps")
                d["snap:st_snaps"] = r.get("st_snaps")
                v = _num(r.get("offense_pct"))
                d["snap:offense_pct"] = None if v is None else v
    season_ngs = defaultdict(dict)
    for kind, lst in NGS.items():
        path = os.path.join(RAW, "nflverse", f"ngs_{kind}.csv.gz")
        if not os.path.exists(path):
            continue
        for r in rows(path):
            if str(r.get("season")) != str(season) or (r.get("season_type") or "REG") != "REG":
                continue
            eid = gsis_to_espn.get(r.get("player_gsis_id"))
            if eid is None:
                continue
            wk = int(_num(r.get("week")) or 0)
            vals = {f"ngs:{kind}:{col}": r.get(col) for _, _, col in lst}
            (season_ngs[eid] if wk == 0 else out[(eid, wk)]).update(vals)
    return out, season_ngs


def nflverse_season(season, gsis_to_espn, rows):
    """I rapporti di stagione che nflverse calcola sul totale (quota target, WOPR…)."""
    out = {}
    path = os.path.join(RAW, "nflverse", f"stats_player_reg_{season}.csv")
    if os.path.exists(path):
        for r in rows(path):
            eid = gsis_to_espn.get(r.get("player_id"))
            if eid is not None:
                out[eid] = r
    return out


# ------------------------------------------------------------------- unione
def _ngs_col(field):
    """Per un campo NGS restituisce la chiave usata in nflverse_weeks."""
    key, _, _, _, _, col, _ = field
    for kind, lst in NGS.items():
        for k, _, c in lst:
            if k == key:
                return f"ngs:{kind}:{c}"
    return col


def _pick(field, espn, sleeper, nfl):
    """Il valore del campo e la sua fonte, seguendo la priorità."""
    key, _, _, eid, skey, ncol, typ = field
    # ESPN e Sleeper non scrivono le statistiche a zero: se la fonte ha il
    # tabellino di quella giornata, un conteggio assente vale 0 per lei.
    # Per i rapporti invece l'assenza vuol dire "non calcolato".
    zero = typ in ("sum", "max")
    if espn is not None:
        pts, st = espn
        if eid == "PTS" and pts is not None:
            return pts, "E"
        if isinstance(eid, int) and (eid in st or zero):
            return st.get(eid, 0), "E"
    if sleeper is not None and skey and (skey in sleeper or zero):
        return sleeper.get(skey, 0), "S"
    if nfl is not None and ncol:
        col = _ngs_col(field) if ncol.startswith("ngs:") else ncol
        v = _num(nfl.get(col))
        if v is not None:
            return v, "N"
    return None, "-"


def build(season, week_now, ids, pool, rows, ab, team_by_id, rz_extra=None):
    """Statistiche unite: {"fields": [...], "players": {id: {...}}}.

    `ids` è il crosswalk espn_id -> {gsis, sleeper, pfr}; `rz_extra` sono i dati
    di red zone ricavati dal play-by-play, usati solo dove le fonti mancano.
    """
    wanted = {p["id"] for p in pool}
    gsis_to_espn, pfr_to_espn, sleeper_to_espn = {}, {}, {}
    for e, x in ids.items():
        e = int(e)
        if x.get("gsis"):
            gsis_to_espn[x["gsis"]] = e
        if x.get("pfr"):
            pfr_to_espn[x["pfr"]] = e
        if x.get("sleeper"):
            sleeper_to_espn[str(x["sleeper"])] = e
    sp_path = os.path.join(RAW, "sleeper_players.json")
    if os.path.exists(sp_path):                      # Sleeper conosce anche l'id ESPN di molti giocatori
        for sid, p in _jload(sp_path).items():
            if p.get("espn_id"):
                sleeper_to_espn.setdefault(str(sid), int(p["espn_id"]))
    abbr_to_dst = {}
    for tid, a in team_by_id.items():
        if tid:
            abbr_to_dst[a] = -16000 - tid
            for alt, std in (("WAS", "WSH"), ("JAC", "JAX"), ("LA", "LAR")):
                if std == a:
                    abbr_to_dst[alt] = -16000 - tid

    E = espn_weeks()
    S = sleeper_weeks(season, sleeper_to_espn, abbr_to_dst)
    N, NGS_SEASON = nflverse_weeks(season, gsis_to_espn, pfr_to_espn, rows, ab)
    NS = nflverse_season(season, gsis_to_espn, rows)

    players = {}
    for pid in wanted:
        weeks = {}
        for wk in range(1, week_now + 1):
            e, s, n = E.get((pid, wk)), S.get((pid, wk)), N.get((pid, wk))
            if e is None and s is None and n is None:
                continue
            vals, src = [], []
            for f in FIELDS:
                v, c = _pick(f, e, s, n)
                vals.append(_round(_num(v)) if v is not None else None)
                src.append(c)
            # yard nel primo tempo: Sleeper le divide per tipo
            if s is not None:
                h1 = sum((s.get(k) or 0) for k in ("h1_pass_yd", "h1_rush_yd", "h1_rec_yd"))
                if any(k in s for k in ("h1_pass_yd", "h1_rush_yd", "h1_rec_yd")):
                    vals[IDX["h1Yds"]], src[IDX["h1Yds"]] = _round(h1), "S"
            # quota snap: dagli snap di Sleeper se ci sono, altrimenti nflverse
            i_o, i_t, i_p = IDX["offSnp"], IDX["tmOffSnp"], IDX["snapPct"]
            if vals[i_o] is not None and vals[i_t]:
                vals[i_p], src[i_p] = _round(vals[i_o] / vals[i_t]), src[i_o]
            # red zone: dal play-by-play solo se Sleeper non la dà
            z = (rz_extra or {}).get(pid, {}).get(str(wk))
            if z:
                for k, zk in (("recRz", "tgt"), ("rushRz", "car")):
                    if vals[IDX[k]] is None and z.get(zk) is not None:
                        vals[IDX[k]], src[IDX[k]] = z[zk], "N"
            # giocata o no: ESPN con qualche statistica, o Sleeper che la segna
            played = bool(s and s.get("gp")) or bool(e and any(v for v in e[1].values()))
            weeks[str(wk)] = {"v": vals, "s": "".join(src), "gp": played}
        if not weeks:
            continue
        players[str(pid)] = {"w": weeks, **_season(weeks, NS.get(pid), NGS_SEASON.get(pid))}
    return {"fields": [[k, l, g, t] for k, l, g, _, _, _, t in FIELDS], "players": players,
            "weeks": week_now}


def _season(weeks, ns_row, ngs_row):
    """Totali e rapporti di stagione, con l'elenco delle fonti usate."""
    vals, src = [], []
    played = [w for w in weeks.values() if w["gp"]]
    for i, (key, _, _, _, _, ncol, typ) in enumerate(FIELDS):
        col = [(w["v"][i], w["s"][i]) for w in played if w["v"][i] is not None]
        used = "".join(sorted({c for _, c in col}, key="ESN".index))
        if typ == "sum":
            vals.append(_round(sum(v for v, _ in col)) if col else None)
            src.append(used or "-")
        elif typ == "max":
            vals.append(max(v for v, _ in col) if col else None)
            src.append(used or "-")
        else:
            v = None
            if ncol and ncol.startswith("ngs:") and ngs_row:
                v = _num(ngs_row.get(_ngs_col(FIELDS[i])))
            elif ncol and not ncol.startswith(("snap:", "ngs:")) and ns_row:
                v = _num(ns_row.get(ncol))
            vals.append(_round(v))
            src.append("N" if v is not None else "-")
    g = len(played)
    t = lambda k: vals[IDX[k]]
    # rapporti ricalcolati dai totali uniti: così seguono la priorità delle fonti
    if t("offSnp") is not None and t("tmOffSnp"):
        vals[IDX["snapPct"]], src[IDX["snapPct"]] = _round(t("offSnp") / t("tmOffSnp")), src[IDX["offSnp"]]
    elif played:
        sp = [w["v"][IDX["snapPct"]] for w in played if w["v"][IDX["snapPct"]] is not None]
        if sp:
            vals[IDX["snapPct"]], src[IDX["snapPct"]] = _round(sum(sp) / len(sp)), "N"
    if t("passAtt"):
        a, c, y, td, it = t("passAtt"), t("passCmp") or 0, t("passYds") or 0, t("passTd") or 0, t("passInt") or 0
        clamp = lambda x: max(0, min(2.375, x))
        rating = (clamp((c / a - .3) * 5) + clamp((y / a - 3) * .25) + clamp(td / a * 20)
                  + clamp(2.375 - it / a * 25)) / 6 * 100
        vals[IDX["passRtg"]], src[IDX["passRtg"]] = _round(rating), src[IDX["passAtt"]]
    return {"season": vals, "seasonSrc": "|".join(src), "gp": g}


# ------------------------------------------- dati derivati per le altre pagine
def value(m, pid, key, wk=None):
    """Un valore unito: di stagione, o di una giornata se `wk` è dato."""
    p = m["players"].get(str(pid))
    if not p:
        return None
    if wk is None:
        return p["season"][IDX[key]]
    w = p["w"].get(str(wk))
    return w["v"][IDX[key]] if w else None


def adv_overrides(m, pid):
    """I campi stagionali che le pagine già usano, ricalcolati con la priorità
    ESPN → Sleeper → nflverse. Quota target, WOPR, RACR ed EPA non li tocca:
    li fornisce solo nflverse e restano quelli."""
    p = m["players"].get(str(pid))
    if not p or not p["gp"]:
        return None
    g = p["gp"]
    v = lambda k: p["season"][IDX[k]]
    tgt, rec, car = v("tgt") or 0, v("rec") or 0, v("rushAtt") or 0
    r = lambda x, d=1: None if x is None else round(x, d)
    out = {"gp": g, "fpg": r((v("pts") or 0) / g), "tgtPerGame": r(tgt / g),
           "carriesPerGame": r(car / g), "recTd": int(v("recTd") or 0), "rushTd": int(v("rushTd") or 0),
           "ydsPerTgt": r((v("recYds") or 0) / tgt) if tgt else None,
           "ydsPerCarry": r((v("rushYds") or 0) / car) if car else None,
           "catchRate": r(rec / tgt, 2) if tgt else None,
           "wk": [w["v"][IDX["pts"]] for k, w in sorted(p["w"].items(), key=lambda kv: int(kv[0])) if w["gp"]]}
    if v("snapPct") is not None:
        out["snapPct"] = r(v("snapPct"), 3)
    return out
