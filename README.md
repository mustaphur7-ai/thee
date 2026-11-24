# XAUUSD Levels

Static gold levels page. A GitHub Action runs once a day at 17:33 Kenya time (14:33 UTC), reads the GLD options chain, and writes data/levels.json. The page only reads that file, so the levels stay frozen until the next run. Spot price comes live from Binance in the browser.

Levels: call wall, put wall, gamma flip, plus 3 resistances and 3 supports scored from open interest, Greeks (gamma, delta, vega) and implied volatility.

## Setup
1. Create a new public GitHub repository.
2. Upload all files keeping the folders: .github/workflows/analyze.yml, scripts/analyze.py, data/levels.json, index.html, style.css, app.js, requirements.txt, README.md.
3. Settings > Actions > General > Workflow permissions: choose "Read and write permissions" and save.
4. Settings > Pages: Source "Deploy from a branch", branch main, folder / (root), save.
5. Actions tab > "Daily levels analysis" > Run workflow. When it finishes, levels.json updates and the sample banner disappears.
6. Open https://YOUR-USERNAME.github.io/REPO-NAME/

## Notes
- GitHub cron can run several minutes late. The page shows the real analysis time.
- If a run fails, the old levels.json is kept and the page warns when it is over 26 hours old.
- GLD options data is delayed, so treat levels as estimates of positioning.
