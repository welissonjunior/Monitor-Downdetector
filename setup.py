#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup.py — Configuração automática do Downdetector Monitor via APIs Zabbix e Grafana.

Uso:
    python3 setup.py zabbix  --url http://127.0.0.1/zabbix --user Admin --password zabbix
    python3 setup.py grafana --url http://127.0.0.1:3000 --user admin --password admin
    python3 setup.py full    --zabbix-url ... --grafana-url ...
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERRO: pacote 'requests' não instalado. Execute: pip install requests")
    sys.exit(1)


INSTALL_DIR = Path(os.environ.get("INSTALL_DIR", "/opt/downdetector-zabbix"))
TEMPLATE_FILE = INSTALL_DIR / "zbx_downdetector_template.yaml"
DASHBOARD_FILE = INSTALL_DIR / "downdetector_dashboard.json"
LOGOS_DIR = Path("/usr/share/grafana/public/img/downdetector")


def set_install_dir(path):
    """Permite instalar em diretório diferente do padrão (--install-dir)."""
    global INSTALL_DIR, TEMPLATE_FILE, DASHBOARD_FILE
    INSTALL_DIR = Path(path)
    TEMPLATE_FILE = INSTALL_DIR / "zbx_downdetector_template.yaml"
    DASHBOARD_FILE = INSTALL_DIR / "downdetector_dashboard.json"

# UID exigido pelo dashboard downdetector-noc-1; o install.sh provisiona o
# datasource com este UID via arquivo (PROVISIONED_DS_FILE), sem senha admin.
DS_UID = "PA67C5EADE9207728"
PROVISIONED_DS_FILE = "/etc/grafana/provisioning/datasources/downdetector-zabbix.yaml"


