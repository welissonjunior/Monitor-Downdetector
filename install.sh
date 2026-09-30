#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Downdetector → Zabbix → Grafana — Instalador Automático
# ═══════════════════════════════════════════════════════════════════════════════
# Compatível com: Debian 11/12/13, Ubuntu 22.04/24.04, RHEL/Rocky/Alma/Oracle 8/9
#
# Uso (interativo — recomendado):
#   sudo ./install.sh
#
# Uso (sem perguntas — usa flags/env):
#   sudo UNATTENDED=1 ./install.sh \
#        --zabbix-url http://127.0.0.1/zabbix --zabbix-user Admin --zabbix-pass '****' \
#        --grafana-url http://127.0.0.1:3000 --grafana-user admin --grafana-pass '****'
#
# Flags:
#   --install-dir DIR
#   --zabbix-url URL   --zabbix-user U   --zabbix-pass P
#   --grafana-url URL  --grafana-user U  --grafana-pass P
#   -y, --yes          responde "sim" a tudo que for opcional
#   --unattended       não faz nenhuma pergunta
#   --no-seed          não roda a coleta inicial (não semeia dados)
#   --no-kiosk         não configura a TV/kiosk
#   --no-cron          não agenda coleta automática
#   -h, --help
#
# Env equivalente: INSTALL_DIR ZABBIX_URL ZABBIX_USER ZABBIX_PASS
#                  GRAFANA_URL GRAFANA_USER GRAFANA_PASS
#                  UNATTENDED=1 SKIP_ZABBIX=1 SKIP_GRAFANA=1
#
# Pré-requisitos (o instalador NÃO instala): Zabbix Server e Grafana rodando.
# Ele instala os plugins do Grafana, gera dashboards, baixa ícones e semeia
# dados automaticamente quando faltarem.
# ═══════════════════════════════════════════════════════════════════════════════

if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -Eeuo pipefail

# ── Cores ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ── Estado / defaults ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-/opt/downdetector-zabbix}"
ZABBIX_URL="${ZABBIX_URL:-http://127.0.0.1/zabbix}"
ZABBIX_USER="${ZABBIX_USER:-Admin}"
ZABBIX_PASS="${ZABBIX_PASS:-}"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASS="${GRAFANA_PASS:-}"
UNATTENDED="${UNATTENDED:-0}"
ASSUME_YES="${ASSUME_YES:-0}"
SKIP_ZABBIX="${SKIP_ZABBIX:-0}"
SKIP_GRAFANA="${SKIP_GRAFANA:-0}"
DO_SEED=1
DO_CRON=""
DO_KIOSK=""
KIOSK_DASH="downdetector-tv-1"
GF_RESTART_NEEDED=0
VERIFY_FAILS=0
LOG_FILE=""
STEP_N=0; STEP_TOTAL=13

VENV_DIR=""; LOG_DIR=""; STATE_DIR=""
CRON_FILE="/etc/cron.d/downdetector-zabbix"

# ── Helpers ───────────────────────────────────────────────────────────────────
log_info() { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()   { echo -e "${GREEN}[ OK ]${NC}  $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_err()  { echo -e "${RED}[ERRO]${NC}  $1"; }

die() { log_err "$1"; [ -n "$LOG_FILE" ] && log_err "Log completo: $LOG_FILE"; exit 1; }

on_error() {
    local rc=$?
    echo ""
    log_err "Falha inesperada na etapa '$CURRENT_STEP' (linha $1, código $rc)."
    [ -n "$LOG_FILE" ] && log_err "Veja o log: $LOG_FILE"
    exit "$rc"
}
trap 'on_error $LINENO' ERR

CURRENT_STEP="início"
step() {
    STEP_N=$((STEP_N + 1))
    CURRENT_STEP="$1"
    echo ""
    echo -e "${CYAN}── [$STEP_N/$STEP_TOTAL] $1 ─────────────────────────────────────${NC}"
}

is_unattended() { [ "$UNATTENDED" = "1" ] || [ ! -t 0 ]; }

# ask VAR "mensagem" "padrão"  → pergunta (ou usa o padrão). Nunca ecoa segredo.
ask() {
    local __var="$1" msg="$2" def="${3:-}" ans=""
    if is_unattended; then printf -v "$__var" '%s' "$def"; return 0; fi
    if [ -n "$def" ]; then read -rp "$msg [$def]: " ans || true; else read -rp "$msg: " ans || true; fi
    [ -z "$ans" ] && ans="$def"
    printf -v "$__var" '%s' "$ans"
}
ask_secret() {
    local __var="$1" msg="$2" def="${3:-}" ans=""
    if is_unattended; then printf -v "$__var" '%s' "$def"; return 0; fi
    read -rsp "$msg: " ans || true; echo ""
    [ -z "$ans" ] && ans="$def"
    printf -v "$__var" '%s' "$ans"
}
# confirm "mensagem" "y|n"  → true/false
confirm() {
    local msg="$1" def="${2:-y}" ans="" prompt="[s/N]"
    [ "$def" = "y" ] && prompt="[S/n]"
    if [ "$ASSUME_YES" = "1" ]; then return 0; fi
    if is_unattended; then [ "$def" = "y" ]; return $?; fi
    read -rp "$msg $prompt " ans || true
    [ -z "$ans" ] && ans="$def"
    [[ "$ans" =~ ^[SsYy]$ ]]
}

zbx_api_url() {
    local u="${1%/}"
    case "$u" in
        *api_jsonrpc.php) echo "$u" ;;
        *) echo "$u/api_jsonrpc.php" ;;
    esac
}

