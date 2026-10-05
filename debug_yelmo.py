import json
import urllib.error
import urllib.request
from pathlib import Path

URLS = [
    "https://inetvis.yelmocines.es/WSVistaWebClient/OData.svc/Cinemas?$format=json",
    "https://inetvis.yelmocines.es/WSVistaWebClient/OData.svc/Sessions?$format=json",
    "https://inetvis.yelmocines.es/WSVistaWebClient/OData.svc/GetNowShowingScheduledFilms?$expand=Sessions&$format=json",
    "https://inetvis.yelmocines.es/WSVistaWebClient/",
    "https://preprod.yelmocines.es/cartelera/malaga",
    "https://eu-preprod.yelmocines.es/cartelera/malaga",
]

out = []
for url in URLS:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(25000).decode("utf-8", errors="replace")
            out.append({
                "url": url,
                "status": response.status,
                "final_url": response.url,
                "content_type": response.headers.get("content-type"),
                "headers": dict(response.headers),
                "body": body,
            })
    except urllib.error.HTTPError as exc:
        body = exc.read(12000).decode("utf-8", errors="replace")
        out.append({"url": url, "status": exc.code, "headers": dict(exc.headers), "body": body})
    except Exception as exc:
        out.append({"url": url, "error": repr(exc)})

Path("debug-output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
