#!/usr/bin/env python3
"""Captura os dashboards NOC em kiosk 1920x1080 (Grafana local, logado como admin).
Roda na própria VM: /opt/downdetector-zabbix/venv/bin/python /tmp/shot_dashboards.py
"""
import os
import sys
import time

BASE = "http://127.0.0.1:3000"
USER = os.environ.get("GRAFANA_USER", "admin")
PASS = os.environ.get("GRAFANA_PASS", "")
OUT = {"user": "/tmp/user_kiosk.png", "wallboard": "/tmp/wallboard_kiosk.png"}


def shoot(playwright_mod):
    with playwright_mod.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page = ctx.new_page()
        page.set_default_timeout(60000)

        # login
        page.goto(BASE + "/login", wait_until="networkidle")
        for _ in range(30):
            if page.locator('input[name="user"]').count():
                break
            time.sleep(1)
        page.fill('input[name="user"]', USER)
        page.fill('input[name="password"]', PASS)
        page.locator('form button[type="submit"]').click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=60000)
        print("login ok")

        for nome, uid in (("wallboard", "downdetector-tv-1"), ("user", "downdetector-noc-1")):
            page.goto(f"{BASE}/d/{uid}?kiosk", wait_until="networkidle")
            print(f"{nome}: aguardando painel...")
            ok = False
            for _ in range(60):
                ready = page.evaluate(
                    """() => {
                      for (const e of document.querySelectorAll('*')) {
                        const sr = e.shadowRoot;
                        if (sr) {
                          const d = sr.getElementById && sr.getElementById('dd');
                          if (d) return { txt: d.innerText.length, h: d.getBoundingClientRect().height };
                        }
                      }
                      return null;
                    }"""
                )
                if ready and ready.get("txt", 0) > 150:
                    ok = True
                    break
                time.sleep(1.5)
            if not ok:
                print(f"{nome}: painel não renderizou a tempo")
                continue
            time.sleep(6)  # assenta layout (fitCanvas/fontes/queries)
            page.screenshot(path=OUT[nome], clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
            print(f"{nome}: print salvo em {OUT[nome]}")

        browser.close()


def main():
    for modname in ("playwright.sync_api", "patchright.sync_api"):
        try:
            mod = __import__(modname, fromlist=["sync_playwright"])
        except Exception as e:
            print(modname, "indisponível:", e)
            continue
        try:
            shoot(mod)
            return 0
        except Exception as e:
            print(modname, "falhou:", e)
    return 1


if __name__ == "__main__":
    sys.exit(main())
