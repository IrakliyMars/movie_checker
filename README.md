# Movie Checker

A tiny GitHub Pages site for **English-language / VOSE screenings at Yelmo cinemas**, grouped the way a moviegoer needs them:

```text
City
  Movie
    Date
      Cinema — clickable showtime
```

Málaga is the default city. Its Yelmo locations are:

- Vialia Málaga
- Plaza Mayor
- Rincón de la Victoria

Only movies that actually have English-language / VOSE sessions are shown. A movie with no qualifying sessions is not rendered.

## Frontend

The static frontend supports a city selector and aggregates the same film across cinemas. Under each movie it shows every published date, then the cinema name and individual clickable showtimes for that date.

The data format is city-based so additional cities can be added without redesigning the frontend:

```json
{
  "cities": [
    {
      "id": "malaga",
      "name": "Málaga",
      "cinemas": []
    }
  ]
}
```

## GitHub-only architecture

There is **no public backend API and no personal server**.

```text
GitHub Actions (every 2 hours)
        |
        v
schedule collector -> movies.json
        |
        v
GitHub Pages -> visitors
```

Visitors only download static HTML/CSS and the already-generated `movies.json`. Opening or reloading Movie Checker does not trigger a request to Yelmo.

## Rate / overload protection

- refresh at most once every **2 hours**
- only one deployment workflow may run at once
- build timeout prevents stuck collectors
- no user-accessible scraping endpoint
- Reload only reloads static JSON from GitHub Pages
- an empty or obviously malformed result is rejected, so it cannot overwrite the previous known-good deployment

## Current source constraint

Yelmo currently places its public schedule pages behind Cloudflare anti-bot protection. GitHub-hosted runners can be rejected even when the same pages work normally in a consumer browser. Movie Checker does **not** attempt to bypass that protection and does not embed private credentials.

The frontend and data model are intentionally independent from the collector, so a permitted JSON/feed source can replace the collector without changing the site UI.

## Files

- `scraper.py` — current schedule collector and Málaga cinema definitions
- `generate_data.py` — generates and validates `movies.json`
- `site/index.html` — static city/movie/date/cinema frontend
- `site/styles.css` — styles
- `.github/workflows/deploy-pages.yml` — scheduled GitHub Pages build/deploy
- `requirements.txt` — collector dependencies

## GitHub Pages

Pages is deployed through GitHub Actions. In repository settings the publishing source should be **GitHub Actions**.
