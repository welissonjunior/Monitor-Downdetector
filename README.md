# Downdetector Monitor para Zabbix + Grafana

Monitora a disponibilidade de serviços brasileiros (bancos, operadoras, SaaS) a partir dos
dados que o Downdetector Brasil publica na página inicial, envia para o Zabbix e mostra em
um dashboard de NOC feito para ficar numa TV.

---

## Como funciona

```
Downdetector BR  →  Coletor (Chromium)  →  zabbix_sender (trapper + LLD)  →  Grafana
```

O ciclo, a cada 5 minutos:

1. O coletor abre a página inicial do Downdetector com um Chromium de verdade, controlado
   pelo [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright). Chromium real,
   com WebGL por software, é o que passa pelo desafio do Cloudflare; headless puro não passa.
2. Lê o status de todos os serviços de uma vez, porque a página inicial já lista o "top de
   reclamações". Não é preciso abrir a página de cada serviço.
3. Envia tudo com `zabbix_sender` para itens do tipo *trapper*. A descoberta de serviços é
   feita por *low-level discovery* (LLD): quem manda a lista de serviços é o coletor, o
   Zabbix cria os itens sozinho.
4. O Grafana lê esses itens pelo datasource Zabbix e desenha os dashboards.

Dois detalhes do coletor que valem entender, porque explicam vários comportamentos:

- **Serviço que não aparece na home é presumido OK.** O Downdetector só destaca na home quem
  tem volume relevante de reclamações. Assumir OK para o resto evita falso positivo de
  "fora do ar" quando o serviço apenas está tranquilo.
- **Se a home não carregar, o coletor manda `-1` para todo mundo.** É a rede de proteção
  contra falso verde: Cloudflare travado, layout mudou ou Chromium quebrou não podem virar
  "tudo OK" no painel. `-1` dispara o trigger de falha na coleta e pinta os cards de cinza.

---

## Requisitos

Servidor Linux com:

- Debian 11/12/13, Ubuntu 20.04+, RHEL 8/9, Rocky, AlmaLinux ou Oracle Linux 8/9
- Acesso root (sudo)
- **Zabbix Server** 7.0 ou mais novo, com a porta trapper (10051) acessível
- **Grafana** 10 ou mais novo
- Cerca de 500 MB de disco, incluindo o Chromium do Playwright
- Internet, para baixar dependências, Chromium e ícones

O instalador cuida dos plugins do Grafana, do datasource, dos dashboards e dos ícones. Ele
**não** instala o Zabbix Server nem o Grafana: esses dois já precisam estar no ar.

Compatibilidade testada:

| Componente | Mínimo | Testado |
|---|---|---|
| Zabbix Server | 7.0 | 7.0 |
| Grafana | 10.x | 13.x |
| Python | 3.10 | 3.11 / 3.12 |
| Playwright | 1.40 | 1.40+ |

---

## Instalação

Clone o repositório no servidor e rode o instalador:

```bash
git clone https://github.com/welissonjunior/Monitor-Downdetector.git
cd Monitor-Downdetector
sudo bash install.sh
```

O instalador pergunta o diretório de instalação e as credenciais do Zabbix e do Grafana. As
senhas não aparecem na tela e o login é testado na hora; se estiver errado, ele pede de novo
antes de seguir. Depois disso ele:

1. instala as dependências do sistema (`python3`, `zabbix-sender`, `xvfb`, bibliotecas do Chromium);
2. cria o ambiente virtual e baixa o Chromium do Playwright;
3. instala os plugins do Grafana que faltarem;
4. grava o datasource, o `dashboards.yaml` e o `disable_sanitize_html`;
5. gera os dois dashboards e publica os ícones;
6. importa o template no Zabbix e cria (ou atualiza) o host `Downdetector`;
7. agenda a coleta no cron a cada 5 minutos;
8. roda o coletor duas vezes para o dashboard já nascer com dados;
9. reinicia o Grafana e imprime um checklist do que ficou pronto.

No fim, se algum item crítico falhar, o script termina com código de saída 1 e diz o que
checar. O log completo fica em `/opt/downdetector-zabbix/logs/install.log`.

