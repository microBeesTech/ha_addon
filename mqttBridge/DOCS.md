# microBees MQTT Bridge

Legge dispositivi, entità e stati da Home Assistant e li pubblica su MQTT verso microBees, **così come sono**.

## Configurazione

| Opzione | Default | Descrizione |
|---|---|---|
| `mqtt_host` | — | Broker MQTT microBees (es. `test.microbees.com`) |
| `mqtt_port` | `1883` | Porta (senza TLS in questa versione) |
| `mqtt_username` / `mqtt_password` | — | Credenziali del broker (la password non compare mai nei log) |
| `topic` | `ha.bridge` | Topic di tutti i messaggi. Non usare `sensor.in.*`: lì ascolta BnBees, che proverebbe a elaborarli. Il consumer `ha-bridge-consumer` lo lega con la stessa routing key |
| `smartgate_serial` | vuoto | Serial del gateway; vuoto = MAC dell'host, calcolato come l'integrazione |
| `heartbeat_interval` | `300` | Secondi tra due heartbeat |
| `send_device_status` | `true` | Inoltra gli eventi `state_changed` |
| `log_level` | `info` | `off` nessun log · `error` solo errori · `warning` anche avvisi (riconnessioni) · `info` anche avvio, connessioni e riepilogo dell'invio iniziale · `debug` anche ogni JSON inviato per intero (`MQTT → <topic> <json>`) |

## Cosa pubblica
**Nessuna logica sui dati**: l'add-on prende i dati di Home Assistant così come sono, li mette in un pacchetto JSON e
li invia sul `topic` della configurazione. Non calcola, non converte, non filtra, non aspetta: ogni evento diventa un
messaggio e le decisioni le prende il consumer. Sono incluse anche le entità **senza dispositivo** (helper, `sun`,
`person`, automazioni…). QoS 0: il broker non conferma la consegna.

Ogni messaggio ha `message_type`, `smartgate_serial` e `timestamp` (ms).

| Quando | `message_type` | Contenuto |
|---|---|---|
| Avvio e ogni riconnessione con Home Assistant | `new_device` | Un messaggio per **ogni** dispositivo: `DeviceEntry.dict_repr` + `entities` (ciascuna `RegistryEntry.extended_dict` + `state_obj` = stato di HA com'è, null se assente) |
| Avvio e ogni riconnessione: ogni entità senza dispositivo | `new_entity` | `RegistryEntry.extended_dict` + `state_obj` (stato di HA com'è, null se assente) |
| Evento `device_registry_updated` (create, update, remove) | `device_registry_updated` | `event` = evento di HA com'è; `device` = dispositivo com'è ora (null se rimosso) |
| Evento `entity_registry_updated` (create, update, remove) | `entity_registry_updated` | `event` = evento di HA com'è; `entity` = entità com'è ora (null se rimossa) |
| Evento `state_changed` | `state_changed` | `event` = evento di HA com'è (`old_state`, `new_state` completi) |
| Connessione al broker e ogni `heartbeat_interval` | `smartgate_heartbeat` | solo i campi comuni |

Rispetto all'integrazione `bnbees_integration` il dispositivo e le entità sono identici; mancano i campi che lei
calcolava (`available`, `domain`, `state_obj` come stringa, `relay_value`, `is_on`): si ricavano nel consumer
(`domain` = prima parte di `entity_id`, `available` = `state_obj.state != "unavailable"`).

Un dispositivo nuovo arriva come una serie di eventi (`device_registry_updated` create, poi un
`entity_registry_updated` create per ogni entità, poi gli `state_changed`): il consumer li ricompone.

## Come funziona
- **Home Assistant**: API WebSocket tramite il Supervisor (`homeassistant_api: true`, `SUPERVISOR_TOKEN`), in sola
  lettura: `config/device_registry/list`, `config/entity_registry/list` + `get_entries`, `get_states`, eventi
  `device_registry_updated`, `entity_registry_updated` e `state_changed`. Se Home Assistant si riavvia, l'add-on si riconnette (attesa crescente fino
  a 60 s) e rifà l'invio iniziale.
- **MQTT**: paho-mqtt 2.x, riconnessione automatica (1–120 s). L'invio iniziale parte solo a broker connesso e viene
  rifatto a ogni riconnessione; gli eventi arrivati mentre il broker non era raggiungibile sono scartati (log WARNING).
- **Utente MQTT su RabbitMQ**: il plugin MQTT ricava il vhost dal nome utente, `vhost:utente` (es. `bnbees:homeassistant`).
  Senza prefisso i messaggi finiscono nel vhost predefinito `/` e il consumer sul vhost `bnbees` non li vede.
- **Serial del gateway**: `host_network: true`, quindi `uuid.getnode()` vede le interfacce dell'host come il core di HA.
  Se il MAC non è leggibile il log lo segnala: impostare `smartgate_serial`.

## Limiti (versione 0.1.0)
- Niente TLS né certificati: l'accesso a RabbitMQ con certificati arriverà in una versione successiva.
- Nessun comando in ingresso (il topic `gate.<serial>` dell'integrazione non è gestito).
- Ogni evento è un messaggio: con molti dispositivi gli `state_changed` sono tanti (si possono spegnere con `send_device_status`).
- Nessuna coda locale dei messaggi quando il broker è irraggiungibile.

## Sviluppo
```bash
cd mqttBridge
python3 -m venv .venv && .venv/bin/pip install paho-mqtt==2.1.0 websockets==13.1 pytest
.venv/bin/python -m pytest -q        # test, compreso il confronto con un messaggio reale dell'integrazione
ruff check . && ruff format --check .
docker build --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 -t mqtt-bridge .
```
Moduli: `messages.py` (pacchetti JSON), `bridge.py` (lettura e invio), `ha_client.py` (WebSocket),
`publisher.py` (MQTT), `config.py` (opzioni e serial), `__main__.py` (avvio).
