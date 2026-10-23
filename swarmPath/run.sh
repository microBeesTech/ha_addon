#!/command/with-contenv bash
set -uo pipefail

OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
CHILD_PIDS=()

log() {
    printf '[swarmPath] %s\n' "$1"
}

if [[ ! -r "$OPTIONS_FILE" ]]; then
    log "File opzioni non disponibile."
    exit 1
fi

VPN_ENABLED="$(jq -r 'if has("vpn_enabled") then .vpn_enabled else true end' "$OPTIONS_FILE")"
API_ENABLED="$(jq -r 'if has("api_enabled") then .api_enabled else false end' "$OPTIONS_FILE")"

if [[ "$VPN_ENABLED" != "true" && "$VPN_ENABLED" != "false" ]]; then
    log "vpn_enabled deve essere booleano."
    exit 1
fi
if [[ "$API_ENABLED" != "true" && "$API_ENABLED" != "false" ]]; then
    log "api_enabled deve essere booleano."
    exit 1
fi
if [[ "$API_ENABLED" == "true" ]]; then
    API_BIND="$(jq -r '.api_bind // "127.0.0.1"' "$OPTIONS_FILE")"
    API_PORT="$(jq -r '.api_port // 8099' "$OPTIONS_FILE")"
    API_ALLOWED_CLIENTS="$(jq -c '.api_allowed_clients // ["127.0.0.1"]' "$OPTIONS_FILE")"

    if [[ -z "${SUPERVISOR_TOKEN:-}" ]]; then
        log "SUPERVISOR_TOKEN non disponibile per l'API PoC."
        exit 1
    fi

    python3 -u /app/supervisor_poc.py \
        --bind "$API_BIND" \
        --port "$API_PORT" \
        --allowed-clients-json "$API_ALLOWED_CLIENTS" &
    CHILD_PIDS+=("$!")
    log "API PoC avviata su $API_BIND:$API_PORT."
fi

if [[ "$VPN_ENABLED" == "true" ]]; then
    bash "${VPN_SCRIPT:-/app/vpn.sh}" &
    CHILD_PIDS+=("$!")
    log "Avvio del client VPN originale."
fi

if [[ "${#CHILD_PIDS[@]}" -eq 0 ]]; then
    log "VPN e API disabilitate; processo in attesa."
    exec /bin/sh -c 'while true; do sleep 3600; done'
fi

shutdown() {
    trap - TERM INT
    for pid in "${CHILD_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    for pid in "${CHILD_PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
}

trap shutdown TERM INT
set +e
wait -n "${CHILD_PIDS[@]}"
STATUS=$?
set -e
log "Un processo figlio è terminato (exit $STATUS); arresto gli altri."
shutdown
exit "$STATUS"