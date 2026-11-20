# Draft War Room

Console fantasy della lega ESPN **Topina** (`leagueId 1948241900`): draft room, rosa,
waiver, scambi, avversari, calendario e storico. Progetto **isolato**: non legge nulla da
altri progetti a runtime, e tutte le elaborazioni sono negli script qui dentro.

## Avvio rapido

```bash
python3 scripts/serve.py          # http://localhost:8787
```

La pagina si aggiorna **da sola ogni 30 secondi** con punteggi, stato delle partite e
curve dei punti presi da ESPN. In basso a destra c'è la barra di controllo: `↻` forza
l'aggiornamento, `rigenera tutto` rilancia l'intera pipeline in background.

La prima volta (o dopo giorni di stop) servono i dati completi:

```bash
python3 scripts/fetch_sources.py        # scarica tutte le sorgenti in data/raw/
python3 scripts/build_console.py        # calcola tutto in data/build/console.json
python3 scripts/export_console_assets.py
python3 scripts/fetch_images.py                 # foto dei giocatori e loghi NFL (una volta)
python3 scripts/make_icons.py                   # icone del sito in web/icons/ (solo se cambi il disegno)
python3 scripts/build_page.py --mode web        # web/index.html (sito locale)
python3 scripts/build_page.py --mode artifact   # dist/console.html (file unico)
```

## Come è fatto

| Cartella | Cosa c'è |
|---|---|
| `scripts/` | Le quattro fasi: scarico, calcolo, esportazione, assemblaggio della pagina. Più `serve.py`, il server locale. |
| `web/parts/` | I pezzi della pagina (stili, viste, moduli JS). La pagina si assembla da qui. |
| `web/` | Il sito locale: `index.html`, `live.js`, i dati in `web/data/*.js` e le immagini in `web/img/`. |
| `dist/` | La copia a file unico, con i dati dentro, da pubblicare come artifact. |
| `data/raw/` | Le risposte grezze delle sorgenti. |
| `data/build/` | `console.json` (tutto il calcolato) e `console-assets/` (i pezzi per la pagina). |
| `data/vendor/` | **Copia una tantum** dello storico 2019-2025. Vedi il README lì dentro. |
| `data/history/` | **Archivio delle stagioni** (`season_{anno}.json`: analisi e giocatori da ricordare) e le tue stelle e note (`notes_{anno}.json`). Non si cancella: la draft room dell'anno dopo lo legge. |

Due versioni della stessa pagina: quella **web** carica i dati da file esterni e si
aggiorna dal server; quella **artifact** li ha incorporati ed è una fotografia. Il codice
dell'interfaccia è lo stesso, cambia solo come arrivano i dati.

## Le sorgenti, in ordine di priorità

1. **ESPN** — lega, roster, formazioni, punti e proiezioni per giornata, ADP, stato delle
   partite, quote e meteo, **play-by-play in tempo reale**.
2. **Sleeper** — statistiche per giornata (red zone, snap, drop…), età, esperienza, depth chart, giocatori più presi nelle ultime 24 ore.
3. **nflverse** — utilizzo e quote di reparto, snap (attacco e special team), Next Gen
   Stats, punti concessi dalle difese, statistiche di kicker e difese, bollettini medici,
   risultati NFL, play-by-play storico.
4. **Fantasy Football Calculator** — ADP di mercato con deviazione standard, anche storico.
5. **DynastyProcess** — tabella di corrispondenza fra gli id delle varie fonti.

Quando un dato esiste su più fonti vince quella più in alto; quando manca si scende.

### Statistiche unite (`scripts/merge_stats.py`)

Per la stagione in corso ogni statistica, giornata per giornata, prende **ESPN se la
fornisce, poi Sleeper, poi nflverse**, e porta con sé la lettera della fonte (E, S, N).
La scheda del giocatore le mostra tutte in "Tutte le statistiche della stagione".

- **ESPN**: punti nello scoring della lega, passaggi, corse, ricezioni, target, YAC,
  primi down, fumble, calci, ritorni, statistiche delle difese.
- **Sleeper** (`api.sleeper.com/stats`, una richiesta per giornata): red zone, drop,
  placcaggi evitati, yard dopo il contatto, snap, air yards, giocate più lunghe,
  ricezioni per distanza, yard nel primo tempo, posizione settimanale nel ruolo.
- **nflverse**: quota target e air yards, WOPR, RACR, EPA, CPOE, PACR, DAKOTA,
  Next Gen Stats; e qualunque campo che manchi alle prime due.

