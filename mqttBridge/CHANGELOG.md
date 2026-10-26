# Changelog

## [0.1.1] - 2026-10-26
### Corretto
- Avvio con `with-contenv` (`run.sh`): senza, s6-overlay non passava `SUPERVISOR_TOKEN` e l'add-on si fermava subito.

## [0.1.0] - 2026-10-26
### Aggiunto
- Prima versione: all'avvio un `new_device` per ogni dispositivo (registro + entità + stati di Home Assistant così come
  sono), poi inoltro degli eventi `device_registry_updated`, `entity_registry_updated`, `state_changed` e heartbeat,
  sul topic della configurazione. Nessuna logica sui dati; incluse le entità senza dispositivo (`new_entity`).
