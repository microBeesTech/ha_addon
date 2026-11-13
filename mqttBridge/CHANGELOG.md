# Changelog

## Non rilasciato
### Modificato
- I percorsi CA predefiniti puntano ai file pubblici forniti sotto `/ssl`; i certificati non sono inclusi nell'add-on. La password bootstrap resta esterna.
- Corretto l'handler SUBACK effettivamente usato: il callback di connessione viene chiamato dopo un SUBACK positivo; un rifiuto viene propagato al ciclo di retry invece di lasciare il bridge in attesa fino al timeout.
- Dopo `pending`, il provisioning mantiene aperta la sottoscrizione bootstrap; alla riconnessione ripubblica la stessa identità e lo stesso `request_id`.
### Aggiunto
- Indicatori di stato sul ring DSGW e callback MQTT per mostrare la riconnessione. L'add-on dichiara `/dev/i2c-0`; l'avvio su host senza questo device resta da verificare.
### Collaudato
- Claim online e recupero dopo un claim offline. La perdita di `approved` è stata simulata lato client: il gateway riprende dopo la riconnessione.
## [0.4.2] - 2026-11-12
### Aggiunto
- Indicazione degli stati del bridge sul ring LED DSGW-210, con rilevamento facoltativo del bus I²C.
- Opzione `led_status` per disattivare gli indicatori.
- Percorsi predefiniti per le CA pubbliche del provisioning e del broker sotto `/ssl`; certificati e password non sono incorporati nell'immagine.

## [0.4.1] - 2026-11-06
### Aggiunto
- Identità persistente del gateway (`provisioning_mode: provisioned`): chiave EC P-256 in PKCS8, CSR, `request_id`,
  stato e certificato/chain in `/data/provisioning`, con scritture atomiche e permessi minimi.
- Verifica del certificato emesso: catena verso la CA pubblica configurata, validità, CN atteso, corrispondenza con la
  chiave privata, `clientAuth` e non-CA.
- Stati `pending`, `certificate_received`, `operational`, `rejected`, `invalid_identity`, `expired`; nessun rinnovo
  automatico e nessun ripiego sulle credenziali MQTT manuali.
- Opzioni `provisioning_mode`, `provisioning_ca_file`, `provisioning_common_name`; dipendenza `cryptography`.
- M2: client bootstrap MQTT TLS che invia il CSR su `ha/provisioning/requests`, riceve la risposta correlata,
  salva il certificato verificato e ritenta con lo stesso `request_id`. Opzioni per porta bootstrap, CA TLS del
  broker, timeout e prefissi dei topic; `allow_legacy_ca` solo laboratorio e con CA esplicita.
- M4: connessione operativa mTLS su 8884 con certificato/key persistenti, pubblicazione `ha/in` e sottoscrizione
  `ha/cmd/<serial>`; nessun fallback a password.
- Gating comandi: il bridge non pubblica inventario finché il broker non conferma il SUBACK della sottoscrizione;
  un SUBACK rifiutato forza la riconnessione.
- `mqtt_password_file`: password bootstrap letta da file esterno, senza inserirla nelle opzioni o nell'immagine.
- `provisioning_reset_identity`: reset una-tantum di `/data/provisioning` senza disinstallare l'add-on.
- Configurazione bootstrap dedicata: host, utente e file password separati dal collegamento operativo, senza ripiego sulle credenziali legacy quando abilitata.
### Compatibilità
- La modalità predefinita resta `manual`; il provisioning si attiva esplicitamente con `provisioning_mode: provisioned`.
- Nome e slug del prodotto invariati. La versione passa da `0.4.0` a `0.4.1`; i riferimenti M2/M4 descrivono le fasi del lavoro, non versioni da installare.
- Conservare i dati persistenti durante l’aggiornamento; non è richiesto un reset dell’identità.

## [0.4.0] - 2026-10-29
### Aggiunto
- `unit_system` di Home Assistant (`get_config`: temperatura, lunghezza, massa, volume...) così com'è in `new_device`,
  `new_entity` e `smartgate_heartbeat` (null nell'heartbeat finché non è stato letto). Le entità `climate` non
  dicono in che unità sono `temperature`, `current_temperature`, `min_temp` e `max_temp`: sono nell'unità
  dell'installazione, e al Cloud serve per mostrarla nell'app. Letto a ogni invio iniziale.

## [0.3.2] - 2026-10-28
### Corretto
- Gli eventi `device_registry_updated` ed `entity_registry_updated` si bloccavano fino al `TimeoutError` (60 s): la
  callback aspettava la risposta a un comando, ma la risposta la doveva leggere proprio il task fermo sulla callback.
  Nel frattempo non si leggeva più niente, Home Assistant chiudeva la connessione e le richieste rimaste in attesa
  finivano in decine di `Future exception was never retrieved`. Ora gli eventi li gestisce un task separato, in ordine,
  e la lettura non si ferma mai. Un comando scaduto non resta più tra quelli in attesa.

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
