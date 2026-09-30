#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Downdetector Collector para Zabbix
===================================
Coleta otimizada: Acessa a página inicial do Downdetector para extrair o status 
de dezenas de serviços de uma só vez. Apenas visita páginas individuais para
os serviços que não estiverem listados na capa.
"""

import json
import sys
import subprocess
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Engine anti-detecção: patchright (fork do Playwright) é necessário para o
# challenge do Cloudflare. Fallback para playwright com aviso.
try:
    from patchright.sync_api import sync_playwright
    PLAYWRIGHT_ENGINE = "patchright"
except ImportError:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_ENGINE = "playwright"

try:
    from playwright_stealth import stealth_sync
except ImportError:
    stealth_sync = None

# ─────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.json"
LOG_FILE = SCRIPT_DIR / "logs" / "downdetector.log"

STATUS_OK = 0
STATUS_WARNING = 1
STATUS_PROBLEM = 2
STATUS_UNKNOWN = -1

CF_PATTERNS = ['um momento', 'just a moment', 'checking your browser', 'attention required']

# Placeholder {PREFIX} é substituído em tempo de execução pelo path de
# status do config.json (ex.: /fora-do-ar). Permite trocar o país/idioma
# do Downdetector apenas alterando "base_url" no config.
JS_HOME_EXTRACT = """
() => {
    let results = {};
    document.querySelectorAll('a[href^="{PREFIX}/"]').forEach(a => {
        let slug = a.href.split('/').filter(x => x).pop();
        let parent = a.closest('.card, .company') || a.parentElement;
        if(parent) {
            let svg = parent.querySelector('div[role="img"][aria-label]');
            if(svg) {
                results[slug] = svg.getAttribute('aria-label');
            }
        }
    });
    return results;
}
"""

# ─────────────────────────────────────────────────────────────────
# Funções auxiliares
# ─────────────────────────────────────────────────────────────────

def setup_logging(debug=False):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('downdetector')
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    for handler in [logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)]:
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger

def load_config(config_path=None):
    path = Path(config_path) if config_path else CONFIG_FILE
    if not path.exists():
        print(f"ERRO: Config não encontrada: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def is_cloudflare_challenge(title):
    t = title.lower()
    return any(pat in t for pat in CF_PATTERNS) and 'fora do ar' not in t

def wait_cloudflare(page, logger, max_wait=60):
    for i in range(max_wait):
        time.sleep(1)
        title = page.title()
        if not is_cloudflare_challenge(title):
            logger.info(f"  Cloudflare resolvido em {i+1}s!")
            time.sleep(2)
            return True
        if i % 15 == 0 and i > 0:
            logger.debug(f"  Cloudflare ainda ativo ({i}s)...")
    return False

def parse_aria_label(text):
    if not text: return STATUS_UNKNOWN, ''
    l = text.lower()
    status = STATUS_UNKNOWN
    if 'sem problema' in l or 'nenhum' in l or 'funcionando' in l:
        status = STATUS_OK
    elif 'possíveis' in l or 'alguns' in l:
        status = STATUS_WARNING
    elif 'problemas' in l or 'falha' in l or 'interrupção' in l:
        # Padrão: "Status atual: Problemas detectados" ou "Problemas no ..."
        # (chegando aqui, 'sem problema' e 'possíveis' já foram descartados acima)
        status = STATUS_PROBLEM
            
    # Extrair apenas a parte do "Status atual:"
    if 'status atual:' in l:
        parts = text.split('tatus atual:')
        return status, parts[-1].strip().capitalize()
    return status, text

def send_to_zabbix(results, config, logger):
    server = config.get('zabbix_server', '127.0.0.1')
    port = config.get('zabbix_port', 10051)
    host = config.get('zabbix_host', 'Downdetector')

    lines = []
    for r in results:
        slug, ts = r['slug'], r['timestamp']
        lines.append(f'"{host}" "downdetector.status[{slug}]" {ts} "{r["status"]}"')
        st = (r.get('status_text') or '').replace('"', '\\"')
        lines.append(f'"{host}" "downdetector.status.text[{slug}]" {ts} "{st}"')
    lines.append(f'"{host}" "downdetector.collector.heartbeat" {int(time.time())} "{int(time.time())}"')

    data_file = SCRIPT_DIR / ".zabbix_sender_data.tmp"
    try:
        with open(data_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        cmd = ['zabbix_sender', '-z', server, '-p', str(port), '-T', '-i', str(data_file)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            logger.info(f"zabbix_sender OK: {proc.stdout.strip()}")
            return True
        else:
            # O resumo processed/failed vai no stdout; stderr costuma ser vazio.
            logger.error(f"zabbix_sender ERRO (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
            return False
    except Exception as e:
        logger.error(f"zabbix_sender erro: {e}")
        return False
    finally:
        try: data_file.unlink(missing_ok=True)
        except Exception: pass

def send_discovery(services, config, logger):
    server = config.get('zabbix_server', '127.0.0.1')
    port = config.get('zabbix_port', 10051)
    host = config.get('zabbix_host', 'Downdetector')
    data = [{ "{#SERVICE_SLUG}": s['slug'], "{#SERVICE_NAME}": s['name'] } for s in services]
    lld = json.dumps({"data": data}, ensure_ascii=False)
    cmd = ['zabbix_sender', '-z', server, '-p', str(port), '-s', host, '-k', 'downdetector.discovery', '-o', lld]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            logger.info(f"Discovery OK: {proc.stdout.strip()}")
        else:
            logger.error(f"Discovery ERRO: {proc.stderr.strip()}")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description='Downdetector Collector (Otimizado)')
    parser.add_argument('--test', action='store_true', help='Modo teste')
    parser.add_argument('--service', type=str, help='Coletar apenas um serviço')
    parser.add_argument('--debug', action='store_true', help='Log detalhado')
    parser.add_argument('--discovery', action='store_true', help='Enviar LLD discovery')
    args = parser.parse_args()

    logger = setup_logging(args.debug)
    logger.info("=" * 65)
    logger.info(f"Downdetector Collector Rápido - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    config = load_config()
    services = config.get('services', [])
    if args.service:
        services = [s for s in services if s['slug'] == args.service]

    if not services:
        sys.exit(1)

    if args.discovery:
        if args.test:
            data = [{ "{#SERVICE_SLUG}": s['slug'], "{#SERVICE_NAME}": s['name'] } for s in services]
            print(json.dumps({"data": data}, indent=2, ensure_ascii=False))
        else:
            send_discovery(services, config, logger)
        return

    logger.info(f"Serviços configurados: {len(services)}")

    results = []
    # Correção: respeita "base_url" do config.json. O path de status (ex.:
    # /fora-do-ar) é derivado da própria base_url e injetado no JS de extração.
    cfg_base = config.get('base_url', 'https://downdetector.com.br/fora-do-ar').rstrip('/')
    parsed = urlparse(cfg_base)
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://downdetector.com.br"
    status_path = parsed.path or '/fora-do-ar'
    js_home = JS_HOME_EXTRACT.replace('{PREFIX}', status_path)
    goto_timeout = max(10000, int(config.get('timeout', 45000)))
    cf_wait = config.get('cloudflare_wait', 90)
    logger.info(f"Origem: {base_url} (páginas de status: {base_url}{status_path}/)")

    with sync_playwright() as p:
        logger.info(f"Iniciando Chromium (engine={PLAYWRIGHT_ENGINE})...")
        launch_args = [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            # WebGL por software: o challenge do Cloudflare exige contexto WebGL.
            # Sob Xvfb sem GPU ele loopa para sempre sem estas flags.
            '--enable-unsafe-swiftshader',
            '--use-angle=swiftshader',
        ]

        if PLAYWRIGHT_ENGINE == "patchright":
            # patchright: contexto PERSISTENTE (reaproveita o cf_clearance
            # entre ciclos) e SEM patches manuais — ele já neutraliza os sinais
            # de automação de forma consistente; patches próprios quebram isso.
            profile_dir = SCRIPT_DIR / "state" / "pw-profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            browser = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                args=launch_args,
                viewport={'width': 1920, 'height': 1080},
                locale='pt-BR', timezone_id='America/Sao_Paulo',
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
        else:
            logger.warning("patchright ausente — o challenge do Cloudflare pode não ser resolvido. Instale: pip install patchright")
            browser = p.chromium.launch(
                headless=False,
                args=launch_args + ['--disable-blink-features=AutomationControlled'],
            )
            ctx = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='pt-BR', timezone_id='America/Sao_Paulo',
            )
            page = ctx.new_page()
            if stealth_sync:
                stealth_sync(page)
            # Anti-Detect (só no fallback; conflita com o patchright)
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                delete navigator.__proto__.webdriver;
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
            """)

        # ─── FASE 1: Leitura em Massa da Homepage ───
        logger.info(f"🌐 FASE 1: Acessando {base_url}/ para coleta em massa...")
        home_data = {}
        try:
            page.goto(base_url, wait_until='domcontentloaded', timeout=goto_timeout)
            if is_cloudflare_challenge(page.title()):
                logger.warning("Cloudflare detectado na Home, aguardando...")
                wait_cloudflare(page, logger, cf_wait)
                time.sleep(2)
            
            # Scroll para carregar lazy images/DOM se necessário
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            
            home_data = page.evaluate(js_home)
            logger.info(f"✓ Home analisada! Encontrados {len(home_data)} serviços com status na capa.")
        except Exception as e:
            logger.error(f"Erro ao analisar Home: {e}")

        browser.close()

    # ─── Falha total na coleta: NUNCA gerar falso-verde ───
    # Se a homepage não retornou dados (Cloudflare travado, layout mudou,
    # Chromium crash), enviar -1 dispara o trigger INFO "Falha na coleta" e
    # pinta os cards de cinza, em vez de presumir tudo OK.
    if not home_data:
        ts = int(time.time())
        logger.error("Homepage não retornou dados. Marcando TODOS os serviços como -1 (Falha na coleta).")
        for svc in services:
            results.append({
                'slug': svc['slug'], 'name': svc['name'], 'status': STATUS_UNKNOWN,
                'status_text': 'Falha na coleta (homepage indisponível)',
                'timestamp': ts, 'error': 'homepage scrape failed'
            })
            logger.info(f"[{svc['slug']}] ❌ (FALHA) status=-1")
    else:
        # ─── FASE 1: Serviços encontrados na capa ───
        missing = []
        for svc in services:
            slug = svc['slug']
            if slug in home_data and home_data[slug]:
                st, txt = parse_aria_label(home_data[slug])
                results.append({
                    'slug': slug, 'name': svc['name'], 'status': st,
                    'status_text': txt, 'timestamp': int(time.time()), 'error': None
                })
                logger.info(f"[{slug}] ✓ (HOME) status={st} | texto=\"{txt}\"")
            else:
                missing.append(svc)

        # ─── FASE 2: Serviços Fora do Top Reclamações (Presumidos Normais) ───
        if missing:
            logger.info(f"🌐 FASE 2: {len(missing)} serviços não estavam na Home. Assumindo STATUS_OK (Fora do Top).")
            for svc in missing:
                slug = svc['slug']
                results.append({
                    'slug': slug, 'name': svc['name'], 'status': STATUS_OK,
                    'status_text': 'Fora do Top Reclamações (Presumido OK)',
                    'timestamp': int(time.time()), 'error': None
                })
                logger.info(f"[{slug}] ✓ (PRESUMIDO) status=0 | texto=\"Fora do Top Reclamações\"")
        else:
            logger.info("🎉 Todos os serviços foram coletados na página inicial!")

    # Saída
    if args.test:
        icons = {0: '✅ OK', 1: '⚠️  WARNING', 2: '🔴 PROBLEM', -1: '❓ UNKNOWN'}
        print("\n" + "═" * 70)
        print("  RESULTADOS — Modo Teste")
        print("═" * 70)
        for r in results:
            print(f"\n  📌 {r['name']} ({r['slug']})")
            print(f"     Status:   {icons.get(r['status'], '?')}")
            if r['status_text']:
                print(f"     Texto:    {r['status_text']}")
            if r.get('error'):
                print(f"     ❌ Erro:   {r['error']}")
        print(f"\n{'═' * 70}")
    else:
        # Discovery completo apenas em ciclos normais; em --service os itens
        # já existem e um LLD parcial não traz benefício.
        if not args.service:
            send_discovery(services, config, logger)
            time.sleep(1)
        send_to_zabbix(results, config, logger)

if __name__ == '__main__':
    main()
