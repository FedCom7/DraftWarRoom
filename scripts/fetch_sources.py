#!/usr/bin/env python3
"""Scarica tutte le sorgenti pubbliche in data/raw/.

Nessuna dipendenza dal progetto Topina: ogni file qui dentro viene da un URL
pubblico, interrogato da questo script. L'unico dato che NON si scarica è lo
storico 2019-2025, che sta in data/vendor/ (vedi il README lì).

Uso:  python3 scripts/fetch_sources.py [--season 2026]
"""
import argparse, json, os, sys, time, urllib.request, urllib.error, gzip, io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
LEAGUE_ID = os.environ.get("ESPN_LEAGUE_ID", "1948241900")   # Topina, lega pubblica
ESPN = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
UA = {"User-Agent": "Mozilla/5.0 (DraftWarRoom data build)"}


def get(url, headers=None, tries=3, timeout=90, ua=True):
    """GET con retry. Restituisce i byte grezzi.

    `ua=False` per le API sportive di ESPN: rispondono 403 se ricevono uno
    user agent da browser, mentre accettano quello di default di urllib.
    """
    h = dict(UA) if ua else {}
    h.update(headers or {})
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                      # noqa: BLE001 - qualunque errore merita un retry
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fallito {url}: {last}")


def save(name, data, label=None):
    path = os.path.join(RAW, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    print(f"  {label or name}: {len(data)/1024:.0f} KB")
    return path


# Registro dei file di giornata: per ognuno, la giornata in corso quando è stato
# scaricato. Un file è definitivo solo se scaricato almeno due giornate dopo la
# sua (partite finite e correzioni del lunedì incluse); altrimenti si riscarica.
# Senza registro un tabellino preso prima delle partite restava a zero per sempre.
FETCHED = os.path.join(RAW, "_fetched.json")


def _registry():
    try:
        with open(FETCHED, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def is_final(name, wk):
    return os.path.exists(os.path.join(RAW, name)) and _registry().get(name, 0) >= wk + 2


def mark(name, week_now):
    reg = _registry()
    reg[name] = week_now
    with open(FETCHED, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=0, sort_keys=True)


def espn_league(season, views, fname, fantasy_filter=None, extra=""):
    q = "&".join(f"view={v}" for v in views)
    url = f"{ESPN}/seasons/{season}/segments/0/leagues/{LEAGUE_ID}?{q}{extra}"
    headers = {"X-Fantasy-Filter": json.dumps(fantasy_filter)} if fantasy_filter else None
    return save(fname, get(url, headers), f"ESPN {'+'.join(views)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=int(os.environ.get("SEASON", 2026)))
    a = ap.parse_args()
    y = a.season
    prev = y - 1
    os.makedirs(RAW, exist_ok=True)

    print(f"ESPN — lega {LEAGUE_ID}, stagione {y}")
    espn_league(y, ["mSettings", "mTeam", "mDraftDetail", "mRoster"], "espn_league.json")
    espn_league(y, ["mMatchupScore"], "espn_schedule.json")
    # pool giocatori ordinato per percentuale di possesso: i waiver interessanti
    # stanno fuori dai primi 240 per ranking, quindi si allarga a 520.
    espn_league(y, ["kona_player_info"], "espn_players.json",
                {"players": {"limit": 520, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}})
    save("espn_proteams.json", get(f"{ESPN}/seasons/{y}?view=proTeamSchedules_wl"), "ESPN calendario NFL")
    # proiezioni ufficiali ESPN giornata per giornata: il pool va richiesto una
    # volta per ogni scoringPeriodId, altrimenti torna solo la settimana in corso.
    week_now = json.loads(open(os.path.join(RAW, "espn_league.json"), encoding="utf-8").read()).get("scoringPeriodId") or 1
    # movimenti: ESPN restituisce solo quelli della giornata richiesta, quindi
    # vanno chiesti uno per uno
    for wk in range(1, week_now + 1):
        name = f"espn_tx_{wk}.json"
        if is_final(name, wk):
            continue
        espn_league(y, ["mTransactions2"], name, extra=f"&scoringPeriodId={wk}")
        mark(name, week_now)
    # formazioni schierate in ogni giornata: servono a rivedere le settimane passate
    for wk in range(1, week_now + 1):
        name = f"espn_box_{wk}.json"
        if is_final(name, wk):
            continue
        espn_league(y, ["mBoxscore", "mMatchupScore"], name, extra=f"&scoringPeriodId={wk}")
        mark(name, week_now)
    # giornate già giocate: il tabellino di ognuna resta in cache quando è definitivo
    for wk in range(1, week_now):
        name = f"espn_week_{wk}.json"
        if is_final(name, wk):
            print(f"  settimana {wk}: già in cache")
            continue
        espn_league(y, ["kona_player_info"], name,
                    {"players": {"limit": 520, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}},
                    extra=f"&scoringPeriodId={wk}")
        mark(name, week_now)
    for wk in range(week_now, week_now + 4):
        espn_league(y, ["kona_player_info"], f"espn_proj_w{wk}.json",
                    {"players": {"limit": 520, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}},
                    extra=f"&scoringPeriodId={wk}")

    print("nflverse — statistiche pubbliche")
    for season in (y, prev):
        save(f"nflverse/stats_player_reg_{season}.csv",
             get(f"{NFLVERSE}/stats_player/stats_player_reg_{season}.csv"), f"player reg {season}")
        save(f"nflverse/snap_counts_{season}.csv",
             get(f"{NFLVERSE}/snap_counts/snap_counts_{season}.csv"), f"snap counts {season}")
        save(f"nflverse/stats_team_reg_{season}.csv",
             get(f"{NFLVERSE}/stats_team/stats_team_reg_{season}.csv"), f"team reg {season}")
    for season in (y, prev):
        save(f"nflverse/stats_player_week_{season}.csv",
             get(f"{NFLVERSE}/stats_player/stats_player_week_{season}.csv"), f"player week {season}")
    for season in (y, prev):
        save(f"nflverse/injuries_{season}.csv",
             get(f"{NFLVERSE}/injuries/injuries_{season}.csv"), f"infortuni {season}")
    # Next Gen Stats: nflverse non pubblica i file per singolo anno recenti, ma
    # quelli multi-anno compressi contengono anche 2025 e 2026.
    for kind in ("receiving", "rushing", "passing"):
        save(f"nflverse/ngs_{kind}.csv.gz",
             get(f"{NFLVERSE}/nextgen_stats/ngs_{kind}.csv.gz"), f"next gen {kind}")
    save(f"nflverse/pbp_{y}.csv.gz",
         get(f"{NFLVERSE}/pbp/play_by_play_{y}.csv.gz"), "play-by-play")
    save("nflverse/games.csv",
         get("https://github.com/nflverse/nfldata/raw/master/data/games.csv"), "risultati NFL")

    # --- ESPN play-by-play: è l'unica fonte che ha le giocate mentre la partita
    # è in corso. nflverse pubblica il play-by-play solo a partita conclusa.
    print("ESPN — play-by-play della giornata")
    week = json.loads(open(os.path.join(RAW, "espn_league.json"), encoding="utf-8").read()).get("scoringPeriodId") or 1
    sb = get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={y}&seasontype=2&week={week}", ua=False)
    save("espn_scoreboard.json", sb, f"tabellone settimana {week}")
    # tabelloni delle prossime giornate: portano quote, meteo, campo e orario
    for wk in range(week + 1, week + 4):
        try:
            save(f"espn_scoreboard_{wk}.json",
                 get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={y}&seasontype=2&week={wk}", ua=False),
                 f"tabellone settimana {wk}")
        except RuntimeError as err:
            print(f"  settimana {wk} non disponibile: {err}")
    events = json.loads(sb).get("events", [])
    core = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events"
    n = 0
    for e in events:
        state = (((e.get("competitions") or [{}])[0].get("status") or {}).get("type") or {}).get("state")
        if state == "pre":                      # non ancora iniziata: niente giocate
            continue
        eid = e["id"]
        try:
            save(f"espn_plays/{eid}.json", get(f"{core}/{eid}/competitions/{eid}/plays?limit=400", ua=False),
                 f"giocate {e.get('shortName', eid)}")
            for kind in ("drives", "probabilities"):
                try:
                    save(f"espn_{kind}/{eid}.json",
                         get(f"{core}/{eid}/competitions/{eid}/{kind}?limit=400", ua=False))
                except RuntimeError:
                    pass
            n += 1
        except RuntimeError as err:
            print(f"  giocate non disponibili per {eid}: {err}")
    print(f"  partite con giocate: {n}/{len(events)}")

    print("mercato")
    # ADP dell'anno per la console, e degli anni passati per misurare quanto
    # ogni manager ha anticipato il mercato nelle sue draft.
    for season in range(2019, y + 1):
        teams = 10 if season >= 2026 else 12
        save(f"ffc/adp_{season}.json",
             get(f"https://fantasyfootballcalculator.com/api/v1/adp/ppr?teams={teams}&year={season}"),
             f"ADP FFC {season}")
    # chi stanno prendendo e mollando tutti: segnale di mercato in tempo reale
    for kind in ("add", "drop"):
        save(f"sleeper_trending_{kind}.json",
             get(f"https://api.sleeper.app/v1/players/nfl/trending/{kind}?lookback_hours=24&limit=60"),
             f"tendenze Sleeper ({kind})")
    save("sleeper_players.json",
         get("https://api.sleeper.app/v1/players/nfl"), "anagrafica Sleeper")
    # statistiche Sleeper giornata per giornata: red zone, drop, snap, placcaggi
    # evitati e altro che ESPN non dà. In cache solo quando definitive (vedi is_final).
    # api.sleeper.com rifiuta lo user agent di Python e quello da browser: va
    # mandato quello di curl.
    for wk in range(1, week_now + 1):
        name = f"sleeper/stats_{y}_w{wk}.json"
        if is_final(name, wk):
            continue
        save(name, get(f"https://api.sleeper.com/stats/nfl/{y}/{wk}?season_type=regular",
                       headers={"User-Agent": "curl/8.4.0"}), f"statistiche Sleeper sett. {wk}")
        mark(name, week_now)
    save("dp_playerids.csv",
         get("https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"),
         "crosswalk ID")

    print("fatto. I file sono in data/raw/")


if __name__ == "__main__":
    sys.exit(main())
