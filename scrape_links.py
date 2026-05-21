import re
import requests
from bs4 import BeautifulSoup

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
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # 1. Look for all links
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if any(term in href for term in ('ludocid', 'place', 'cid', 'kgmid', 'maps')):
            links.append(href)
            
    print(f"\nFound {len(links)} interesting links in the page:")
    for l in list(set(links))[:20]:
        print(f"  - {l}")
        
    # 2. Let's search the entire text for some common patterns
    print("\nSearching text for ludocid or CID patterns...")
    cids = re.findall(r'ludocid=(\d+)', resp.text)
    if cids:
        print(f"Found CIDs: {set(cids)}")
    else:
        print("No ludocids found.")
        
except Exception as e:
    print(f"Error: {e}")
