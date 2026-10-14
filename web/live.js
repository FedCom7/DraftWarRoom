/* Aggiornamento automatico della console (versione web: locale e GitHub Pages).
 *
 * Ogni 30 secondi prende la parte viva — punteggi di giornata, stato delle
 * partite, curve dei punti, quote — la innesta in window.TOPINA e fa
 * ridisegnare la pagina aperta. Il resto (storico, metriche, mercato) resta
 * quello generato dalla pipeline: cambia una volta al giorno, non ogni minuto.
 *
 * Due strade per la stessa risposta:
 *  - in locale la chiede a serve.py (/api/live), che ha la cache condivisa;
 *  - su GitHub Pages non c'è server, quindi la ricompone qui dalle API ESPN,
 *    che rispondono anche al browser (CORS aperto, la lega è pubblica). È la
 *    stessa logica di build_live() in serve.py: se cambia lì, va cambiata qui.
 */
(() => {
  'use strict';
  const EVERY = 30000;
  const SERVER = !!window.DWR_SERVER;
  const bar = document.createElement('div');
  bar.id = 'liveBar';
  bar.innerHTML = '<span class="dot"></span><b>auto</b><span class="txt">avvio…</span>' +
                  '<button id="liveNow" title="aggiorna adesso">↻</button>' +
                  (SERVER ? '<button id="liveAll" title="rigenera anche storico e metriche">rigenera tutto</button>' : '');
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(bar));

  const css = document.createElement('style');
  css.textContent = `
    #liveBar{position:fixed;right:14px;bottom:14px;z-index:70;display:flex;align-items:center;gap:8px;
      background:#10161E;border:1px solid #232D3A;border-radius:999px;padding:6px 10px;font:600 12px var(--sans);
      color:#E8EDF2;box-shadow:0 6px 20px rgb(0 0 0/.45)}
    #liveBar .dot{width:8px;height:8px;border-radius:50%;background:#2FD27A;animation:lbp 1.8s ease-in-out infinite}
    #liveBar.err .dot{background:#F0524A;animation:none}
    #liveBar.work .dot{background:#F5A524}
    #liveBar b{font:700 11px var(--mono);letter-spacing:.06em;color:#8593A2}
    #liveBar .txt{color:#8593A2;font-weight:500}
    #liveBar button{background:#151D27;border:1px solid #232D3A;color:#E8EDF2;border-radius:999px;
      padding:3px 9px;cursor:pointer;font:600 11px var(--sans)}
    #liveBar button:hover{border-color:#34414F}
    @keyframes lbp{50%{opacity:.35}}
    @media (prefers-reduced-motion:reduce){#liveBar .dot{animation:none}}`;
  document.head.appendChild(css);

  const say = (txt, cls) => {
    const b = document.getElementById('liveBar');
    if (!b) return;
    b.className = cls || '';
    b.querySelector('.txt').textContent = txt;
  };

  function apply(d) {
    const T = window.TOPINA;
    if (!T || !d || d.error) return false;
    // giornata nuova: la pagina legge la giornata una volta sola, quindi va
    // ricaricata, ma solo quando il server ha già rigenerato i dati statici.
    // Altrimenti si ricaricherebbe all'infinito sulla giornata vecchia.
    if (T.week && d.week && d.week !== T.week) {
      if (d.builtWeek === d.week) {
        const key = 'dwr-reload-' + d.week;
        let done = false;
        try { done = sessionStorage.getItem(key) === '1'; sessionStorage.setItem(key, '1'); } catch (e) {}
        if (!done) { location.reload(); return true; }
      }
      say(SERVER ? `giornata ${d.week} iniziata: rigenero i dati…`
                 : `giornata ${d.week} iniziata: il sito si rigenera in automatico, ricarica più tardi`, 'work');
      return 'wait';
    }
    T.generatedAt = d.generatedAt;
    T.week = d.week;
    T.lg = T.lg || {};
    T.lg.lineups = d.lineups;
    T.lg.rec = Object.fromEntries(Object.entries(d.rec).map(([k, v]) => [Number(k), v]));
    if (d.own && window.DWR_OWN) window.DWR_OWN(d.own);   // chi è libero cambia durante la settimana
    T.gameState = d.gameState;
    T.games = d.games;
    // le curve della giornata sostituiscono solo quella settimana, lo storico resta
    Object.entries(d.curves || {}).forEach(([pid, weeks]) => {
      T.curves[pid] = Object.assign(T.curves[pid] || {}, weeks);
    });
    const view = (location.hash || '#myteam').slice(1);
    if (window.DWR_VIEW) window.DWR_VIEW(view);
    return true;
  }

  /* ---- parte viva calcolata nel browser (solo senza server) ---- */
  const LEAGUE = 1948241900;
  const ESPN = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl';
  const CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events';
  const SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl';
  const SLOT = { 0: 'QB', 2: 'RB', 3: 'RB/WR', 4: 'WR', 6: 'TE', 16: 'D/ST', 17: 'K', 20: 'BE', 21: 'IR', 23: 'FLEX' };
  const INJ = { ACTIVE: '', NORMAL: '', QUESTIONABLE: 'Q', OUT: 'O', INJURY_RESERVE: 'IR',
                DOUBTFUL: 'D', SUSPENSION: 'SUS', PROBABLE: 'P' };
  const ABBR = { LA: 'LAR', WAS: 'WSH', JAC: 'JAX', SD: 'LAC', OAK: 'LV', STL: 'LAR' };
  const ORDER = { QB: 0, RB: 1, 'RB/WR': 2, FLEX: 2, WR: 3, TE: 4, 'D/ST': 5, K: 6, BE: 7, IR: 8 };
  const ab = (t) => ABBR[t] || t;
  const rnd = (v) => (v == null ? null : Math.round(v * 10) / 10);
  const plays = {};          // id partita -> giocate; una partita finita si scarica una volta sola
  let builtWeek = null;      // la giornata dei dati statici pubblicati

  const getJSON = async (url) => {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${r.status} da ${new URL(url).host}`);
    return r.json();
  };

  function curvesFrom(week) {
    const events = {};
    Object.values(plays).forEach((items) => items.forEach((pl) => {
      const per = (pl.period || {}).number || 1;
      const clock = (pl.clock || {}).value;
      if (clock == null) return;
      const elapsed = Math.trunc((per - 1) * 900 + (900 - clock));
      const parts = {};
      (pl.participants || []).forEach((part) => {
        const m = /\/athletes\/(\d+)/.exec(((part.athlete || {}).$ref) || '');
        if (m) (parts[part.type] = parts[part.type] || []).push(Number(m[1]));
      });
      if (!Object.keys(parts).length) return;
      const yards = pl.statYardage || 0;
      const text = pl.text || '';
      const up = text.toUpperCase();
      const td = !!pl.scoringPlay && (pl.scoringType || {}).abbreviation === 'TD';
      const add = {};
      const plus = (pid, v) => { add[pid] = (add[pid] || 0) + v; };
      const rec = (parts.receiver || [null])[0];
      const rush = (parts.rusher || [null])[0];
      const pas = (parts.passer || [null])[0];
      if (rec != null && !up.includes('INTERCEPT') && !text.toLowerCase().includes('incomplete')) {
        plus(rec, 1 + yards * 0.1);
        if (pas != null) plus(pas, yards * 0.04);
      }
      if (rush != null) plus(rush, yards * 0.1);
      if (up.includes('INTERCEPT') && pas != null) plus(pas, -2);
      if (td) {
        const scorer = (parts.scorer || [null])[0] || rec || rush;
        if (scorer != null) plus(scorer, 6);
        if (pas != null && rec != null && scorer === rec) plus(pas, 4);
      }
      if (pl.isTurnover && parts.fumbler) plus(parts.fumbler[0], -2);
      Object.entries(add).forEach(([pid, pts]) => {
        if (Math.abs(pts) < 0.05) return;
        const row = [elapsed, Math.round(pts * 100) / 100];
        if (Math.abs(pts) >= 4) row.push(text.slice(0, 90));
        (events[pid] = events[pid] || []).push(row);
      });
    }));
    const curves = {};
    Object.entries(events).forEach(([pid, evs]) => {
      evs.sort((a, b) => a[0] - b[0]);
      let tot = 0;
      curves[pid] = { [week]: evs.map((ev) => {
        tot += ev[1];
        const row = [ev[0], rnd(tot)];
        if (ev[2]) row.push(ev[2]);
        return row;
      }) };
    });
    return curves;
  }

  function gameStateFrom(sb) {
    const out = {};
    (sb.events || []).forEach((e) => {
      const comp = (e.competitions || [{}])[0];
      const status = comp.status || {};
      const st = status.type || {};
      const teams = (comp.competitors || []).map((c) => (c.team || {}).abbreviation);
      teams.forEach((t, i) => {
        if (!t) return;
        let el = null;            // minuto di gioco, per fermare le curve delle partite in corso
        if (st.state === 'in') {
          const [mm, ss] = (status.displayClock || '0:00').split(':').map(Number);
          if (!Number.isNaN(mm) && !Number.isNaN(ss)) el = Math.trunc(((status.period || 1) - 1) * 900 + (900 - (mm * 60 + ss)));
        }
        out[ab(t)] = { state: st.state, detail: st.shortDetail, el, opp: ab(teams[1 - i] || ''), kick: e.date };
      });
    });
    return out;
  }

  // quote, meteo e campo della giornata: le giornate successive restano quelle statiche
  function gamesFrom(sb, week) {
    const out = JSON.parse(JSON.stringify(window.TOPINA.games || {}));
    (sb.events || []).forEach((e) => {
      const comp = (e.competitions || [{}])[0];
      const odds = (comp.odds || [])[0] || {};
      const total = odds.overUnder;
      const venue = comp.venue || {};
      const wx = e.weather || {};
      const comps = comp.competitors || [];
      comps.forEach((c) => {
        const t = ab((c.team || {}).abbreviation || '');
        if (!t) return;
        const o = comps.find((x) => x !== c);
        const fav = odds.details ? odds.details.split(' ')[0] : null;
        const spread = odds.spread;
        const mine = spread != null && fav ? (fav === t ? spread : -spread) : null;
        const implied = total != null && mine != null ? rnd(total / 2 - mine / 2) : null;
        (out[t] = out[t] || {})[String(week)] = {
          opp: o ? ab((o.team || {}).abbreviation || '') : null, home: c.homeAway === 'home', kick: e.date,
          total: total ?? null, spread: mine, implied,
          venue: venue.fullName ?? null, indoor: venue.indoor ?? null,
          temp: wx.temperature ?? null, sky: wx.displayValue || wx.conditionId || null,
        };
      });
    });
    return out;
  }

  async function liveFromESPN() {
    const T = window.TOPINA;
    if (builtWeek == null) builtWeek = T.week;
    const season = T.season || new Date().getFullYear();
    const lg = await getJSON(`${ESPN}/seasons/${season}/segments/0/leagues/${LEAGUE}?view=mTeam&view=mRoster`);
    const week = lg.scoringPeriodId || 1;
    const lineups = {}, own = {}, rec = {};
    lg.teams.forEach((t) => {
      const rows = ((t.roster || {}).entries || []).map((e) => {
        own[e.playerId] = t.id;
        const pl = (e.playerPoolEntry || {}).player || {};
        const stats = pl.stats || [];
        const pick = (src) => { const s = stats.find((x) => x.scoringPeriodId === week && x.statSourceId === src); return s ? s.appliedTotal : null; };
        return { id: e.playerId, slot: SLOT[e.lineupSlotId] || '?', starter: ![20, 21].includes(e.lineupSlotId),
                 inj: INJ[pl.injuryStatus || e.injuryStatus || 'ACTIVE'] ?? '?', proj: rnd(pick(1)), act: rnd(pick(0)) };
      });
      rows.sort((a, b) => ((ORDER[a.slot] ?? 9) - (ORDER[b.slot] ?? 9)) || ((b.proj || 0) - (a.proj || 0)));
      lineups[t.id] = rows;
      const o = ((t.record || {}).overall) || {};
      rec[t.id] = { w: o.wins, l: o.losses, pf: rnd(o.pointsFor), pa: rnd(o.pointsAgainst) };
    });

    const sb = await getJSON(`${SITE}/scoreboard?dates=${season}&seasontype=2&week=${week}`);
    if (week !== builtWeek) Object.keys(plays).forEach((k) => delete plays[k]);
    await Promise.all((sb.events || []).map(async (e) => {
      const state = ((((e.competitions || [{}])[0].status || {}).type) || {}).state;
      if (state === 'pre' || (state === 'post' && plays[e.id])) return;
      try {
        plays[e.id] = (await getJSON(`${CORE}/${e.id}/competitions/${e.id}/plays?limit=400`)).items || [];
      } catch (err) { /* una partita che non risponde non ferma il resto */ }
    }));

    const now = new Date();
    return {
      generatedAt: new Date(now - now.getTimezoneOffset() * 60000).toISOString().slice(0, 19),
      week, builtWeek, lineups, rec, own,
      gameState: gameStateFrom(sb), curves: curvesFrom(week), games: gamesFrom(sb, week),
    };
  }

  async function tick(manual) {
    try {
      if (manual) say('aggiorno…', 'work');
      let d;
      if (SERVER) {
        const r = await fetch('/api/live', { cache: 'no-store' });
        d = await r.json();
      } else {
        d = await liveFromESPN();
      }
      if (d.error) return say('errore: ' + d.error, 'err');
      const res = apply(d);
      if (res === 'wait') return;
      const when = new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      say(`${d.cached ? 'dalla cache' : 'aggiornato'} alle ${when}`);
    } catch (e) {
      say(SERVER ? 'server locale non raggiungibile' : 'ESPN non risponde: riprovo fra poco', 'err');
    }
  }

  document.addEventListener('click', (e) => {
    if (e.target.id === 'liveNow') tick(true);
    if (e.target.id === 'liveAll') {
      say('rigenero tutto…', 'work');
      fetch('/api/rebuild').then(() => say('pipeline avviata: ricarica fra un minuto', 'work'));
    }
  });

  tick();
  setInterval(tick, EVERY);
  // quando torni sulla scheda, non aspettare il giro successivo
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') tick(); });
})();
