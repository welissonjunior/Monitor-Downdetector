#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Downdetector NOC — dois dashboards gerados a partir deste builder:
  - downdetector_dashboard.json    → "Downdetector NOC - User" (downdetector-noc-1):
    42 cards por categoria — visão de investigação p/ desktop.
  - downdetector_dashboard_tv.json → "Downdetector NOC - Wallboard" (downdetector-tv-1):
    wallboard de detecção p/ TV (veredito + incidentes + matriz de pontos por categoria;
    ver DEV/REDESIGN_TV_40.md).
Visual alinhado ao Downdetector.com.br (dark): fundo preto, cards brancos,
acento vermelho, sparklines de status.
"""

import json
from pathlib import Path

DS_UID = "PA67C5EADE9207728"
HOST_FILTER = "Downdetector"
STATUS_ITEM_PATTERN = "/Downdetector: .* - Status/"

CATEGORY_ORDER = [
    "Instituições Financeiras", "Microsoft 365", "Telecom", "Internet/Apps", "Segurança", "Governo", "Outros"
]

# Layout rows: categories + CSS grid-template-columns
LAYOUT_ROWS = [
    {"cats": ["Instituições Financeiras"], "cols": "1fr"},
    {"cats": ["Telecom", "Internet/Apps"], "cols": "1fr 1fr"},
    {"cats": ["Microsoft 365", "Segurança"], "cols": "2fr 1fr"},
    {"cats": ["Governo"], "cols": "1fr"},
    {"cats": ["Outros"], "cols": "1fr"},
]


def load_config():
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def zabbix_target_status():
    return {
        "datasource": {"type": "alexanderzobnin-zabbix-datasource", "uid": DS_UID},
        "group": {"filter": "/.*/"},
        "host": {"filter": HOST_FILTER},
        "application": {"filter": ""},
        "itemTag": {"filter": ""},
        "item": {"filter": STATUS_ITEM_PATTERN},
        "functions": [],
        "options": {"showTopology": False, "disableDataAlignment": False},
        "queryType": 0,
        "refId": "A",
    }


def zabbix_target_heartbeat():
    return {
        "datasource": {"type": "alexanderzobnin-zabbix-datasource", "uid": DS_UID},
        "group": {"filter": "/.*/"},
        "host": {"filter": HOST_FILTER},
        "application": {"filter": ""},
        "itemTag": {"filter": ""},
        "item": {"filter": "downdetector.collector.heartbeat"},
        "functions": [],
        "options": {"showTopology": False, "disableDataAlignment": False},
        "queryType": 0,
        "refId": "B",
    }


def build_js(categories, services_cfg, cat_order, layout_rows, visual_cfg):
    cat_json = json.dumps(categories, ensure_ascii=False)
    services_json = json.dumps(services_cfg, ensure_ascii=False)
    order_json = json.dumps(cat_order, ensure_ascii=False)
    layout_json = json.dumps(layout_rows, ensure_ascii=False)
    visual_json = json.dumps(visual_cfg, ensure_ascii=False)

    return r"""
