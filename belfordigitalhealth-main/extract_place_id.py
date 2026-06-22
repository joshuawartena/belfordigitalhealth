import re
import requests

url = (
    "https://www.google.com/search?q=Forks+Chem-Dry"
    "&kgmid=/g/1v2kx2df&kgs=d66460b4eb214ede"
)
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

try:
    print("Fetching Google Search knowledge panel page...")
    resp = requests.get(url, headers=headers, timeout=15)
    print(f"Status Code: {resp.status_code}")
    
    # Search for Place ID patterns (ChIJ followed by 23 alphanumeric characters, hyphens or underscores)
    place_ids = re.findall(r'ChIJ[A-Za-z0-9_-]{23}', resp.text)
    
    # De-duplicate
    unique_ids = list(set(place_ids))
    print(f"\nFound {len(unique_ids)} potential Place IDs in page source:")
    for pid in unique_ids:
        print(f"  - {pid}")
        
except Exception as e:
    print(f"Failed to fetch or parse search page: {e}")
