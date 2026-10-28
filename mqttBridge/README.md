# MQTT Bridge

Add-on per Home Assistant che invia su MQTT, **così come sono**, tutti i dispositivi e le entità
(`new_device`, `new_entity`), gli eventi dei registri e dei cambi di stato e un heartbeat del gateway, ed esegue i comandi
ricevuti su MQTT (servizi di Home Assistant). Nessuna logica sui dati: broker, credenziali e topic dalla configurazione.

Configurazione e dettagli: [DOCS.md](DOCS.md).
