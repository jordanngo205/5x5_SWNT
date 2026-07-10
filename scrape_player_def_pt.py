#!/usr/bin/env python3
"""
Scrape player defensive play types (reportType=1) for all 11 play types.
Saves to data/2025/player_def_pt.json — a single file, no per-player file reads.
build_dashboard.py merges this at build time.
"""

import pkce, requests, json, os, sys, time
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

PLAY_TYPES = [
    ('Transition',           1),
    ('Spot Up',             50),
    ('P&R Ball Handler',    11),
    ('Miscellaneous Plays', 124),
    ('Cut',                 81),
    ('Offensive Rebounds',  89),
    ('Isolation',           10),
    ('Post-Up',             15),
    ('Off Screen',          67),
    ('P&R Roll Man',        31),
    ('Handoffs',            78),
]

OUT_FILE = DIR / 'data' / '2025' / 'player_def_pt.json'


def fresh_auth():
    session = requests.Session()
    cv = pkce.generate_code_verifier(length=128)
    cc = pkce.get_code_challenge(cv)
    token_type, _, access_token = sf.get_access_token(
        session, cv, cc,
        os.getenv('SYNERGY_USERNAME'), os.getenv('SYNERGY_PASSWORD'))
    if not access_token:
        sys.exit('Auth failed')
    (DIR / '.synergy_token').write_text(json.dumps(
        {'token_type': token_type, 'access_token': access_token}))
    print('Auth OK')
    return session, token_type, access_token


def make_headers(token_type, access_token):
    return {
        'Authorization': f'{token_type} {access_token}',
        'Accept': 'application/json, text/plain, */*',
        'X-SYNERGY-CLIENT': 'ProductVersion=2026.02.25.10717; ProductName=Basketball.TeamSite',
        'Origin': 'https://apps.synergysports.com',
        'Referer': 'https://apps.synergysports.com/',
    }


def extract_pr(pr):
    return {
        'possessions':            pr.get('possessions', 0),
        'gp':                     pr.get('gp', 0),
        'pointMade':              pr.get('pointMade', 0),
        'fgAttempt':              pr.get('fgAttempt', 0),
        'fgMade':                 pr.get('fgMade', 0),
        'shot2Attempt':           pr.get('shot2Attempt', 0),
        'shot2Made':              pr.get('shot2Made', 0),
        'shot2Miss':              pr.get('shot2Miss', 0),
        'shot3Attempt':           pr.get('shot3Attempt', 0),
        'shot3Made':              pr.get('shot3Made', 0),
        'shot3Miss':              pr.get('shot3Miss', 0),
        'shotAttempt':            pr.get('shotAttempt', 0),
        'shotMade':               pr.get('shotMade', 0),
        'shotMiss':               pr.get('shotMiss', 0),
        'turnover':               pr.get('turnover', 0),
        'ftAttempt':              pr.get('ftAttempt', 0),
        'ftMade':                 pr.get('ftMade', 0),
        'ftTimes':                pr.get('ftTimes', 0),
        'ftmiss':                 pr.get('ftmiss', 0),
        'score':                  pr.get('score', 0),
        'plusOne':                pr.get('plusOne', 0),
        'shotFoul':               pr.get('shotFoul', 0),
        'shotQualityTotal':       pr.get('shotQualityTotal', 0),
        'shotQualityAttempt':     pr.get('shotQualityAttempt', 0),
        'lowShotQualityAttempt':  pr.get('lowShotQualityAttempt', 0),
        'highShotQualityAttempt': pr.get('highShotQualityAttempt', 0),
        'lowShotQualityMade':     pr.get('lowShotQualityMade', 0),
        'lowShotQualityMiss':     pr.get('lowShotQualityMiss', 0),
        'highShotQualityMade':    pr.get('highShotQualityMade', 0),
        'highShotQualityMiss':    pr.get('highShotQualityMiss', 0),
    }


def assign_ranks(records_by_pid):
    """Rank defenders: rank 1 = lowest PPP allowed (best defender)."""
    items = [(pid, d) for pid, d in records_by_pid.items() if d.get('possessions', 0) > 0]

    def safe_ppp(d):
        p = d.get('possessions', 0)
        return d.get('pointMade', 0) / p if p else 999

    sorted_ppp  = sorted(items, key=lambda x: safe_ppp(x[1]))
    sorted_poss = sorted(items, key=lambda x: x[1].get('possessions', 0), reverse=True)
    ppp_ranks  = {pid: i + 1 for i, (pid, _) in enumerate(sorted_ppp)}
    poss_ranks = {pid: i + 1 for i, (pid, _) in enumerate(sorted_poss)}
    for pid, d in records_by_pid.items():
        d['pppRank']  = ppp_ranks.get(pid)
        d['possRank'] = poss_ranks.get(pid)


def main():
    teams_dir = DIR / 'data' / '2025' / 'teams'

    # Get team IDs from team files only (81 files, fast)
    print('Loading team IDs from team files...')
    team_ids = set()
    for f in teams_dir.glob('*.json'):
        data = json.loads(f.read_text())
        team_ids.add(data['team']['id'])
    print(f'  {len(team_ids)} teams')

    # Auth right before API calls
    session, token_type, access_token = fresh_auth()
    h = make_headers(token_type, access_token)

    # pid → {play_type_name → stats}
    pt_def = {}

    print(f'\n=== Scraping player defensive play types (reportType=1) ===')
    for pt_name, pt_id in PLAY_TYPES:
        print(f'  {pt_name:<25}', end=' ', flush=True)
        r = session.get(BASE + '/leaderboards/recordswithsparseranks',
            params={
                'leagueId': LEAGUE_ID, 'seasonId': SEASON_ID,
                'playType': pt_id, 'reportType': 1,
                'competitionDefinitionKey': COMP_KEY,
                'competitionType': 4, 'rankingType': 4,
                'perGame': 'false', 'minPossessions': 0,
                'minPossessionsPerGame': 'false', 'ascending': 'false',
                'skip': 0, 'take': 4096,
            },
            headers=h, timeout=30)

        if r.status_code == 401:
            print('ERROR 401 — token expired, re-run the script')
            sys.exit(1)

        records = r.json().get('result', [])

        by_pid = {}
        for rec in records:
            pr  = rec.get('possessionReport', {})
            tid = pr.get('team', {}).get('id', '')
            pid = pr.get('player', {}).get('id', '')
            if tid not in team_ids or not pid:
                continue
            by_pid[pid] = extract_pr(pr)

        assign_ranks(by_pid)

        for pid, d in by_pid.items():
            if pid not in pt_def:
                pt_def[pid] = {}
            pt_def[pid][pt_name] = d

        matched = sum(1 for pid in by_pid if pid in by_pid)
        print(f'{len(records)} total  →  {len(by_pid)} senior team players')
        time.sleep(0.15)

    # Save as a single file — no per-player reads/writes needed
    OUT_FILE.write_text(json.dumps(pt_def, indent=2))
    print(f'\nSaved {len(pt_def)} players\' defensive play types to {OUT_FILE}')
    print('\nNext: python3 build_dashboard.py && git add data/ docs/ && git commit -m "data: add player defensive play types" && git push')


if __name__ == '__main__':
    main()
