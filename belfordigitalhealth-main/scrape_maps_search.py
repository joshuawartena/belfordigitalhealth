import re
import requests

url = "https://www.google.com/search"
params = {
    "tbm": "map",
    "authuser": "0",
    "hl": "en",
    "gl": "us",
    "q": "Forks Chem-Dry East Grand Forks MN",
}
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.google.com/maps/"
}

try:
    print("Querying Google Maps search API (/search?tbm=map)...")
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    print(f"Status Code: {resp.status_code}")
    
    text = resp.text
    if text.startswith(")]}'"):
        text = text[4:]
        
    print(f"Response length: {len(text)}")
    
    # Search for Place ID patterns
    pids = list(set(re.findall(r'ChIJ[A-Za-z0-9_-]{23}', text)))
    print(f"\nPlace IDs found in Maps search response: {pids}")
    
    # Also search for "0x" patterns like 0x52c686a1c228e78b:0x44f836ccdf1a6f6f
    feature_ids = list(set(re.findall(r'0x[a-fA-F0-9]+:0x[a-fA-F0-9]+', text)))
    print(f"Feature IDs found in response: {feature_ids}")
    
    # Let's save a snippet to inspect
    print("\nSnippet of response:")
    print(text[:2000])
    
except Exception as e:
    print(f"Error: {e}")
