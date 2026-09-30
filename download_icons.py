import os
import re
import unicodedata
import urllib.request
import urllib.error

domainMap = {
  'WhatsApp': 'whatsapp.com',
  'Caixa Econômica Federal': 'caixa.gov.br',
  'Nubank': 'nubank.com.br',
  'Banco Pan': 'bancopan.com.br',
  'Banco Inter': 'bancointer.com.br',
  'Banco do Brasil': 'bb.com.br',
  'Bradesco': 'bradesco.com.br',
  'Itaú': 'itau.com.br',
  'Santander': 'santander.com.br',
  'Neon': 'neon.com.br',
  'BTG Pactual': 'btgpactual.com',
  'Mercado Pago': 'mercadopago.com.br',
  'PicPay': 'picpay.com',
  'PagSeguro': 'pagseguro.uol.com.br',
  'C6 Bank': 'c6bank.com.br',
  'Vivo': 'vivo.com.br',
  'Claro': 'claro.com.br',
  'TIM': 'tim.com.br',
  'Algar': 'algartelecom.com.br',
  'Google': 'google.com',
  'Cloudflare': 'cloudflare.com',
  'PIX': 'bcb.gov.br',
  'Banco Central': 'www.bcb.gov.br',
  'Sicoob': 'sicoob.com.br',
  'Sicredi': 'sicredi.com.br',
  'Microsoft Copilot': 'copilot.microsoft.com',
  'Microsoft 365': 'microsoft.com',
  'OneDrive': 'onedrive.live.com',
  'Microsoft Teams': 'teams.microsoft.com',
  'Keeper': 'keepersecurity.com',
  'Stone': 'stone.co',
  'gov.br': 'gov.br',
  'Receita Federal': 'receita.fazenda.gov.br',
}


def safe_name(name):
    """Espelha EXATAMENTE o safeName() do dashboard (JS):
    sem acentos, minúsculo, todo char fora de [a-z0-9_] vira '_'.
    Importante: '.' também vira '_' (ex.: 'gov.br' -> 'gov_br'),
    senão o ícone baixado não casa com o que o card procura."""
    plain = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9_]', '_', plain.lower())

os.makedirs('logos', exist_ok=True)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

for name, domain in domainMap.items():
    fname = safe_name(name)
    url = f"https://www.google.com/s2/favicons?sz=128&domain={domain}"
    filepath = f"logos/{fname}.png"

    if not os.path.exists(filepath):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                with open(filepath, 'wb') as out_file:
                    out_file.write(response.read())
            print(f"Baixado: {name} ({domain})")
        except Exception as e:
            print(f"Erro ao baixar {name}: {e}")
    else:
        print(f"Já existe: {name}")

print("Download de logos concluído!")
