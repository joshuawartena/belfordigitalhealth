import os
import requests
from dotenv import load_dotenv

load_dotenv()

key = os.getenv('GOOGLE_API_KEY', '')
url = 'https://forkschemdry.com'
strategy = 'mobile'
psi_url = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed'

print("--- Testing PSI WITH Key ---")
params = {
    'url': url,
    'strategy': strategy,
    'category': ['performance', 'accessibility', 'seo'],
}
if key:
    params['key'] = key

try:
    resp = requests.get(psi_url, params=params, timeout=30)
    print(f"WITH key status code: {resp.status_code}")
    if resp.status_code != 200:
        print(resp.text[:500])
except Exception as e:
    print(f"WITH key failed: {e}")

print("\n--- Testing PSI WITHOUT Key ---")
params_no_key = {
    'url': url,
    'strategy': strategy,
    'category': ['performance', 'accessibility', 'seo'],
}
try:
    resp = requests.get(psi_url, params=params_no_key, timeout=30)
    print(f"WITHOUT key status code: {resp.status_code}")
    if resp.status_code != 200:
        print(resp.text[:500])
    else:
        print("Success without key! Keys returned:")
        print(list(resp.json().keys()))
except Exception as e:
    print(f"WITHOUT key failed: {e}")
