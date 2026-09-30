#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Grafana Kiosk — Downdetector NOC TV (1920x1080)
# ═══════════════════════════════════════════════════════════════

GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
# Dashboard exibido na TV: WALLBOARD por padrão (detecção à distância).
# Visão completa (User):  KIOSK_DASHBOARD_UID=downdetector-noc-1 ./run_kiosk.sh
DASHBOARD_UID="${KIOSK_DASHBOARD_UID:-downdetector-tv-1}"
KIOSK_MODE="full"

# Resolução padrão: 1920x1080
WINDOW_SIZE="1920,1080"
SCALE_FACTOR="1.0"

# Caminho do binário (ajuste conforme instalação)
KIOSK_BIN="${KIOSK_BIN:-/usr/local/bin/grafana-kiosk}"

# Se não encontrar o binário, tenta via Go path
if [ ! -f "$KIOSK_BIN" ]; then
    KIOSK_BIN="$(go env GOPATH 2>/dev/null)/bin/grafana-kiosk"
fi

if [ ! -f "$KIOSK_BIN" ]; then
    echo "ERRO: grafana-kiosk não encontrado. Instale via:"
    echo "  go install github.com/grafana/grafana-kiosk@latest"
    echo "  ou baixe de: https://github.com/grafana/grafana-kiosk/releases"
    exit 1
fi

echo "Iniciando Grafana Kiosk (1920x1080)..."
echo "  URL: ${GRAFANA_URL}/d/${DASHBOARD_UID}"
echo "  Modo: ${KIOSK_MODE}"
echo "  Janela: ${WINDOW_SIZE}"

# Cache-buster para evitar que a TV fique com JS antigo em cache
CACHE_BUSTER="$(date +%s)"

exec "$KIOSK_BIN" \
    -URL="${GRAFANA_URL}/d/${DASHBOARD_UID}?kiosk&_dash.hideTimePicker=true&v=${CACHE_BUSTER}" \
    -kiosk-mode="${KIOSK_MODE}" \
    -window-size="${WINDOW_SIZE}" \
    -scale-factor="${SCALE_FACTOR}" \
    -autofit=true \
    -hide-time-picker=true \
    -hide-links=true \
    -page-load-delay-ms=3000
