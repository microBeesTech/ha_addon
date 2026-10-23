# Changelog

## 1.2.1

- Il bind API ritenta EADDRNOTAVAIL per un massimo di 120 secondi, senza fallback a wildcard; gli altri errori restano immediati.

## 1.2.0

- Aggiornato `POST /commands` al contratto generico `domain`, `service`, `target.entity_id` e `data`; il vecchio formato `{action, entity_id}` della PoC 1.1.0 non è compatibile.
- Documentato il contratto dei comandi HTTP per i servizi Home Assistant.

## 1.1.0

- Aggiunta un'API PoC locale, disabilitata per impostazione predefinita, per elencare entità e comandare esclusivamente luci tramite Supervisor API.
- Lo script VPN originale è preservato in vpn.sh; l'opzione vpn_enabled mantiene l'avvio VPN attivo per impostazione predefinita.
