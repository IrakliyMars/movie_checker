import json
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://api-g.cinepolis.com/shared-services/locations/graphql"
QUERY = "query Cities($country: String!) { cities(country_id: $country) { edges { node { id name timezone } } } }"
payload = json.dumps({"operationName": "Cities", "query": QUERY, "variables": {"country": "ES"}}).encode()
headers = {
    "content-type": "application/json",
    "accept": "application/json",
    "country-id": "ES",
    "language": "ES",
    "user-agent": "Mozilla/5.0",
}
out = {}
try:
    req = urllib.request.Request(URL, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        out = {"status": response.status, "content_type": response.headers.get("content-type"), "body": response.read(20000).decode("utf-8", errors="replace")}
except urllib.error.HTTPError as exc:
    out = {"status": exc.code, "content_type": exc.headers.get("content-type"), "body": exc.read(20000).decode("utf-8", errors="replace")}
except Exception as exc:
    out = {"error": repr(exc)}
Path("probe-output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