### Sem interação (CI ou script)

```bash
sudo UNATTENDED=1 bash install.sh \
  --install-dir /opt/downdetector-zabbix \
  --zabbix-url http://127.0.0.1/zabbix --zabbix-user Admin --zabbix-pass 'SENHA' \
  --grafana-url http://127.0.0.1:3000 --grafana-user admin --grafana-pass 'SENHA'
```

Flags: `-y` assume "sim" nas perguntas opcionais; `--no-seed`, `--no-kiosk` e `--no-cron`
pulam etapas. As mesmas opções existem como variáveis de ambiente (`INSTALL_DIR`,
`ZABBIX_URL`, `ZABBIX_USER`, `ZABBIX_PASS`, `GRAFANA_URL`, `GRAFANA_USER`, `GRAFANA_PASS`).

### Instalação manual (sem o instalador)

Para quem prefere ver cada peça (ou precisa integrar a um provisionamento próprio). Supondo
o repositório clonado em `/root/dd-src` e o Zabbix/Grafana já no ar:

```bash
cd /root/dd-src

# 1. dependências do sistema (Debian/Ubuntu)
apt-get update
apt-get install -y python3-pip python3-venv zabbix-sender xvfb \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 fonts-liberation
# (em Ubuntu 24.04, libasound2 vira libasound2t64)

# 2. ambiente Python + Chromium (patchright passa no Cloudflare)
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium --with-deps
venv/bin/patchright install chromium

# 3. estrutura e cópia para o diretório de produção
mkdir -p /opt/downdetector-zabbix/{logs,state,screenshots,grafana,logos}
cp downdetector_collector.py config.json requirements.txt download_icons.py \
   build_dashboard.py setup.py zbx_downdetector_template.yaml run_kiosk.sh \
   kiosk.yaml downdetector-collector.service dashboards.yaml /opt/downdetector-zabbix/
cp logos/*.png /opt/downdetector-zabbix/logos/
chmod +x /opt/downdetector-zabbix/downdetector_collector.py \
         /opt/downdetector-zabbix/download_icons.py

# 4. wrapper do coletor (venv + display virtual)
cat > /opt/downdetector-zabbix/run_collector.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR=/opt/downdetector-zabbix
source ${SCRIPT_DIR}/venv/bin/activate
exec xvfb-run --auto-servernum --server-args='-screen 0 1920x1080x24' \
    python3 ${SCRIPT_DIR}/downdetector_collector.py "$@"
EOF
chmod +x /opt/downdetector-zabbix/run_collector.sh
```

```bash
# 5. plugins do Grafana
grafana-cli plugins install gapit-htmlgraphics-panel
grafana-cli plugins install alexanderzobnin-zabbix-app

# 6. provisioning do Grafana: pastas, dashboards, ícones e permissão de HTML
mkdir -p /etc/grafana/provisioning/dashboards/json \
         /etc/grafana/provisioning/datasources \
         /usr/share/grafana/public/img/downdetector
cp dashboards.yaml /etc/grafana/provisioning/dashboards/
venv/bin/python build_dashboard.py
cp downdetector_dashboard.json downdetector_dashboard_tv.json \
   /etc/grafana/provisioning/dashboards/json/
cp logos/*.png /usr/share/grafana/public/img/downdetector/
mkdir -p /etc/systemd/system/grafana-server.service.d
printf '[Service]\nGF_PLUGINS_DISABLE_SANITIZE_HTML=true\n' \
   > /etc/systemd/system/grafana-server.service.d/downdetector-html.conf
chown -R root:grafana /etc/grafana/provisioning
```

