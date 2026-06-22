import re
import requests
from bs4 import BeautifulSoup

url = "https://forkschemdry.com/"
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

try:
    print(f"Fetching {url}...")
    resp = requests.get(url, headers=headers, timeout=15)
    print(f"Status Code: {resp.status_code}")
    
    # Search for google.com/maps links in HTML
    soup = BeautifulSoup(resp.text, 'html.parser')
    maps_links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'google.com/maps' in href or 'maps.google' in href or 'maps.app.goo.gl' in href:
            maps_links.append(href)
            
    print(f"\nFound {len(maps_links)} Google Maps links on the homepage:")
    for l in list(set(maps_links)):
        print(f"  - {l}")
        
    # Search JSON-LD schemas
    print("\nSearching for JSON-LD schemas...")
    schemas = soup.find_all('script', type='application/ld+json')
    print(f"Found {len(schemas)} JSON-LD blocks.")
    for idx, s in enumerate(schemas):
        text = s.string or ""
        if 'hasMap' in text or 'maps.google' in text or 'google.com/maps' in text or 'sameAs' in text:
            print(f"Block {idx} contains map info:")
            print(text[:2000])  # Print first 2000 chars of matching block
            
except Exception as e:
    print(f"Error: {e}")