zbx_login_ok() { # api user pass
    local api="$1" user="$2" pass="$3" payload out
    payload=$(python3 -c 'import json,sys;print(json.dumps({"jsonrpc":"2.0","method":"user.login","params":{"username":sys.argv[1],"password":sys.argv[2]},"id":1}))' "$user" "$pass" 2>/dev/null || echo '')
    [ -n "$payload" ] || return 1
    out=$(curl -s -m 10 -X POST "$api" -H 'Content-Type: application/json-rpc' -d "$payload" 2>/dev/null || true)
    [[ "$out" == *'"result"'* ]]
}

grafana_health_ok() { # url
    local code
    code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "${1%/}/api/health" 2>/dev/null || true)
    [ "$code" = "200" ]
}
grafana_auth_ok() { # url user pass
    local code
    code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -u "$2:$3" "${1%/}/api/datasources" 2>/dev/null || true)
    [ "$code" = "200" ]
}
# GET autenticado no Grafana por path → 200?
gf_http_ok() { # path
    local code
    code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' -u "$GRAFANA_USER:$GRAFANA_PASS" "${GRAFANA_URL%/}$1" 2>/dev/null || true)
    [ "$code" = "200" ]
}

usage() {
    sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
}

# ── Flags ─────────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --install-dir)  INSTALL_DIR="$2"; shift 2 ;;
        --zabbix-url)   ZABBIX_URL="$2"; shift 2 ;;
        --zabbix-user)  ZABBIX_USER="$2"; shift 2 ;;
        --zabbix-pass)  ZABBIX_PASS="$2"; shift 2 ;;
        --grafana-url)  GRAFANA_URL="$2"; shift 2 ;;
        --grafana-user) GRAFANA_USER="$2"; shift 2 ;;
        --grafana-pass) GRAFANA_PASS="$2"; shift 2 ;;
        -y|--yes)       ASSUME_YES=1; shift ;;
        --unattended)   UNATTENDED=1; shift ;;
        --no-seed)      DO_SEED=0; shift ;;
        --no-kiosk)     DO_KIOSK="n"; shift ;;
        --no-cron)      DO_CRON="n"; shift ;;
        -h|--help)      usage; exit 0 ;;
        *) die "Opção desconhecida: $1 (use --help)" ;;
    esac
done

# ── 1. Pré-voo ────────────────────────────────────────────────────────────────
require_root() {
    [ "$(id -u)" -eq 0 ] || die "Execute como root: sudo ./install.sh"
}

detect_os() {
    [ -f /etc/os-release ] || die "Não foi possível detectar o SO (/etc/os-release ausente)"
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_NAME="$ID"
    log_ok "SO: ${PRETTY_NAME:-$ID $VERSION_ID}"
}

install_system_deps() {
    step "Instalando dependências do sistema"
    case "$OS_NAME" in
        debian|ubuntu)
            apt-get update -qq || true
            ALSA_LIB="libasound2"
            apt-cache show libasound2 >/dev/null 2>&1 || ALSA_LIB="libasound2t64"
            apt-get install -y -qq \
                python3 python3-pip python3-venv ca-certificates \
                zabbix-sender xvfb curl wget \
                libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
                libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
                libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
                libcairo2 "${ALSA_LIB}" libxshmfence1 \
                fonts-liberation xdg-utils \
                >/dev/null 2>&1 || true
            ;;
        ol|rhel|centos|rocky|almalinux|oracle)
            dnf install -y python3 python3-pip ca-certificates curl wget \
                xorg-x11-server-Xvfb nss nspr atk at-spi2-atk cups-libs libdrm \
                libxkbcommon libXcomposite libXdamage libXrandr mesa-libgbm \
                pango cairo alsa-lib liberation-fonts >/dev/null 2>&1 || true
            command -v zabbix_sender >/dev/null 2>&1 || \
                dnf install -y zabbix-sender >/dev/null 2>&1 || true
            ;;
        *) die "SO não suportado: ${OS_NAME:-?}. Instale as dependências manualmente." ;;
    esac

    command -v python3 >/dev/null 2>&1 || die "python3 não instalado (instale e rode de novo)."
    command -v curl    >/dev/null 2>&1 || die "curl não instalado (instale e rode de novo)."
    command -v zabbix_sender >/dev/null 2>&1 || \
        log_warn "zabbix_sender NÃO encontrado — o coletor não consegue enviar. Configure o repo Zabbix e instale 'zabbix-sender'."
    log_ok "Dependências do sistema prontas"
}


