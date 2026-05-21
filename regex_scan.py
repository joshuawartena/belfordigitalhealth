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
    resp = requests.get(url, headers=headers, timeout=15)
    html = resp.text
    
    print(f"Total HTML length: {len(html)}")
    
    # 1. Search for any ChIJ pattern (Place ID)
    pids = list(set(re.findall(r'ChIJ[A-Za-z0-9_-]{23}', html)))
    print(f"Place IDs found: {pids}")
    
    # 2. Search for any ludocid
    ludocids = list(set(re.findall(r'ludocid=(\d+)', html)))
    print(f"ludocids found: {ludocids}")
    
    # 3. Search for any 19-digit CIDs
    cids = list(set(re.findall(r'\b\d{18,20}\b', html)))
    print(f"Potential 18-20 digit CIDs found (top 10): {cids[:10]}")
    
    # 4. Search for google.com/maps or maps.google
    maps_links = list(set(re.findall(r'https?://[^\s"\'<>]*google\.[a-z]+/maps[^\s"\'<>]*', html)))
    print(f"Google Maps links found: {maps_links}")
    
    # 5. Search for share.google or goo.gl
    goo_links = list(set(re.findall(r'https?://[^\s"\'<>]*goo\.gl[^\s"\'<>]*', html)))
    print(f"goo.gl links found: {goo_links}")
    
except Exception as e:
    print(f"Error: {e}")
