# MQTT Bridge

Legge dispositivi, entità e stati da Home Assistant e li pubblica su MQTT, **così come sono**, ed esegue i comandi
che riceve dal Cloud.

## Configurazione

| Opzione | Default | Descrizione |
|---|---|---|
| `mqtt_host` | — | Host del broker MQTT |
| `mqtt_port` | `1883` | Porta (senza TLS in questa versione) |
| `mqtt_username` / `mqtt_password` | — | Credenziali del broker, utente nel formato `vhost:<utente>` (la password non compare mai nei log) |
| `topic` | `ha/in` | Topic di tutti i messaggi in uscita. Con la barra: RabbitMQ lo traduce nella routing key `ha.in` (scritto `ha.in` diventerebbe `ha/in` e non arriverebbe al Cloud) |
| `command_topic` | vuoto | Topic dei comandi dal Cloud. Vuoto = `ha/cmd/<serial>` con i due punti, in minuscolo (es. `ha/cmd/30:ae:7b:ea:86:80`): RabbitMQ lo traduce nella routing key `ha.cmd.30:ae:7b:ea:86:80` |
| `smartgate_serial` | vuoto | Serial del gateway; vuoto = MAC dell'host |
| `heartbeat_interval` | `300` | Secondi tra due heartbeat |
| `send_device_status` | `true` | Inoltra gli eventi `state_changed` |
| `log_level` | `info` | `off` nessun log · `error` solo errori · `warning` anche avvisi (riconnessioni) · `info` anche avvio, connessioni e riepilogo dell'invio iniziale · `debug` anche ogni JSON inviato per intero (`MQTT → <topic> <json>`) e ogni comando ricevuto (`MQTT ← <topic> <json>`) |

## Cosa pubblica
**Nessuna logica sui dati**: l'add-on prende i dati di Home Assistant così come sono, li mette in un pacchetto JSON e
li invia sul `topic` della configurazione. Non calcola, non converte, non filtra, non aspetta: ogni evento diventa un
messaggio e le decisioni le prende il consumer. Sono incluse anche le entità **senza dispositivo** (helper, `sun`,
`person`, automazioni…). QoS 0: il broker non conferma la consegna.

Ogni messaggio ha `message_type`, `smartgate_serial` e `timestamp` (ms).