# ── 2. Configuração (validada) ────────────────────────────────────────────────
collect_config() {
    echo ""
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${CYAN}  Configuração do Downdetector Monitor${NC}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${NC}"
    [ "$UNATTENDED" = "1" ] && echo -e "  ${YELLOW}Modo não-interativo (UNATTENDED=1)${NC}"
    echo ""

    if ! is_unattended; then
        ask INSTALL_DIR "Diretório de instalação" "$INSTALL_DIR"
    fi
    VENV_DIR="${INSTALL_DIR}/venv"
    LOG_DIR="${INSTALL_DIR}/logs"
    STATE_DIR="${INSTALL_DIR}/state"
    mkdir -p "$LOG_DIR"
    LOG_FILE="${LOG_DIR}/install.log"
    # A partir daqui, tudo vai para a tela E para o log.
    exec > >(tee -a "$LOG_FILE") 2>&1

    # Zabbix
    if [ "$SKIP_ZABBIX" != "1" ]; then
        local api ok=0 i
        api="$(zbx_api_url "$ZABBIX_URL")"
        for i in 1 2 3; do
            if [ -n "$ZABBIX_PASS" ] && zbx_login_ok "$api" "$ZABBIX_USER" "$ZABBIX_PASS"; then ok=1; break; fi
            [ "$ok" = "1" ] && break
            if is_unattended; then break; fi
            [ "$i" != "1" ] && log_warn "Autenticação no Zabbix falhou — tente de novo."
            ask ZABBIX_URL  "Zabbix URL"   "$ZABBIX_URL"
            ask ZABBIX_USER "Zabbix usuário" "$ZABBIX_USER"
            ask_secret ZABBIX_PASS "Zabbix senha"
            api="$(zbx_api_url "$ZABBIX_URL")"
        done
        [ "$ok" = "1" ] || die "Não consegui autenticar no Zabbix ($api). Verifique URL/usuário/senha."
        log_ok "Zabbix autenticado: $ZABBIX_URL"
    else
        log_warn "SKIP_ZABBIX=1 — Zabbix não será configurado"
    fi

    # Grafana
    if [ "$SKIP_GRAFANA" != "1" ]; then
        grafana_health_ok "$GRAFANA_URL" || die "Grafana inacessível em $GRAFANA_URL (verifique se está rodando e a URL)."
        local ok=0 i
        for i in 1 2 3; do
            if [ -n "$GRAFANA_PASS" ] && grafana_auth_ok "$GRAFANA_URL" "$GRAFANA_USER" "$GRAFANA_PASS"; then ok=1; break; fi
            if is_unattended; then break; fi
            [ "$i" != "1" ] && log_warn "Login no Grafana falhou — tente de novo."
            ask GRAFANA_URL  "Grafana URL"   "$GRAFANA_URL"
            ask GRAFANA_USER "Grafana usuário" "$GRAFANA_USER"
            ask_secret GRAFANA_PASS "Grafana senha"
        done
        [ "$ok" = "1" ] || die "Não consegui autenticar no Grafana (${GRAFANA_URL}, usuário ${GRAFANA_USER})."
        log_ok "Grafana autenticado: $GRAFANA_URL"
    else
        log_warn "SKIP_GRAFANA=1 — Grafana não será configurado"
    fi

    # Opcionais
    if [ -z "$DO_CRON" ]; then confirm "Agendar coleta automática a cada 5 minutos (cron)?" y && DO_CRON="y" || DO_CRON="n"; fi
    if [ -z "$DO_KIOSK" ]; then
        if confirm "Configurar este servidor como TV (kiosk em tela cheia)?" n; then
            DO_KIOSK="y"
            ask KIOSK_DASH "Dashboard da TV (downdetector-tv-1=Wallboard / downdetector-noc-1=User)" "$KIOSK_DASH"
        else
            DO_KIOSK="n"
        fi
    fi
}

