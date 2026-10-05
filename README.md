# Movie Checker

A tiny local website that shows **English-language / VOSE screenings at Yelmo cinemas in Málaga**.

It currently checks:

- Yelmo Vialia Málaga
- Yelmo Plaza Mayor

The frontend is intentionally minimal. Movie titles are clickable and open the corresponding Yelmo film page when Yelmo exposes one. Each showtime is also clickable: when Yelmo exposes a direct booking/session URL, Movie Checker preserves it; otherwise it safely falls back to the film or cinema page.

## Stack

- Python
- Flask
- Playwright (Chromium)
- Plain HTML/CSS/JavaScript
- No database

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python app.py
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Then open:

```text
http://127.0.0.1:5000
```

## How it works

`GET /api/movies` opens Yelmo's Málaga cinema pages in headless Chromium, waits for the JavaScript-rendered schedule, keeps only **INGLÉS SUBTITULADO EN ESPAÑOL (VOSE)** screenings, and returns a small JSON payload to the frontend.

Results are cached for 10 minutes so reloading the page does not repeatedly launch a browser. The **Refresh** button calls `/api/movies?refresh=1` and bypasses that cache.

## Why Playwright?

Yelmo renders important schedule information dynamically. A browser-based scraper is less brittle than assuming the initial HTML contains the complete timetable. The extractor also avoids depending on a single Yelmo CSS class and instead looks for semantic signals: movie headings, the VOSE label, time-shaped session links, and their nearest DOM containers.

## If Yelmo changes its website

The likely file to update is `scraper.py`. The rest of the app is deliberately independent of Yelmo's page structure.