ESPN e Sleeper omettono le statistiche a zero: se una fonte ha il tabellino di quella
giornata, un conteggio assente vale 0 per lei.

I codici numerici delle statistiche ESPN non sono documentati. La loro corrispondenza è
stata **ricavata confrontando i valori sulle stesse partite** (settimane 1-4 del 2026)
con nflverse e con Sleeper: sono usati solo i codici che coincidono almeno nel 99% dei
casi. Quelli che coincidono solo con "partita giocata" sono soglie di punteggio (bonus
40+ yard, "ogni 5 completi"…) e sono esclusi. Se ESPN cambiasse i codici, il confronto
va rifatto.

Escluse di proposito: i campi bonus di Sleeper (regole di punteggio, non statistiche),
le statistiche IDP (la lega non le usa) e i punteggi in formati diversi dal PPR.

## Questa settimana (`#week`, `web/parts/pU_*.html`)

La pagina di apertura del blocco Stagione: la lista di cose da fare prima del lock, in
ordine di urgenza (rosso: punti sicuri persi; giallo: da controllare). Titolari schierati
su ESPN in bye, fuori o a zero, con il sostituto dalla panchina o il miglior libero;
punti lasciati dalla formazione schierata rispetto a quella migliore; reparti senza
riserve; giocatori del giovedì; buchi nelle prossime tre giornate; liberi che valgono
più di un tuo titolare; scadenza degli scambi; priorità e giorni dei waiver; sfida della
settimana; mosse degli avversari. Sotto: formazione schierata contro migliore, orari
delle partite in ora italiana, bollettino dei tuoi giocatori, liberi da guardare.

## Lega NFL (`#nflleague`, `web/parts/pU_*.html`)

Classifica per division (da `games.csv`), attacchi e difese a confronto (punti, yard,
EPA per giocata, ritmo, quota di passaggi, palle perse, sack; da `stats_team_reg`),
punti fantasy concessi per reparto con la tendenza delle ultime 4 giornate, chi sale e
chi scende per snap e opportunità (ultime 3 partite contro le precedenti), bollettino
infortuni dei giocatori della lega, bye che restano. I dati li prepara `nfl_league()` in
`scripts/build_console.py` (chiave `nfl` del bundle).

## Regole della lega e classifica

`build_console.py` porta nel bundle `rules` (stagione regolare, settimane dei playoff,
seeding, scadenza scambi, tipo e giorni dei waiver) e `standings` (seed, serie,
casa/trasferta, priorità waiver, mosse, proiezione ESPN di rango) lette da
`espn_league.json`. Le pagine non hanno più settimane o scadenze scritte a mano.

Nota sulle proiezioni: in stagione il campo `proj` di ESPN è la proiezione **sul resto
della stagione NFL** (fino alla 18ª), non sull'intera stagione. A gara si divide per le
partite che restano al giocatore (`window.DWR_PPG`), non per 17.

## Struttura delle pagine (`web/parts/pS_ui.html`)

Sotto i 1100px le griglie diventano a una colonna; le tabelle che scorrono in
orizzontale tengono fisso il nome; le tabelle lunghe (`data-clip="N"`) mostrano le prime
N righe e un pulsante "Mostra tutte" invece di un riquadro con scroll interno.

## Partite NFL (`#nfl`, `web/parts/pN_*.html`)

Nel blocco Stagione, un riquadro per ogni partita della giornata, quelle in corso in testa:
punteggio per quarto, cronometro, chi ha la palla, down e red zone, ultima giocata, chi ha
segnato, i giocatori della lega in campo con i punti ESPN. Sotto, tre letture dei palloni
per squadra:

- *Target*: quota target (target del giocatore sui target della squadra), con le ricezioni
  dentro la barra e una tacca sulla quota media della stagione. È il blocco "Targets and
  catches" del live di Topina, esteso a tutte le partite.
- *Corse*: quota delle corse, yard e yard a portata.
- *Passaggi*: completati, yard, TD, intercetti, yard a tentativo.

I dati arrivano dal browser, anche in locale, da `site.api.espn.com` (`scoreboard` e
`summary`, CORS aperto): ogni 30 secondi se c'è una partita in corso, altrimenti ogni 5
minuti. Una partita finita si legge una volta sola. Se ESPN manda un tabellino senza
statistiche dei giocatori (succede, con categorie "xfl"/"ufl"), non viene tenuto come
definitivo e si riprova al giro dopo. Con le frecce si rivedono le giornate passate.

## Waiver (`#waiver`, `web/parts/pW_js.html`)

Tutti i giocatori liberi della lega (il pool ESPN completo, non solo quelli della draft)
contro la tua rosa, con la rosa viva che arriva dal live.

