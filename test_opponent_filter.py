#!/usr/bin/env python3
"""
Test whether Synergy API accepts opponentTeamIds filtering.
Tries two approaches:
  A) leaderboard endpoint with opponentTeamIds query param
  B) possessionreports endpoint with opponentTeamIds in body

Run this after fresh auth (python3 do_auth.py first if needed).
"""

import pkce, requests, json, os, sys
from pathlib import Path
from dotenv import load_dotenv

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR))
import synergy_functions as sf

load_dotenv(DIR / '.env')

BASE      = 'https://basketball.synergysportstech.com/api'
LEAGUE_ID = '54457dce300969b132fcfb41'
SEASON_ID = '684205c6d01c0c93c586dbf2'
COMP_KEY  = f'{LEAGUE_ID}:ALL'

# USA and Brazil IDs (from user's example URL)
USA_ID    = '54457df7300969b132fd104f'
BRAZIL_ID = '54457df8300969b132fd109e'

def fresh_auth():
    session = requests.Session()
    cv = pkce.generate_code_verifier(length=128)
    cc = pkce.get_code_challenge(cv)
    token_type, _, access_token = sf.get_access_token(
        session, cv, cc,
        os.getenv('SYNERGY_USERNAME'), os.getenv('SYNERGY_PASSWORD'))
    if not access_token:
        sys.exit('Auth failed')
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

def main():
    session, token_type, access_token = fresh_auth()
    h = headers(token_type, access_token)

    # ── Baseline: USA overall offense (no opponent filter) ────────────────────
    print('\n── Baseline: USA overall offense (all opponents) ──')
    r = session.post(BASE + '/possessionreports',
        headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
        json={
            'expressions': [f'season eq oid({SEASON_ID}) and offensiveteam eq oid({USA_ID}) and play eq 1 group offensiveteam'],
            'includePartiallyLoggedGames': False,
            'includePlayByPlayStats': False,
        }, timeout=30)
    data = r.json()
    baseline_poss = data[0].get('possessions', 0) if data else 0
    print(f'  Status: {r.status_code}  Possessions: {baseline_poss}  GP: {data[0].get("gp","?") if data else "?"}')

    # ── Test A: possessionreports with opponentTeamIds in body ───────────────
    print('\n── Test A: possessionreports + opponentTeamIds body param ──')
    r = session.post(BASE + '/possessionreports',
        headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
        json={
            'expressions': [f'season eq oid({SEASON_ID}) and offensiveteam eq oid({USA_ID}) and play eq 1 group offensiveteam'],
            'includePartiallyLoggedGames': False,
            'includePlayByPlayStats': False,
            'opponentTeamIds': [BRAZIL_ID],
        }, timeout=30)
    data = r.json()
    poss_a = data[0].get('possessions', 0) if isinstance(data, list) and data else 0
    print(f'  Status: {r.status_code}  Possessions: {poss_a}  (expect < {baseline_poss})')
    if isinstance(data, dict):
        print(f'  Response (dict): {json.dumps(data)[:200]}')

    # ── Test B: leaderboard with opponentTeamIds query param ─────────────────
    print('\n── Test B: leaderboard + opponentTeamIds query param (P&R BH, reportType=2) ──')
    r = session.get(BASE + '/leaderboards/recordswithsparseranks',
        params={
            'leagueId': LEAGUE_ID, 'seasonId': SEASON_ID,
            'playType': 11,  # P&R Ball Handler
            'reportType': 2, # Team Offensive
            'competitionDefinitionKey': COMP_KEY,
            'competitionType': 4, 'rankingType': 4,
            'perGame': 'false', 'minPossessions': 0,
            'minPossessionsPerGame': 'false', 'ascending': 'false',
            'skip': 0, 'take': 300,
            'opponentTeamIds': BRAZIL_ID,
        }, headers=h, timeout=30)
    data = r.json()
    results = data.get('result', [])
    usa_rec = next((r for r in results if r.get('possessionReport',{}).get('team',{}).get('id') == USA_ID), None)
    print(f'  Status: {r.status_code}  Total records: {len(results)}')
    if usa_rec:
        pr = usa_rec['possessionReport']
        print(f'  USA P&R BH possessions: {pr.get("possessions","?")}')
    else:
        print(f'  USA not found in results (may have 0 poss vs Brazil in P&R BH)')

    # ── Test C: expression with defensiveteam filter ──────────────────────────
    print('\n── Test C: possessionreports expression with defensiveteam clause ──')
    r = session.post(BASE + '/possessionreports',
        headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
        json={
            'expressions': [f'season eq oid({SEASON_ID}) and offensiveteam eq oid({USA_ID}) and defensiveteam eq oid({BRAZIL_ID}) and play eq 1 group offensiveteam'],
            'includePartiallyLoggedGames': False,
            'includePlayByPlayStats': False,
        }, timeout=30)
    data = r.json()
    poss_c = data[0].get('possessions', 0) if isinstance(data, list) and data else 0
    gp_c   = data[0].get('gp', 0) if isinstance(data, list) and data else 0
    print(f'  Status: {r.status_code}  Possessions: {poss_c}  GP: {gp_c}')

    # ── Test D: multiple defensiveteam OR via multiple expressions ────────────
    print('\n── Test D: two expressions in one request (USA vs Brazil + USA vs France) ──')
    # France ID (let's use a known T1 team)
    import os as _os
    teams_dir = DIR / 'data' / '2025' / 'teams'
    team_names = {}
    for f in teams_dir.glob('*.json'):
        d = json.loads(f.read_text())
        team_names[d['team']['name']] = d['team']['id']
    france_id = team_names.get('France', '')
    if france_id:
        r = session.post(BASE + '/possessionreports',
            headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
            json={
                'expressions': [
                    f'season eq oid({SEASON_ID}) and offensiveteam eq oid({USA_ID}) and defensiveteam eq oid({BRAZIL_ID}) and play eq 1 group offensiveteam',
                    f'season eq oid({SEASON_ID}) and offensiveteam eq oid({USA_ID}) and defensiveteam eq oid({france_id}) and play eq 1 group offensiveteam',
                ],
                'includePartiallyLoggedGames': False,
                'includePlayByPlayStats': False,
            }, timeout=30)
        data = r.json()
        print(f'  Status: {r.status_code}  Records returned: {len(data) if isinstance(data, list) else "N/A (dict)"}')
        if isinstance(data, list):
            for row in data:
                print(f'    possessions={row.get("possessions","?")} gp={row.get("gp","?")}')

    print('\n── Summary ──')
    print(f'Baseline (all opponents):  {baseline_poss} poss')
    print(f'Test A (body param):       {poss_a} poss  {"✓ WORKS - fewer than baseline" if 0 < poss_a < baseline_poss else "✗ same as baseline or 0"}')
    print(f'Test C (expression):       {poss_c} poss, {gp_c} GP  {"✓ WORKS" if poss_c > 0 else "✗ empty"}')

if __name__ == '__main__':
    main()
