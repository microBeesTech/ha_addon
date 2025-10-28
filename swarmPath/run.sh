#!/bin/bash
set -u

API_URL="https://backend.swarmpath.microbees.com/provisioning/ovpn"

# Tutto quello che ci identifica va in /data perché /data è persistente nell'add-on
IDENTITY_DIR="/data"
mkdir -p "$IDENTITY_DIR"

CSR_FILE="$IDENTITY_DIR/device.csr"
KEY_FILE="$IDENTITY_DIR/device.key"
OVPN_FILE="$IDENTITY_DIR/client.ovpn"

# Colori per log leggibili
RED="\033[1;31m"
YELLOW="\033[1;33m"
GREEN="\033[1;32m"
CYAN="\033[1;36m"
RESET="\033[0m"

# --- Funzione per ottenere MAC address host o custom ---
get_host_mac() {
    # Se l'utente ha passato MAC_ADDRESS come env (dall'addon config), usiamo quello
    if [ -n "${MAC_ADDRESS:-}" ]; then
        echo "$MAC_ADDRESS"
        return
    fi

    # Proviamo l'interfaccia usata per uscire su Internet
    IFACE=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
    if [ -n "$IFACE" ] && [ -e "/sys/class/net/$IFACE/address" ]; then
        MAC=$(cat "/sys/class/net/$IFACE/address" 2>/dev/null)
        if echo "$MAC" | grep -Eq '^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$' && [ "$MAC" != "00:00:00:00:00:00" ]; then
            echo "$MAC"
            return
        fi
    fi

    # Fallback interfacce note
    for CAND in eno1 eno0 enp1s0 enp2s0 eth0 eth1 wlan0 wlan1; do
        if [ -e "/sys/class/net/$CAND/address" ]; then
            MAC=$(cat "/sys/class/net/$CAND/address" 2>/dev/null)
            if echo "$MAC" | grep -Eq '^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$' && [ "$MAC" != "00:00:00:00:00:00" ]; then
                echo "$MAC"
                return
            fi
        fi
    done

    echo ""
}

# --- Genera CSR solo se NON esiste già ---
generate_csr_once() {
    # Caso 1: esistono già sia CSR che KEY -> li teniamo, NON rigeneriamo
    if [ -f "$CSR_FILE" ] && [ -s "$CSR_FILE" ] && [ -f "$KEY_FILE" ] && [ -s "$KEY_FILE" ]; then
        # Silenzioso: non stampiamo nulla
        return 0
    fi

    # Caso 2: stato incoerente (esiste solo uno dei due file)
    if { [ -f "$CSR_FILE" ] && [ -s "$CSR_FILE" ]; } && { [ ! -f "$KEY_FILE" ] || [ ! -s "$KEY_FILE" ]; }; then
        echo -e "${RED}Esiste $CSR_FILE ma manca/è vuoto $KEY_FILE in $IDENTITY_DIR.${RESET}"
        echo -e "${RED}Per sicurezza NON rigenero automaticamente.${RESET}"
        exit 1
    fi
    if { [ -f "$KEY_FILE" ] && [ -s "$KEY_FILE" ]; } && { [ ! -f "$CSR_FILE" ] || [ ! -s "$CSR_FILE" ]; }; then
        echo -e "${RED}Esiste $KEY_FILE ma manca/è vuoto $CSR_FILE in $IDENTITY_DIR.${RESET}"
        echo -e "${RED}Per sicurezza NON rigenero automaticamente.${RESET}"
        exit 1
    fi

    # Chiave RSA 2048 + CSR col CN = MAC
    # >>> QUI silenziamo completamente openssl (niente +++++ in output)
    openssl req -new -newkey rsa:2048 -nodes \
        -keyout "$KEY_FILE" -out "$CSR_FILE" \
        -subj "/CN=$MAC" >/dev/null 2>&1
    chmod 600 "$KEY_FILE"
}

# --- Invia richiesta certificato / profilo ovpn ---
post_cert_request() {
    local CSR_ESCAPED
    CSR_ESCAPED=$(awk '{printf "%s\\n", $0}' "$CSR_FILE")

    local DATA
    DATA=$(cat <<EOF
{
    "csr": "$CSR_ESCAPED",
    "macAddress": "$MAC"
}
EOF
)

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d "$DATA" "$API_URL")

    BODY=$(echo "$RESPONSE" | head -n -1)
    STATUS=$(echo "$RESPONSE" | tail -n 1)

    echo "HTTP Status: $STATUS"

    case "$STATUS" in
        200)
            echo "$BODY" | grep -q "<ca>"
            if [ $? -eq 0 ]; then
                echo "$BODY" > "$OVPN_FILE"
                echo -e "${GREEN}Config ricevuta${RESET}"
                return 0
            else
                echo -e "${YELLOW}200 ricevuto ma qualcosa è andato storto${RESET}"
                return 1
            fi
            ;;
        400|404)
            echo -e "${RED}Errore permanente. Interrompo.${RESET}"
            return 2
            ;;
        401|403|500|*)
            echo -e "${YELLOW}Errore temporaneo.${RESET}"
            return 1
            ;;
    esac
}

# --- Connessione VPN ---
connect_vpn() {
    # >>> QUI silenziamo OpenVPN:
    # --verb 0 = massima quiete
    # >/dev/null 2>&1 = niente output a console
    exec openvpn --config "$OVPN_FILE" --verb 0 >/dev/null 2>&1
}

# --- MAIN ---
MAC=$(get_host_mac)
if [ -z "$MAC" ]; then
    echo -e "${RED}Impossibile recuperare MAC address${RESET}"
    exit 1
fi
echo -e "${CYAN}MAC rilevato:${RESET} $MAC"

generate_csr_once

MAX_RETRY=10
RETRY=0

while [ $RETRY -lt $MAX_RETRY ]; do

    if post_cert_request; then
        connect_vpn
        # exec rimpiazza il processo e tiene vivo il container/add-on
        exit 0
    else
        CODE=$?
        if [ $CODE -eq 2 ]; then
            echo -e "${RED}Errore fatale, interrompo.${RESET}"
            exit 1
        fi
    fi

    RETRY=$((RETRY+1))
    if [ $RETRY -lt $MAX_RETRY ]; then
        echo -e "${YELLOW}Tentativo fallito. Attendo 5 minuti prima di riprovare...${RESET}"
        sleep 300
    fi
done

echo -e "${RED}Tentativi esauriti dopo $MAX_RETRY iterazioni. Esco.${RESET}"
exit 1