# ── 3. Diretórios e cópia ─────────────────────────────────────────────────────
setup_dirs() {
    step "Criando estrutura em ${INSTALL_DIR}"
    mkdir -p "$INSTALL_DIR" "$LOG_DIR" "$STATE_DIR" \
             "$INSTALL_DIR/screenshots" "$INSTALL_DIR/grafana" "$INSTALL_DIR/logos"
    mkdir -p /etc/grafana/provisioning/dashboards/json \
             /etc/grafana/provisioning/datasources \
             /usr/share/grafana/public/img/downdetector
    log_ok "Diretórios criados"
}

cp_safe() { # src dst → copia, ignorando se for o mesmo arquivo
    [ -e "$1" ] || { log_warn "Arquivo ausente no pacote: $(basename "$1")"; return 0; }
    [ "$(readlink -f "$1" 2>/dev/null)" = "$(readlink -f "$2" 2>/dev/null)" ] && return 0
    cp -f "$1" "$2"
}

copy_files() {
    step "Copiando arquivos do projeto"
    local f
    for f in downdetector_collector.py config.json requirements.txt download_icons.py \
             build_dashboard.py setup.py zbx_downdetector_template.yaml import_zabbix.py \
             run_kiosk.sh kiosk.yaml downdetector-collector.service; do
        cp_safe "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/${f}"
    done
    cp_safe "${SCRIPT_DIR}/dashboards.yaml" "${INSTALL_DIR}/grafana/dashboards.yaml"
    if ls "${SCRIPT_DIR}/logos/"*.png >/dev/null 2>&1; then
        cp -f "${SCRIPT_DIR}/logos/"*.png "${INSTALL_DIR}/logos/" 2>/dev/null || true
    fi
    # Defesa contra CRLF (cópias a partir de Windows/tar).
    find "$INSTALL_DIR" -maxdepth 2 -type f \
        \( -name '*.sh' -o -name '*.py' -o -name '*.service' -o -name '*.yaml' -o -name '*.json' -o -name '*.txt' \) \
        -exec sed -i 's/\r$//' {} + 2>/dev/null || true
    chmod +x "$INSTALL_DIR/downdetector_collector.py" "$INSTALL_DIR/download_icons.py" "$INSTALL_DIR/run_kiosk.sh" 2>/dev/null || true
    log_ok "Arquivos copiados"
}

# ── 4. Python/venv ────────────────────────────────────────────────────────────
setup_venv() {
    step "Ambiente Python + Chromium"
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
        log_ok "Virtualenv criado"
    else
        log_ok "Virtualenv já existe"
    fi
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -q -r "${SCRIPT_DIR}/requirements.txt"
    log_ok "Pacotes Python instalados"
    "$VENV_DIR/bin/playwright" install chromium --with-deps >/dev/null 2>&1 || \
        "$VENV_DIR/bin/playwright" install chromium >/dev/null 2>&1 || \
        log_warn "Não consegui instalar o Chromium do Playwright (verifique rede)."
    [ -x "$VENV_DIR/bin/patchright" ] && { "$VENV_DIR/bin/patchright" install chromium >/dev/null 2>&1 || true; }
    log_ok "Chromium pronto"
}

create_collector_wrapper() {
    step "Criando wrapper do coletor"
    cat > "${INSTALL_DIR}/run_collector.sh" << WRAPPER
#!/bin/bash
SCRIPT_DIR=${INSTALL_DIR}
source \${SCRIPT_DIR}/venv/bin/activate
exec xvfb-run --auto-servernum --server-args='-screen 0 1920x1080x24' python3 \${SCRIPT_DIR}/downdetector_collector.py "\$@"
WRAPPER
    chmod +x "${INSTALL_DIR}/run_collector.sh"
    log_ok "Wrapper: ${INSTALL_DIR}/run_collector.sh"
}

# ── 5. Plugins do Grafana ─────────────────────────────────────────────────────
GF_CLI=""
gf_cli_detect() { # localiza o CLI (o binário legado grafana-cli ainda existe no Grafana 13)
    [ -n "$GF_CLI" ] && return 0
    GF_CLI="$(command -v grafana-cli || command -v /usr/sbin/grafana-cli || true)"
}
gf_cli_run() { # args... → CLI com homepath/config (Grafana 13 falha sem --homepath:
               # "Could not find config defaults")
    gf_cli_detect
    [ -n "$GF_CLI" ] || return 127
    local args=()
    if [ -d /usr/share/grafana ]; then
        args+=(--homepath /usr/share/grafana)
        if [ -f /etc/grafana/grafana.ini ]; then args+=(--config /etc/grafana/grafana.ini); fi
    fi
    "$GF_CLI" "${args[@]}" "$@"
}

