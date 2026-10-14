# Copia una tantum — storico 2019-2025

Questi file sono **dati storici immutabili** copiati il 20/09/2026 dal progetto Topina
(`data/fantasy/` e `data/draft/`), che a sua volta li aveva raccolti da NFL.com quando la
lega girava lì.

Perché sono qui e non vengono scaricati:

- ESPN ospita la lega **solo dal 2026**: `/apis/v3/games/ffl/leagueHistory/1948241900?seasonId=2025`
  risponde **404**, quindi le stagioni precedenti non sono recuperabili da ESPN.
- NFL.com Fantasy non è più interrogabile per quella lega.
- Il 2019-2025 è chiuso: non cambierà mai più, quindi una copia statica è corretta.

Regole di isolamento che questo progetto rispetta:

- Nessuna lettura a runtime da Topina (né repo, né Firebase, né file locali).
- Nessun modello o file derivato copiato: qui c'è solo il dato grezzo. Classifiche,
  scontri diretti, tendenze dei manager e tutto il resto sono **ricalcolati** dagli
  script in `scripts/` con codice di questo progetto.
- Dal 2026 in avanti nulla viene copiato: la stagione in corso arriva da ESPN.

Contenuto:

- `archive/fantasy_data_YYYY.json` — 2019-2025, schieramenti e punteggi settimanali dei 4 manager.
- `drafts/draft_data_YYYY.json` — 2019-2025, le pick di ogni manager con il numero di scelta.
