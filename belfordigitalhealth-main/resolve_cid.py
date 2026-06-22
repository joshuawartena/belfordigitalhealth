import os
import requests
from dotenv import load_dotenv

load_dotenv()

key = os.getenv('GOOGLE_API_KEY', '')
print(f"API Key loaded: '{key}'")

# Hex CID to decimal
hex_cid = "44f836ccdf1a6f6f"
dec_cid = int(hex_cid, 16)
print(f"Hex CID: {hex_cid} -> Decimal CID: {dec_cid}")

print("\n--- Testing Places Details by CID ---")
url = "https://maps.googleapis.com/maps/api/place/details/json"
params = {
    "cid": dec_cid,
    "key": key
}

try:
    resp = requests.get(url, params=params, timeout=10)
    print(f"Status Code: {resp.status_code}")
    data = resp.json()
    print("API Response keys:", data.keys())
    if data.get("status") == "OK":
        result = data.get("result", {})
        print("Success!")
        print(f"  Name:     {result.get('name')}")
        print(f"  Place ID: {result.get('place_id')}")
        print(f"  Address:  {result.get('formatted_address')}")
    else:
        print("Error Response:")
        print(data)
except Exception as e:
    print(f"Request failed: {e}")
