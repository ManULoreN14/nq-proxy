import requests, xml.etree.ElementTree as ET, re

HEADERS = {'User-Agent': 'NQRadar nqradar@example.com', 'Accept': '*/*'}

# Descargar el form4.xml de AAPL que ya sabemos que existe
url = 'https://www.sec.gov/Archives/edgar/data/320193/000114036126023363/form4.xml'
r   = requests.get(url, headers=HEADERS, timeout=15)
xml = r.text

# Quitar namespace si hay
xml_clean = re.sub(r'\s*xmlns[^\"]*\"[^\"]*\"', '', xml)
root = ET.fromstring(xml_clean)

print('=== Todas las nonDerivativeTransaction ===')
for tx in root.findall('.//nonDerivativeTransaction'):
    code   = tx.findtext('.//transactionCode') or 'N/A'
    shares = tx.findtext('.//transactionShares/value') or '0'
    price  = tx.findtext('.//transactionPricePerShare/value') or '?'
    print('  code=' + code + '  shares=' + shares + '  price=' + price)

print()
print('=== derivativeTransaction (opciones/awards) ===')
for tx in root.findall('.//derivativeTransaction'):
    code = tx.findtext('.//transactionCode') or 'N/A'
    print('  code=' + code)