(() => {
  if (!htmlNode) return;
  if (!data || !data.series || data.series.length === 0) {
    htmlNode.innerHTML = '<div class="dd-empty">Aguardando dados do Zabbix...</div>';
    return;
  }

  const categories = """ + cat_json + r""";
  const servicesCfg = """ + services_json + r""";
  const catOrder = """ + order_json + r""";
  const layoutRows = """ + layout_json + r""";
  const visualCfg = """ + visual_json + r""";
  const tvMode = visualCfg.layout_mode === 'tv';
  const isWallboard = visualCfg.layout_mode === 'wallboard';

  const byName = {};
  const bySlug = {};
  servicesCfg.forEach(s => {
    byName[s.name] = s;
    byName[s.name.toLowerCase()] = s;
    bySlug[s.slug] = s;
  });

  function stripAccents(str) {
    return String(str || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }
  function guessSlug(name) {
    return stripAccents(name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }
  function resolveMeta(displayName) {
    if (byName[displayName]) return byName[displayName];
    if (byName[displayName.toLowerCase()]) return byName[displayName.toLowerCase()];
    const g = guessSlug(displayName);
    if (bySlug[g]) return bySlug[g];
    const found = servicesCfg.find(s =>
      stripAccents(s.name).toLowerCase() === stripAccents(displayName).toLowerCase() ||
      g.includes(s.slug) || s.slug.includes(g)
    );
    if (found) return found;
    return { slug: g, name: displayName, category: categories[g] || 'Outros' };
  }
  function valAt(field, i) {
    if (!field || !field.values) return null;
    const vals = field.values;
    if (i < 0 || i >= vals.length) return null;
    let v = (typeof vals.get === 'function') ? vals.get(i) : vals[i];
    if (v === null || v === undefined) return null;
    return v;
  }
  function sinceWhen(timeField, valueField) {
    if (!valueField || !valueField.values || !valueField.values.length) return { status: null, sinceTs: null };
    const n = valueField.values.length;
    let lastIdx = n - 1;
    let status = valAt(valueField, lastIdx);
    while (lastIdx > 0 && (status === null || status === undefined)) { lastIdx--; status = valAt(valueField, lastIdx); }
    if (status === null || status === undefined) return { status: null, sinceTs: null };
    status = Number(status);
    let i = lastIdx;
    while (i > 0) {
      const prev = valAt(valueField, i - 1);
      if (prev === null || prev === undefined) { i--; continue; }
      if (Number(prev) !== status) break;
      i--;
    }
    let sinceTs = null;
    if (timeField && timeField.values && timeField.values.length) sinceTs = Number(valAt(timeField, i));
    return { status, sinceTs };
  }
  function sampleHistory(valueField, maxPts) {
    if (!valueField || !valueField.values || !valueField.values.length) return [];
    const n = valueField.values.length;
    const pts = Math.min(maxPts || 36, n);
    const out = [];
    if (n <= pts) {
      for (let i = 0; i < n; i++) {
        const v = valAt(valueField, i);
        if (v === null || v === undefined) continue;
        out.push(Number(v));
      }
      return out;
    }
    for (let i = 0; i < pts; i++) {
      const idx = Math.round(i * (n - 1) / (pts - 1));
      const v = valAt(valueField, idx);
      out.push(v === null || v === undefined ? 0 : Number(v));
    }
    return out;
  }
  function formatSince(ts) {
    if (!ts) return '';
    if (ts < 1e12) ts = ts * 1000;
    const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
    if (diffSec < 60) return 'agora';
    if (diffSec < 3600) return Math.floor(diffSec / 60) + 'm';
    if (diffSec < 86400) {
      const h = Math.floor(diffSec / 3600), m = Math.floor((diffSec % 3600) / 60);
      return m > 0 ? h + 'h ' + m + 'm' : h + 'h';
    }
    return Math.floor(diffSec / 86400) + 'd';
  }

  const services = [];
  let heartbeatTs = null;

  function pushService(rawName, status, sinceTs, hist) {
    if (status === null || Number.isNaN(status)) return;
    let name = String(rawName || '').replace(/^Downdetector:\s*/i, '').replace(/\s*-\s*Status$/i, '').trim();
    if (!name) return;
    if (services.some(s => s.name === name)) return;
    const meta = resolveMeta(name);
    const slug = meta.slug;
    const category = categories[slug] || meta.category || 'Outros';
    services.push({
      name: meta.name || name,
      status,
      category,
      slug,
      sinceTs: sinceTs || null,
      since: formatSince(sinceTs),
      hist: hist || []
    });
  }

  function extractHeartbeat(seriesList) {
    for (const series of seriesList) {
      const sname = series.name || '';
      const refId = series.refId || '';
      if (!sname.includes('heartbeat') && !sname.includes('Heartbeat') && refId !== 'B') continue;
      const fields = series.fields || [];
      const timeField = fields.find(f => f.type === 'time') || fields[0];
      const valueField = fields.find(f => f.type === 'number') || fields[1];
      if (!valueField || !valueField.values || !valueField.values.length) continue;
      const n = valueField.values.length;
      let lastIdx = n - 1;
      let v = valAt(valueField, lastIdx);
      while (lastIdx > 0 && (v === null || v === undefined)) { lastIdx--; v = valAt(valueField, lastIdx); }
      if (v === null || v === undefined) continue;
      if (timeField && timeField.values && timeField.values.length) {
        heartbeatTs = Number(valAt(timeField, lastIdx));
      } else {
        heartbeatTs = Number(v) * 1000;
      }
      return true;
    }
    return false;
  }

  const seriesList = data.series || [];
  extractHeartbeat(seriesList);

  const isWide = seriesList.length === 1 && ((seriesList[0].name || '').toLowerCase() === 'wide' || ((seriesList[0].fields || []).length > 3));
  if (isWide) {
    const fields = seriesList[0].fields || [];
    const timeField = fields.find(f => f.type === 'time') || fields[0];
    fields.forEach(field => {
      const fname = field.name || '';
      if (field.type === 'time') return;
      if (!fname.includes('Status') && !fname.includes('status')) return;
      const info = sinceWhen(timeField, field);
      pushService(fname, info.status, info.sinceTs, sampleHistory(field, 36));
    });
  } else {
    seriesList.forEach(series => {
      const sname = series.name || '';
      const refId = series.refId || '';
      if (sname.includes('heartbeat') || sname.includes('Heartbeat') || refId === 'B') return;
      if (!sname.includes('Status') && !sname.includes('status')) return;
      const fields = series.fields || [];
      const timeField = fields.find(f => f.type === 'time') || fields[0];
      const valueField = fields.find(f => f.type === 'number') || fields[1];
      const info = sinceWhen(timeField, valueField);
      pushService(sname, info.status, info.sinceTs, sampleHistory(valueField, 36));
    });
  }

  function ageSec(sinceTs) {
    if (!sinceTs) return 0;
    let ts = Number(sinceTs);
    if (ts < 1e12) ts *= 1000;
    return Math.max(0, Math.floor((Date.now() - ts) / 1000));
  }
  function isProblem(s) { return s.status === 1 || s.status === 2; }
  function isLong(s) { return isProblem(s) && ageSec(s.sinceTs) >= 3600; }

  const total = services.length;
  const instaveis = services.filter(isProblem).length;
  const longos = services.filter(isLong).length;
  const ok = services.filter(s => s.status === 0).length;
  const now = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

  function lastUpdateText() {
    if (!visualCfg.show_last_update) return '';
    let ts = heartbeatTs || 0;
    if (!ts) return 'Atualizado: ' + now;
    if (ts < 1e12) ts = ts * 1000;
    const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
    let txt = '';
    if (diffSec < 60) txt = 'agora';
    else if (diffSec < 3600) txt = Math.floor(diffSec / 60) + 'min';
    else if (diffSec < 86400) {
      const h = Math.floor(diffSec / 3600), m = Math.floor((diffSec % 3600) / 60);
      txt = m > 0 ? h + 'h ' + m + 'min' : h + 'h';
    } else txt = Math.floor(diffSec / 86400) + 'd';
    if (diffSec > 600) return '<span style="color:#e8a317">Atualizado há ' + txt + '</span>';
    return 'Atualizado há ' + txt;
  }

  function isSicoob(s) {
    return s.slug === 'sicoob' || stripAccents(s.name).toLowerCase() === 'sicoob';
  }
  function sortServices(a, b) {
    // Sicoob always first card (even when OK)
    if (isSicoob(a) && !isSicoob(b)) return -1;
    if (!isSicoob(a) && isSicoob(b)) return 1;
    // long problems first, then short problems, then unknown, then OK
    const rank = (s) => {
      if (isLong(s)) return 0;
      if (isProblem(s)) return 1;
      if (s.status === -1) return 2;
      return 3;
    };
    const ra = rank(a), rb = rank(b);
    if (ra !== rb) return ra - rb;
    if (isProblem(a) && isProblem(b)) return ageSec(b.sinceTs) - ageSec(a.sinceTs);
    return a.name.localeCompare(b.name, 'pt-BR');
  }
  function safeName(n) {
    return stripAccents(n).toLowerCase().replace(/ /g, '_').replace(/\//g, '_').replace(/[^a-z0-9_]/g, '_');
  }
  function stColor(s) {
    if (s.status === 0) return '#1a9e4a';
    if (s.status === -1) return '#8a8a8a';
    if (isLong(s)) return '#e11d2e';
    if (s.status === 1) return '#e8a317';
    return '#f47c20';
  }
  function stLabel(s) {
    if (s.status === 0) return 'OK';
    if (s.status === -1) return 'Sem dados';
    if (!visualCfg.show_problem_severity) return 'Problema';
    if (s.status === 2) return 'Crítico';
    return 'Instável';
  }
  function edge(s) {
    if (!isProblem(s)) return '';
    if (isLong(s)) return 'border-color:rgba(225,29,46,.7);box-shadow:inset 3px 0 0 #e11d2e';
    if (s.status === 2) return 'border-color:rgba(244,124,32,.65);box-shadow:inset 3px 0 0 #f47c20';
    return 'border-color:rgba(232,163,23,.55);box-shadow:inset 3px 0 0 #e8a317';
  }
  function pulseClass(s) {
    return (visualCfg.pulse_critical && isLong(s)) ? 'dd-pulse' : '';
  }

  function sparkline(s, w, h, sw) {
    w = w || 72; h = h || 36; sw = sw || 2;
    const pad = 2;
    let pts = (s.hist && s.hist.length) ? s.hist.slice() : [s.status];
    if (pts.length === 1) pts = [pts[0], pts[0]];
    function yOf(v) {
      const n = Number(v);
      let lvl = 0;
      if (n === 1 || n === 2) lvl = isLong(s) && n === pts[pts.length - 1] ? 2 : 1;
      if (n >= 2) lvl = Math.max(lvl, isLong(s) ? 2 : 1);
      if (n === 1) lvl = Math.max(lvl, 1);
      return h - pad - (lvl / 2) * (h - pad * 2);
    }
    const step = (w - pad * 2) / (pts.length - 1);
    let d = '';
    for (let i = 0; i < pts.length; i++) {
      const x = pad + i * step;
      const y = yOf(pts[i]);
      d += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1) + ' ';
    }
    const col = isProblem(s) ? stColor(s) : '#3db7e4';
    return '<svg class="dd-spark" viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h + '" aria-hidden="true">' +
      '<path d="' + d.trim() + '" fill="none" stroke="' + col + '" stroke-width="' + sw + '" stroke-linejoin="round" stroke-linecap="round"/>' +
      '</svg>';
  }

  function renderCard(s) {
    const safe = safeName(s.name);
    const init = s.name.charAt(0).toUpperCase();
    const color = stColor(s);
    const since = (isProblem(s) && s.since) ? ' · há ' + s.since : '';
    const catColor = visualCfg.category_colors[s.category] || '#e11d2e';
    return '<a class="dd-card ' + pulseClass(s) + '" href="' + visualCfg.status_base + s.slug + '/" target="_blank" rel="noopener" style="' + edge(s) + '">' +
      '<div class="dd-logo" style="border-color:' + catColor + '30">' +
        '<img src="/public/img/downdetector/' + safe + '.png" alt="" onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\'">' +
        '<span class="dd-fb" style="background:' + catColor + '22;color:' + catColor + '">' + init + '</span>' +
      '</div>' +
      '<div class="dd-meta">' +
        '<span class="dd-name" title="' + s.name + '">' + s.name + '</span>' +
        '<span class="dd-st" style="color:' + color + '"><i class="dd-dot" style="background:' + color + '"></i>' + stLabel(s) + since + '</span>' +
      '</div>' +
      sparkline(s) +
    '</a>';
  }

  function renderSection(cat) {
    const list = services.filter(s => s.category === cat).sort(sortServices);
    if (!list.length) return '';
    const badN = list.filter(s => s.status === 1 || s.status === 2).length;
    const okN = list.length - badN;
    const catColor = visualCfg.category_colors[cat] || '#e11d2e';
    let count = okN + '/' + list.length + ' OK';
    if (badN) count += ' · <span class="bad">' + badN + ' problema' + (badN > 1 ? 's' : '') + '</span>';
    let h = '<div class="dd-sec"><div class="dd-sec-hd"><span class="dd-sec-title" style="border-color:' + catColor + '">' + cat + '</span><span class="dd-sec-count">' + count + '</span></div><div class="dd-grid">';
    list.forEach(s => { h += renderCard(s); });
    h += '</div></div>';
    return h;
  }

  // ── MODO TV (layout_mode: "tv") ─────────────────────────────────────────
  // Legibilidade a 3-4m: só problemas ganham cards grandes (fonte 30px);
  // serviços OK viram chips (identificação, não leitura) e nunca escondemos
  // um problema atrás de um "OK" genérico (anti falso-verde).
  const TV_MAX_PROBLEMS = 12;

  function renderTvProblemCard(s) {
    const safe = safeName(s.name);
    const init = s.name.charAt(0).toUpperCase();
    const color = stColor(s);
    const catColor = visualCfg.category_colors[s.category] || '#e11d2e';
    return '<a class="dd-pcard ' + pulseClass(s) + '" href="' + visualCfg.status_base + s.slug + '/" target="_blank" rel="noopener" style="border-color:' + color + '55">' +
      '<span class="dd-pband" style="background:' + color + '"></span>' +
      '<div class="dd-plogo" style="border-color:' + catColor + '44">' +
        '<img src="/public/img/downdetector/' + safe + '.png" alt="" onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\'">' +
        '<span class="dd-pfb" style="background:' + catColor + '22;color:' + catColor + '">' + init + '</span>' +
      '</div>' +
      '<div class="dd-pmeta">' +
        '<span class="dd-pname" title="' + s.name + '">' + s.name + '</span>' +
        '<span class="dd-pcat">' + s.category + '</span>' +
      '</div>' +
      '<div class="dd-pstat">' +
        '<span class="dd-plabel" style="color:' + color + '"><i class="dd-dot" style="background:' + color + '"></i>' + stLabel(s) + '</span>' +
        '<span class="dd-psince">' + (s.since ? 'há ' + s.since : '') + '</span>' +
      '</div>' +
      sparkline(s) +
    '</a>';
  }

  function renderTvChips(list, color) {
    let h = '<div class="dd-chips">';
    list.forEach(s => {
      const safe = safeName(s.name);
      h += '<span class="dd-chip" title="' + s.name + '">' +
        '<img src="/public/img/downdetector/' + safe + '.png" alt="" onerror="this.style.display=\'none\'">' +
        '<i class="dd-dot" style="background:' + color + '"></i>' + s.name +
      '</span>';
    });
    return h + '</div>';
  }

  function renderTv() {
    const problems = services.filter(isProblem).sort(sortServices);
    const oks = services.filter(s => s.status === 0).sort(sortServices);
    const unknown = services.filter(s => s.status === -1).sort(sortServices);
    let h = '';

    if (problems.length) {
      const shown = problems.slice(0, TV_MAX_PROBLEMS);
      catOrder.filter(c => shown.some(s => s.category === c)).forEach(cat => {
        const list = shown.filter(s => s.category === cat);
        const catColor = visualCfg.category_colors[cat] || '#e11d2e';
        h += '<div class="dd-tblock"><div class="dd-thead">' +
          '<span class="dd-ttitle" style="border-color:' + catColor + '">' + cat + '</span>' +
          '<span class="dd-tcount">' + list.length + ' problema' + (list.length > 1 ? 's' : '') + '</span>' +
          '</div><div class="dd-pgrid">' + list.map(renderTvProblemCard).join('') + '</div></div>';
      });
      if (problems.length > TV_MAX_PROBLEMS) {
        h += '<div class="dd-thead"><span class="dd-tcount">+ ' + (problems.length - TV_MAX_PROBLEMS) +
             ' outros problemas — ver dashboard completo</span></div>';
      }
    } else if (unknown.length) {
      // Anti falso-verde: sem coleta NÃO é "tudo ok".
      h += '<div class="dd-okhero"><div class="dd-okbig" style="color:#e8a317">' + unknown.length + ' SEM DADOS</div>' +
           '<div class="dd-oksub">coleta indisponível — verificar o coletor</div></div>';
    } else {
      h += '<div class="dd-okhero"><div class="dd-okbig" style="color:#1a9e4a">TUDO OK</div>' +
           '<div class="dd-oksub">' + oks.length + ' de ' + total + ' serviços sem problemas</div></div>';
    }

    if (oks.length) {
      h += '<div class="dd-tblock dd-tok"><div class="dd-thead">' +
        '<span class="dd-ttitle" style="border-color:#1a9e4a">Sem problemas (' + oks.length + ')</span>' +
        '<span class="dd-tcount">' + instaveis + ' instáveis · ' + longos + ' com ≥ 1h</span>' +
        '</div>' + renderTvChips(oks, '#1a9e4a') + '</div>';
    }
    if (unknown.length && problems.length) {
      h += '<div class="dd-tblock dd-tok"><div class="dd-thead">' +
        '<span class="dd-ttitle" style="border-color:#8a8a8a">Sem dados (' + unknown.length + ')</span>' +
        '</div>' + renderTvChips(unknown, '#8a8a8a') + '</div>';
    }
    return h;
  }

  // ── MODO WALLBOARD (dashboard "Downdetector NOC - Wallboard", downdetector-tv-1) ──
  // Arquitetura de detecção p/ TV 40" (DEV/REDESIGN_TV_40.md):
  // N1 = veredito + incidentes ativos (linhas grandes) | N2 = matriz de pontos por
  // categoria (os 42 serviços presentes, identificação sem leitura) | N3 (investigar)
  // = dashboard "User" (downdetector-noc-1), intocado.
  const WALL_MAX_ROWS = 5; // linhas da grade de incidentes; 2 colunas → até 10 cartões

  const WALLBOARD_CSS =
    '*{box-sizing:border-box;margin:0;padding:0}' +
    '#dd.dd-wallboard{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#050505;color:#fff;position:absolute;inset:0;width:100%;height:100%;display:flex;flex-direction:column;overflow:hidden}' +
    '.ddw-hd{flex:0 0 auto;height:80px;padding:0 30px;display:flex;align-items:center;justify-content:space-between;gap:24px;border-bottom:1px solid #1f1f1f}' +
    '.ddw-hd-l{display:flex;align-items:center;gap:18px;min-width:0;width:340px;flex-shrink:0}' +
    '.ddw-tenant{height:54px;width:auto;max-width:220px;object-fit:contain;flex-shrink:0}' +
    '.ddw-brand{display:flex;flex-direction:column;gap:2px;min-width:0}' +
    '.ddw-bname{font-size:24px;font-weight:700;letter-spacing:-.01em;white-space:nowrap;color:#fff}.ddw-bname b{color:#e11d2e}' +
    '.ddw-update{font-size:14px;color:#8a8a8a;white-space:nowrap}' +
    // faixa de status = cabeçalho do bloco de incidentes (contagem integrada)
    '.ddw-shead{flex:0 0 auto;display:flex;align-items:center;gap:18px;padding:0 2px 12px}' +
    '.ddw-sbadge{display:inline-flex;align-items:center;justify-content:center;width:50px;height:50px;border-radius:50%;font-size:27px;font-weight:800;color:#fff;line-height:1;flex-shrink:0}' +
    '.ddw-stitle{font-size:40px;font-weight:800;line-height:1;letter-spacing:.01em;white-space:nowrap}' +
    '.ddw-ssub{margin-left:auto;font-size:20px;color:#a8a8a8;font-weight:600;white-space:nowrap}' +
    '.ddw-hd-r{display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0;width:240px}' +
    '.ddw-clock{font-family:Consolas,ui-monospace,monospace;font-size:36px;font-weight:700;line-height:1;color:#fff}' +
    '.ddw-collect{font-size:14px;color:#8a8a8a;white-space:nowrap}.ddw-collect.ddw-late{color:#e8a317;font-weight:700}' +
    '.ddw-inc{flex:0 0 auto;min-height:0;overflow:hidden;padding:10px 26px;display:flex;flex-direction:column;gap:8px}' +
    '.ddw-chead{flex:0 0 auto;display:flex;align-items:baseline;justify-content:space-between;gap:16px}' +
    '.ddw-ctitle{font-size:20px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#fff}' +
    '.ddw-cnote{font-size:15px;color:#8a8a8a;font-weight:600}' +
    '.ddw-ilist{flex:0 0 auto;display:grid;grid-template-columns:repeat(2,1fr);gap:8px 12px}' +
    '.ddw-irow{height:56px;display:flex;align-items:center;gap:14px;padding:0 20px 0 14px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.10);border-radius:5px;min-width:0;min-height:0;overflow:hidden}' +
    '.dd-pulse{animation:dd-pulse 1.6s ease-in-out infinite}' +
    '@keyframes dd-pulse{0%,100%{box-shadow:0 0 0 0 rgba(225,29,46,.35)}50%{box-shadow:0 0 0 6px rgba(225,29,46,0)}}' +
    '.ddw-ilog{width:32px;height:32px;flex-shrink:0;border-radius:8px;overflow:hidden;display:flex;align-items:center;justify-content:center;position:relative;border:1px solid rgba(255,255,255,.08)}' +
    '.ddw-ilog img{width:100%;height:100%;object-fit:contain;padding:2px}' +
    '.ddw-ifb{display:none;width:100%;height:100%;align-items:center;justify-content:center;font-size:16px;font-weight:700;position:absolute;inset:0}' +
    '.ddw-imeta{flex:1;min-width:0;display:flex;align-items:center}' +
    '.ddw-iname{font-size:24px;font-weight:700;line-height:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#f5f5f5}' +
    '.ddw-ist{display:flex;align-items:center;gap:10px;flex-shrink:0}' +
    '.ddw-ilabel{font-size:19px;font-weight:700;display:flex;align-items:center;gap:8px;white-space:nowrap}' +
    '.ddw-ilabel .dd-dot{width:12px;height:12px;border-radius:50%}' +
    '.ddw-isince{font-size:16px;font-weight:600;color:#d8d8d8;white-space:nowrap;min-width:70px;text-align:right}' +
    '.ddw-cfoot{flex:0 0 auto;font-size:16px;color:#9a9a9a;font-weight:600;text-align:right;padding-right:6px}' +
    '.ddw-okline{flex:0 0 auto;display:flex;align-items:center;gap:14px;border:1px solid;border-radius:5px;padding:12px 20px;font-size:26px;font-weight:700;background:rgba(255,255,255,.04)}' +
    // ── serviços em 3 faixas horizontais (não grade) ────────────────────────────
    '.ddw-cat{flex:1 1 auto;min-height:0;overflow:hidden;padding:12px 26px 14px;display:flex;flex-direction:column;justify-content:space-evenly;gap:10px;border-top:1px solid #1f1f1f}' +
    '.ddw-band{flex:0 0 auto;display:flex;flex-direction:column;gap:6px;min-height:0}' +
    '.ddw-band-hd{display:flex;align-items:baseline;justify-content:space-between;gap:14px}' +
    '.ddw-band-name{font-size:22px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#fff;padding-left:12px;border-left:5px solid #e11d2e;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
    '.ddw-band-count{font-size:14px;color:#8a8a8a;font-weight:600;white-space:nowrap}' +
    '.ddw-band-cok{color:#8a8a8a}.ddw-band-cbad{color:#e8a317;font-weight:700}.ddw-band-cunk{color:#8a8a8a}' +
    '.ddw-band-chips{display:grid;grid-template-columns:repeat(auto-fill,minmax(252px,1fr));gap:8px;align-content:start}' +
    '.ddw-band-grow{flex:1 1 auto;min-height:0}' +
    // chip: 1 chip = 1 serviço; logo + nome + ponto de estado
    '.ddw-chip{display:flex;width:100%;min-width:0;align-items:center;gap:8px;height:38px;padding:0 12px 0 6px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.10);border-radius:4px;font-size:18px;font-weight:600;color:#eaeaea;white-space:nowrap}' +
    '.ddw-chip .ddw-cname{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis}' +
    '.ddw-chip img{width:26px;height:26px;object-fit:contain;border-radius:3px}' +
    '.ddw-chip .ddw-cfb{display:none;width:26px;height:26px;border-radius:3px;align-items:center;justify-content:center;font-size:14px;font-weight:700;flex-shrink:0}' +
    '.ddw-chip .ddw-cdot{width:10px;height:10px;border-radius:50%;flex-shrink:0}' +
    '.ddw-chip.ddw-prob{background:rgba(232,163,23,.10);border-color:rgba(232,163,23,.40)}' +
    '.ddw-chip.ddw-crit{background:rgba(244,124,32,.12);border-color:rgba(244,124,32,.45)}' +
    '.ddw-chip.ddw-long{background:rgba(225,29,46,.12);border-color:rgba(225,29,46,.50);animation:ddw-dotpulse 1.6s ease-in-out infinite}' +
    // unk = visível, só com borda tracejada (não opacidade — não some)
    '.ddw-chip.ddw-unk{background:rgba(255,255,255,.03);border:1px dashed rgba(255,255,255,.30);color:#8a8a8a}' +
    '.ddw-chip.ddw-unk .ddw-cdot{background:#6b6b6b !important}' +
    '.ddw-chip.ddw-first{outline:2px solid rgba(255,255,255,.55);outline-offset:2px}' +
    // tiers de chip por medição (espaço real disponível p/ serviços)
    '.ddw-cat.ddw-chips-xl .ddw-chip{height:58px;font-size:26px;gap:12px;padding:0 20px 0 8px}.ddw-cat.ddw-chips-xl .ddw-chip img,.ddw-cat.ddw-chips-xl .ddw-cfb{width:40px;height:40px}.ddw-cat.ddw-chips-xl .ddw-cfb{font-size:21px}.ddw-cat.ddw-chips-xl .ddw-band-chips{gap:14px;grid-template-columns:repeat(auto-fill,minmax(336px,1fr))}.ddw-cat.ddw-chips-xl .ddw-band-name{font-size:27px}' +
    '.ddw-cat.ddw-chips-lg .ddw-chip{height:48px;font-size:22px;gap:10px;padding:0 16px 0 7px}.ddw-cat.ddw-chips-lg .ddw-chip img,.ddw-cat.ddw-chips-lg .ddw-cfb{width:32px;height:32px}.ddw-cat.ddw-chips-lg .ddw-cfb{font-size:17px}.ddw-cat.ddw-chips-lg .ddw-band-chips{gap:10px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}.ddw-cat.ddw-chips-lg .ddw-band-name{font-size:24px}' +
    '.ddw-cat.ddw-chips-sm .ddw-chip{height:32px;font-size:15px;gap:6px;padding:0 10px 0 5px}.ddw-cat.ddw-chips-sm .ddw-chip img,.ddw-cat.ddw-chips-sm .ddw-cfb{width:20px;height:20px}.ddw-cat.ddw-chips-sm .ddw-cfb{font-size:11px}.ddw-cat.ddw-chips-sm .ddw-band-chips{gap:5px;grid-template-columns:repeat(auto-fill,minmax(198px,1fr))}.ddw-cat.ddw-chips-sm .ddw-band-name{font-size:19px}' +
    '@keyframes ddw-dotpulse{0%,100%{opacity:1}50%{opacity:.5}}';

  function wColor(s) {
    if (s.status === 0) return '#2a5c40';
    if (s.status === -1) return '#6b6b6b';
    if (isLong(s)) return '#e11d2e';
    if (s.status === 1) return '#e8a317';
    return '#f47c20';
  }

  function wVerdict() {
    const unknown = services.filter(s => s.status === -1);
    const problems = services.filter(isProblem);
    if (problems.length) {
      let color = '#e8a317';
      if (problems.some(isLong)) color = '#e11d2e';
      else if (problems.some(s => s.status === 2)) color = '#f47c20';
      const crit = problems.filter(s => s.status === 2).length;
      const inst = problems.length - crit;
      let sub = crit + (crit === 1 ? ' crítico' : ' críticos') + ' · ' + inst + (inst === 1 ? ' instável' : ' instáveis');
      if (unknown.length) sub += ' · <span style="color:#9a9a9a">' + unknown.length + ' sem dados</span>';
      return { icon: '!', big: problems.length + ' PROBLEMA' + (problems.length > 1 ? 'S' : ''), sub: sub, color: color, pulse: problems.some(isLong) };
    }
    if (unknown.length) {
      return { icon: '!', big: unknown.length + ' SEM DADOS', sub: 'coleta indisponível — verificar o coletor', color: '#e8a317', pulse: false };
    }
    if (!total) {
      return { icon: '!', big: 'SEM DADOS', sub: 'nenhum serviço recebido do Zabbix', color: '#e8a317', pulse: false };
    }
    // anti falso-verde residual: sem coleta recente não se afirma estado atual
    const hb = wHb();
    if (hb.stale) {
      return { icon: '✓', big: 'TUDO OK', sub: 'dados desatualizados — coleta há ' + hb.text + ' (verificar o coletor)', color: '#e8a317', pulse: false };
    }
    return { icon: '✓', big: 'TUDO OK', sub: ok + ' de ' + total + ' serviços sem problemas', color: '#1a9e4a', pulse: false };
  }

  function wIncidentRow(s) {
    const safe = safeName(s.name);
    const init = s.name.charAt(0).toUpperCase();
    const color = stColor(s);
    const catColor = visualCfg.category_colors[s.category] || '#e11d2e';
    return '<div class="ddw-irow ' + pulseClass(s) + '" style="background:' + color + '0f;border-color:' + color + '33">' +
      '<div class="ddw-ilog">' +
        '<img src="/public/img/downdetector/' + safe + '.png" alt="" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">' +
        '<span class="ddw-ifb" style="background:' + catColor + '22;color:' + catColor + '">' + init + '</span>' +
      '</div>' +
      '<div class="ddw-imeta">' +
        '<span class="ddw-iname" title="' + s.name + '">' + s.name + '</span>' +
      '</div>' +
      '<div class="ddw-ist">' +
        '<span class="ddw-ilabel" style="color:' + color + '"><i class="dd-dot" style="background:' + color + '"></i>' + stLabel(s) + '</span>' +
        '<span class="ddw-isince">' + (s.since || 'agora') + '</span>' +
      '</div>' +
    '</div>';
  }

  function wBand(name, servicesInBand, grow) {
    const catColor = visualCfg.category_colors[(servicesInBand[0] || {}).category] || '#e11d2e';
    const okN = servicesInBand.filter(s => s.status === 0).length;
    const badN = servicesInBand.filter(isProblem).length;
    const unkN = servicesInBand.filter(s => s.status === -1).length;
    let count = '<span class="ddw-band-cok">' + okN + ' ok</span>';
    if (badN) count += ' · <span class="ddw-band-cbad">' + badN + ' problema' + (badN > 1 ? 's' : '') + '</span>';
    if (unkN) count += ' · <span class="ddw-band-cunk">' + unkN + ' sem dados</span>';
    const chips = servicesInBand.map(s => {
      const cls = s.status === -1 ? ' ddw-unk' : isLong(s) ? ' ddw-long' : s.status === 2 ? ' ddw-crit' : (isProblem(s) ? ' ddw-prob' : '');
      return '<span class="ddw-chip' + cls + (isSicoob(s) ? ' ddw-first' : '') + '" title="' + s.name + '">' +
        '<img src="/public/img/downdetector/' + safeName(s.name) + '.png" alt="" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">' +
        '<span class="ddw-cfb" style="background:' + catColor + '22;color:' + catColor + '">' + s.name.charAt(0).toUpperCase() + '</span>' +
        '<span class="ddw-cname">' + s.name + '</span>' +
        '<i class="ddw-cdot" style="background:' + wColor(s) + '"></i>' +
      '</span>';
    }).join('');
    return '<div class="ddw-band' + (grow ? ' ddw-band-grow' : '') + '">' +
      '<div class="ddw-band-hd">' +
        '<span class="ddw-band-name" style="border-color:' + catColor + '">' + name + '</span>' +
        '<span class="ddw-band-count">' + count + '</span>' +
      '</div>' +
      '<div class="ddw-band-chips">' + chips + '</div>' +
    '</div>';
  }

  function wallboardHtml() {
    const v = wVerdict();
    const problems = services.filter(isProblem).sort(sortServices);
    const unknown = services.filter(s => s.status === -1);
    const shown = problems.slice(0, WALL_MAX_ROWS * 2); // 5 linhas × 2 colunas

    // faixa de status integrada: a contagem É o cabeçalho do bloco de incidentes
    let inc = '<div class="ddw-shead">' +
      '<span class="ddw-sbadge" style="background:' + v.color + '">' + v.icon + '</span>' +
      '<span class="ddw-stitle" style="color:' + v.color + '">' + v.big + '</span>' +
      '<span class="ddw-ssub">' + v.sub + '</span>' +
    '</div>';
    if (problems.length) {
      inc += '<div class="ddw-ilist">' + shown.map(wIncidentRow).join('') + '</div>' +
        '<div class="ddw-cfoot" style="display:none"></div>';
    }

    // categorias → 3 faixas horizontais (1ª full-width, 2ª e 3ª compartilham)
// Faixa 1: Instituições Financeiras (≥10) — sozinha, full-width
// Faixa 2: Microsoft 365 + Telecom (juntas)
// Faixa 3: Internet/Apps + Segurança + Governo (juntas) — última cresce p/ preencher
    const cats = catOrder.filter(c => services.some(s => s.category === c));
    const byCat = (cat) => services.filter(s => s.category === cat).slice().sort((a, b) => (isSicoob(b) ? 1 : 0) - (isSicoob(a) ? 1 : 0));
    const band1 = ['Instituições Financeiras'];
    const band2 = ['Microsoft 365', 'Telecom'];
    const band3 = ['Internet/Apps', 'Segurança', 'Governo', 'Outros'];
    const find = (name) => cats.find(c => c === name);
    const b1Cats = band1.map(find).filter(Boolean);
    const b2Cats = band2.map(find).filter(Boolean);
    const b3Cats = band3.map(find).filter(Boolean);
    let bandHtml = '';
    if (b1Cats.length) {
      const all = b1Cats.flatMap(byCat);
      bandHtml += wBand(b1Cats.join(' & '), all, false);
    }
    if (b2Cats.length) {
      const all = b2Cats.flatMap(byCat);
      bandHtml += wBand(b2Cats.join(' & '), all, false);
    }
    if (b3Cats.length) {
      const all = b3Cats.flatMap(byCat);
      bandHtml += wBand(b3Cats.join(' · '), all, false);
    }

    return '<style>' + WALLBOARD_CSS + '</style>' +
      '<div id="dd" class="dd-wallboard">' +
        '<div class="ddw-hd">' +
          '<div class="ddw-hd-l">' +
            '<img class="ddw-tenant" src="/public/img/downdetector/header_sicoob_credipeu.png?v=6" alt="Sicoob" onerror="this.style.display=\'none\'">' +
            '<div class="ddw-brand">' +
              '<span class="ddw-bname">Down<b>detector</b> · NOC</span>' +
              '<span class="ddw-update">' + lastUpdateText() + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="ddw-hd-r">' +
            '<span class="ddw-clock">--:--</span>' +
            '<span class="ddw-collect" id="ddw-collect"></span>' +
          '</div>' +
        '</div>' +
        '<div class="ddw-inc">' + inc + '</div>' +
        '<div class="ddw-cat">' + bandHtml + '</div>' +
      '</div>';
  }

  function wHb() {
    let ts = heartbeatTs || 0;
    if (!ts) return { stale: false, noHb: true, text: 'sem heartbeat' };
    if (ts < 1e12) ts *= 1000;
    const d = Math.max(0, Math.floor((Date.now() - ts) / 1000));
    const t = d < 60 ? d + 's' : d < 3600 ? Math.floor(d / 60) + 'min' : d < 86400 ? Math.floor(d / 3600) + 'h' : Math.floor(d / 86400) + 'd';
    return { stale: d > 600, noHb: false, ageSec: d, text: t };
  }

  function wCollectText() {
    const hb = wHb();
    if (hb.noHb) return 'coleta: ' + hb.text;
    return 'coleta há ' + hb.text;
  }

  function startWallboardClock() {
    if (typeof window === 'undefined') return;
    if (window.__ddwTimer) { clearInterval(window.__ddwTimer); window.__ddwTimer = null; }
    const tick = () => {
      const root = htmlNode.querySelector('#dd');
      const c = root && root.querySelector('.ddw-clock');
      if (!c) { if (window.__ddwTimer) { clearInterval(window.__ddwTimer); window.__ddwTimer = null; } return; }
      c.textContent = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      const col = root.querySelector('.ddw-collect');
      if (col) {
        col.textContent = wCollectText();
        let ts = heartbeatTs || 0;
        if (ts < 1e12) ts *= 1000;
        col.classList.toggle('ddw-late', !!heartbeatTs && (Date.now() - ts) > 600000);
      }
    };
    tick();
    window.__ddwTimer = setInterval(tick, 1000);
  }

  // Encaixe por medição: incidentes em grade de 2 colunas (56px/linha, até
  // WALL_MAX_ROWS linhas = 10 cartões); se as faixas de serviços transbordarem
  // o #dd, esconde cartões e contabiliza no "+N"; a área de serviços (chips)
  // sempre preenche o resto e escala em 4 tiers (xl/lg/md/sm) conforme o
  // espaço real — a tela nunca fica vazia nem cortada.
  function fitWallboard() {
    const root = htmlNode.querySelector('#dd');
    const inc = htmlNode.querySelector('.ddw-inc');
    const ilist = htmlNode.querySelector('.ddw-ilist');
    const cat = htmlNode.querySelector('.ddw-cat');
    if (!root || !cat) return;
    const problemsTotal = services.filter(isProblem).length;
    const all = ilist ? Array.from(ilist.querySelectorAll('.ddw-irow')) : [];
    const foot = inc ? inc.querySelector('.ddw-cfoot') : null;
    let visible = all.length;
    const apply = () => { all.forEach((r, i) => { r.style.display = i < visible ? 'flex' : 'none'; }); };
    apply();
    const fits = () => (cat.offsetTop + cat.offsetHeight) <= root.clientHeight + 1;
    let guard = 0;
    while (guard < 8 && visible > 1 && !fits()) { visible--; apply(); guard++; }
    if (foot) {
      const extra = problemsTotal - visible;
      foot.style.display = extra > 0 ? 'block' : 'none';
      if (extra > 0) foot.textContent = '+ ' + extra + ' outros problemas — investigar no dashboard User';
    }
    // escala dos chips conforme o espaço real disponível p/ serviços
    const tiers = ['ddw-chips-xl', 'ddw-chips-lg', 'ddw-chips-md', 'ddw-chips-sm'];
    const avail = root.clientHeight - (inc ? inc.offsetHeight : 0);
    let ti = avail >= 820 ? 0 : avail >= 640 ? 1 : avail >= 470 ? 2 : 3;
    cat.classList.remove('ddw-chips-xl', 'ddw-chips-lg', 'ddw-chips-md', 'ddw-chips-sm');
    cat.classList.add(tiers[ti]);
    let g2 = 0;
    while (g2 < 5 && !fits() && ti < 3) {
      ti++;
      cat.classList.remove(tiers[ti - 1]);
      cat.classList.add(tiers[ti]);
      g2++;
    }
  }

  if (isWallboard) {
    try {
      let el = htmlNode;
      for (let i = 0; i < 8 && el; i++) {
        el.style.boxSizing = 'border-box';
        el.style.width = '100%';
        el.style.height = '100%';
        el.style.minHeight = '0';
        el.style.overflow = 'hidden';
        el = el.parentElement;
      }
      htmlNode.style.position = 'relative';
    } catch (e) {}
    htmlNode.innerHTML = wallboardHtml();
    startWallboardClock();
    setTimeout(fitWallboard, 50);
    setTimeout(fitWallboard, 200);
    window.addEventListener('resize', () => setTimeout(fitWallboard, 50));
    return;
  }

  let html = '<style>' +
    '*{box-sizing:border-box;margin:0;padding:0}' +
    '#dd{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#050505;color:#fff;position:absolute;inset:0;width:100%;height:100%;display:flex;flex-direction:column;overflow:hidden;font-size:14px}' +
    '.dd-empty{color:#888;text-align:center;margin-top:48px;font-size:18px}' +
    '.dd-hd{height:72px;padding:0 22px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;gap:18px;border-bottom:1px solid #1f1f1f}' +
    '.dd-hd-l{display:flex;align-items:center;gap:20px;min-width:0}' +
    '.dd-tenant{height:56px;width:auto;max-width:280px;object-fit:contain;background:transparent;flex-shrink:0}' +
    '.dd-brand-wrap{display:flex;flex-direction:column;gap:2px}' +
    '.dd-brand-txt{font-size:30px;font-weight:700;letter-spacing:-.02em;white-space:nowrap;color:#fff}' +
    '.dd-brand-txt b{color:#e11d2e;font-weight:700}' +
    '.dd-update{font-size:13px;color:#9a9a9a;white-space:nowrap}' +
    '.dd-hd-r{display:flex;align-items:center;gap:18px;flex-shrink:0}' +
    '.dd-kpi{text-align:center;min-width:64px}' +
    '.dd-kpi .v{font-family:Consolas,ui-monospace,monospace;font-size:32px;font-weight:700;line-height:1;color:#fff}' +
    '.dd-kpi .l{font-size:13px;color:#888;margin-top:3px;text-transform:uppercase;letter-spacing:.02em}' +
    '.dd-kpi.r .v{color:#e11d2e}' +
    '.dd-kpi.w .v{color:#e8a317}' +
    '.dd-kpi.g .v{color:#1a9e4a}' +
    '.dd-sep{width:1px;height:42px;background:#222}' +
    '.dd-body{flex:1 1 auto;min-height:0;overflow:hidden;padding:12px 16px 12px;display:flex;flex-direction:column;gap:12px}' +
    '.dd-row{display:grid;gap:14px;flex:0 0 auto;align-items:start}' +
    '.dd-sec{min-width:0;display:flex;flex-direction:column}' +
    '.dd-sec-hd{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding:0 0 6px 0;border-bottom:1px solid rgba(255,255,255,.12);flex-shrink:0;height:30px}' +
    '.dd-sec-title{font-size:16px;font-weight:700;color:#fff;letter-spacing:.04em;text-transform:uppercase;padding-left:10px;border-left:3px solid #e11d2e;line-height:1.2}' +
    '.dd-sec-count{font-size:14px;color:#9a9a9a;font-weight:500}' +
    '.dd-sec-count .bad{color:#e8a317;font-weight:600}' +
    '.dd-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;align-content:start}' +
    '.dd-card{display:flex;align-items:center;gap:13px;padding:12px 14px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);border-radius:14px;text-decoration:none;color:#f2f2f2;box-sizing:border-box;backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);transition:transform .15s,box-shadow .15s,border-color .15s}' +
    '.dd-card:hover{background:rgba(255,255,255,.10);transform:translateY(-1px)}' +
    '.dd-pulse{animation:dd-pulse 1.6s ease-in-out infinite}' +
    '@keyframes dd-pulse{0%,100%{box-shadow:0 0 0 0 rgba(225,29,46,.35)}50%{box-shadow:0 0 0 5px rgba(225,29,46,0)}}' +
    '.dd-logo{width:52px;height:52px;flex-shrink:0;border-radius:12px;overflow:hidden;background:transparent;border:1px solid rgba(255,255,255,.08);display:flex;align-items:center;justify-content:center;position:relative}' +
    '.dd-logo img{width:100%;height:100%;object-fit:contain;background:transparent;padding:3px}' +
    '.dd-fb{display:none;width:100%;height:100%;align-items:center;justify-content:center;font-size:20px;font-weight:700;border-radius:12px;position:absolute;inset:0}' +
    '.dd-meta{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px}' +
    '.dd-name{font-size:14px;font-weight:600;color:#f5f5f5;line-height:1.15;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word}' +
    '.dd-st{font-size:14px;font-weight:600;display:flex;align-items:center;gap:7px;white-space:nowrap}' +
    '.dd-dot{display:inline-block;width:10px;height:10px;border-radius:50%;flex-shrink:0}' +
    '.dd-spark{flex-shrink:0;opacity:.95}' +
    '.dd-ft{display:none}' +
    // layout_mode=compact: densidade maior (cards menores, mais por linha)
    '.dd-compact .dd-grid{grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px}' +
    '.dd-compact .dd-card{padding:8px 11px;gap:10px;border-radius:10px}' +
    '.dd-compact .dd-name{font-size:13px}' +
    '.dd-compact .dd-st{font-size:12px}' +
    '.dd-compact .dd-sec-hd{height:26px;margin-bottom:6px}' +
    // modo "tight": acionado automaticamente quando muitos serviços/seções
    // não cabem em 1920x1080 — mantém TODOS os cards visíveis (fonte/logo menores)
    '.dd-tight .dd-card{padding:6px 10px;gap:9px;border-radius:9px}' +
    '.dd-tight .dd-grid{gap:8px}' +
    '.dd-tight .dd-name{font-size:12px;line-height:1.12;-webkit-line-clamp:2}' +
    '.dd-tight .dd-st{font-size:11px}' +
    '.dd-tight .dd-sec-hd{height:24px;margin-bottom:4px}' +
    '.dd-tight .dd-spark{height:24px}' +
    // ── MODO TV (layout_mode: "tv") — legibilidade a 3-4m em TV 40-55" ──
    // Só problemas ganham cards grandes; serviços OK viram chips compactos
    // (precisam ser identificados, não lidos). Regra de mercado: ~1" de letra
    // por 10 pés de distância → fontes >=24px no painel.
    '.dd-tv .dd-hd{height:104px;padding:0 26px}' +
    '.dd-tv .dd-tenant{height:76px}' +
    '.dd-tv .dd-brand-txt{font-size:40px}' +
    '.dd-tv .dd-update{font-size:16px}' +
    '.dd-tv .dd-kpi{min-width:96px}' +
    '.dd-tv .dd-kpi .v{font-size:56px}' +
    '.dd-tv .dd-kpi .l{font-size:15px}' +
    '.dd-tv .dd-sep{height:64px}' +
    '.dd-tv .dd-body{gap:16px;padding:16px 22px}' +
    '.dd-tv .dd-thead{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,.14);padding-bottom:8px;margin-bottom:12px}' +
    '.dd-tv .dd-ttitle{font-size:22px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding-left:12px;border-left:5px solid #e11d2e;line-height:1.2;color:#fff}' +
    '.dd-tv .dd-tcount{font-size:18px;color:#9a9a9a;font-weight:600}' +
    '.dd-tv .dd-pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:14px}' +
    '.dd-tv .dd-pcard{position:relative;display:flex;align-items:center;gap:16px;padding:13px 18px 13px 26px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.13);border-radius:14px;text-decoration:none;color:#f2f2f2;overflow:hidden;min-height:106px}' +
    '.dd-tv .dd-pband{position:absolute;left:0;top:0;bottom:0;width:8px}' +
    '.dd-tv .dd-plogo{width:62px;height:62px;flex-shrink:0;border-radius:12px;border:1px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:center;overflow:hidden}' +
    '.dd-tv .dd-plogo img{width:100%;height:100%;object-fit:contain;padding:4px}' +
    '.dd-tv .dd-pfb{display:none;width:100%;height:100%;align-items:center;justify-content:center;font-size:26px;font-weight:700}' +
    '.dd-tv .dd-pmeta{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}' +
    '.dd-tv .dd-pname{font-size:30px;font-weight:700;line-height:1.05;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
    '.dd-tv .dd-pcat{font-size:15px;color:#8f8f8f;text-transform:uppercase;letter-spacing:.04em}' +
    '.dd-tv .dd-pstat{display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0}' +
    '.dd-tv .dd-plabel{font-size:24px;font-weight:700;display:flex;align-items:center;gap:9px;white-space:nowrap}' +
    '.dd-tv .dd-psince{font-size:20px;font-weight:600;color:#d8d8d8}' +
    '.dd-tv .dd-spark{width:110px;height:40px;flex-shrink:0}' +
    '.dd-tv .dd-okhero{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px}' +
    '.dd-tv .dd-okbig{font-size:92px;font-weight:800;letter-spacing:.02em;line-height:1}' +
    '.dd-tv .dd-oksub{font-size:22px;color:#9a9a9a}' +
    '.dd-tv .dd-chips{display:flex;flex-wrap:wrap;gap:8px}' +
    '.dd-tv .dd-tok{flex:1 1 auto;min-height:0;overflow:hidden}' +
    '.dd-tv .dd-chip{display:flex;align-items:center;gap:9px;font-size:19px;font-weight:600;color:#eaeaea;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:999px;padding:6px 15px 6px 8px;white-space:nowrap}' +
    '.dd-tv .dd-chip img{width:26px;height:26px;object-fit:contain;border-radius:7px}' +
    '.dd-tv .dd-chip .dd-dot{width:9px;height:9px}' +
  '</style>' +
  '<div id="dd"' + (tvMode ? ' class="dd-tv"' : (visualCfg.layout_mode === 'compact' ? ' class="dd-compact"' : '')) + '>' +
    '<div class="dd-hd">' +
      '<div class="dd-hd-l">' +
        '<img class="dd-tenant" src="/public/img/downdetector/header_sicoob_credipeu.png?v=6" alt="Sicoob" onerror="this.style.display=\'none\'">' +
        '<div class="dd-brand-wrap">' +
          '<span class="dd-brand-txt">Down<b>detector</b></span>' +
          '<span class="dd-update">' + lastUpdateText() + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="dd-hd-r">' +
        '<div class="dd-kpi r"><div class="v">' + longos + '</div><div class="l">≥ 1h</div></div>' +
        '<div class="dd-sep"></div>' +
        '<div class="dd-kpi w"><div class="v">' + instaveis + '</div><div class="l">Instáveis</div></div>' +
        '<div class="dd-sep"></div>' +
        '<div class="dd-kpi g"><div class="v">' + ok + '</div><div class="l">OK</div></div>' +
        '<div class="dd-sep"></div>' +
        '<div class="dd-kpi"><div class="v">' + total + '</div><div class="l">Total</div></div>' +
      '</div>' +
    '</div>' +
    '<div class="dd-body">';

  if (tvMode) {
    html += renderTv();
  } else {
    const rendered = {};
    layoutRows.forEach(row => {
      const cats = row.cats || row;
      const colTpl = row.cols || (cats.length >= 2 ? '1fr 1fr' : '1fr');
      const parts = cats.map(cat => ({ cat, html: renderSection(cat) })).filter(p => p.html);
      if (!parts.length) return;
      parts.forEach(p => { rendered[p.cat] = true; });
      let tpl = colTpl;
      if (parts.length !== cats.length) {
        tpl = parts.map(() => '1fr').join(' ');
      } else if (parts.length === 1) {
        tpl = '1fr';
      }
      html += '<div class="dd-row" style="grid-template-columns:' + tpl + '">';
      parts.forEach(p => { html += p.html; });
      html += '</div>';
    });
    catOrder.forEach(cat => {
      if (rendered[cat]) return;
      const sec = renderSection(cat);
      if (sec) html += '<div class="dd-row" style="grid-template-columns:1fr">' + sec + '</div>';
    });
  }

  html += '</div></div>';
  htmlNode.innerHTML = html;

  // Fit #dd exactly to the Grafana panel host (no overflow). Uniform card heights.
  function fitCanvas() {
    const root = htmlNode.querySelector('#dd');
    const body = htmlNode.querySelector('.dd-body');
    const hd = htmlNode.querySelector('.dd-hd');
    if (!root || !body || !hd) return;

    try {
      let el = htmlNode;
      for (let i = 0; i < 8 && el; i++) {
        el.style.boxSizing = 'border-box';
        el.style.width = '100%';
        el.style.height = '100%';
        el.style.minHeight = '0';
        el.style.overflow = 'hidden';
        el = el.parentElement;
      }
      if (htmlNode.style) {
        htmlNode.style.position = 'relative';
      }
    } catch (e) {}

    // Always fill host — never larger than parent (that caused the cut-off)
    root.style.position = 'absolute';
    root.style.inset = '0';
    root.style.width = '100%';
    root.style.height = '100%';
    root.style.maxWidth = '100%';
    root.style.maxHeight = '100%';

    const rootH = root.clientHeight || root.getBoundingClientRect().height;
    const hdH = hd.offsetHeight || 70;
    const bodyH = Math.max(100, Math.floor(rootH - hdH));
    body.style.height = bodyH + 'px';
    body.style.minHeight = bodyH + 'px';
    body.style.flex = 'none';
    body.style.overflow = 'hidden';

    const cards = Array.from(body.querySelectorAll('.dd-card'));
    if (!cards.length) return;

    // provisional height to detect row count
    cards.forEach(c => {
      c.style.height = '76px';
      c.style.minHeight = '76px';
      c.style.maxHeight = '76px';
    });

    const tops = [];
    cards.forEach(c => {
      const t = Math.round(c.getBoundingClientRect().top);
      if (!tops.some(x => Math.abs(x - t) < 4)) tops.push(t);
    });
    const cardRows = Math.max(1, tops.length);

    const bodyStyle = getComputedStyle(body);
    const padY = (parseFloat(bodyStyle.paddingTop) || 0) + (parseFloat(bodyStyle.paddingBottom) || 0);
    const bodyGap = parseFloat(bodyStyle.gap) || 12;
    const majorRows = body.querySelectorAll('.dd-row').length;
    const secHds = body.querySelectorAll('.dd-sec-hd').length;
    // 38 = altura real do cabeçalho de seção (30px + 8px de margem). Ligeira
    // sobre-estimativa é segura: o passo "eat leftover gap" cresce os cards
    // depois, e nunca cortamos a última seção.
    const chromeH = padY + Math.max(0, majorRows - 1) * bodyGap + secHds * 38;
    const gridGap = 10;
    const usable = bodyH - chromeH - gridGap * Math.max(0, cardRows - 1) - 2;
    let cardH = Math.floor(usable / cardRows);
    if (cardH < 34) cardH = 34;
    if (cardH > 120) cardH = 120;

    function applyCardH(h) {
      const tight = h < 62;
      body.classList.toggle('dd-tight', tight);
      cards.forEach(c => {
        c.style.height = h + 'px';
        c.style.minHeight = h + 'px';
        c.style.maxHeight = h + 'px';
      });
      const logoBase = visualCfg.layout_mode === 'compact' ? 44 : 54;
      const logoMax = tight ? 34 : logoBase;
      const logoFloor = tight ? 26 : 36;
      const logo = Math.max(logoFloor, Math.min(logoMax, Math.round(h * 0.62)));
      body.querySelectorAll('.dd-logo').forEach(l => {
        l.style.width = logo + 'px';
        l.style.height = logo + 'px';
      });
    }
    applyCardH(cardH);

    // Feedback REAL do DOM (não estimativa): mede o fundo do último card contra
    // o limite interno do body. Encolhe até caber e depois cresce até encostar —
    // garante que NENHUMA seção (ex.: Governo) seja cortada em qualquer tela.
    function overflows() {
      const last = cards[cards.length - 1];
      if (!last) return false;
      const bodyStyle = getComputedStyle(body);
      const padBottom = parseFloat(bodyStyle.paddingBottom) || 0;
      const limit = body.getBoundingClientRect().bottom - padBottom;
      return last.getBoundingClientRect().bottom > limit + 1;
    }
    let guard = 0;
    while (overflows() && cardH > 34 && guard < 40) { cardH -= 2; applyCardH(cardH); guard++; }
    guard = 0;
    while (cardH < 120 && guard < 40) {
      const test = cardH + 2;
      applyCardH(test);
      if (overflows()) { applyCardH(cardH); break; }
      cardH = test; guard++;
    }
  }

  setTimeout(fitCanvas, 50);
  setTimeout(fitCanvas, 200);
  window.addEventListener('resize', () => setTimeout(fitCanvas, 50));
})();
"""


def build_dashboard(variant="user"):
    cfg = load_config()
    categories = cfg.get("categories", {})
    services_cfg = cfg.get("services", [])
    hide_timepicker = cfg.get("hide_timepicker", False)
    if variant == "wallboard":
        # Wallboard de detecção p/ TV (mode fixo; ignorar layout_mode do config)
        layout_mode = "wallboard"
        title = "Downdetector NOC - Wallboard"
        uid = "downdetector-tv-1"
        tags = ["downdetector", "zabbix", "noc", "tv", "wallboard"]
    else:
        # Visão de investigação p/ desktop (comfortable/compact/tv via config)
        layout_mode = cfg.get("layout_mode", "comfortable")
        title = "Downdetector NOC - User"
        uid = "downdetector-noc-1"
        tags = ["downdetector", "zabbix", "noc", "tv", "user"]
    visual_cfg = {
        "show_last_update": cfg.get("show_last_update", True),
        "pulse_critical": cfg.get("pulse_critical", True),
        "show_problem_severity": cfg.get("show_problem_severity", True),
        "category_colors": cfg.get("category_colors", {}),
        "layout_mode": layout_mode,
        # Correção: links dos cards respeitam base_url do config (país/idioma)
        "status_base": cfg.get("base_url", "https://downdetector.com.br/fora-do-ar").rstrip("/") + "/",
    }
    js = build_js(categories, services_cfg, CATEGORY_ORDER, LAYOUT_ROWS, visual_cfg)

    return {
        "title": title,
        "uid": uid,
        "tags": tags,
        "timezone": "browser",
        "refresh": "30s",
        "schemaVersion": 39,
        "editable": True,
        "graphTooltip": 0,
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {
            "refresh_intervals": ["15s", "30s", "1m", "5m", "15m"],
            "hidden": hide_timepicker,
        },
        "annotations": {
            "list": [{
                "builtIn": 1,
                "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                "enable": True,
                "hide": True,
                "iconColor": "rgba(0, 211, 255, 1)",
                "name": "Annotations & Alerts",
                "type": "dashboard",
            }]
        },
        "templating": {"list": []},
        "panels": [{
            "id": 1,
            "type": "gapit-htmlgraphics-panel",
            "title": "",
            "gridPos": {"h": 24, "w": 24, "x": 0, "y": 0},
            "transparent": True,
            "options": {
                "add100Percentage": True,
                "centerAlignContent": False,
                "css": "",
                "html": "",
                "onInit": "",
                "onInitOnResize": False,
                "onRender": js,
                "codeData": "{}",
                "dynamicData": False,
                "dynamicFieldDisplayValues": False,
                "dynamicHtmlGraphics": False,
                "dynamicProps": False,
                "overflow": "hidden",
                "panelupdateOnMount": True,
                "renderOnMount": True,
            },
            "targets": [zabbix_target_status(), zabbix_target_heartbeat()],
        }],
    }


if __name__ == "__main__":
    # Dois artefatos a partir do mesmo builder (nunca editar os JSON à mão):
    out_dir = Path(__file__).resolve().parent
    for variant, filename in (
        ("user", "downdetector_dashboard.json"),
        ("wallboard", "downdetector_dashboard_tv.json"),
    ):
        dashboard = build_dashboard(variant)
        out_path = out_dir / filename
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(dashboard, f, ensure_ascii=False, indent=2)
        print(f"OK: {out_path}")
