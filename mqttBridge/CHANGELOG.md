# Changelog

## [0.3.1] - 2026-10-28
### Aggiunto
- Log INFO della connessione MQTT per capire dove arrivano i messaggi su RabbitMQ: all'avvio utente e versione; alla
  connessione utente, vhost (ricavato da `vhost:utente`, altrimenti quello predefinito del broker), `client_id` e
  sessione; all'iscrizione topic, routing key AMQP, nome della coda RabbitMQ (`mqtt-subscription-<client_id>qos0`) e
  l'esito confermato dal broker; al primo messaggio pubblicato su ogni topic la routing key AMQP e il vhost. In caso di
  connessione o iscrizione rifiutata, l'errore con utente, vhost e `client_id`. Mai la password.

## [0.3.0] - 2026-10-28
### Aggiunto
- Comando `registry_update`: rinomina dall'app verso Home Assistant. `params.registry` = `device`
  (`config/device_registry/update`, es. `device_id` + `name_by_user`) o `entity` (`config/entity_registry/update`,
  es. `entity_id` + `name`); gli altri campi di `params` passano così come sono. Esito in `command_result`.
### Modificato
- Un `command` sconosciuto ora riceve un `command_result` con `success: false` ed `error: "unsupported: <command>"`
  (prima solo il log), così il Cloud chiude il comando.
### Corretto
- Topic predefinito `ha/in` (prima `ha.in`): RabbitMQ converte `/` in `.`, quindi `ha/in` è la routing key `ha.in` che
  ascolta il Cloud, mentre `ha.in` diventava `ha/in` e i messaggi non arrivavano. **Le installazioni esistenti tengono
  il topic salvato: va cambiato a mano in `ha/in`.**

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