ensure_grafana_plugins() {
    [ "$SKIP_GRAFANA" = "1" ] && return 0
    step "Garantindo plugins do Grafana"
    gf_cli_detect
    if [ -z "$GF_CLI" ]; then
        log_warn "grafana-cli não encontrado — não consigo instalar plugins automaticamente."
        log_warn "Instale manualmente: gapit-htmlgraphics-panel e alexanderzobnin-zabbix-app."
        return 0
    fi
    local installed pid
    installed="$(gf_cli_run plugins ls 2>/dev/null || true)"
    for pid in gapit-htmlgraphics-panel alexanderzobnin-zabbix-app; do
        if echo "$installed" | grep -q "$pid"; then
            log_ok "Plugin presente: $pid"
        else
            log_info "Instalando plugin: $pid ..."
            local out
            if out="$(gf_cli_run plugins install "$pid" 2>&1)"; then
                log_ok "Plugin instalado: $pid"
                GF_RESTART_NEEDED=1
            else
                log_warn "Falha ao instalar $pid — saída do cli:"
                printf '%s\n' "$out" | tail -5 | sed 's/^/        /'
                log_warn "Instale manualmente e reinicie o Grafana."
            fi
        fi
    done
    return 0
}

# ── 6. Grafana (provisioning) ─────────────────────────────────────────────────
setup_grafana() {
    [ "$SKIP_GRAFANA" = "1" ] && return 0
    step "Provisionando Grafana (datasource, dashboards, ícones)"

    # Permite o HTML/JS injetado pelo painel gapit-htmlgraphics.
    local gf_env_dir="/etc/systemd/system/grafana-server.service.d"
    mkdir -p "$gf_env_dir"
    cat > "${gf_env_dir}/downdetector-html.conf" << 'CONF'
[Service]
Environment=GF_PLUGINS_DISABLE_SANITIZE_HTML=true
CONF

    # Valida os YAMLs de provisioning (um YAML quebrado derruba o Grafana no boot).
    "$VENV_DIR/bin/python" - << 'PYEOF' || true
import glob, os, shutil, time, sys
try:
    import yaml
except Exception:
    sys.exit(0)
bad = []
for f in glob.glob("/etc/grafana/provisioning/**/*.yaml", recursive=True):
    try:
        yaml.safe_load(open(f, "r", encoding="utf-8", errors="replace"))
    except Exception as e:
        bad.append((f, str(e).split("\n")[0][:90]))
if bad:
    bak = "/root/grafana-provisioning-bak-" + time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(bak, exist_ok=True)
    for f, err in bad:
        print("  [QUARENTENA] " + f + " :: " + err)
        shutil.move(f, os.path.join(bak, os.path.basename(f)))
    print("  %d arquivo(s) inválido(s) -> %s" % (len(bad), bak))
PYEOF

    # Datasource Zabbix via arquivo (não depende de senha admin do Grafana).
    local zabbix_api
    zabbix_api="$(zbx_api_url "$ZABBIX_URL")"
    local ds_file="/etc/grafana/provisioning/datasources/downdetector-zabbix.yaml"
    cat > "$ds_file" << DSFILE
apiVersion: 1

# Provisionado pelo install.sh do Downdetector Monitor.
datasources:
  - name: Zabbix
    type: alexanderzobnin-zabbix-datasource
    access: proxy
    url: ${zabbix_api}
    uid: PA67C5EADE9207728
    isDefault: false
    jsonData:
      username: "${ZABBIX_USER}"
      trends: true
      # O plugin cacheia nomes de métricas (default 1h). 5m faz serviços novos
      # aparecerem no dashboard em minutos, sem restart.
      cacheTTL: "5m"
      dbConnectionEnable: false
    secureJsonData:
      password: "${ZABBIX_PASS}"
    editable: true
DSFILE
    chown root:grafana "$ds_file" 2>/dev/null || true
    chmod 640 "$ds_file"
    log_ok "Datasource Zabbix provisionado (uid PA67C5EADE9207728)"

    cp -f "${INSTALL_DIR}/grafana/dashboards.yaml" /etc/grafana/provisioning/dashboards/dashboards.yaml

    # Gera os DOIS dashboards a partir do builder (fonte única).
    log_info "Gerando dashboards..."
    if (cd "$INSTALL_DIR" && "$VENV_DIR/bin/python" build_dashboard.py >/dev/null 2>&1); then
        cp -f "$INSTALL_DIR/downdetector_dashboard.json" /etc/grafana/provisioning/dashboards/json/
        cp -f "$INSTALL_DIR/downdetector_dashboard_tv.json" /etc/grafana/provisioning/dashboards/json/
        log_ok "Dashboards copiados (User + Wallboard)"
    else
        log_warn "build_dashboard.py falhou — usando JSONs pré-compilados, se existirem."
        for j in downdetector_dashboard.json downdetector_dashboard_tv.json; do
            [ -f "${SCRIPT_DIR}/${j}" ] && cp -f "${SCRIPT_DIR}/${j}" /etc/grafana/provisioning/dashboards/json/
        done
    fi

    # Ícones: baixa automaticamente se faltarem.
    if ! ls "${INSTALL_DIR}/logos/"*.png >/dev/null 2>&1; then
        log_info "Baixando ícones dos serviços (pode levar 1-2 min)..."
        (cd "$INSTALL_DIR" && "$VENV_DIR/bin/python" download_icons.py >/dev/null 2>&1) || \
            log_warn "download_icons.py falhou (sem internet?). Cards usarão letras."
    fi
    if ls "${INSTALL_DIR}/logos/"*.png >/dev/null 2>&1; then
        cp -f "${INSTALL_DIR}/logos/"*.png /usr/share/grafana/public/img/downdetector/ 2>/dev/null || true
        log_ok "Ícones instalados ($(ls "${INSTALL_DIR}/logos/"*.png 2>/dev/null | wc -l) arquivos)"
    fi

    chown -R root:grafana /etc/grafana/provisioning/dashboards 2>/dev/null || true
    chmod -R 755 /etc/grafana/provisioning/dashboards
    chmod -R 755 /usr/share/grafana/public/img/downdetector 2>/dev/null || true

    "$VENV_DIR/bin/python" "${INSTALL_DIR}/setup.py" grafana \
        --install-dir "$INSTALL_DIR" \
        --url "$GRAFANA_URL" --user "$GRAFANA_USER" --password "$GRAFANA_PASS" \
        --zabbix-url "$ZABBIX_URL" --zabbix-user "$ZABBIX_USER" --zabbix-password "$ZABBIX_PASS" \
        || log_warn "Ajustes finos do Grafana via API falharam (o provisioning por arquivo já cobre o essencial)."
    log_ok "Grafana provisionado"
}

