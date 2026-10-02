# Canada Basketball — 5×5 Women's Analytics

**Live dashboard:** https://jordanngo205.github.io/5x5_SWNT/

Scrapers, ratings and an interactive dashboard for 5×5 senior women's national teams (2025), built on Synergy Sports data for Canada Basketball.

---

## What's in the dashboard

- **Team profiles** — offensive and defensive efficiency (points per possession) and play-type breakdowns for all 81 senior teams
- **Quality-filtered stats** — team and player numbers counted only in games against Tier 1 and Tier 2 opponents
- **Player ratings** — 40–99 overall rating based on Hollinger's Game Score per 40 minutes
- **Play types** — all 11 Synergy play types, offense and defense, for teams and players

---

## Setup

```bash
pip install requests python-dotenv pkce openpyxl
```

Create a `.env` file with your Synergy credentials:

```
SYNERGY_USERNAME=you@example.com
SYNERGY_PASSWORD=...
```

Then authenticate once (handles 2FA and saves a reusable token to `.synergy_token`):

```bash
python do_auth.py
```

---

## Pipeline

```
Synergy API
  ↓
scrape_teams_2025.py            → team offense/defense + play types
scrape_players_2025.py          → player offense/defense
scrape_boxscores.py             → player box scores (all 81 teams)
scrape_vs_quality.py            → team/player stats vs T1/T2 opponents
scrape_boxscores_vs_quality.py  → player box scores vs T1/T2 opponents
scrape_pt_vs_quality.py         → play types vs T1/T2 opponents
scrape_player_def_pt.py         → player defensive play types
  ↓                               (all write to data/2025/)
build_ratings.py                → player + team ratings
  ↓
build_dashboard.py              → docs/index.html (served by GitHub Pages)
```

---

## Files

| File | Purpose |
|---|---|
| `synergy_functions.py` | Synergy API auth and request helpers |
| `do_auth.py` | One-time interactive login that saves a token |
| `scrape_*.py` | Data scrapers (see pipeline above) |
| `build_ratings.py` | Player OVR and team ratings from quality-filtered stats |
| `build_dashboard.py` | Builds the self-contained dashboard HTML |
| `teams_senior_2025.json` | Senior team list with tiers |
| `test_opponent_filter.py` | Checks Synergy's `opponentTeamIds` filtering |
