import os
import requests
from dotenv import load_dotenv

load_dotenv()

key = os.getenv('GOOGLE_API_KEY', '')
print(f"API Key loaded: '{key}'")

# Test 5: Places API Text Search for Forks Chem-Dry
print("\n--- Testing Places Text Search for Forks Chem-Dry ---")
search_url = 'https://places.googleapis.com/v1/places:searchText'
search_headers = {
    'X-Goog-Api-Key': key,
    'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress',
    'Content-Type': 'application/json',
}
search_body = {'textQuery': 'Forks Chem-Dry Grand Forks ND'}

try:
    resp = requests.post(search_url, json=search_body, headers=search_headers, timeout=10)
    print(f"Places Text Search Status Code: {resp.status_code}")
    if resp.status_code != 200:
        print("Places Text Search Error Response:")
        print(resp.text)
    else:
        print("Places Text Search Success!")
        print(resp.json())
except Exception as e:
    print(f"Places Text Search Request failed: {e}")