# ── 7. Zabbix ─────────────────────────────────────────────────────────────────
setup_zabbix() {
    [ "$SKIP_ZABBIX" = "1" ] && return 0
    step "Configurando Zabbix (template + host)"
    "$VENV_DIR/bin/python" "${INSTALL_DIR}/setup.py" zabbix \
        --install-dir "$INSTALL_DIR" \
        --url "$ZABBIX_URL" --user "$ZABBIX_USER" --password "$ZABBIX_PASS" \
        || die "Falha ao importar template/criar host no Zabbix. Veja o log."
    log_ok "Zabbix configurado"
}

# ── 8. Agendamento ────────────────────────────────────────────────────────────
setup_cron() {
    step "Agendando coleta (cron */5)"
    if [ "$DO_CRON" != "y" ]; then log_warn "Coleta automática não agendada."; return 0; fi
    cat > "$CRON_FILE" << CRON
# Downdetector Monitor — coleta a cada 5 minutos
*/5 * * * * root ${INSTALL_DIR}/run_collector.sh >> ${LOG_DIR}/cron.log 2>&1
CRON
    chmod 644 "$CRON_FILE"
    log_ok "Cron: $CRON_FILE"
}

# ── 9. Kiosk (TV) ─────────────────────────────────────────────────────────────
setup_kiosk() {
    step "Configurando kiosk da TV"
    if [ "$DO_KIOSK" != "y" ]; then log_info "Kiosk não configurado (ok)."; return 0; fi

    if ! command -v grafana-kiosk >/dev/null 2>&1 && [ ! -f /usr/local/bin/grafana-kiosk ]; then
        case "$(uname -m)" in
            x86_64)  KURL="https://github.com/grafana/grafana-kiosk/releases/download/v1.0.12/grafana-kiosk-v1.0.12-linux-amd64" ;;
            aarch64) KURL="https://github.com/grafana/grafana-kiosk/releases/download/v1.0.12/grafana-kiosk-v1.0.12-linux-arm64" ;;
            *) log_warn "Arquitetura $(uname -m) sem download automático do grafana-kiosk."; return ;;
        esac
        if wget -q -O /usr/local/bin/grafana-kiosk "$KURL" && [ -s /usr/local/bin/grafana-kiosk ]; then
            chmod +x /usr/local/bin/grafana-kiosk
            log_ok "grafana-kiosk instalado"
        else
            rm -f /usr/local/bin/grafana-kiosk
            log_warn "Falha ao baixar grafana-kiosk — instale manualmente."
            return
        fi
    fi

    # run_kiosk.sh aponta para o dashboard escolhido.
    if [ -f "${INSTALL_DIR}/run_kiosk.sh" ]; then
        sed -i "s|downdetector-tv-1|${KIOSK_DASH}|g" "${INSTALL_DIR}/run_kiosk.sh" 2>/dev/null || true
    fi

    if [ -d /etc/xdg/autostart ]; then
        cat > /etc/xdg/autostart/downdetector-kiosk.desktop << DESKTOP