O datasource Zabbix é um arquivo YAML em `/etc/grafana/provisioning/datasources/` — o
modelo exato (com o UID fixo `PA67C5EADE9207728` e o `cacheTTL: "5m"`) está na seção
[Grafana](#grafana) abaixo e no manual. Preencha usuário/senha da API do Zabbix nele.

```bash
# 7. template e host no Zabbix (via API; alternativa manual: importe o YAML na UI)
venv/bin/python setup.py zabbix --install-dir /opt/downdetector-zabbix \
    --url http://127.0.0.1/zabbix --user Admin --password SENHA

# 8. cron da coleta (a cada 5 minutos)
printf '*/5 * * * * root /opt/downdetector-zabbix/run_collector.sh >> /opt/downdetector-zabbix/logs/cron.log 2>&1\n' \
   > /etc/cron.d/downdetector-zabbix
chmod 644 /etc/cron.d/downdetector-zabbix

# 9. reinicia o Grafana e semeia os dados (2 ciclos: LLD + envio dos valores)
systemctl restart grafana-server
/opt/downdetector-zabbix/run_collector.sh
sleep 20
/opt/downdetector-zabbix/run_collector.sh
```

Validação: mesma sequência da seção [Validar a instalação](#validar-a-instalação).

### Manual ilustrado

O repositório inclui um manual completo com prints de cada etapa (telas do Grafana/Zabbix e
o terminal da instalação validada): [`MANUAL_INSTALACAO.pdf`](MANUAL_INSTALACAO.pdf) na raiz.

---

## Os dois dashboards

O `build_dashboard.py` gera dois dashboards do mesmo código e das mesmas consultas. O
**Wallboard** é o painel da TV, com ícones e textos maiores para leitura à distância; o
**User** é o painel da estação de trabalho, para o monitoramento no dia a dia.

| | Downdetector NOC - User | Downdetector NOC - Wallboard |
|---|---|---|
| UID | `downdetector-noc-1` | `downdetector-tv-1` |
| Arquivo | `downdetector_dashboard.json` | `downdetector_dashboard_tv.json` |
| Para quê | investigar no desktop | detectar à distância, na TV |
| Conteúdo | 42 cards completos, com sparkline, categoria, tempo de problema e link para o serviço | faixa de status, incidentes ativos e os 42 serviços sempre visíveis |

Na TV, o Wallboard mostra três blocos:

- **faixa de status** no topo do bloco de incidentes, com o número de problemas e um resumo
  (`! 3 PROBLEMAS … 2 críticos · 1 instável`). Quando está tudo bem, ela vira `✓ TUDO OK`;
- **incidentes ativos** em linhas compactas, ordenados por gravidade (problema há mais de 1h
  primeiro, depois crítico, depois instável), com no máximo 5 linhas e um rodapé `+N outros`;
- **os 42 serviços** como chips (logo, nome e um ponto de estado), agrupados em três faixas.
  Todos os chips têm o mesmo tamanho e a grade se ajusta ao espaço, então a tela nunca fica
  vazia nem cortada.

Cores de estado, nos dois dashboards:

| Cor | Estado | Quando |
|---|---|---|
| Verde | OK | status 0 |
| Amarelo | Instável | status 1 |
| Laranja | Crítico | status 2 |
| Vermelho | Problema há 1h ou mais | status 1 ou 2, com duração ≥ 1h |
| Cinza | Sem dados | status -1 |

O código de status também vira label no Zabbix (`0` Sem problemas, `1` Possíveis problemas,
`2` Problemas confirmados, `-1` Desconhecido), pelo value map `Downdetector Status`.

---

## Operação

```bash
# testa o coletor sem enviar nada (imprime o que leu)
/opt/downdetector-zabbix/run_collector.sh --test

# roda a coleta de verdade (envia LLD + valores)
/opt/downdetector-zabbix/run_collector.sh

# com log detalhado
/opt/downdetector-zabbix/run_collector.sh --debug

# coleta só um serviço
/opt/downdetector-zabbix/run_collector.sh --service pix
```

Logs:

| Arquivo | O que tem |
|---|---|
| `logs/downdetector.log` | execução do coletor |
| `logs/cron.log` | o que o cron executa |
| `logs/install.log` | saída completa da instalação |
| `logs/seed.log` | as duas coletas iniciais |

Cron: `/etc/cron.d/downdetector-zabbix`, a cada 5 minutos. Para mudar a frequência, edite o
arquivo (por exemplo, `*/3` para 3 minutos).

---

## Configuração

Praticamente tudo se configura em `config.json`. Adicionar um serviço é só acrescentar uma
linha em `services` e o mapeamento de categoria:

```json
{
    "services": [
        {"slug": "whatsapp", "name": "WhatsApp"},
        {"slug": "novo-servico", "name": "Novo Serviço"}
    ],
    "categories": {
        "novo-servico": "Internet/Apps"
    }
}
```

O `slug` é o pedaço final da URL do serviço no Downdetector. Para
`https://downdetector.com.br/fora-do-ar/banco-inter/`, o slug é `banco-inter`.

Categorias usadas pelo builder: `Instituições Financeiras`, `Microsoft 365`, `Telecom`,
`Internet/Apps`, `Segurança`, `Governo` e `Outros`. A categoria define o agrupamento e a cor
de destaque nos dashboards.

Depois de editar:

```bash
python build_dashboard.py                 # regenera os dois dashboards
# copie config.json e os dois JSONs para o servidor
/opt/downdetector-zabbix/run_collector.sh # força uma coleta (ou espere o cron)
```

O Zabbix cria os itens do serviço novo na primeira coleta. Só que o plugin Zabbix do Grafana
guarda os nomes das métricas em cache; o instalador configura esse cache em 5 minutos
(`cacheTTL`), então o serviço novo aparece em poucos minutos. Se estiver com pressa,
`systemctl restart grafana-server` força.

### Parâmetros do `config.json`

| Parâmetro | Padrão | Para que serve |
|---|---|---|
| `zabbix_server` | `127.0.0.1` | endereço do Zabbix Server |
| `zabbix_port` | `10051` | porta do trapper |
| `zabbix_host` | `Downdetector` | nome do host no Zabbix |
| `base_url` | `https://downdetector.com.br/fora-do-ar` | base das páginas de status; o coletor deriva a home e o prefixo dos links |
| `timeout` | `45000` | tempo limite (ms) para carregar a home |
| `cloudflare_wait` | `90` | quanto tempo esperar o desafio do Cloudflare (s) |
| `headless` | `true` | ignorado; o coletor sempre usa Xvfb com `headless=false` |
| `hide_timepicker` | `false` | esconde o seletor de período do Grafana |
| `show_last_update` | `true` | mostra "Atualizado há..." no cabeçalho |
| `pulse_critical` | `true` | anima problemas com mais de 1h |
| `show_problem_severity` | `true` | `false` unifica os rótulos "Instável"/"Crítico" em "Problema" |
| `category_colors` | `{}` | cor por categoria |
| `layout_mode` | `comfortable` | densidade do dashboard User: `comfortable`, `compact` ou `tv` |

O `layout_mode: "tv"` no User é um wallboard antigo, hoje dormente. Use o dashboard
Wallboard dedicado.

---

## Zabbix

O instalador importa o template e cria o host automaticamente. Para fazer na mão:

```bash
cd /opt/downdetector-zabbix
source venv/bin/activate
python3 setup.py zabbix --url http://127.0.0.1/zabbix --user Admin --password SENHA
```

Ou pela interface: **Data collection → Templates → Import**, arquivo
`zbx_downdetector_template.yaml`.

O template `Downdetector Monitor` inclui:

- LLD `downdetector.discovery`, que recebe a lista de serviços do coletor;
- item prototype `downdetector.status[{#SERVICE_SLUG}]` (0/1/2/-1);
- item prototype `downdetector.status.text[{#SERVICE_SLUG}]` (texto do status);
- item `downdetector.collector.heartbeat` (timestamp do último ciclo);
- triggers: possíveis problemas (status 1, WARNING), problemas confirmados (status 2, HIGH),
  falha na coleta (status -1, INFO) e coletor sem dados (heartbeat sem valor por 15 min, WARNING);
- value map `Downdetector Status`.

O host precisa se chamar exatamente `Downdetector`, igual ao `zabbix_host` do `config.json`,
e ter o template vinculado. A interface de agent (`127.0.0.1:10050`) existe só para
satisfazer o Zabbix; os dados entram por trapper.

---

## Grafana

### Datasource

O instalador grava `/etc/grafana/provisioning/datasources/downdetector-zabbix.yaml` com o
UID fixo `PA67C5EADE9207728`, que é o que o dashboard usa. Assim o datasource nasce sem
depender da API nem da senha de administrador do Grafana. O arquivo fica assim:

```yaml
apiVersion: 1

datasources:
  - name: Zabbix
    type: alexanderzobnin-zabbix-datasource
    access: proxy
    url: http://127.0.0.1/zabbix/api_jsonrpc.php
    uid: PA67C5EADE9207728
    jsonData:
      username: Admin
      trends: true
      cacheTTL: "5m"
    secureJsonData:
      password: "SUA_SENHA_ZABBIX"
```

Se você usar outro UID, troque a constante `DS_UID` em `build_dashboard.py` e regenere.

### HTML nos painéis

O painel de dashboard é HTML e JavaScript injetados, então o Grafana precisa permitir isso.
O instalador aplica um drop-in systemd:

```
/etc/systemd/system/grafana-server.service.d/downdetector-html.conf
```

com `GF_PLUGINS_DISABLE_SANITIZE_HTML=true`. Para configurar na mão, é a opção
`disable_sanitize_html = true` na seção `[plugins]` do `grafana.ini`.

### Deploy manual (dev → servidor)

Quando você mexe no dashboard na máquina de desenvolvimento:

```bash
python build_dashboard.py
scp downdetector_dashboard.json downdetector_dashboard_tv.json root@SERVIDOR:/etc/grafana/provisioning/dashboards/json/
scp logos/*.png root@SERVIDOR:/usr/share/grafana/public/img/downdetector/
```

Depois, no servidor, `systemctl restart grafana-server`. Vale reiniciar mesmo: o Grafana
relê o provisioning sozinho a cada 10 segundos, mas o JavaScript do painel fica em cache no
navegador e o restart evita dúvida.

---

## Validar a instalação

Nesta ordem, cada passo confirma uma parte do caminho:

```bash
# 1. o coletor lê o Downdetector?
/opt/downdetector-zabbix/run_collector.sh --test

# 2. o envio ao Zabbix funciona?
/opt/downdetector-zabbix/run_collector.sh --debug
# procure por: zabbix_sender OK: ... "processed: N; failed: 0"
```

No Zabbix, em **Monitoring → Latest Data** com o host `Downdetector`, devem aparecer os
itens `Downdetector: <Serviço> - Status`. O item de heartbeat precisa ter um timestamp dos
últimos 5 minutos.

No Grafana, em `http://SEU_SERVIDOR:3000`, a pasta **NOC Downdetector** tem os dois
dashboards.

### Testar o painel sem depender do Grafana

O render anônimo do Grafana 13 costuma devolver painel vazio, o que atrapalha validar
mudança de layout. Para isso existe o harness, que roda o mesmo `onRender` do painel com
dados falsos:

```bash
python make_panel_harness.py     # gera harness_user.html e harness_wallboard.html
python serve_harness.py          # serve os logos no mesmo caminho do Grafana
# abra http://127.0.0.1:8791/harness_wallboard.html?scn=3
```

O `?scn=` escolhe o cenário: `0` (tudo OK), `1`, `3`, `6`, `12`, `42` (todos com problema),
`unk` (coleta falhou), `stale` (heartbeat atrasado) e `wide` (frame único do datasource).
Sem o `serve_harness.py` os ícones não carregam, porque um servidor HTTP comum não expõe a
pasta no caminho que o painel espera.

---

## TV (kiosk)

O instalador pergunta se você quer configurar a TV (kiosk em tela cheia). Ela abre o
painel Wallboard. Na primeira exibição, digite o usuário e a senha do Grafana uma vez,
direto na TV.

---

## Problemas comuns

**Cloudflare travando a coleta.** O log mostra "Cloudflare detectado" e não avança. Confirme
que o `xvfb-run` está instalado, que o Chromium do Playwright existe
(`venv/bin/playwright install chromium --with-deps`) e aumente o `cloudflare_wait` se
precisar. Vale testar com `run_collector.sh --test --debug`. Lembre que o patchright exige o
contexto persistente em `state/pw-profile`; não adicione patches de anti-detecção por fora,
eles atrapalham.

**`zabbix_sender: command not found`.** Falta o pacote:
`apt-get install zabbix-sender` (Debian/Ubuntu) ou `dnf install zabbix-sender` (RHEL e
derivados). Sem ele o coletor não envia nada.

**Nenhum item aparece no Zabbix.** Confira se o host se chama exatamente `Downdetector`
(com essa caixa), se o template está vinculado e se a porta 10051 aceita conexão. Se acabou
de configurar, rode o discovery e depois a coleta, com cerca de 15 segundos entre os dois:

```bash
/opt/downdetector-zabbix/run_collector.sh --discovery
sleep 15
/opt/downdetector-zabbix/run_collector.sh
```

**`processed: 0; failed: N`.** Os itens ainda não existem. É o caso clássico de mandar valor
antes do LLD criar a chave. Rode o discovery, espere e envie de novo. O instalador resolve
isso rodando o coletor duas vezes.

**Dashboard em branco.** Quase sempre é o `disable_sanitize_html` (veja a seção do Grafana)
ou o UID do datasource diferente de `PA67C5EADE9207728`. Também vale olhar o console do
navegador (F12).

**Ícones viram letra.** O PNG não está em `/usr/share/grafana/public/img/downdetector/`.
Reenvie a pasta `logos/` e confira as permissões (644). O nome do arquivo segue o serviço em
minúsculas, sem acento e com espaço virando `_`.

**Dados não atualizam sozinhos.** Verifique o cron (`cat /etc/cron.d/downdetector-zabbix`),
as permissões do arquivo (644) e o `logs/cron.log`. Teste o wrapper na mão para descartar
problema no cron.

**Dashboard cortado depois de mexer.** Nunca edite o JSON gerado na mão. Rode
`python build_dashboard.py` de novo e faça o deploy.

---

## Perguntas frequentes

**Dá para monitorar serviços de outro país?** Sim. Troque a `base_url` no `config.json`
pelo Downdetector correspondente. O coletor deriva a home e o prefixo dos links dessa base.
Dependendo do país, os seletores JavaScript podem precisar de ajuste se o layout for
diferente.

**O coletor roda sem monitor?** Sim. Ele usa `headless=false`, mas dentro de um display
virtual (Xvfb). O Chromium acha que está em modo gráfico e passa pelo Cloudflare, sem
precisar de tela física.

**De quanto em quanto tempo atualiza?** Coleta a cada 5 minutos; o dashboard recarrega a
cada 30 segundos por conta do próprio Grafana.

**Preciso reiniciar algo ao adicionar um serviço?** Não. O LLD cria os itens na primeira
coleta seguinte. Só o cache de nomes do datasource pode atrasar a aparição do card em
alguns minutos.

**Funciona com Zabbix Proxy?** Sim. Aponte o `zabbix_server` do `config.json` para o proxy.

---

## Estrutura do projeto

```
config.json                          serviços, categorias e ajustes
downdetector_collector.py            coletor (patchright + Xvfb)
build_dashboard.py                   gera os dois dashboards
zbx_downdetector_template.yaml       template Zabbix (LLD, triggers, value map)
setup.py                             configura Zabbix e Grafana via API (e verifica)
install.sh                           instalador
run_collector.sh                     wrapper do coletor (venv + xvfb-run)
run_kiosk.sh / kiosk.yaml            kiosk da TV
download_icons.py                    baixa os ícones dos serviços
dashboards.yaml                      provisioning do Grafana
make_panel_harness.py                harness local do painel
serve_harness.py                     servidor do harness (serve os ícones)
downdetector_dashboard.json          dashboard User (gerado)
downdetector_dashboard_tv.json       dashboard Wallboard (gerado)
docs/                                manual de instalação (HTML fonte + PDF com prints)
logos/                               ícones PNG
```

Histórico de versões em [CHANGELOG.md](CHANGELOG.md).
