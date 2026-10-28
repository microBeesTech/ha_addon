# Changelog

## [0.2.0] - 2026-10-28
### Aggiunto
- Comandi dal Cloud su `command_topic` (nuova opzione; vuoto = `ha/cmd/<serial>`, routing key `ha.cmd.<serial>`),
  nella busta `{"nonce", "command", "version", "params"}`:
  - `resync`: rimanda tutti i `new_device` e i `new_entity`;
  - `call_service`: chiama il servizio di Home Assistant con `params` = `{domain, service, target, data}`, così com'è,
    senza filtri. Senza `command`, `{domain, service, target, data}` è accettato come `call_service`;
  - un `command` sconosciuto viene scartato e scritto nel log.
  L'esito torna sul `topic` come `command_result`.
- `addon_version` nell'heartbeat (`smartgate_heartbeat`).
### Modificato
- Topic predefinito `ha.in` (prima `ha.bridge`).
  Le installazioni esistenti tengono il topic salvato: va cambiato a mano nella configurazione.

## [0.1.6] - 2026-10-26
### Corretto
- L'invio iniziale (`new_device`, `new_entity`) aspetta la connessione al broker: prima poteva partire con MQTT ancora
  non connesso e i messaggi andavano persi.
- Dopo una riconnessione al broker l'invio iniziale viene rifatto.

## [0.1.5] - 2026-10-26
### Modificato
- Topic predefinito `ha.bridge`.

## [0.1.4] - 2026-10-26
### Aggiunto
- `log_level: off` per non avere log; livelli in ordine `off`, `error`, `warning`, `info`, `debug`.

## [0.1.3] - 2026-10-26
### Modificato
- Con `log_level: debug` il log mostra per intero ogni JSON inviato (`MQTT → <topic> <json>`); i log interni di
  websockets e paho restano a INFO (prima stampavano frame troncati e ping).

## [0.1.2] - 2026-10-26
### Aggiunto
- Icona e logo (`icon.png`, `logo.png`).

## [0.1.1] - 2026-10-26
### Corretto
- Avvio con `with-contenv` (`run.sh`): senza, s6-overlay non passava `SUPERVISOR_TOKEN` e l'add-on si fermava subito.

## [0.1.0] - 2026-10-26
### Aggiunto
- Prima versione: all'avvio un `new_device` per ogni dispositivo (registro + entità + stati di Home Assistant così come
  sono), poi inoltro degli eventi `device_registry_updated`, `entity_registry_updated`, `state_changed` e heartbeat,
  sul topic della configurazione. Nessuna logica sui dati; incluse le entità senza dispositivo (`new_entity`).
