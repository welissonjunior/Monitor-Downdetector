#!/usr/bin/env python3
"""Captura as telas do Zabbix (hosts + dados recentes) FILTRADAS pelo host Downdetector.

Não expõe outros hosts da rede. Roda na VM:
  ZBX_UI_USER (padrão Admin) e ZBX_UI_PASS (obrigatório) via ambiente.

Ex.: ZBX_UI_PASS='...' /opt/downdetector-zabbix/venv/bin/python /tmp/shot_zabbix.py
"""
import os
import sys

import subprocess

BASE = "http://127.0.0.1/zabbix"
USER = os.environ.get("ZBX_UI_USER", "Admin")
PASS = os.environ.get("ZBX_UI_PASS", "")
OUT = {"hosts": "/tmp/zbx_hosts.png", "latest": "/tmp/zbx_latest.png"}
PROIBIDOS = ["3161", "ASTERISK", "HOMESEVER", "JUNIOR-PC", "ROTEADOR", "Sicoob_Central", "VITALINO", "HSVC", "316100"]

from playwright.sync_api import sync_playwright


def login(page):
    page.goto(BASE + "/index.php", wait_until="networkidle")
    for _ in range(30):
        if page.locator('input[name="name"]').count():
            break
        page.wait_for_timeout(1000)
    page.fill('input[name="name"]', USER)
    page.fill('input[name="password"]', PASS)
    page.locator("#enter").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def verify(text, must_host="Downdetector"):
    if must_host.lower() not in text.lower():
        raise RuntimeError("host Downdetector não encontrado na tela")
    for p in PROIBIDOS:
        if p.lower() in text.lower():
            raise RuntimeError(f"host proibido visível na tela: {p}")


def main() -> int:
    proibidos_vistos = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        page.set_default_timeout(45000)
        login(page)
        print("login na UI ok")

        # 1) Hosts: filtro Nome (input texto name="name", id name_0) + Aplicar
        page.goto(BASE + "/zabbix.php?action=host.view", wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.fill('input[name="name"]', "Downdetector")
        page.locator('button[name="filter_apply"]').click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        text = page.inner_text("body")
        verify(text)
        page.screenshot(path=OUT["hosts"])
        print("hosts: print ok (somente Downdetector)")

        # 2) Dados recentes: filtro por host Downdetector (perfil salva por usuário)
        page.goto(BASE + "/zabbix.php?action=latest.view", wait_until="networkidle")
        page.wait_for_timeout(3000)
        text = page.inner_text("body")
        try:
            verify(text)
        except RuntimeError as e:
            print("AVISO latest:", e)
            proibidos_vistos.append("latest")
            # fallback: filtro por etiqueta component:downdetector via URL
            page.goto(BASE + "/zabbix.php?action=latest.view&filter_set=1&filter_tags%5B0%5D%5Btag%5D=component&filter_tags%5B0%5D%5Bvalue%5D=downdetector",
                      wait_until="networkidle")
            page.wait_for_timeout(3000)
            text = page.inner_text("body")
            verify(text)
            proibidos_vistos.clear()
        page.screenshot(path=OUT["latest"])
        print("latest: print ok (somente Downdetector)")
        browser.close()

    if proibidos_vistos:
        print("FALHA: telas com hosts proibidos:", proibidos_vistos)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
