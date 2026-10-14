#!/usr/bin/env python3
"""Server locale della console: serve la pagina e tiene i dati vivi.

    python3 scripts/serve.py            → http://localhost:8787

Cosa fa:
  - serve web/ (la pagina e i suoi dati statici);
  - /api/live  ricompone ogni volta la parte viva (punteggi di giornata, stato
    delle partite, curve dei punti) chiamando ESPN, con una cache breve per non
    martellarlo: la pagina lo interroga da sola ogni 30 secondi;
  - /api/rebuild rigenera tutto il resto (storico, metriche, mercato) lanciando
    la pipeline in background.

Il proxy verso ESPN passa dal server e non dal browser: così non dipendiamo dai
permessi CORS e la cache vale per tutte le schede aperte.
"""
import http.server, json, os, socketserver, subprocess, sys, threading, time, urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
RAW = os.path.join(ROOT, "data", "raw")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

PORT = int(os.environ.get("PORT", 8787))
LEAGUE_ID = os.environ.get("ESPN_LEAGUE_ID", "1948241900")
SEASON = int(os.environ.get("SEASON", 2026))
ESPN = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events"
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
LIVE_TTL = 25          # secondi di cache: la pagina chiede ogni 30
_cache = {"at": 0, "payload": None}
_lock = threading.Lock()
_rebuild = {"running": False}
BUNDLE = os.path.join(ROOT, "data", "build", "console-assets", "bundle.json")


def built_week():
    """La giornata dei dati statici già generati."""
    try:
        with open(BUNDLE, encoding="utf-8") as f:
            head = f.read(400)
        import re
        m = re.search(r'"week":\s*(\d+)', head)
        return int(m.group(1)) if m else None
    except OSError:
        return None


