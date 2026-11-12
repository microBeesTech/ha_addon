# MQTT Bridge

Legge dispositivi, entità e stati da Home Assistant e li pubblica su MQTT, **così come sono**, ed esegue i comandi
che riceve dal Cloud.

## Configurazione

### Indicatori LED

`led_status` è attivo per impostazione predefinita. Il ring RGB del DSGW richiede che Home Assistant esponga `/dev/i2c-0` all'add-on: `config.yaml` dichiara questo device. Se il nodo non è presente o il driver non riesce ad accedere al bus, il codice LED registra l'indisponibilità e il bridge prosegue senza indicatori. Resta da verificare se Home Assistant avvia l'add-on su un host che non dispone del device dichiarato; la gestione dell'errore nel driver non dimostra che il Supervisor consenta l'avvio. Disattiva `led_status` per lasciare il ring a un altro software.

Gli stati mostrati sono: avvio (blu con respiro), richiesta di provisioning in attesa di claim (ambra con respiro), connessione in corso (ciano rotante), connessione MQTT e sincronizzazione HA riuscite (verde fisso), riconnessione (ambra rotante), errore di provisioning (rosso fisso).

L'add-on non include certificati CA. Fornisci i certificati **pubblici** sotto `/ssl`: `broker-ca.crt` verifica il certificato server del broker sia nel bootstrap sia nella connessione operativa; `provisioning-ca.crt` verifica il certificato gateway emesso dal Cloud. Le chiavi private non sono incluse. La password bootstrap resta separata: fornisci un file sotto `/ssl` e indica il percorso in `provisioning_bootstrap_password_file`.

| Opzione | Default | Descrizione |
|---|---|---|
| `led_status` | `true` | Mostra gli stati sul ring DSGW, se il device `/dev/i2c-0` è disponibile |
| `mqtt_host` | — | Host del broker MQTT |
| `mqtt_port` | `1883` | Porta MQTT senza TLS usata soltanto in modalità `manual` |
| `mqtt_username` / `mqtt_password` | — | Credenziali del broker, utente nel formato `vhost:<utente>` (la password non compare mai nei log) |
| `mqtt_password_file` | vuoto | File password per la modalità manuale o il bootstrap legacy; alternativo a `mqtt_password` |
| `mqtt_tls_port` | `8884` | Porta MQTT TLS operativa in modalità `provisioned` |
| `mqtt_tls_ca_file` | `/ssl/broker-ca.crt` | `broker-ca.crt`: verifica il server del broker operativo |
| `topic` | `ha/in` | Topic di tutti i messaggi in uscita. Con la barra: RabbitMQ lo traduce nella routing key `ha.in` (scritto `ha.in` diventerebbe `ha/in` e non arriverebbe al Cloud) |
| `command_topic` | vuoto | Topic dei comandi dal Cloud. Vuoto = `ha/cmd/<serial>` con i due punti, in minuscolo (es. `ha/cmd/30:ae:7b:ea:86:80`): RabbitMQ lo traduce nella routing key `ha.cmd.30:ae:7b:ea:86:80` |
| `smartgate_serial` | vuoto | Serial del gateway; vuoto = MAC dell'host |
| `heartbeat_interval` | `300` | Secondi tra due heartbeat |
| `send_device_status` | `true` | Inoltra gli eventi `state_changed` |
| `log_level` | `info` | `off` nessun log · `error` solo errori · `warning` anche avvisi (riconnessioni) · `info` anche avvio, connessioni e riepilogo dell'invio iniziale · `debug` anche ogni JSON inviato per intero (`MQTT → <topic> <json>`) e ogni comando ricevuto (`MQTT ← <topic> <json>`) |
| `provisioning_mode` | `manual` | `manual` mantiene il percorso 0.4.0 con credenziali configurate qui. `provisioned` usa l'identità persistente e, dopo l'approvazione, la connessione operativa mTLS. Nessun passaggio automatico fra le due modalità |
| `provisioning_ca_file` | `/ssl/provisioning-ca.crt` | `provisioning-ca.crt`: verifica il certificato gateway emesso; obbligatorio in modalità `provisioned` |
| `provisioning_common_name` | — | CN atteso nel certificato. Vuoto = `gateBee_<serial compatto minuscolo>`. Il CN operativo è fissato dal backend |
| `provisioning_bootstrap_port` | `8883` | Porta MQTT TLS del canale bootstrap (distinta dalla `mqtt_port` manuale) |
| `provisioning_bootstrap_dedicated` | `false` | Se `true`, usa solo l'endpoint e le credenziali bootstrap dedicate qui sotto; nella modalità `provisioned` rifiuta password legacy configurate |
| `provisioning_bootstrap_host` | — | Host del broker nel vhost bootstrap; obbligatorio con configurazione dedicata |
| `provisioning_bootstrap_username` | — | Utente bootstrap dedicato, senza privilegi amministrativi |
| `provisioning_bootstrap_password_file` | — | Percorso assoluto del file password bootstrap dedicato; obbligatorio con configurazione dedicata |
| `provisioning_bootstrap_ca_file` | `/ssl/broker-ca.crt` | `broker-ca.crt`: verifica il server del broker bootstrap |
| `provisioning_allow_legacy_ca` | `false` | Solo laboratorio: allenta il profilo X.509, non catena/hostname/scadenze. Richiede una CA esplicita |
| `provisioning_request_topic` | `ha/provisioning/requests` | Topic della richiesta di provisioning |
| `provisioning_reply_prefix` | `ha/provisioning/replies/` | Prefisso del topic di risposta; si aggiunge il `request_id` |
| `provisioning_timeout` | `30` | Attesa di connessione, sottoscrizione e risposta, in secondi |
| `provisioning_reset_identity` | `false` | Cancella una sola volta l’identità locale; non revoca il certificato sul broker né elimina la pratica Cloud |

