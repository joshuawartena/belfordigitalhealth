import requests

url = "https://share.google/tVwc6oHjsuaLaE9JT"
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

try:
    print(f"Tracing redirects for: {url}")
    session = requests.Session()
    resp = session.get(url, headers=headers, timeout=15)
    
    print("\nRedirect History:")
    for r in resp.history:
        print(f"  Code {r.status_code} -> {r.url}")
        
    print(f"\nFinal URL: {resp.url}")
    print(f"Final Status Code: {resp.status_code}")
    
    # Check if there is any Place ID pattern in the final URL
    import re
    pids = list(set(re.findall(r'ChIJ[A-Za-z0-9_-]{23}', resp.url)))
    print(f"Place IDs in Final URL: {pids}")
    
    # Also look at first 1000 characters of the page
    print("\nFirst 1000 chars of final page:")
    print(resp.text[:1000])
except Exception as e:
    print(f"Error tracing redirects: {e}")