class ZabbixAPI:
    def __init__(self, url, user, password):
        self.url = url.rstrip("/")
        if not self.url.endswith("/api_jsonrpc.php"):
            self.api_url = self.url + "/api_jsonrpc.php"
        else:
            self.api_url = self.url
        self.user = user
        self.password = password
        self.auth = None
        self._use_bearer = False
        self._session = requests.Session()

    def call(self, method, params=None):
        params = params or {}
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        headers = {}
        if self.auth and not self._use_bearer:
            # Zabbix <= 7.0: aceita "auth" no payload
            payload["auth"] = self.auth
        if self.auth and self._use_bearer:
            # Zabbix 7.2+/8.0: "auth" foi removido; usar header Bearer
            headers["Authorization"] = f"Bearer {self.auth}"

        try:
            resp = self._session.post(self.api_url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                err = str(data["error"])
                # Compat: Zabbix >= 7.2 rejeita o parâmetro "auth" — trocar p/ Bearer e reenviar
                if self.auth and not self._use_bearer and 'unexpected parameter "auth"' in err:
                    self._use_bearer = True
                    return self.call(method, params)
                raise RuntimeError(f"Zabbix API error: {data['error']}")
            return data.get("result")
        except requests.RequestException as e:
            raise RuntimeError(f"Falha na requisição Zabbix: {e}")

    def login(self):
        try:
            self.auth = self.call("user.login", {"username": self.user, "password": self.password})
        except RuntimeError:
            self.auth = self.call("user.login", {"user": self.user, "password": self.password})
        if not self.auth:
            raise RuntimeError("Falha ao autenticar no Zabbix")
        print(f"✓ Logado no Zabbix ({self.url})")

    def import_template(self):
        if not TEMPLATE_FILE.exists():
            raise RuntimeError(f"Template não encontrado: {TEMPLATE_FILE}")
        source = TEMPLATE_FILE.read_text(encoding="utf-8")
        params = {
            "format": "yaml",
            "rules": {
                "templates": {"createMissing": True, "updateExisting": True},
                "items": {"createMissing": True, "updateExisting": True},
                "discoveryRules": {"createMissing": True, "updateExisting": True},
                "triggers": {"createMissing": True, "updateExisting": True},
                "graphs": {"createMissing": True, "updateExisting": True},
                "valueMaps": {"createMissing": True, "updateExisting": True},
                "templateLinkage": {"createMissing": True},
            },
            "source": source,
        }
        self.call("configuration.import", params)
        print("✓ Template 'Downdetector Monitor' importado/atualizado")

    def get_template_id(self):
        result = self.call("template.get", {"filter": {"host": ["Downdetector Monitor"]}})
        if not result:
            raise RuntimeError("Template 'Downdetector Monitor' não encontrado após importação")
        return result[0]["templateid"]

    def get_group_id(self):
        result = self.call("hostgroup.get", {"output": ["groupid"], "limit": 1})
        if not result:
            raise RuntimeError("Nenhum hostgroup encontrado")
        return result[0]["groupid"]

    def create_or_update_host(self, template_id, group_id):
        host_check = self.call("host.get", {"filter": {"host": ["Downdetector"]}})
        if host_check:
            host_id = host_check[0]["hostid"]
            self.call("host.update", {
                "hostid": host_id,
                "templates": [{"templateid": template_id}],
            })
            print("✓ Host 'Downdetector' atualizado")
            return host_id

        result = self.call("host.create", {
            "host": "Downdetector",
            "name": "Downdetector",
            "interfaces": [{
                "type": 1,
                "main": 1,
                "useip": 1,
                "ip": "127.0.0.1",
                "dns": "",
                "port": "10050",
            }],
            "groups": [{"groupid": group_id}],
            "templates": [{"templateid": template_id}],
        })
        print("✓ Host 'Downdetector' criado")
        return result["hostids"][0]

    def run_discovery(self):
        """Opcional: envia discovery inicial se o coletor ainda não rodou."""
        pass


class GrafanaAPI:
    def __init__(self, url, user, password):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self._session = requests.Session()
        self._session.auth = (user, password)
        self._headers = {"Content-Type": "application/json"}

    @staticmethod
    def _short(e):
        msg = str(e)
        return msg[:110] + ("..." if len(msg) > 110 else "")

    def get(self, path, **kwargs):
        resp = self._session.get(f"{self.url}{path}", timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def post(self, path, json_data=None, **kwargs):
        resp = self._session.post(f"{self.url}{path}", json=json_data, headers=self._headers, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def reload_provisioning(self):
        try:
            self.post("/api/admin/provisioning/dashboards/reload")
            print("✓ Provisioning do Grafana recarregado")
        except Exception as e:
            # O dashboards.yaml tem updateIntervalSeconds: 10 — o Grafana relê
            # sozinho; o reload por API é só um atalho.
            print(f"ℹ Reload por API indisponível ({self._short(e)}); o provisioning por arquivo recarrega sozinho.")

    def enable_plugin(self, plugin_id):
        """Habilita um plugin.

        Grafana 11+/12+/13 auto-desabilita plugins no upgrade de versão
        (ex.: o painel gapit-htmlgraphics-panel). Sem isso, o dashboard
        provisionado fica vazio. Requer credencial com permissão de admin.
        """
        try:
            self.post(f"/api/plugins/{plugin_id}/settings", {"enabled": True, "pinned": True})
            print(f"✓ Plugin {plugin_id} habilitado")
            return True
        except Exception as e:
            # Ex.: credencial sem papel de Grafana Admin. O plugin normalmente
            # já vem habilitado; isto só cobre o auto-desligamento em upgrades.
            print(f"ℹ {plugin_id}: sem permissão para habilitar via API ({self._short(e)}).")
            print(f"   Se o painel aparecer vazio: Configuration → Plugins → {plugin_id} → Enable")
            return False

    def find_datasource(self, name="Zabbix"):
        """Procura primeiro pelo UID exigido pelo dashboard, depois por tipo/nome."""
        try:
            ds = self.get("/api/datasources")
            for d in ds:
                if d.get("uid") == DS_UID:
                    return d
            for d in ds:
                if d.get("type") == "alexanderzobnin-zabbix-datasource" or d.get("name") == name:
                    return d
        except Exception as e:
            print(f"⚠ Erro ao listar datasources: {e}")
        return None

    def create_zabbix_datasource(self, zabbix_url, zabbix_user, zabbix_password):
        """Cria o datasource Zabbix no Grafana se não existir."""
        api_url = zabbix_url.rstrip("/")
        if not api_url.endswith("/api_jsonrpc.php"):
            api_url += "/api_jsonrpc.php"

        payload = {
            "name": "Zabbix",
            "type": "alexanderzobnin-zabbix-datasource",
            "access": "proxy",
            "url": api_url,
            "uid": DS_UID,
            "jsonData": {
                "username": zabbix_user,
                "trends": True,
                "dbConnectionEnable": False,
            },
            "secureJsonData": {
                "password": zabbix_password,
            },
        }
        try:
            result = self.post("/api/datasources", payload)
            print(f"✓ Datasource Zabbix criado no Grafana (uid={result.get('datasource', {}).get('uid')})")
            return result
        except Exception as e:
            print(f"⚠ Não foi possível criar datasource Zabbix: {e}")
            return None


def copy_logos():
    """Garante que os ícones existam no Grafana."""
    src = INSTALL_DIR / "logos"
    if not src.exists():
        print(f"⚠ Pasta de logos não encontrada: {src}")
        return
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.png"):
        dst = LOGOS_DIR / f.name
        dst.write_bytes(f.read_bytes())
    print(f"✓ Ícones copiados para {LOGOS_DIR}")


def cmd_zabbix(args):
    api = ZabbixAPI(args.url, args.user, args.password)
    api.login()
    api.import_template()
    template_id = api.get_template_id()
    group_id = api.get_group_id()
    api.create_or_update_host(template_id, group_id)
    print("✓ Zabbix configurado com sucesso")


def cmd_grafana(args):
    api = GrafanaAPI(args.url, args.user, args.password)

    # O install.sh provisiona o datasource via ARQUIVO (uid fixo, dispensa
    # senha admin do Grafana). Só usa a API quando o arquivo não existe.
    if os.path.exists(PROVISIONED_DS_FILE):
        print(f"✓ Datasource Zabbix provisionado via arquivo (uid={DS_UID})")
    else:
        ds = api.find_datasource()
        if ds and ds.get("uid") == DS_UID:
            print(f"✓ Datasource Zabbix correto: {ds.get('name')} (uid={ds.get('uid')})")
        elif ds:
            print(f"⚠ Existe datasource Zabbix com UID diferente ({ds.get('uid')}); o dashboard espera {DS_UID}.")
            print("  Criando datasource adicional com o UID correto...")
            api.create_zabbix_datasource(
                getattr(args, "zabbix_url", "http://127.0.0.1/zabbix"),
                getattr(args, "zabbix_user", "Admin"),
                getattr(args, "zabbix_password", "zabbix"),
            )
        else:
            print("⚠ Datasource Zabbix não encontrado. Criando automaticamente...")
            api.create_zabbix_datasource(
                getattr(args, "zabbix_url", "http://127.0.0.1/zabbix"),
                getattr(args, "zabbix_user", "Admin"),
                getattr(args, "zabbix_password", "zabbix"),
            )

    copy_logos()
    # Grafana 11+/12+/13 auto-desabilita plugins no upgrade — habilitar o painel
    # HTML é obrigatório para o dashboard renderizar (descoberto em teste live).
    api.enable_plugin("gapit-htmlgraphics-panel")
    api.enable_plugin("alexanderzobnin-zabbix-app")
    api.reload_provisioning()
    print("✓ Grafana configurado com sucesso")


def cmd_full(args):
    print("\n[1/2] Configurando Zabbix...")
    cmd_zabbix(args)
    print("\n[2/2] Configurando Grafana...")
    cmd_grafana(args)
    print("\n✓ Configuração completa finalizada")


def cmd_verify(args):
    """Verifica template, host e itens criados pelo LLD (usa o install.sh)."""
    api = ZabbixAPI(args.url, args.user, args.password)
    api.login()

    if not api.call("template.get", {"filter": {"host": ["Downdetector Monitor"]}}):
        raise SystemExit("✗ Template 'Downdetector Monitor' não encontrado")
    if not api.call("host.get", {"filter": {"host": ["Downdetector"]}}):
        raise SystemExit("✗ Host 'Downdetector' não encontrado")

    # O LLD cria os itens de status de forma assíncrona após o discovery:
    # tenta por até ~2 minutos.
    status_items, hb_item = [], None
    for _ in range(12):
        items = api.call("item.get", {
            "host": "Downdetector",
            "search": {"key_": "downdetector."},
            "output": ["key_", "lastvalue", "lastclock"],
        }) or []
        status_items = [i for i in items if i["key_"].startswith("downdetector.status[")]
        hb_item = next((i for i in items if i["key_"] == "downdetector.collector.heartbeat"), None)
        if status_items and hb_item:
            break
        time.sleep(10)

    if not hb_item:
        raise SystemExit("✗ Item de heartbeat ausente (template vinculado ao host?)")
    if not status_items:
        raise SystemExit("✗ Nenhum item de status criado — o coletor já enviou o discovery?")

    print(f"✓ Template, host e heartbeat presentes")
    print(f"✓ {len(status_items)} itens de status criados pelo LLD")
    if hb_item.get("lastvalue") not in (None, ""):
        print(f"✓ Último heartbeat: {hb_item['lastvalue']}")


def main():
    parser = argparse.ArgumentParser(description="Configuração automática Downdetector Monitor")
    sub = parser.add_subparsers(dest="command", required=True)

    p_zabbix = sub.add_parser("zabbix", help="Importa template e cria host no Zabbix")
    p_zabbix.add_argument("--install-dir", default=None)
    p_zabbix.add_argument("--url", default="http://127.0.0.1/zabbix")
    p_zabbix.add_argument("--user", default="Admin")
    p_zabbix.add_argument("--password", default="zabbix")
    p_zabbix.set_defaults(func=cmd_zabbix)

    p_grafana = sub.add_parser("grafana", help="Configura dashboard/ícones no Grafana")
    p_grafana.add_argument("--install-dir", default=None)
    p_grafana.add_argument("--url", default="http://127.0.0.1:3000")
    p_grafana.add_argument("--user", default="admin")
    p_grafana.add_argument("--password", default="admin")
    p_grafana.add_argument("--zabbix-url", default="http://127.0.0.1/zabbix")
    p_grafana.add_argument("--zabbix-user", default="Admin")
    p_grafana.add_argument("--zabbix-password", default="zabbix")
    p_grafana.set_defaults(func=cmd_grafana)

    p_full = sub.add_parser("full", help="Configura Zabbix e Grafana")
    p_full.add_argument("--install-dir", default=None)
    p_full.add_argument("--zabbix-url", default="http://127.0.0.1/zabbix")
    p_full.add_argument("--zabbix-user", default="Admin")
    p_full.add_argument("--zabbix-password", default="zabbix")
    p_full.add_argument("--grafana-url", default="http://127.0.0.1:3000")
    p_full.add_argument("--grafana-user", default="admin")
    p_full.add_argument("--grafana-password", default="admin")
    p_full.set_defaults(func=cmd_full)

    p_verify = sub.add_parser("verify", help="Verifica template, host e itens no Zabbix")
    p_verify.add_argument("--install-dir", default=None)
    p_verify.add_argument("--url", default="http://127.0.0.1/zabbix")
    p_verify.add_argument("--user", default="Admin")
    p_verify.add_argument("--password", default="zabbix")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    if getattr(args, "install_dir", None):
        set_install_dir(args.install_dir)
    args.func(args)


if __name__ == "__main__":
    main()
