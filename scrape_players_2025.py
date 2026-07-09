#!/usr/bin/env python3
"""
FIBA 5x5 Women 2025 - Player Scraper
For each player on the 81 senior teams:
  - overall offense   (from team cumulative_box already scraped)
  - overall defense   (per-team possession report, grouped by defensiveplayer)
  - play type offense (leaderboard reportType=0, all 11 play types)

Note: player-level defense by play type is not logged by Synergy for FIBA.

Data saved to data/2025/players/{player_id}.json
Index saved to data/2025/players_index.json
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
SEASON_ID = '684205c6d01c0c93c586dbf2'   # 2025
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


# ── Auth ──────────────────────────────────────────────────────────────────────

def auth():
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


def make_headers(token_type, access_token):
    return {
        'Authorization': f'{token_type} {access_token}',
        'Accept': 'application/json, text/plain, */*',
        'X-SYNERGY-CLIENT': 'ProductVersion=2026.02.25.10717; ProductName=Basketball.TeamSite',
        'Origin': 'https://apps.synergysports.com',
        'Referer': 'https://apps.synergysports.com/',
    }


# ── API helpers ───────────────────────────────────────────────────────────────

def get_leaderboard_players(session, h, play_type, report_type=0):
    """Fetch all player records for a play type from the leaderboard."""
    r = session.get(BASE + '/leaderboards/recordswithsparseranks',
        params={
            'leagueId': LEAGUE_ID, 'seasonId': SEASON_ID,
            'playType': play_type, 'reportType': report_type,
            'competitionDefinitionKey': COMP_KEY,
            'competitionType': 4, 'rankingType': 4,
            'perGame': 'false', 'minPossessions': 0,
            'minPossessionsPerGame': 'false', 'ascending': 'false',
            'skip': 0, 'take': 4096,
        },
        headers=h, timeout=30)
    return r.json().get('result', [])


def get_poss_report(session, h, expression):
    r = session.post(BASE + '/possessionreports',
        headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
        json={'expressions': [expression],
              'includePartiallyLoggedGames': False,
              'includePlayByPlayStats': False},
        timeout=30)
    data = r.json()
    return data if isinstance(data, list) else []


# ── Data extraction ───────────────────────────────────────────────────────────

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
    """Inject pppRank and possRank across all players for a given play type slice."""
    items = [(pid, d) for pid, d in records_by_pid.items() if d.get('possessions', 0) > 0]

    def safe_ppp(d):
        p = d.get('possessions', 0)
        return d.get('pointMade', 0) / p if p else 0

    sorted_ppp  = sorted(items, key=lambda x: safe_ppp(x[1]),              reverse=True)
    sorted_poss = sorted(items, key=lambda x: x[1].get('possessions', 0),  reverse=True)

    ppp_ranks  = {pid: i + 1 for i, (pid, _) in enumerate(sorted_ppp)}
    poss_ranks = {pid: i + 1 for i, (pid, _) in enumerate(sorted_poss)}

    for pid, d in records_by_pid.items():
        d['pppRank']  = ppp_ranks.get(pid)
        d['possRank'] = poss_ranks.get(pid)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session, token_type, access_token = auth()
    h = make_headers(token_type, access_token)

    teams_dir  = DIR / 'data' / '2025' / 'teams'
    player_dir = DIR / 'data' / '2025' / 'players'
    player_dir.mkdir(parents=True, exist_ok=True)

    # ── Load team files → build player roster from cumulative_box ────────────
    print('\nLoading team files...')
    team_ids    = set()
    all_teams   = []    # [{id, name, gp}]
    # player_id → {player info, team info, overall offense}
    player_off  = {}

    for f in sorted(teams_dir.glob('*.json')):
        data = json.loads(f.read_text())
        team = data['team']
        team_ids.add(team['id'])
        all_teams.append(team)

        for p in data.get('cumulative_box', {}).get('players', []):
            pid = p.get('player', {}).get('id')
            if not pid:
                continue
            stats = {k: v for k, v in p.items() if k != 'player'}
            player_off[pid] = {
                'player': p['player'],
                'team':   team,
                'gp':     p.get('gp', team.get('gp', 0)),
                'overall_offense': stats,
            }

    total_players = len(player_off)
    print(f'  {len(all_teams)} teams, {total_players} players found')

    # ── Phase 1: Player play-type leaderboard (offense, 11 calls) ────────────
    print(f'\n=== Phase 1: Player play type leaderboard (offense) ===')
    # pt_lb[player_id][pt_name] = stats dict
    pt_lb = {pid: {} for pid in player_off}

    for pt_name, pt_id in PLAY_TYPES:
        print(f'  {pt_name:<25}', end=' ', flush=True)
        records = get_leaderboard_players(session, h, pt_id, report_type=0)

        by_pid = {}
        for rec in records:
            pr   = rec.get('possessionReport', {})
            tid  = pr.get('team', {}).get('id', '')
            pid  = pr.get('player', {}).get('id', '')
            if tid not in team_ids or not pid:
                continue
            by_pid[pid] = extract_pr(pr)

        assign_ranks(by_pid)

        for pid, d in by_pid.items():
            if pid in pt_lb:
                pt_lb[pid][pt_name] = d

        matched = sum(1 for pid in by_pid if pid in player_off)
        print(f'{len(records)} total  →  {matched} senior team players')
        time.sleep(0.15)

    # ── Phase 2: Per-team player defense overall (81 calls) ───────────────────
    print(f'\n=== Phase 2: Player defense overall (81 team calls) ===')
    # player_id → defense stats dict
    player_def = {}

    for i, team in enumerate(sorted(all_teams, key=lambda x: x['name']), 1):
        tid   = team['id']
        tname = team['name']
        print(f'  [{i:>2}/81] {tname:<35}', end=' ', flush=True)

        rows = get_poss_report(session, h,
            f'season eq oid({SEASON_ID}) and defensiveteam eq oid({tid})'
            f' and play eq 1 group defensiveteam, defensiveplayer')

        count = 0
        for row in rows:
            pid = row.get('player', {}).get('id', '')
            if pid:
                player_def[pid] = extract_pr(row)
                count += 1

        print(f'{count} players')
        time.sleep(0.2)

    # ── Save player files ─────────────────────────────────────────────────────
    print(f'\nSaving {total_players} player files...')
    index = []

    for pid, base_data in player_off.items():
        record = {
            'player': base_data['player'],
            'team':   base_data['team'],
            'gp':     base_data['gp'],
            'overall': {
                'offense': base_data['overall_offense'],
                'defense': player_def.get(pid, {}),
            },
            'play_types': {
                'offense': pt_lb.get(pid, {}),
            },
        }
        (player_dir / f'{pid}.json').write_text(json.dumps(record, indent=2))
        index.append({
            'name':    base_data['player']['name'],
            'id':      pid,
            'team':    base_data['team']['name'],
            'team_id': base_data['team']['id'],
            'gp':      base_data['gp'],
        })

    index.sort(key=lambda x: (x['team'], x['name']))
    (DIR / 'data' / '2025' / 'players_index.json').write_text(json.dumps({
        'league_id': LEAGUE_ID, 'season_id': SEASON_ID, 'season': '2025',
        'total': len(index),
        'players': index,
    }, indent=2))

    print(f'Done. {len(index)} player files saved to {player_dir}')
    print(f'Index: data/2025/players_index.json')


if __name__ == '__main__':
    main()
