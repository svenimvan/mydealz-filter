#!/bin/bash
# Schreibt den OpenRouter-Key sicher in die .env auf LXC 100.
# Der Key wird verdeckt eingegeben (kein Echo) und nirgendwo gespeichert.

set -e
read -rs -p "OpenRouter API Key: " KEY
echo
[ -z "$KEY" ] && { echo "Kein Key eingegeben, abgebrochen."; exit 1; }

ssh root@192.168.178.200 "pct exec 100 -- bash -c 'cat > /opt/mydealz-filter/.env && chmod 600 /opt/mydealz-filter/.env'" <<EOF
OPENROUTER_API_KEY=$KEY
EOF

unset KEY
echo "OK — .env geschrieben."
