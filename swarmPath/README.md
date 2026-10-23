# swarmPath

Add-on Home Assistant per il gateway microBees.

## API PoC locale per Home Assistant

La prova API è disabilitata per impostazione predefinita (api_enabled false). Usa il SUPERVISOR_TOKEN fornito al container dal Supervisor e parla solo con http://supervisor/core/api. Non crea token HA per l'utente. L'API HTTP della PoC non ha autenticazione applicativa ed è protetta da allowlist IP sorgente: è destinata esclusivamente alla LAN di test, non all'esposizione Internet.

Per una prova locale:

1. Impostare `vpn_enabled: false` se si desidera usare soltanto l'API senza contattare il provisioning VPN.
2. Abilitare `api_enabled` e configurare `api_bind`, `api_port` e `api_allowed_clients` con gli indirizzi della propria rete di test. Per impostazione predefinita l'API e disabilitata e il bind e limitato a loopback.
3. Salvare le opzioni e avviare o riavviare l'add-on. Chiamare prima `GET /health` e `GET /entities`, quindi inviare soltanto il comando desiderato a un'entita di test.
4. Le richieste `POST /commands` devono includere `Content-Type: application/json`.

Gli IP sorgente sono verificati dal socket TCP: `X-Forwarded-For` non viene usato.
Il bind dell'API ritenta solo EADDRNOTAVAIL per un massimo di 120 secondi, utile mentre l'indirizzo VPN viene assegnato. Gli altri errori di bind terminano subito; dopo l'avvio il listener non riconnette automaticamente.

Endpoint:

- GET /health restituisce lo stato del processo API.
- GET /entities restituisce entity ID, nome e stato letti da Home Assistant.
- POST /commands accetta `{ "domain": "light", "service": "turn_on", "target": { "entity_id": "light.example" }, "data": {} }`. `data` è opzionale e, se presente, deve essere un oggetto. `target` deve contenere un solo `entity_id`; il dominio deve corrispondere al prefisso dell'entità. Le chiavi in `data` non possono sostituire il target. Le chiamate valide vengono inoltrate a Home Assistant; i domini di amministrazione/infrastruttura e quelli `script`/`automation` sono esclusi.
- La risposta include `command_id`, `service` (`accepted`, `http_status`) e `observed_state` (`state`, `http_status`, `matches_request`). L'accettazione del servizio e la lettura dello stato sono due risultati distinti: `observed_state` è una singola osservazione dopo la chiamata, non conferma che il dispositivo abbia completato fisicamente l'azione. Non sono promessi retry, deduplicazione o completamento asincrono.

L'accesso è limitato all'IP sorgente configurato. Gli header proxy non possono ampliare l'allowlist. Il token Supervisor resta nel processo add-on; non viene scritto nei log o nelle risposte. Gli errori upstream espongono solo lo status HTTP, mai il body grezzo.

L'API usa HTTP senza TLS: non usarla su reti non fidate o come configurazione di produzione. Un futuro proxy/VPN dovrebbe terminare TLS e mantenere la verifica dell'IP client attendibile. La PoC non crea tunnel, provisioning o inventario persistente.