I percorsi predefiniti puntano ai file forniti sotto `/ssl`. Se usi nomi o directory diversi, imposta un percorso assoluto alternativo; se le CA bootstrap e operativa differiscono, configura separatamente i due campi `*_ca_file` del broker. La password bootstrap non è una CA e va fornita separatamente tramite `provisioning_bootstrap_password_file` o il campo password previsto.

Esempio per la modalità provisioned: predisponi i certificati CA pubblici e il file password bootstrap sotto `/ssl`.

```yaml
provisioning_mode: provisioned
mqtt_tls_ca_file: /ssl/broker-ca.crt
provisioning_ca_file: /ssl/provisioning-ca.crt
provisioning_bootstrap_ca_file: /ssl/broker-ca.crt
provisioning_bootstrap_password_file: /ssl/gateway-provisioning-password
```

## Identità persistente del gateway

Con `provisioning_mode: provisioned` l'add-on crea al primo avvio e conserva in `/data/provisioning`:

| File | Contenuto |
|---|---|
| `gateway-key.pem` | chiave privata EC P-256 in PKCS8, mai trasmessa e mai scritta nei log |
| `gateway.csr` | CSR con CN = serial dichiarato. Il CN operativo lo fissa il backend |
| `identity.json` | `request_id`, serial, versione dell'add-on, impronta della chiave, stato e date del certificato |
| `gateway-cert.pem` | certificato foglia + catena, scritto solo dopo la verifica |

Stati persistiti: `pending` (CSR pronta, claim/firma da fare), `certificate_received` (certificato presente ma non verificabile, per esempio CA non configurata), `operational` (certificato valido), `rejected`, `invalid_identity`, `expired`. Lo stato del broker è separato: un broker irraggiungibile non rigenera l'identità.

Regole:
- chiave, CSR e `request_id` vengono creati una sola volta e riusati dopo riavvio o aggiornamento;
- una chiave privata mancante è un errore esplicito: non viene rigenerata in silenzio;
- un CSR mancante viene rigenerato dalla stessa chiave, con lo stesso `request_id`;
- un serial configurato diverso da quello dell'identità persistente è un errore;
- il certificato diventa `operational` solo se supera catena verso la CA configurata, validità, CN atteso, corrispondenza con la chiave privata, `clientAuth` e assenza di `CA:TRUE`; il certificato emesso deve quindi contenere `BasicConstraints` con `ca=false` ed `ExtendedKeyUsage` con `clientAuth`;
- un certificato scaduto resta `expired`: nessun rinnovo automatico, nessuna sostituzione silenziosa della chiave;
- in `provisioned` non si usano le credenziali MQTT manuali come ripiego: il provisioning ritenta solo sul canale bootstrap.

## Bootstrap del provisioning