def start_rebuild():
    """Lancia la pipeline completa in background, una volta sola alla volta."""
    with _lock:
        if _rebuild["running"]:
            return False
        _rebuild["running"] = True

    def run():
        try:
            for script in ("fetch_sources.py", "build_console.py", "export_console_assets.py", "build_page.py"):
                args = [sys.executable, os.path.join(SCRIPTS, script)]
                if script == "build_page.py":
                    args += ["--mode", "web"]
                subprocess.run(args, cwd=ROOT, check=False)
        finally:
            _rebuild["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return True


def fetch(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def espn_league(views, extra=""):
    q = "&".join(f"view={v}" for v in views)
    return fetch(f"{ESPN}/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}?{q}{extra}",
                 {"User-Agent": "Mozilla/5.0 (DraftWarRoom live)"})


def build_live():
    """Ricostruisce la parte che cambia durante la giornata."""
    import build_console as B                     # riusa le stesse funzioni della pipeline

    lg = espn_league(["mTeam", "mRoster"])
    week = lg.get("scoringPeriodId") or 1
    lineups, roster = {}, {}          # roster: id giocatore -> squadra, adesso
    for t in lg["teams"]:
        rows = []
        for e in (t.get("roster") or {}).get("entries") or []:
            roster[e["playerId"]] = t["id"]
            pl = ((e.get("playerPoolEntry") or {}).get("player") or {})
            stats = pl.get("stats") or []
            pick = lambda src: next((s.get("appliedTotal") for s in stats
                                     if s.get("scoringPeriodId") == week and s.get("statSourceId") == src), None)
            rows.append({"id": e["playerId"], "slot": B.SLOT.get(e.get("lineupSlotId"), "?"),
                         "starter": e.get("lineupSlotId") not in (20, 21),
                         "inj": B.INJ.get(pl.get("injuryStatus") or e.get("injuryStatus") or "ACTIVE", "?"),
                         "proj": B.rnd(pick(1)), "act": B.rnd(pick(0))})
        order = {"QB": 0, "RB": 1, "RB/WR": 2, "FLEX": 2, "WR": 3, "TE": 4, "D/ST": 5, "K": 6, "BE": 7, "IR": 8}
        lineups[str(t["id"])] = sorted(rows, key=lambda r: (order.get(r["slot"], 9), -(r["proj"] or 0)))

    rec = {str(t["id"]): {"w": (t.get("record") or {}).get("overall", {}).get("wins"),
                          "l": (t.get("record") or {}).get("overall", {}).get("losses"),
                          "pf": B.rnd((t.get("record") or {}).get("overall", {}).get("pointsFor")),
                          "pa": B.rnd((t.get("record") or {}).get("overall", {}).get("pointsAgainst"))}
           for t in lg["teams"]}

    # stato delle partite NFL e giocate di quelle iniziate
    sb = fetch(f"{SITE}/scoreboard?dates={SEASON}&seasontype=2&week={week}")
    os.makedirs(os.path.join(RAW, "espn_plays"), exist_ok=True)
    with open(os.path.join(RAW, "espn_scoreboard.json"), "w", encoding="utf-8") as f:
        json.dump(sb, f)
    for e in sb.get("events", []):
        state = (((e.get("competitions") or [{}])[0].get("status") or {}).get("type") or {}).get("state")
        if state == "pre":
            continue
        eid = e["id"]
        dest = os.path.join(RAW, "espn_plays", f"{eid}.json")
        # una partita finita non cambia più: le sue giocate si riscaricano una volta sola
        if state == "post" and os.path.exists(dest):
            continue
        try:
            plays = fetch(f"{CORE}/{eid}/competitions/{eid}/plays?limit=400")
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(plays, f)
        except Exception:                          # una partita che non risponde non ferma il resto
            pass

    game_state = B.week_game_state(SEASON, week)
    curves, _ = B.espn_curves(week)
    games = B.week_games(SEASON, week)
    return {"generatedAt": datetime.now().isoformat(timespec="seconds"), "week": week,
            "lineups": lineups, "rec": rec, "own": {str(k): v for k, v in roster.items()},
            "gameState": game_state, "curves": curves, "games": games}


def live_payload():
    with _lock:
        if _cache["payload"] and time.time() - _cache["at"] < LIVE_TTL:
            return _cache["payload"], True
    payload = build_live()
    with _lock:
        _cache.update({"at": time.time(), "payload": payload})
    return payload, False


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True          # riavviare il server non deve aspettare il timeout della porta
    daemon_threads = True


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def end_headers(self):
        # i file cambiano a ogni rigenerazione: il browser deve sempre ricontrollarli,
        # altrimenti tiene una pagina e dei dati di giornate diverse
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # stelle e appunti della pagina "Da ricordare": restano in data/history
        if self.path.startswith("/api/notes"):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                season, pid = int(body["season"]), str(int(body["pid"]))
                path = os.path.join(ROOT, "data", "history", f"notes_{season}.json")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with _lock:
                    try:
                        with open(path, encoding="utf-8") as f:
                            notes = json.load(f)
                    except (OSError, ValueError):
                        notes = {}
                    entry = {"star": bool(body.get("star")), "note": str(body.get("note") or "")[:500]}
                    if entry["star"] or entry["note"]:
                        notes[pid] = entry
                    else:
                        notes.pop(pid, None)
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(notes, f, ensure_ascii=False, indent=1)
                return self._json({"ok": True})
            except (KeyError, ValueError) as e:
                return self._json({"error": f"richiesta non valida: {e}"}, 400)
        return self._json({"error": "non trovato"}, 404)

    def do_GET(self):
        if self.path.startswith("/api/notes"):
            from urllib.parse import parse_qs, urlparse
            season = (parse_qs(urlparse(self.path).query).get("season") or [str(SEASON)])[0]
            path = os.path.join(ROOT, "data", "history", f"notes_{int(season)}.json")
            try:
                with open(path, encoding="utf-8") as f:
                    return self._json(json.load(f))
            except (OSError, ValueError):
                return self._json({})
        if self.path.startswith("/api/live"):
            try:
                payload, cached = live_payload()
                payload["cached"] = cached
                payload["builtWeek"] = built_week()
                # giornata nuova su ESPN e dati statici ancora vecchi: si rigenera da solo
                if payload["builtWeek"] != payload.get("week"):
                    start_rebuild()
                payload["rebuilding"] = _rebuild["running"]
                return self._json(payload)
            except Exception as e:                 # meglio un errore leggibile che una pagina muta
                return self._json({"error": str(e)}, 502)
        if self.path.startswith("/api/rebuild"):
            started = start_rebuild()
            return self._json({"ok": True, "msg": "pipeline avviata in background" if started
                               else "pipeline già in corso"})
        return super().do_GET()

    def log_message(self, fmt, *args):             # meno rumore: solo gli errori
        if "api/live" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main():
    os.chdir(WEB)
    with Server(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Draft War Room su http://localhost:{PORT}")
        print("  /api/live     punteggi e curve aggiornati (cache 25 s)")
        print("  /api/rebuild  rigenera storico, metriche e mercato")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nchiuso")


if __name__ == "__main__":
    sys.exit(main())
