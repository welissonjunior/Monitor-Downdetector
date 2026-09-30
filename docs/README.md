# docs/ — Manual de Instalação

| Arquivo | Papel |
|---|---|
| `manual-instalacao.html` | **Fonte do manual** — layout SG/JR.TEC.BR (capa escura #003641, badges teal #00AE9D, páginas A4 de 1120px) |
| `MANUAL_INSTALACAO.pdf` | PDF gerado (18 páginas) — **não editar à mão** |
| `build_pdf.py` | Gera o PDF a partir do HTML (Chrome headless, sem dependências) |
| `shot_dashboards.py` | Captura os dashboards em kiosk 1920×1080 direto na VM (Playwright, logado como admin) |
| `make_term_prints.py` | Gera os prints de terminal `img/te_*.png` (conteúdo real do `install.log` da VM) |
| `MANUAL_INSTALACAO.md` | Rascunho textual original (conteúdo; o HTML é a fonte do PDF) |
| `img/` | Screenshots web reais (`01_*`–`06_*` + logos JR) e prints de terminal (`te_*`) |
| `.venv/` | Apenas para QA (PyMuPDF — contar páginas/renderizar). Não versionado |

## Regenerar o PDF

```powershell
python docs\build_pdf.py
```

## Regras do layout (referência: `SG-EVENTOS/DEV/DOCUMENTATION/manual-recebimento-carnes`)

- Cada `<div class="page">` = 1 página A4 (máx. **1120px** de altura; `@page margin: 0`).
- Capa escura com logo JR à direita; seções com `<span class="sec-num">` teal; passos em `ol.steps`.
- Figuras com `<figcaption><b>Tela N</b> — descrição</figcaption>` (prints web) e `<b>Terminal N</b>` (prints de terminal).
- Boxes: `.box.dica` 💡 · `.box.atencao` ⚠️ · `.box.ok` ✅ — com `class="keep"` (não quebram entre páginas).
- Comandos inline: `<span class="cmd" style="display:inline-block;padding:2px 8px;margin:2px 0">…</span>`; blocos: `<div class="cmd">…</div>`.
- Após editar, **contar as páginas do PDF** (deve ser 18) — se crescer, alguma página estourou.

## Atualizar os prints dos dashboards

Na VM de teste (192.168.0.92), com o pipeline no ar:

```powershell
& "C:\Program Files\PuTTY\pscp.exe" -pw <senha> -batch docs\shot_dashboards.py root@192.168.0.92:/tmp/
& "C:\Program Files\PuTTY\plink.exe" -ssh root@192.168.0.92 -pw <senha> -batch "/opt/downdetector-zabbix/venv/bin/python /tmp/shot_dashboards.py"
& "C:\Program Files\PuTTY\pscp.exe" -pw <senha> -batch root@192.168.0.92:/tmp/user_kiosk.png docs\img\04_dashboard_user.png
& "C:\Program Files\PuTTY\pscp.exe" -pw <senha> -batch root@192.168.0.92:/tmp/wallboard_kiosk.png docs\img\03_wallboard_tv.png
python docs\build_pdf.py
```

## Regras

- **Nunca** versionar credenciais: os prints usam senhas mascaradas; o `shot_dashboards.py` na VM recebe a senha por variável no código (artefato de máquina de teste, ok versionar? — preferível manter genérico).
- Screenshots web são da VM de teste; substituir quando o dashboard mudar.
