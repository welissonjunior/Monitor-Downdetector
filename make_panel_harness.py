#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Harness de verificação dos dashboards Downdetector (User e Wallboard).

Gera páginas HTML locais que executam o onRender do painel (gapit-htmlgraphics)
com dados FALSOS, simulando os frames do datasource Zabbix. Serve para validar
mudanças de painel sem depender do render do Grafana (o render anônimo do
Grafana 13 mostra shell vazio — ver AGENTS.md / DEV/VERIFY.md).

Uso:
    python make_panel_harness.py                       # gera os dois harness
    python make_panel_harness.py --only wallboard      # só o wallboard
    python make_panel_harness.py --only user           # só o User

Cenários via query string (?scn=):
    0 | 1 | 3 | 6 | 12 | 42 | unk | stale | wide

Abra no navegador (o `serve_harness.py` serve os logos no mesmo caminho do Grafana,
`/public/img/downdetector/` — sem isso os ícones caem no fallback de iniciais):

    python serve_harness.py            # http://127.0.0.1:8791
    # http://127.0.0.1:8791/harness_wallboard.html?scn=3
    # http://127.0.0.1:8791/harness_user.html?scn=3
"""

import argparse
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
POINTS = 72          # 6h a cada 5 min (bate com time range now-6h)
STEP = 300           # cadência do coletor (s)

SERVICES_ORDER = ["pix", "bcb", "nubank", "banco-itau", "bradesco", "banco-do-brasil",
                  "caixa-economica-federal", "santander", "banco-inter", "c6-bank",
                  "sicredi", "sicoob", "neon", "btg-pactual", "banco-pan",
                  "mercado-pago", "picpay", "pagseguro", "banco-bv", "banrisul",
                  "cielo", "clear-corretora", "infinitepay", "iti", "next", "rico",
                  "xp-investimentos", "stone", "whatsapp", "google", "cloudflare",
                  "microsoft-copilot", "microsoft-365", "microsoftonedrive", "teams",
                  "keeper", "vivo", "claro", "tim", "algar", "govbr", "receite-federal"]


def load_services():
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    by_slug = {s["slug"]: s for s in cfg["services"]}
    return [by_slug[s] for s in SERVICES_ORDER if s in by_slug]


def mk_points(now, status, since=None):
    """72 pontos; a partir de (now - since) o status vira `status`, antes é 0."""
    t0 = now - (POINTS - 1) * STEP
    times = [(t0 + i * STEP) * 1000 for i in range(POINTS)]
    vals = []
    for i in range(POINTS):
        ts = t0 + i * STEP
        if status == -1:
            vals.append(-1)
        elif since is not None:
            vals.append(status if ts >= now - since else 0)
        else:
            vals.append(status)
    return times, vals


def heartbeat_series(now, age):
    times, vals = mk_points(now, 1)
    if age:
        for i in range(len(times)):
            if times[i] > (now - age) * 1000:
                times[i] = (now - age) * 1000
                vals[i] = int((now - age))
    return {
        "name": "downdetector.collector.heartbeat", "refId": "B",
        "fields": [
            {"name": "time", "type": "time", "values": times},
            {"name": "downdetector.collector.heartbeat", "type": "number", "values": vals},
        ],
    }


def build_series(services, status_map, since_map, now, heartbeat_age=0, wide=False):
    if wide:
        fields = []
        _, times = None, None
        t0 = now - (POINTS - 1) * STEP
        times = [(t0 + i * STEP) * 1000 for i in range(POINTS)]
        fields.append({"name": "time", "type": "time", "values": times})
        for svc in services:
            st = status_map.get(svc["slug"], 0)
            since = since_map.get(svc["slug"])
            _, vals = mk_points(now, st, since)
            fields.append({"name": f"Downdetector: {svc['name']} - Status",
                           "type": "number", "values": vals})
        return [{"name": "Wide", "refId": "A", "fields": fields}]

    series = []
    for svc in services:
        st = status_map.get(svc["slug"], 0)
        since = since_map.get(svc["slug"])
        times, vals = mk_points(now, st, since)
        series.append({
            "name": f"Downdetector: {svc['name']} - Status", "refId": "A",
            "fields": [
                {"name": "time", "type": "time", "values": times},
                {"name": f"Downdetector: {svc['name']} - Status", "type": "number", "values": vals},
            ],
        })
    series.append(heartbeat_series(now, heartbeat_age))
    return series


def build_scenarios():
    services = load_services()
    slugs = [s["slug"] for s in services]
    now = int(time.time())
    sc = {}

    sc["0"] = build_series(services, {}, {}, now)
    sc["1"] = build_series(services, {"claro": 1}, {"claro": 20 * 60}, now)
    # wireframe do relatório: Itaú (crítico ≥1h), Microsoft 365 (crítico 48m), Claro (instável 12m)
    sc["3"] = build_series(
        services,
        {"banco-itau": 2, "microsoft-365": 2, "claro": 1},
        {"banco-itau": 2 * 3600 + 15 * 60, "microsoft-365": 48 * 60, "claro": 12 * 60},
        now,
    )
    six = {"vivo": 2, "google": 1, "nubank": 2, "sicoob": 1, "teams": 1, "govbr": 2}
    since6 = {k: (65 if k == "vivo" else 25) * 60 for k in six}
    sc["6"] = build_series(services, six, since6, now)
    twelve = dict(six)
    twelve.update({"pix": 1, "bradesco": 2, "banco-do-brasil": 1, "whatsapp": 1,
                   "onedrive" if False else "microsoftonedrive": 2, "tim": 1,
                   "cloudflare": 1, "picpay": 1, "banrisul": 1})
    since12 = {k: 10 * 60 for k in twelve}
    since12["vivo"] = 65 * 60
    sc["12"] = build_series(services, twelve, since12, now)
    sc["42"] = build_series(services, {s: 2 for s in slugs},
                            {s: 15 * 60 for s in slugs}, now)
    sc["unk"] = build_series(services, {s: -1 for s in slugs}, {}, now)
    sc["stale"] = build_series(services, {}, {}, now, heartbeat_age=2 * 3600)
    sc["wide"] = build_series(
        services,
        {"banco-itau": 2, "microsoft-365": 2, "claro": 1},
        {"banco-itau": 2 * 3600 + 15 * 60, "microsoft-365": 48 * 60, "claro": 12 * 60},
        now, wide=True,
    )
    return sc


HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>__TITLE__ — harness</title>
<style>
  html,body{margin:0;padding:0;background:#111}
  #bar{font:13px/1.4 system-ui,sans-serif;color:#ddd;background:#222;padding:6px 10px}
  #bar a{color:#7fd;margin-right:8px}
  /* host em 1920x1080 reais; !important vence o inline do parent-chain do painel.
     zoom = viewport/1920 -> o board inteiro cabe na janela para inspeção/screenshot. */
  #host{position:relative;width:1920px !important;height:1080px !important;background:#050505;overflow:hidden}
</style>
</head>
<body>
<div id="bar">harness __TITLE__ · cenário:
<a href="?scn=0">0 (ok)</a><a href="?scn=1">1</a><a href="?scn=3">3</a><a href="?scn=6">6</a><a href="?scn=12">12</a><a href="?scn=42">42</a><a href="?scn=unk">unk</a><a href="?scn=stale">stale</a><a href="?scn=wide">wide</a>
· atual: <b id="scn"></b></div>
<div id="host"><div id="panel"></div></div>
<script>
(function fitZoom(){
  // ?raw=1 desliga o encaixe e mostra o board em 1:1 (role a página p/ ver tudo)
  if (new URLSearchParams(location.search).has('raw')) { document.getElementById('host').style.zoom = 1; return; }
  const z = window.innerWidth / 1920;
  document.getElementById('host').style.zoom = z;
  window.addEventListener('resize', fitZoom);
})();
</script>
<script>
const SCEN = __SCEN__;
const params = new URLSearchParams(location.search);
const scn = params.get('scn') || '3';
document.getElementById('scn').textContent = scn;
var htmlNode = document.getElementById('panel');
var data = { series: SCEN[scn] || SCEN['3'] };
__ONRENDER__
</script>
</body>
</html>
"""


def gen(dash_file, out_file):
    dash = json.loads((HERE / dash_file).read_text(encoding="utf-8"))
    js = dash["panels"][0]["options"]["onRender"]
    sc = build_scenarios()
    html = (HTML
            .replace("__TITLE__", dash["title"])
            .replace("__SCEN__", json.dumps(sc))
            .replace("__ONRENDER__", js))
    out = HERE / out_file
    out.write_text(html, encoding="utf-8")
    print(f"OK: {out} ({out.stat().st_size // 1024} KB, {len(sc)} cenários)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["user", "wallboard"], default=None)
    args = ap.parse_args()
    if args.only in (None, "user"):
        gen("downdetector_dashboard.json", "harness_user.html")
    if args.only in (None, "wallboard"):
        gen("downdetector_dashboard_tv.json", "harness_wallboard.html")


if __name__ == "__main__":
    main()
