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
    resp = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(resp.text, 'html.parser')
    print(f"Page Title: {soup.title.text if soup.title else 'No Title'}")
    print(f"Page text length: {len(resp.text)}")
    print("\nFirst 1000 characters of response:")
    print(resp.text[:1000])
except Exception as e:
    print(f"Error: {e}")
