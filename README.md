# microBees Add-ons per Home Assistant

Repository ufficiale degli add-on di [microBees](https://microbees.com) per
[Home Assistant](https://www.home-assistant.io/). Gli add-on collegano un'installazione di Home Assistant ai servizi
microBees e si installano e si configurano direttamente dall'interfaccia di Home Assistant.

## Add-on disponibili

| Add-on | Cartella | Cosa fa |
|---|---|---|
| **swarmPath** | [`swarmPath/`](swarmPath/) | Collega il dispositivo a swarmPath per la gestione e il monitoraggio centralizzati, tramite una connessione VPN sicura |
| **MQTT Bridge** | [`mqttBridge/`](mqttBridge/) | Invia su MQTT dispositivi, entità ed eventi di Home Assistant così come sono ed esegue i comandi ricevuti. Dettagli in [`DOCS.md`](mqttBridge/DOCS.md) |

Tutti gli add-on sono disponibili per `aarch64`, `amd64`, `armhf`, `armv7` e `i386`.

## Installazione

1. In Home Assistant apri **Impostazioni → Componenti aggiuntivi → Raccolta di componenti aggiuntivi**.
2. Dal menu **⋮** in alto a destra scegli **Repository** e aggiungi:
   ```
   https://github.com/microBeesTech/ha_addon
   ```
3. Gli add-on microBees compaiono nell'elenco: apri quello che ti serve, premi **Installa**, compila la scheda
   **Configurazione** e avvialo.

Gli aggiornamenti compaiono in Home Assistant quando cambia la versione dell'add-on; le novità di ogni versione sono
nel `CHANGELOG.md` dell'add-on.

## Struttura del repository

```
repository.yaml        nome e manutentore del repository, letti da Home Assistant
<add-on>/
  config.yaml          nome, versione, opzioni e permessi dell'add-on
  build.yaml           immagine base per ogni architettura
  Dockerfile, run.sh   container dell'add-on
  README.md, DOCS.md   descrizione e documentazione (DOCS.md si vede nell'interfaccia di HA)
  CHANGELOG.md         novità di ogni versione
  translations/        testi delle opzioni in italiano e inglese
```

## Sviluppo

- Ogni add-on ha il suo branch, con lo stesso nome della cartella (es. `mqttBridge`).
- Ogni modifica di comportamento aumenta `version` in `config.yaml` e ha una voce in `CHANGELOG.md`.
- I comandi per test e build di ogni add-on sono nel suo `DOCS.md`.

## Supporto

Per problemi o richieste: [developers@microbees.com](mailto:developers@microbees.com).

## Licenza

© microBees Italia srl, tutti i diritti riservati. Il codice si può consultare a scopo informativo o didattico, ma non
copiare, modificare, ridistribuire o usare senza autorizzazione scritta. Testo completo in [`LICENCE`](LICENCE).