Con `provisioning_mode: provisioned` l'add-on apre una connessione **MQTT TLS** usando la CA `provisioning_bootstrap_ca_file`. Per compatibilità, `provisioning_bootstrap_dedicated: false` mantiene host, username e password legacy (`mqtt_host`, `mqtt_username`, `mqtt_password`/`mqtt_password_file`). Se attiva, `provisioning_bootstrap_dedicated: true` richiede `provisioning_bootstrap_host`, `provisioning_bootstrap_username` e `provisioning_bootstrap_password_file`; non ripiega sulle credenziali legacy e rifiuta una configurazione incompleta. Nel modo `manual` le credenziali legacy restano disponibili per il trasporto operativo. Pubblica su `provisioning_request_topic` (default `ha/provisioning/requests`) e si iscrive a `provisioning_reply_prefix + request_id`.

- QoS 1, nessun retained.
- La risposta deve avere lo stesso `request_id`; una risposta con ID diverso viene scartata.
- `pending` e `error` retryable → disconnessione e nuovo tentativo con la stessa identità e lo stesso request ID, con backoff (5 s fino a 300 s, jitter). Tra i tentativi il gateway non resta in ascolto; prima dell’approvazione non invia inventario o heartbeat operativo.
- `approved` → il certificato viene verificato e salvato; senza `provisioning_ca_file` resta `certificate_received`.
- `rejected`/`conflict` → stato `rejected`, nessun nuovo tentativo automatico; serve un intervento manuale (nessun reset o nuova chiave automatici).
- La verifica TLS del server non viene mai disabilitata. `provisioning_allow_legacy_ca` allenta solo il profilo X.509 e richiede una CA esplicita.
- Dopo la verifica del certificato l’add-on avvia il bridge operativo in mTLS, senza username/password. Inventario e heartbeat partono soltanto dopo il SUBACK positivo della sottoscrizione comandi; un rifiuto provoca la riconnessione.

Sul broker `gate_exchange` deve essere **di tipo topic e durable**: su un exchange `direct` il suffisso `#` non è una wildcard e le risposte possono non arrivare. Il codice non verifica automaticamente il tipo dell’exchange. Servono i binding `amq.topic → gate_exchange` per `ha.provisioning.requests`, `gate_exchange → amq.topic` per `ha.provisioning.replies.#` e la coda `ha_provisioning_queue` legata a `gate_exchange` con `ha.provisioning.requests`. In modalità bootstrap dedicata queste risorse e i binding devono esistere nel vhost dedicato: i binding non attraversano vhost. Sono modifiche al broker da applicare a mano e autorizzare. I nomi restano invariati in questa fase.

Predisporre sull’installazione HA, ad esempio nella cartella montata come `/ssl`, soltanto i certificati **pubblici**: la CA server del broker (per `provisioning_bootstrap_ca_file`) e la CA di provisioning (per `provisioning_ca_file`). La privata della CA resta sul servizio di firma; la privata del gateway viene generata localmente e non deve essere copiata da un altro gateway.

Il completamento del provisioning richiede inoltre una CA emittente fidata dal broker, l'identità `gateBee_<serial>` e le ACL coerenti: sono prerequisiti esterni, non configurazioni inventate dall'add-on.

La dipendenza `cryptography` è fissata in `requirements.txt`. Prima della build multi-arch verificare la disponibilità dei wheel su `armhf`, `armv7` e `i386`: se mancano, la build richiede gli strumenti di compilazione (Rust) e va concordata, non aggirata cambiando la verifica TLS.

## Esempio: bootstrap dedicato e operatività mTLS

Sostituire i segnaposto con i valori del proprio ambiente. Predisporre i file sotto `/ssl` prima dell’avvio; la password bootstrap va nel file, non nel repository o nell’immagine.

```yaml
provisioning_mode: provisioned
mqtt_host: "<broker-operativo-dns>"
mqtt_username: ""
mqtt_password: ""
mqtt_password_file: ""
mqtt_tls_port: 8884
mqtt_tls_ca_file: /ssl/broker-ca.crt
smartgate_serial: "aa:bb:cc:dd:ee:ff"
provisioning_ca_file: /ssl/provisioning-ca.crt
provisioning_bootstrap_dedicated: true
provisioning_bootstrap_host: "<broker-bootstrap-dns>"
provisioning_bootstrap_username: "gateway-provisioning:gateway-provisioning-user"
provisioning_bootstrap_password_file: /ssl/gateway-provisioning-password
provisioning_bootstrap_port: 8883
provisioning_bootstrap_ca_file: /ssl/broker-ca.crt
provisioning_allow_legacy_ca: false
provisioning_reset_identity: false
```

