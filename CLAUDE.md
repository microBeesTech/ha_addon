# Add-on per Home Assistant — Claude Context (STRICT MODE)

Repository di add-on (`repository.yaml`): una cartella per add-on (`swarmPath/`, `mqttBridge/`, …), ognuna con
`config.yaml`, `build.yaml`, `Dockerfile`, `README.md`, `DOCS.md`, `CHANGELOG.md`, `translations/`.

## Regole (OBBLIGATORIE)
- Branch: uno per add-on, **chiamato come l'add-on** (`remoteBrowser`, `mqttBridge`). Niente git worktree.
- Ogni modifica di comportamento: **bump di `version`** in `config.yaml` + voce in `CHANGELOG.md` (è ciò che fa
  comparire l'aggiornamento in Home Assistant).
- Opzioni: sempre con `schema` tipizzato; credenziali con tipo `password`; mai segreti nel codice, nei log o nei test.
- Immagini base ufficiali `ghcr.io/home-assistant/<arch>-base(-python)` con tag fisso; dipendenze Python con versione
  esatta in `requirements.txt`.
- Permessi minimi in `config.yaml` (`privileged`, `map`, `host_network` solo se servono, con commento del perché).
- Python: logica separata dall'I/O (funzioni pure testabili), `logging` con il nome del modulo, niente `print`.

## mqttBridge (CRITICO)
- **Nessuna logica sui dati** (decisione di Federico, ADR 0001): prende i dati di Home Assistant e li invia così come
  sono. VIETATI calcoli, conversioni, valori ricavati, filtri, attese/raggruppamenti. Entità senza dispositivo
  incluse (`new_entity`). QoS 0. Ogni nuova regola è una decisione di Federico, da registrare nell'ADR.
- Topic, broker e credenziali solo dalla configurazione dell'add-on.
- Home Assistant tramite WebSocket del Supervisor: in lettura, più i comandi del Cloud su `ha.cmd.<serial>` (busta
  `{nonce, command, version, params}`: `resync`, `call_service` passato così com'è, senza filtri; ADR 0002).

## Test e controlli prima del commit
`cd <addon> && .venv/bin/python -m pytest -q`, `ruff check . && ruff format --check .`, build Docker di almeno una architettura.

## Documentazione
- `<addon>/DOCS.md` — configurazione, messaggi, funzionamento, limiti (si vede nell'interfaccia di HA)
- `docs/adr/` — decisioni

**Dopo ogni feature aggiorna nello stesso commit** DOCS.md, CHANGELOG.md e l'ADR se cambia una decisione.
Commit: conventional commits in inglese (`feat(mqttBridge): …`). Mai push senza ok di Federico.
Se qualcosa non è chiaro → non inventare, chiedere.