[Desktop Entry]
Type=Application
Name=Downdetector Kiosk
Exec=${INSTALL_DIR}/run_kiosk.sh
X-GNOME-Autostart-enabled=true
DESKTOP
        log_ok "Autostart criado (/etc/xdg/autostart)"
    fi

    # TV sem login: habilita acesso anônimo (Viewer) no Grafana.
    local env_dir="/etc/systemd/system/grafana-server.service.d"
    mkdir -p "$env_dir"
    cat > "${env_dir}/downdetector-kiosk.conf" << 'CONF'
[Service]
Environment=GF_AUTH_ANONYMOUS_ENABLED=true
Environment=GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
Environment=GF_AUTH_ANONYMOUS_HIDE_VERSION=true
CONF
    GF_RESTART_NEEDED=1
    log_ok "Acesso anônimo habilitado para a TV"
}

# ── 10. Semear dados ──────────────────────────────────────────────────────────
seed_data() {
    step "Coleta inicial (semeia o dashboard)"
    if [ "$DO_SEED" != "1" ]; then log_warn "Coleta inicial ignorada (--no-seed)."; return 0; fi
    [ "$SKIP_ZABBIX" = "1" ] && return 0
    log_info "Rodando o coletor (1/2) — primeira passada cria o LLD..."
    if timeout 240 "${INSTALL_DIR}/run_collector.sh" >>"${LOG_DIR}/seed.log" 2>&1; then
        log_ok "Coleta 1 concluída"
    else
        log_warn "Coleta 1 falhou/demorou (Cloudflare?). Veja ${LOG_DIR}/seed.log"
    fi
    log_info "Aguardando o Zabbix processar o LLD (20s)..."
    sleep 20
    log_info "Rodando o coletor (2/2) — envia os valores das chaves criadas..."
    if timeout 240 "${INSTALL_DIR}/run_collector.sh" >>"${LOG_DIR}/seed.log" 2>&1; then
        log_ok "Coleta 2 concluída"
    else
        log_warn "Coleta 2 falhou/demorou. O cron tentará de novo em até 5 min."
    fi
}

# ── 11. Verificação ───────────────────────────────────────────────────────────
check() { # descrição, comando... → roda e marca. NUNCA retorna erro: sob set -e/ERR, return 1 abortaria o verify.
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $desc"
    else
        echo -e "  ${RED}✗${NC} $desc"
        VERIFY_FAILS=$((VERIFY_FAILS + 1))
    fi
    return 0
}

verify_plugin_html() { # check do painel HTML com diagnóstico: 200 ok; 401/403 + plugin no disco = ok; senão falha com dica
    local code
    code="$(curl -s -m 8 -o /dev/null -w '%{http_code}' -u "$GRAFANA_USER:$GRAFANA_PASS" "${GRAFANA_URL%/}/api/plugins/gapit-htmlgraphics-panel/settings" 2>/dev/null || true)"
    if [ "$code" = "200" ]; then
        echo -e "  ${GREEN}✓${NC} Grafana: plugin HTML ativo"
        return 0
    fi
    if { [ "$code" = "401" ] || [ "$code" = "403" ]; } \
        && gf_cli_run plugins ls 2>/dev/null | grep -q gapit-htmlgraphics-panel; then
        echo -e "  ${GREEN}✓${NC} Grafana: plugin HTML ativo (instalado; API negou conferência HTTP $code)"
        return 0
    fi
    echo -e "  ${RED}✗${NC} Grafana: plugin HTML ativo (HTTP ${code:-?} — plugin ausente ou não carregado)"
    echo -e "      ${YELLOW}→ Corrija com: grafana-cli --homepath /usr/share/grafana plugins install gapit-htmlgraphics-panel && systemctl restart grafana-server${NC}"
    VERIFY_FAILS=$((VERIFY_FAILS + 1))
    return 0
}