Il seriale dell’esempio non identifica un dispositivo reale: impostare quello del gateway o lasciare vuoto per il rilevamento automatico. Se i broker hanno CA diverse usare file distinti. Il broker deve selezionare il vhost bootstrap dallo username e mappare il listener operativo al vhost che contiene utenti e ACL dei gateway; nel laboratorio il mapping è `8884 -> beessmart`. I log del client non sostituiscono la verifica del mapping sul broker.

Il certificato pubblico della CA di provisioning deve essere attendibile anche sul broker operativo. Il Cloud deve avere il servizio di firma, l’accesso Management HTTPS e consumer configurati: un add-on connesso non dimostra che il backend stia elaborando l’inventario. La credenziale bootstrap comune è una scelta attuale; non costituisce una prova dell’identità fisica del gateway.

### Aggiornamento e reset

Aggiornare l’add-on preservando `/data/provisioning`: il riavvio riutilizza chiave e certificato. Non clonare questi dati in un’immagine destinata ad altri gateway e non eseguire due bridge con lo stesso client ID.

Solo per un reset concordato, impostare `provisioning_reset_identity: true` e riavviare: il reset cancella i file dell’identità, preservando le opzioni. Un marker impedisce di ripeterlo a ogni riavvio. Riportare poi l’opzione a `false` e riavviare per riarmare un eventuale reset successivo. Coordinare separatamente lo stato Cloud e la revoca sul broker: una nuova identità può incontrare un conflitto con una pratica già attiva. Il reset non è necessario per aggiornare il software.

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
| SUBACK comandi confermato e ogni `heartbeat_interval` | `smartgate_heartbeat` | `addon_version` = versione dell'add-on (`version` di `config.yaml`; `dev` nelle build locali); `unit_system` = unità dell'installazione da `get_config` (null finché non è stato letto all'invio iniziale) |
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
- **MQTT**: paho-mqtt 2.x, riconnessione automatica (1–120 s). Con un topic comandi configurato, il publisher diventa pronto solo dopo il SUBACK positivo e chiama il callback di connessione; a quel punto il bridge avvia l'invio iniziale, che viene ripetuto a ogni riconnessione. Se il broker rifiuta il SUBACK, il publisher registra l'errore, non chiama il callback e `wait_ready` forza la disconnessione e il nuovo tentativo: niente inventario o heartbeat viene inviato in quella sessione. Alla disconnessione il callback aggiorna il ring LED a `reconnecting` (ambra rotante); al tentativo successivo passa a `connecting` (ciano rotante). Gli eventi arrivati mentre il broker non era raggiungibile sono scartati (log WARNING).
- **Utente MQTT manuale/bootstrap su RabbitMQ**: il plugin MQTT può ricavare il vhost dal nome utente, `vhost:utente` (es. `vhost:homeassistant`).
  Senza prefisso usa il vhost configurato come predefinito sul broker.
- **Log di connessione** (livello `info`, senza i messaggi): utente, vhost, `client_id`, topic con la routing key AMQP
  (`ha/in` → `ha.in`), coda RabbitMQ delle iscrizioni (`mqtt-subscription-<client_id>qos0`) ed esito
  dell'iscrizione confermato dal broker, primo messaggio pubblicato su ogni topic. Servono a ritrovare connessione e
  coda nella console di RabbitMQ.
- **Serial del gateway**: `host_network: true`, quindi `uuid.getnode()` vede le interfacce dell'host come il core di HA.
  Se il MAC non è leggibile il log lo segnala: impostare `smartgate_serial`.

## Limiti
- La modalità `manual` continua a usare le credenziali configurate e il trasporto non mTLS. La modalità `provisioned` apre la connessione operativa mTLS solo dopo avere verificato e salvato l'identità emessa.
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
docker build --build-arg BUILD_VERSION=0.4.1 --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 -t mqtt-bridge .
```
Moduli: `messages.py` (pacchetti JSON), `bridge.py` (lettura e invio), `ha_client.py` (WebSocket),
`publisher.py` (MQTT), `config.py` (opzioni e serial), `identity.py` (chiave, CSR e verifica certificato),
`provisioning.py` (richiesta e risposta bootstrap), `__main__.py` (avvio).
