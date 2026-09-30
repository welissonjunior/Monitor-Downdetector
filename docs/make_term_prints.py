#!/usr/bin/env python3
"""Gera 'prints de terminal' (PNG) com conteúdo REAL capturado na VM de teste.

Uso:  python make_term_prints.py
Saída: docs/img/te_*.png (via Chrome headless)
"""
from __future__ import annotations
import html
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
IMG = HERE / "img"
TMP = HERE / "_tmp_term"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#202124; padding:0; font-family:Consolas,'Cascadia Mono','Segoe UI Symbol','Segoe UI Emoji',monospace; }
.win { border-radius:8px; overflow:hidden; box-shadow:0 10px 40px rgba(0,0,0,.55); background:#1b1b1f; }
.bar { height:34px; background:#2d2d33; display:flex; align-items:center; padding:0 12px; gap:7px; }
.dot { width:11px; height:11px; border-radius:50%; }
.dot.r{background:#ff5f56}.dot.y{background:#ffbd2e}.dot.g{background:#27c93f}
.ttl { margin-left:10px; color:#9aa0a6; font-size:12px; font-family:'Segoe UI',Arial,sans-serif; }
.term { padding:14px 18px 18px; font-size:13px; line-height:19px; color:#d8d8d8; white-space:pre-wrap; word-break:break-all; }
.p  { color:#9cdcfe; }        /* prompt */
.c  { color:#4ec9b0; }        /* comando */
.g  { color:#6a9955; }        /* ok verde */
.b  { color:#569cd6; }        /* azul */
.yl { color:#dcdcaa; }        /* amarelo */
.r  { color:#f48771; }        /* vermelho */
.d  { color:#808080; }        /* dim */
.w  { color:#ffffff; font-weight:600; }
.cy { color:#4dd0e1; }
"""

PROMPT = '<span class="p">root@debian</span><span class="d">:</span><span class="c">~</span><span class="d">$</span> '


def ansi_to_html(text: str) -> str:
    """Converte códigos ANSI simples (usados pelo install.sh) em spans HTML."""
    out, open_span = [], False
    i = 0
    color_map = {
        "0;32": "g", "1;32": "g", "0;34": "b", "0;36": "cy", "1;33": "yl",
        "0;31": "r", "1;31": "r", "1;36": "cy", "1;35": "cy", "0;1": "w", "1": "w",
    }
    while i < len(text):
        ch = text[i]
        if ch == "\x1b" and i + 1 < len(text) and text[i + 1] == "[":
            j = text.find("m", i)
            if j != -1:
                code = text[i + 2 : j]
                cls = color_map.get(code)
                if open_span:
                    out.append("</span>")
                    open_span = False
                if cls:
                    out.append(f'<span class="{cls}">')
                    open_span = True
                i = j + 1
                continue
        out.append(html.escape(ch, quote=False))
        i += 1
    if open_span:
        out.append("</span>")
    return "".join(out)


def page(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div class="win" style="width:1180px">
<div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
<span class="ttl">{html.escape(title)}</span></div>
<div class="term">{body_html}</div></div></body></html>"""


def shot(html_path: pathlib.Path, png_path: pathlib.Path, width: int, height: int) -> None:
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--screenshot=" + str(png_path), f"--window-size={width},{height}",
         "--default-background-color=00000000", "file:///" + str(html_path).replace("\\", "/")],
        check=True, capture_output=True, timeout=90,
    )


BLOCKS: list[dict] = []


def block(name: str, title: str, lines_html: list[str], height: int) -> None:
    BLOCKS.append({"name": name, "title": title, "lines": lines_html, "height": height})


# ── T1: pré-requisitos (saída REAL capturada via SSH na VM, 2026-09-30) ──────
block("te_01_preflight", "root@debian: — verificação de pré-requisitos (saída real)", [
    PROMPT + '<span class="c">systemctl is-active grafana-server zabbix-server apache2</span>',
    "active\nactive\nactive",
    "",
    PROMPT + '<span class="c">grafana-server -v</span>',
    "Version 13.2.3 (commit: 90ffed056f0884267356c12a0eeb72a022af53f1, branch: release-13.2.3#patched)",
    "",
    PROMPT + '<span class="c">zabbix_server --version</span>',
    "zabbix_server (Zabbix) 7.4.15",
    "",
    PROMPT + '<span class="c">python3 --version</span>',
    "Python 3.13.5",
    "",
    PROMPT + '<span class="c">free -h | head -2; df -h / | tail -1</span>',
    '               total       usada       livre    compart.  buff/cache  disponível',
    "Mem.:          5,8Gi       1,8Gi       1,3Gi        30Mi       3,0Gi       4,0Gi",
    "/dev/sda1        47G   15G   30G  34% /",
], 560)

# ── T2: início da instalação — STDOUT REAL da execução v1.1.2 + perguntas interativas ──
block("te_02_inicio", "sudo ./install.sh — início e configuração (rep. fiel da execução real)", [
    '<span class="b">════════════════════════════════════════════════════════════════</span>',
    '<span class="b">  Downdetector → Zabbix → Grafana — Instalador</span>',
    '<span class="b">════════════════════════════════════════════════════════════════</span>',
    '<span class="g">[ OK ]</span>  SO: Debian GNU/Linux 13 (trixie)',
    "",
    '<span class="cy">── [1/13] Instalando dependências do sistema ─────────────────────────────────────</span>',
    '<span class="g">[ OK ]</span>  Dependências do sistema prontas',
    "",
    '<span class="cy">════════════════════════════════════════════════════════════</span>',
    '<span class="cy">  Configuração do Downdetector Monitor</span>',
    '<span class="cy">════════════════════════════════════════════════════════════</span>',
    "",
    'Diretório de instalação [/opt/downdetector-zabbix]: <span class="d">⏎</span>',
    'Zabbix URL [http://127.0.0.1/zabbix]: <span class="d">⏎</span>',
    'Zabbix usuário [Admin]: <span class="d">⏎</span>',
    '<span class="w">Zabbix senha:</span> <span class="d">********</span>',
    '<span class="g">[ OK ]</span>  Zabbix autenticado: http://127.0.0.1/zabbix',
    'Grafana URL [http://127.0.0.1:3000]: <span class="d">⏎</span>',
    'Grafana usuário [admin]: <span class="d">⏎</span>',
    '<span class="w">Grafana senha:</span> <span class="d">********</span>',
    '<span class="g">[ OK ]</span>  Grafana autenticado: http://127.0.0.1:3000',
    'Agendar coleta automática a cada 5 minutos (cron)? <span class="b">[S/n]</span> S',
    'Configurar este servidor como TV (kiosk em tela cheia)? <span class="b">[s/N]</span> n',
], 560)

# ── T3: etapas 4–7 (log real v1.1.2) ────────────────────────────────────────
block("te_03_estrutura", "install.sh — etapas 3 a 6 (log real)", [
    '<span class="cy">── [3/13] Copiando arquivos do projeto ─────────────────────────────────────</span>',
    '<span class="g">[ OK ]</span>  Arquivos copiados',
    "",
    '<span class="cy">── [4/13] Ambiente Python + Chromium ─────────────────────────────────────</span>',
    '<span class="g">[ OK ]</span>  Virtualenv já existe',
    '<span class="g">[ OK ]</span>  Pacotes Python instalados',
    '<span class="g">[ OK ]</span>  Chromium pronto',
    "",
    '<span class="cy">── [5/13] Criando wrapper do coletor ─────────────────────────────────────</span>',
    '<span class="g">[ OK ]</span>  Wrapper: /opt/downdetector-zabbix/run_collector.sh',
    "",
    '<span class="cy">── [6/13] Garantindo plugins do Grafana ─────────────────────────────────────</span>',
    '<span class="g">[ OK ]</span>  Plugin presente: gapit-htmlgraphics-panel',
    '<span class="g">[ OK ]</span>  Plugin presente: alexanderzobnin-zabbix-app',
], 480)

# ── T4: etapas 8–10 (log real v1.1.2) ────────────────────────────────────────
block("te_04_provisioning", "install.sh — etapas 7 a 9 (log real)", [
    '<span class="cy">── [7/13] Provisionando Grafana (datasource, dashboards, ícones) ─────────────────────────────────────</span>',
    '<span class="g">[ OK ]</span>  Datasource Zabbix provisionado (uid PA67C5EADE9207728)',
    '<span class="b">[INFO]</span>  Gerando dashboards...',
    '<span class="g">[ OK ]</span>  Dashboards copiados (User + Wallboard)',
    '<span class="g">[ OK ]</span>  Ícones instalados (51 arquivos)',
    '<span class="d">✓ Datasource Zabbix provisionado via arquivo (uid=PA67C5EADE9207728)</span>',
    '<span class="d">✓ Ícones copiados para /usr/share/grafana/public/img/downdetector</span>',
    '<span class="d">✓ Plugin gapit-htmlgraphics-panel habilitado</span>',
    '<span class="d">✓ Plugin alexanderzobnin-zabbix-app habilitado</span>',
    '<span class="d">✓ Provisioning do Grafana recarregado</span>',
    '<span class="g">[ OK ]</span>  Grafana provisionado',
    "",
    '<span class="cy">── [8/13] Configurando Zabbix (template + host) ─────────────────────────────────────</span>',
    '<span class="d">✓ Logado no Zabbix (http://127.0.0.1/zabbix)</span>',
    '<span class="d">✓ Template \'Downdetector Monitor\' importado/atualizado</span>',
    '<span class="d">✓ Host \'Downdetector\' atualizado</span>',
    '<span class="g">[ OK ]</span>  Zabbix configurado',
    "",
    '<span class="cy">── [9/13] Agendando coleta (cron */5) ─────────────────────────────────────</span>',
    '<span class="g">[ OK ]</span>  Cron: /etc/cron.d/downdetector-zabbix',
], 720)

# ── T5: etapas 11–14 + resumo (log real v1.1.2) ────────────────────────────
block("te_05_final", "install.sh — etapas 10 a 13 e resumo (log real)", [
    '<span class="cy">── [10/13] Configurando kiosk da TV ─────────────────────────────────────</span>',
    '<span class="b">[INFO]</span>  Kiosk não configurado (ok).',
    "",
    '<span class="cy">── [11/13] Coleta inicial (semeia o dashboard) ─────────────────────────────────────</span>',
    '<span class="b">[INFO]</span>  Rodando o coletor (1/2) — primeira passada cria o LLD...',
    '<span class="g">[ OK ]</span>  Coleta 1 concluída',
    '<span class="b">[INFO]</span>  Aguardando o Zabbix processar o LLD (20s)...',
    '<span class="b">[INFO]</span>  Rodando o coletor (2/2) — envia os valores das chaves criadas...',
    '<span class="g">[ OK ]</span>  Coleta 2 concluída',
    "",
    '<span class="cy">── [12/13] Reiniciando Grafana (aplica plugins/provisioning) ─────────────────────────────────────</span>',
    '<span class="b">[INFO]</span>  Aguardando o Grafana voltar (até 4 min)...',
    '<span class="g">[ OK ]</span>  Grafana no ar',
    "",
    '<span class="cy">── [13/13] Verificação final ─────────────────────────────────────</span>',
    '  <span class="g">✓</span> Zabbix: template, host e itens LLD',
    '  <span class="g">✓</span> Grafana: serviço ativo',
    '  <span class="g">✓</span> Grafana: datasource Zabbix responde',
    '  <span class="g">✓</span> Grafana: plugin HTML ativo',
    '  <span class="g">✓</span> Dashboard \'User\' provisionado',
    '  <span class="g">✓</span> Dashboard \'Wallboard\' provisionado',
    '  <span class="g">✓</span> Ícones publicados no Grafana',
    '  <span class="g">✓</span> Playwright importa no venv',
    '  <span class="g">✓</span> Wrapper do coletor executável',
    '  <span class="g">✓</span> Cron agendado (ou desabilitado)',
    "",
    '<span class="g">════════════════════════════════════════════════════════════════</span>',
    '<span class="g">  ✅ Instalação concluída e verificada</span>',
    '<span class="g">════════════════════════════════════════════════════════════════</span>',
    "",
    '  <span class="w">Dashboards</span>',
    '   TV/Wallboard:  <span class="cy">http://127.0.0.1:3000/d/downdetector-tv-1?kiosk</span>',
    '   Investigação:  <span class="cy">http://127.0.0.1:3000/d/downdetector-noc-1</span>',
    "",
    '  <span class="w">Operação</span>',
    '   Testar coletor:  <span class="yl">/opt/downdetector-zabbix/run_collector.sh --test</span>',
    '   Forçar coleta:   <span class="yl">/opt/downdetector-zabbix/run_collector.sh</span>',
    '   Log da instalação:  <span class="yl">/opt/downdetector-zabbix/logs/install.log</span>',
    '   Cron:            <span class="yl">/etc/cron.d/downdetector-zabbix (a cada 5 min)</span>',
], 940)

# ── T6: coleta funcionando (log real do coletor) ─────────────────────────────
block("te_06_coletor", "Coletor em operação — log real (/opt/downdetector-zabbix/logs/downdetector.log)", [
    '<span class="d">2026-09-30 15:05:05</span> <span class="b">[INFO]</span> Discovery OK: Response from "127.0.0.1:10051": '
    '"processed: 1; failed: 0; total: 1; seconds spent: 0.000067"',
    '<span class="d">2026-09-30 15:05:06</span> <span class="b">[INFO]</span> zabbix_sender OK: Response from "127.0.0.1:10051": '
    '"<span class="g">processed: 85; failed: 0</span>; total: 85; seconds spent: 0.000327"',
    '<span class="d">2026-09-30 15:10:07</span> <span class="b">[INFO]</span> Discovery OK: Response from "127.0.0.1:10051": '
    '"processed: 1; failed: 0; total: 1; seconds spent: 0.000068"',
    '<span class="d">2026-09-30 15:10:08</span> <span class="b">[INFO]</span> zabbix_sender OK: Response from "127.0.0.1:10051": '
    '"<span class="g">processed: 85; failed: 0</span>; total: 85; seconds spent: 0.000343"',
], 300)

# ── T7: deploy a partir do Windows (PowerShell) ─────────────────────────────
PS = '<span class="p">PS C:\PROJETOS\SEU_PROJETO&gt;</span> '
block("te_07_deploy_windows", "Windows PowerShell — deploy do repositório para o servidor", [
    PS + '<span class="c">$srv = "root@IP_DA_VM"; $pw = "••••••"</span>',
    "",
    PS + '<span class="c">&amp; "C:\\Program Files\\PuTTY\\pscp.exe" -pw $pw -batch .\\downdetector_dashboard.json $srv:/etc/grafana/provisioning/dashboards/json/</span>',
    "downdetector_dashboard.json     | 128 kB | 100%",
    PS + '<span class="c">&amp; "C:\\Program Files\\PuTTY\\pscp.exe" -pw $pw -batch .\\downdetector_dashboard_tv.json $srv:/etc/grafana/provisioning/dashboards/json/</span>',
    "downdetector_dashboard_tv.json  |  96 kB | 100%",
    PS + '<span class="c">&amp; "C:\\Program Files\\PuTTY\\plink.exe" -ssh $srv -pw $pw -batch "curl -s -X POST -u admin:***** http://127.0.0.1:3000/api/admin/provisioning/dashboards/reload &amp;&amp; systemctl restart grafana-server"</span>',
    '<span class="g">{}</span>',
], 420)


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)
    for b in BLOCKS:
        html_path = TMP / (b["name"] + ".html")
        png_path = IMG / (b["name"] + ".png")
        html_path.write_text(page(b["title"], "\n".join(b["lines"])), encoding="utf-8")
        shot(html_path, png_path, 1220, b["height"])
        print(f"ok {png_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