- **Valore atteso di una giornata**: proiezione ESPN di quella settimana (65%) più la
  media delle ultime cinque partite giocate (35%). Proiezione a zero = fuori o in bye.
  Le partite saltate (riga a zero senza snap) non entrano nelle medie.
- **Mosse**: per ogni libero si prova a togliere ognuno dei tuoi e si ricalcola la
  formazione migliore (prima i posti fissi, poi il flex RB/WR) su 1, 2 o 4 giornate. Il
  guadagno è solo quello dei titolari. A parità si taglia chi ha la proiezione più bassa
  nel resto della stagione; le mosse di un reparto danno per fatte quelle del piano negli
  altri, così un giocatore che vale zero non viene "tagliato" per ogni libero.
- **Piano**: fino a quattro mosse in sequenza, ognuna sulla rosa già cambiata.
- **Confronta su → Partite giocate**: la stessa simulazione (mosse, piano, grafico dei
  reparti, Δ in tabella) rifatta sulle giornate della finestra "Forma" con i punti veri.
  Una partita saltata vale la media di stagione del giocatore, così una sola partita
  nella finestra non diventa la sua media. Accanto a ogni guadagno c'è sempre quello
  dell'altra base: quando i due non sono d'accordo, la lettura del testa a testa lo dice.
- **Grafici**: dove i liberi battono i tuoi titolari (per reparto), classifica del
  reparto su 12 misure, volume contro punti (target share per WR/TE, opportunità per i
  RB, yard per i QB), testa a testa con punti e utilizzo giornata per giornata e le
  barre delle statistiche, tabella completa ordinabile con i tuoi in blu.
- **Target share**: quella di nflverse; se manca, target del giocatore sui target della
  squadra in quella giornata (la squadra si riconosce da settimana + avversario, quindi
  regge anche i cambi di maglia). Sulle giornate 1-10 del 2026 lo scarto medio da
  nflverse è 1,2 punti percentuali.

## Analisi di stagione (`scripts/season_review.py`)

Due pagine nel blocco Stagione, calcolate sulle sole giornate concluse e sui punti dei titolari:

- **Analisi squadre**, in quattro schede, sempre la tua squadra contro una a scelta (o la
  media delle altre). Tu in blu, la squadra scelta in arancione, le altre in grigio: quattro
  tinte nello stesso grafico a punti non si distinguono.
  - *Panoramica*: numeri chiave, fortuna o bravura (record "tutti contro tutti", punti
    subiti), giornata per giornata, forma delle ultime tre, verdetto.
  - *Reparti*: rosa completa per ruolo, titolari per posto in formazione (stessi posti per
    tutti) e panchina per ruolo; differenze, matrice con efficienza della formazione,
    dipendenza dalle stelle, quota di punti da touchdown.
  - *Scelte e mercato*: punti contro proiezioni ESPN e scelte di formazione, saldo del
    mercato, draft (valore per pick e chi l'ha vinto).
  - *Resto della stagione*: simulazione di seed e titolo (tutte e 4 vanno ai playoff),
    calendario delle difese che restano e bye da coprire.
- **Da ricordare**: chi ha fatto la differenza in tutta la lega, con etichette
  (fuoriclasse, esplosivo, costante, colpo dal waiver, furto al draft, delusione, tesoro in
  panchina, scartato e poi esploso, mai preso). Nel sito locale si possono aggiungere
  stelle e appunti (`/api/notes`).

A ogni rigenerazione l'analisi si salva in `data/history/season_{anno}.json`. L'anno dopo
la draft room e il value board mostrano un segnale (es. `★26`) accanto a quei giocatori.

## Note

- Le API sportive di ESPN rifiutano gli user agent da browser: per loro non se ne manda.
- `api.sleeper.com` rifiuta lo user agent di Python e quello da browser: si manda quello di curl.
- `/api/live` tiene una cache di 25 secondi e riscarica solo le partite ancora in corso.
- La lega è pubblica, quindi non servono cookie né credenziali.
- I file di giornata (tabellini, statistiche, movimenti) restano in cache solo se scaricati
  almeno due giornate dopo: il registro è `data/raw/_fetched.json`. Un file preso prima
  delle partite verrebbe altrimenti tenuto a zero per sempre.
- ESPN dà i movimenti di mercato una giornata alla volta: si chiedono tutte.
- Le foto dei giocatori arrivano da ESPN: il sito locale le legge da `web/img/`, la copia a
  file unico le incorpora, perché una pagina pubblicata non può caricare immagini esterne.
