# Movie Checker

A tiny GitHub Pages site that shows **English-language / VOSE screenings at Yelmo cinemas in Málaga**.

It checks:

- Yelmo Vialia Málaga
- Yelmo Plaza Mayor

Movie titles are clickable. Each showtime is clickable too: when Yelmo exposes a direct session/booking URL, Movie Checker keeps that URL; otherwise it falls back to the relevant film or cinema page.

## Architecture

There is **no public backend API and no personal server**.

```text
GitHub Actions (every 2 hours)
        |
        v
Playwright scraper -> movies.json
        |
        v
GitHub Pages -> visitors
```

Visitors only download static HTML/CSS and the already-generated `movies.json` from GitHub Pages. Opening or reloading the site never scrapes Yelmo.

This means traffic to the public site cannot multiply requests to Yelmo. Whether one person or many people open Movie Checker, Yelmo is contacted only by the scheduled GitHub Actions job.

## Rate / overload protection

The workflow is intentionally conservative:

- scheduled once every **2 hours** in `Europe/Madrid`
- only one Movie Checker deployment workflow can run at a time (`concurrency`)
- scraper/build timeout prevents stuck jobs
- no user-accessible endpoint can trigger scraping
- the frontend Reload button only reloads the static JSON from GitHub Pages
- if scraping clearly fails and produces no usable movie data, deployment aborts and the previous successful Pages version stays live

A manual refresh is still possible from **GitHub → Actions → Refresh movies and deploy Pages → Run workflow**.

## Files

- `scraper.py` — reads Yelmo with headless Chromium and extracts VOSE movies/showtimes
- `generate_data.py` — generates `movies.json` and validates the scrape
- `site/index.html` — static frontend
- `site/styles.css` — styles
- `.github/workflows/deploy-pages.yml` — scheduled scraping + GitHub Pages deployment
- `requirements.txt` — Playwright dependency

## GitHub Pages setup

The workflow uses GitHub's official Pages Actions. In repository settings, set the Pages publishing source to **GitHub Actions**:

**Settings → Pages → Build and deployment → Source → GitHub Actions**

After that, run the workflow once manually or push to `main`. Scheduled refreshes happen automatically every two hours.

> GitHub Pages from a private personal repository requires a GitHub plan that supports Pages for private repositories. The published Pages site itself may still be public depending on your GitHub account/organization setup.

## Optional local scrape test

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python generate_data.py
```

That writes `site/data/movies.json` locally. You can then serve the `site` directory with any static web server, for example:

```bash
python -m http.server 8000 -d site
```

Open `http://127.0.0.1:8000`.

## If Yelmo changes its website

The likely file to update is `scraper.py`. The frontend and GitHub Pages deployment are deliberately independent of Yelmo's DOM structure.
