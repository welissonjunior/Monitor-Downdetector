#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_zabbix.py — LEGADO: importação manual do template Zabbix.

PREFERÍVEL: `python3 setup.py zabbix --url ... --user ... --password ...`
Este script existe apenas como opção offline sem argparse. Ele NÃO contém
credenciais: tudo vem de variáveis de ambiente.

Uso:
    export ZABBIX_URL="http://127.0.0.1/zabbix"
    export ZABBIX_USER="Admin"
    export ZABBIX_PASS="********"
    python3 import_zabbix.py
"""

import json
import os
import sys

import requests

url = os.environ.get("ZABBIX_URL", "").rstrip("/")
user = os.environ.get("ZABBIX_USER", "")
password = os.environ.get("ZABBIX_PASS", "")

if not (url and user and password):
    print("ERRO: defina as variáveis de ambiente ZABBIX_URL, ZABBIX_USER e ZABBIX_PASS.")
    print("Dica: prefira o setup.py (python3 setup.py zabbix --url ... --user ... --password ...).")
    sys.exit(1)

headers = {'Content-Type': 'application/json-rpc'}


def api_call(method, params, auth=None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    if auth:
        headers["Authorization"] = f"Bearer {auth}"

    try:
        response = requests.post(url, json=payload, headers=headers)
        res_json = response.json()
        if "error" in res_json:
            print(f"ERRO ({method}): {res_json['error']['data']}")
        return res_json
    except Exception as e:
        print(f"HTTP ERROR: {e}")
        return {}


def main():
    print("Logando na API do Zabbix...")
    # Tenta com 'username' (Zabbix >= 5.4) e fallback para 'user' (< 5.4)
    login_res = api_call("user.login", {"username": user, "password": password})
    if "error" in login_res:
        login_res = api_call("user.login", {"user": user, "password": password})

    auth_token = login_res.get("result")
    if not auth_token:
        print("Falha ao autenticar no Zabbix.")
        sys.exit(1)

    print("Token obtido com sucesso.")

    print("Importando template...")
    try:
        with open("zbx_downdetector_template.yaml", "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        print(f"Erro ao ler arquivo yaml: {e}")
        sys.exit(1)

    import_params = {
        "format": "yaml",
        "rules": {
            "templates": {"createMissing": True, "updateExisting": True},
            "items": {"createMissing": True, "updateExisting": True},
            "discoveryRules": {"createMissing": True, "updateExisting": True},
            "triggers": {"createMissing": True, "updateExisting": True},
            "graphs": {"createMissing": True, "updateExisting": True},
            "valueMaps": {"createMissing": True, "updateExisting": True},
            "templateLinkage": {"createMissing": True}
        },
        "source": source
    }
    import_res = api_call("configuration.import", import_params, auth_token)
    if "result" in import_res:
        print("Template importado com sucesso!")

    print("Buscando o ID do Template importado...")
    tmpl_res = api_call("template.get", {"filter": {"host": ["Downdetector Monitor"]}}, auth_token)
    if not tmpl_res.get("result"):
        print("Template 'Downdetector Monitor' não encontrado!")
        sys.exit(1)
    template_id = tmpl_res["result"][0]["templateid"]

    print("Buscando um Hostgroup válido...")
    group_res = api_call("hostgroup.get", {"output": "extend"}, auth_token)
    if not group_res.get("result"):
        print("Nenhum hostgroup encontrado!")
        sys.exit(1)
    group_id = group_res["result"][0]["groupid"]

    print("Verificando se o Host Downdetector já existe...")
    host_check = api_call("host.get", {"filter": {"host": ["Downdetector"]}}, auth_token)

    if host_check.get("result"):
        print("Host Downdetector já existe! Atualizando templates vinculados...")
        host_id = host_check["result"][0]["hostid"]
        update_params = {
            "hostid": host_id,
            "templates": [{"templateid": template_id}]
        }
        api_call("host.update", update_params, auth_token)
        print("Host atualizado.")
    else:
        print("Criando o Host Downdetector...")
        host_params = {
            "host": "Downdetector",
            "name": "Downdetector",
            "interfaces": [
                {
                    "type": 1,
                    "main": 1,
                    "useip": 1,
                    "ip": "127.0.0.1",
                    "dns": "",
                    "port": "10050"
                }
            ],
            "groups": [{"groupid": group_id}],
            "templates": [{"templateid": template_id}]
        }
        create_res = api_call("host.create", host_params, auth_token)
        if "result" in create_res:
            print("Host criado com sucesso!")

    print("Finalizado!")


if __name__ == "__main__":
    main()