| Quando | `message_type` | Contenuto |
|---|---|---|
| Avvio e ogni riconnessione con Home Assistant | `new_device` | Un messaggio per **ogni** dispositivo: `DeviceEntry.dict_repr` + `entities` (ciascuna `RegistryEntry.extended_dict` + `state_obj` = stato di HA com'è, null se assente) + `unit_system` |
| Avvio e ogni riconnessione: ogni entità senza dispositivo | `new_entity` | `RegistryEntry.extended_dict` + `state_obj` (stato di HA com'è, null se assente) + `unit_system` |
| Evento `device_registry_updated` (create, update, remove) | `device_registry_updated` | `event` = evento di HA com'è; `device` = dispositivo com'è ora (null se rimosso) |
| Evento `entity_registry_updated` (create, update, remove) | `entity_registry_updated` | `event` = evento di HA com'è; `entity` = entità com'è ora (null se rimossa) |
| Evento `state_changed` | `state_changed` | `event` = evento di HA com'è (`old_state`, `new_state` completi) |
| Connessione al broker e ogni `heartbeat_interval` | `smartgate_heartbeat` | `addon_version` = versione dell'add-on (`version` di `config.yaml`; `dev` nelle build locali); `unit_system` = unità dell'installazione da `get_config` (null finché non è stato letto all'invio iniziale) |
| Dopo ogni comando ricevuto | `command_result` | `command` = comando ricevuto com'è, `nonce` compreso (il testo, se non è JSON); `success`; `result` = risposta di HA com'è (`context`, `response`; null per `resync`); `error` = errore di HA o di lettura del comando (null se riuscito) |

Nessun campo calcolato: i valori derivati si ricavano nel consumer (es. `domain` = prima parte di `entity_id`,
`available` = `state_obj.state != "unavailable"`).

Un dispositivo nuovo arriva come una serie di eventi (`device_registry_updated` create, poi un
`entity_registry_updated` create per ogni entità, poi gli `state_changed`): il consumer li ricompone.

## Comandi
Su `command_topic` arrivano tutti i comandi del Cloud per questa installazione, in una busta unica:

```json
{ "nonce": "<uuid>", "command": "resync", "version": 1, "params": {} }
```

Si legge solo `command`; `nonce` e `version` sono accettati e per ora ignorati (il `nonce` torna nel `command_result`
perché il comando viene riportato com'è).

| `command` | Cosa fa |
|---|---|
| `resync` | Rimanda la fotografia completa: tutti i `new_device` e i `new_entity`, come all'avvio |
| `call_service` | Chiama un servizio di Home Assistant con `params` = `{domain, service, target, data}` |
| `registry_update` | Rinomina nel registro: `params.registry` = `device` → `config/device_registry/update` (es. `device_id`, `name_by_user`), `entity` → `config/entity_registry/update` (es. `entity_id`, `name`); gli altri campi di `params` passano così come sono |
| assente | Formato 0.2.0: il messaggio stesso è `{domain, service, target, data}`, trattato come `call_service` |
| altro | Non eseguito: log (WARNING) e `command_result` con `success: false`, `error: "unsupported: <command>"` |

Esempio di `call_service`:

```json
{
  "nonce": "<uuid>",
  "command": "call_service",
  "version": 1,
  "params": {
    "domain": "light",
    "service": "turn_on",
    "target": { "entity_id": "light.cucina" },
    "data": { "brightness": 128 }
  }
}
```

I campi passano a Home Assistant così come sono (`call_service` dell'API WebSocket, `data` → `service_data`).
`target` e `data` sono facoltativi. **Nessun filtro**: qualsiasi `domain`/`service` viene eseguito e la validazione la
fa Home Assistant. L'esito arriva come `command_result` sul `topic`, mentre l'effetto arriva con i normali
`state_changed`. I segnaposto come `{{lightEntityId}}` vanno sostituiti da chi invia il comando: l'add-on non
interpreta template.

Il Cloud fa scadere un comando dopo 10 minuti. La sessione MQTT dell'add-on però non è persistente (clean session,
QoS 0): mentre è disconnesso il broker non tiene la sua coda, quindi un comando inviato in quel momento va perso. Per
`resync` non cambia niente, perché a ogni riconnessione l'add-on rifà comunque l'invio iniziale.

## Come funziona
- **Home Assistant**: API WebSocket tramite il Supervisor (`homeassistant_api: true`, `SUPERVISOR_TOKEN`):
  in lettura `config/device_registry/list`, `config/entity_registry/list` + `get_entries`, `get_states`, eventi
  `device_registry_updated`, `entity_registry_updated` e `state_changed`; in scrittura solo `call_service` e `config/<registry>_registry/update` per i comandi ricevuti. Se Home Assistant si riavvia,
  l'add-on si riconnette (attesa crescente fino a 60 s) e rifà l'invio iniziale.
- **MQTT**: paho-mqtt 2.x, riconnessione automatica (1–120 s). L'invio iniziale parte solo a broker connesso e viene
  rifatto a ogni riconnessione; gli eventi arrivati mentre il broker non era raggiungibile sono scartati (log WARNING).
- **Utente MQTT su RabbitMQ**: il plugin MQTT ricava il vhost dal nome utente, `vhost:utente` (es. `vhost:homeassistant`).
  Senza prefisso i messaggi finiscono nel vhost predefinito `/`.
- **Log di connessione** (livello `info`, senza i messaggi): utente, vhost, `client_id`, topic con la routing key AMQP
  (`ha/in` → `ha.in`), coda RabbitMQ delle iscrizioni (`mqtt-subscription-<client_id>qos0`) ed esito
  dell'iscrizione confermato dal broker, primo messaggio pubblicato su ogni topic. Servono a ritrovare connessione e
  coda nella console di RabbitMQ.
- **Serial del gateway**: `host_network: true`, quindi `uuid.getnode()` vede le interfacce dell'host come il core di HA.
  Se il MAC non è leggibile il log lo segnala: impostare `smartgate_serial`.

## Limiti (versione 0.2.0)
- Niente TLS né certificati: l'accesso a RabbitMQ con certificati arriverà in una versione successiva.
- Chiunque possa pubblicare su `command_topic` può chiamare qualsiasi servizio di Home Assistant: i permessi vanno
  limitati sul broker.
- Ogni evento è un messaggio: con molti dispositivi gli `state_changed` sono tanti (si possono spegnere con `send_device_status`).
- Nessuna coda locale dei messaggi quando il broker è irraggiungibile.

## Sviluppo
```bash
cd mqttBridge
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q        # test, compreso il confronto con un messaggio new_device reale
ruff check . && ruff format --check .
docker build --build-arg BUILD_VERSION=0.2.0 --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 -t mqtt-bridge .
```
Moduli: `messages.py` (pacchetti JSON), `bridge.py` (lettura e invio), `ha_client.py` (WebSocket),
`publisher.py` (MQTT), `config.py` (opzioni e serial), `__main__.py` (avvio).
