import requests

HEADERS = {'User-Agent': 'NQRadar nqradar@example.com', 'Accept': '*/*'}

accn     = '0001140361-26-023363'
accn_raw = accn.replace('-','')
cik_num  = '320193'
base_url = 'https://www.sec.gov/Archives/edgar/data/' + cik_num + '/' + accn_raw + '/'

for suffix in [accn + '-index.json', accn + '-index.htm', 'form4.xml', 'wk-form4.xml']:
    url = base_url + suffix
    r   = requests.get(url, headers=HEADERS, timeout=15)
    print('--- ' + suffix)
    print('    status=' + str(r.status_code) + '  len=' + str(len(r.content)) + '  ct=' + r.headers.get('Content-Type',''))
    if r.status_code == 200 and len(r.content) > 0:
        print('    preview: ' + r.text[:300])
    print()