verify() {
    step "Verificação final"
    [ "$SKIP_ZABBIX" != "1" ] && check "Zabbix: template, host e itens LLD" \
        "$VENV_DIR/bin/python" "${INSTALL_DIR}/setup.py" verify \
        --install-dir "$INSTALL_DIR" --url "$ZABBIX_URL" --user "$ZABBIX_USER" --password "$ZABBIX_PASS"
    if [ "$SKIP_GRAFANA" != "1" ]; then
        wait_grafana_up 30 || true  # tolera Grafana ainda bootando antes dos checks
        check "Grafana: serviço ativo" systemctl is-active --quiet grafana-server
        check "Grafana: datasource Zabbix responde" gf_http_ok "/api/datasources"
        verify_plugin_html
        check "Dashboard 'User' provisionado" gf_http_ok "/api/dashboards/uid/downdetector-noc-1"
        check "Dashboard 'Wallboard' provisionado" gf_http_ok "/api/dashboards/uid/downdetector-tv-1"
        check "Ícones publicados no Grafana" bash -c "ls /usr/share/grafana/public/img/downdetector/*.png >/dev/null 2>&1"
    fi
    check "Playwright importa no venv" "$VENV_DIR/bin/python" -c "from playwright.sync_api import sync_playwright"
    check "Wrapper do coletor executável" test -x "${INSTALL_DIR}/run_collector.sh"
    check "Cron agendado (ou desabilitado)" bash -c "[ -f '$CRON_FILE' ] || [ '$DO_CRON' != 'y' ]"
}

# ── 12. Resumo ────────────────────────────────────────────────────────────────
summary() {
    echo ""
    if [ "$VERIFY_FAILS" -eq 0 ]; then
        echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  ✅ Instalação concluída e verificada${NC}"
        echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    else
        echo -e "${YELLOW}════════════════════════════════════════════════════════════════${NC}"
        echo -e "${YELLOW}  ⚠ Instalação concluída com ${VERIFY_FAILS} pendência(s)${NC}"
        echo -e "${YELLOW}════════════════════════════════════════════════════════════════${NC}"
    fi
    echo ""
    echo -e "  ${BOLD}Dashboards${NC}"
    echo -e "   TV/Wallboard:  ${CYAN}${GRAFANA_URL%/}/d/downdetector-tv-1?kiosk${NC}"
    echo -e "   Investigação:  ${CYAN}${GRAFANA_URL%/}/d/downdetector-noc-1${NC}"
    echo ""
    echo -e "  ${BOLD}Operação${NC}"
    echo -e "   Testar coletor:  ${YELLOW}${INSTALL_DIR}/run_collector.sh --test${NC}"
    echo -e "   Forçar coleta:   ${YELLOW}${INSTALL_DIR}/run_collector.sh${NC}"
    echo -e "   Config de serviços: ${YELLOW}${INSTALL_DIR}/config.json${NC}"
    echo -e "   Log da instalação:  ${YELLOW}${LOG_FILE}${NC}"
    echo -e "   Log do coletor:     ${YELLOW}${LOG_DIR}/downdetector.log${NC}"
    [ "$DO_CRON" = "y" ] && echo -e "   Cron:            ${YELLOW}${CRON_FILE} (a cada 5 min)${NC}"
    [ "$DO_KIOSK" = "y" ] && echo -e "   Kiosk:           ${YELLOW}${INSTALL_DIR}/run_kiosk.sh${NC}"
    echo ""
    [ "$VERIFY_FAILS" -gt 0 ] && exit 1 || exit 0
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  Downdetector → Zabbix → Grafana — Instalador${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"

    require_root
    detect_os
    install_system_deps
    collect_config
    CURRENT_STEP="estrutura"
    setup_dirs
    copy_files
    setup_venv
    create_collector_wrapper
    ensure_grafana_plugins
    setup_grafana
    setup_zabbix
    setup_cron
    setup_kiosk
    seed_data

    # Reinicia o Grafana uma única vez (plugins + drop-ins + provisioning).
    if [ "$SKIP_GRAFANA" != "1" ]; then
        step "Reiniciando Grafana (aplica plugins/provisioning)"
        systemctl restart grafana-server 2>/dev/null || log_warn "Não consegui reiniciar o grafana-server."
        systemctl daemon-reload 2>/dev/null || true
        log_info "Aguardando o Grafana voltar (até 4 min)..."
        wait_grafana_up 120 && log_ok "Grafana no ar" || log_warn "Grafana não respondeu em ${GRAFANA_URL}."
    fi

    verify
    summary
}

main "$@"
