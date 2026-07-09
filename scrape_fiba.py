#!/usr/bin/env python3
"""
FIBA 3x3 Women's Synergy Scraper
Authenticates with Synergy and fetches team/player possession-report data
for FIBA National Teams Women.

Usage:
    python scrape_fiba.py --discover          # Find league/season/team IDs
    python scrape_fiba.py --team Canada       # Scrape Canada team stats
"""

import argparse, json, os, sys, pkce, requests
from pathlib import Path
from dotenv import load_dotenv

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR))
import synergy_functions as sf

load_dotenv(DIR / '.env')
USERNAME = os.getenv('SYNERGY_USERNAME')
PASSWORD = os.getenv('SYNERGY_PASSWORD')

BASE = 'https://basketball.synergysportstech.com/api'

def auth():
    session = requests.Session()
    cv = pkce.generate_code_verifier(length=128)
    cc = pkce.get_code_challenge(cv)
    print(f'Authenticating as {USERNAME}...')
    token_type, refresh_token, access_token = sf.get_access_token(session, cv, cc, USERNAME, PASSWORD)
    if not access_token:
        sys.exit('Authentication failed.')
    print('Auth OK')
    return session, token_type, access_token


def headers(token_type, access_token):
    return {
        'Authorization': f'{token_type} {access_token}',
        'Accept': 'application/json, text/plain, */*',
        'X-SYNERGY-CLIENT': 'ProductVersion=2026.02.25.10717; ProductName=Basketball.TeamSite',
        'Origin': 'https://apps.synergysports.com',
        'Referer': 'https://apps.synergysports.com/',
    }


def discover(session, token_type, access_token):
    h = headers(token_type, access_token)

    # ── Leagues ──────────────────────────────────────────────────────────────
    print('\n=== Leagues ===')
    r = session.get(f'{BASE}/leagues', headers=h, timeout=30)
    leagues = r.json() if r.status_code == 200 else []
    fiba_leagues = []
    for lg in (leagues if isinstance(leagues, list) else leagues.get('result', [])):
        name = lg.get('name', '')
        if 'fiba' in name.lower() or 'national' in name.lower() or 'women' in name.lower():
            fiba_leagues.append(lg)
            print(f"  {lg.get('id')}  {name}")
    if not fiba_leagues:
        print('  (none matched — printing first 10)')
        for lg in (leagues if isinstance(leagues, list) else leagues.get('result', []))[:10]:
            print(f"  {lg.get('id')}  {lg.get('name')}")

    # ── Seasons ──────────────────────────────────────────────────────────────
    print('\n=== Seasons (FIBA related) ===')
    r = session.get(f'{BASE}/seasons', headers=h, timeout=30)
    seasons = r.json() if r.status_code == 200 else []
    for s in (seasons if isinstance(seasons, list) else seasons.get('result', []))[:20]:
        name = s.get('name', '')
        if 'fiba' in name.lower() or '2025' in name or 'national' in name.lower() or 'women' in name.lower():
            print(f"  {s.get('id')}  {name}")

    # ── Teams search for Canada ───────────────────────────────────────────────
    print('\n=== Teams matching Canada ===')
    r = session.get(f'{BASE}/teams', params={'search': 'Canada', 'take': 20}, headers=h, timeout=30)
    teams = r.json() if r.status_code == 200 else []
    for t in (teams if isinstance(teams, list) else teams.get('result', []))[:20]:
        print(f"  {t.get('id')}  {t.get('name')}  league={t.get('leagueId')}")

    # Save raw discovery
    out = DIR / 'discovery.json'
    out.write_text(json.dumps({'leagues': leagues, 'seasons': seasons}, indent=2, default=str))
    print(f'\nSaved discovery → {out}')


def scrape_team(session, token_type, access_token, team_name, league_id, season_id, comp_key):
    h = headers(token_type, access_token)

    # Find team ID
    r = session.get(f'{BASE}/teams', params={'search': team_name, 'take': 20}, headers=h, timeout=30)
    teams = r.json() if r.status_code == 200 else []
    team_list = teams if isinstance(teams, list) else teams.get('result', [])

    # Filter to matching league if possible
    matched = [t for t in team_list if team_name.lower() in t.get('name', '').lower()]
    if not matched:
        print(f'No teams found for "{team_name}"')
        return

    for t in matched:
        print(f"  Candidate: {t.get('id')}  {t.get('name')}  leagueId={t.get('leagueId')}")

    team = matched[0]
    team_id = team['id']
    print(f'\nUsing team: {team["name"]}  id={team_id}')

    # ── Possession report — overall offense ──────────────────────────────────
    play_types = [
        ('Transition',          'play eq 418'),
        ('P&R Ball Handler',    'play eq 136'),
        ('Isolation',           'play eq 50'),
        ('Post-Up',             'play eq 259'),
        ('Spot Up',             'play eq 400'),
        ('Hand Off',            'play eq 11'),
        ('Cut',                 'play eq 3'),
        ('Offensive Rebounds',  'play eq 415'),
        ('Off Screen',          'play eq 85'),
        ('Miscellaneous',       'play eq 452'),
    ]

    results = {}
    for label, expr in play_types:
        full_expr = (
            f'season eq oid({season_id}) and '
            f'offensiveteam eq oid({team_id}) and '
            f'{expr} and play eq 1 '
            f'group offensiveteam'
        )
        print(f'  Fetching {label}...', end=' ', flush=True)
        try:
            data = sf.get_possession_reports(access_token, session, [full_expr])
            results[label] = data
            rows = len((data or {}).get('result', []))
            print(f'{rows} rows')
        except Exception as e:
            print(f'ERROR: {e}')
            results[label] = None

    out = DIR / f'{team_name.lower().replace(" ","_")}_synergy.json'
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f'\nSaved → {out}')
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--discover', action='store_true', help='Discover league/season/team IDs')
    parser.add_argument('--team', default=None, help='Team name to scrape (e.g. Canada)')
    parser.add_argument('--league-id', default=None, help='Synergy league ID')
    parser.add_argument('--season-id', default=None, help='Synergy season ID')
    parser.add_argument('--comp-key', default=None, help='Competition definition key')
    args = parser.parse_args()

    session, token_type, access_token = auth()

    if args.discover:
        discover(session, token_type, access_token)
    elif args.team:
        league_id  = args.league_id  or ''
        season_id  = args.season_id  or ''
        comp_key   = args.comp_key   or ''
        scrape_team(session, token_type, access_token, args.team, league_id, season_id, comp_key)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
