# homeowner-calculator

[Homeowner Calculator](https://homeowner-calculator.pages.dev/)

# Sources
- [Gemini chat to estimate monthly breakdown categories and values](https://share.google/aimode/ALwoQO3ecn7n5RWfs)
  - [Manually built spreadsheet based on Gemini's input](https://docs.google.com/spreadsheets/d/1RoSdnRnMpINqno-AD_nao3h9IP5vULhof4lXZddu4mE/edit?usp=sharing)
- [Claude chat to generate initial HTML code](https://aiplayground-prod2.stanford.edu/share/1ZP0vqYvgc-tZZmNP39Tg)
- [Gemini chat for Cloudflare deployment](https://share.google/aimode/UAjsZqyRDyK52DXaT)
  - [CLoudflare project](https://dash.cloudflare.com/97dc994edc7b5332da64db25d9fe827d/pages/view/homeowner-calculator)


## Daily mortgage rate automation

A GitHub Actions workflow now automates city-rate refreshes:

- Workflow: `.github/workflows/daily-rate-update.yml`
- Schedule: daily (plus manual `workflow_dispatch`)
- Source: FRED `MORTGAGE30US` CSV feed
- Updater script: `scripts/update_bay_area_rates.py`
- Deployment behavior: validated rate changes are committed directly to the default branch so the published site stays current without a manual merge step

### Update method

- Fetch latest non-empty FRED `MORTGAGE30US` observation.
- Compute the median of current Bay Area city rates.
- Shift every city rate by `(latest_source_rate - current_median)` to preserve city spread while tracking the latest national baseline.
- Update `lastUpdated`, `estimateBasis`, and `source` metadata.
- Update `RATE_MAP_DATA_VERSION` in `index.html` for cache-busting.

### Safety and validation

- Source outage guardrail: if the source is unreachable or empty, the script logs a skip and exits without changing files.
- Workflow validation includes:
  - JSON shape checks for `data/bay-area-city-rates.json`
  - Existing Python unit tests (`python -m unittest -v`)

### Manual run

You can run the updater locally:

```bash
python scripts/update_bay_area_rates.py
```
