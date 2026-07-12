#!/usr/bin/env python3
"""
Scrape team and player stats filtered to games vs T1/T2 opponents only.

Approach:
  1. Fetch full game schedule from /api/games to know who played who
  2. Identify "quality" matchups (defensive team is Tier 1 or 2)
  3. For each (offensive_team, quality_opponent) pair, call possessionreports
  4. Sum the results per team / per player across all their quality games

Outputs:
  data/2025/team_vs_quality.json   {team_id: {off: stats, def: stats, gp: int}}
  data/2025/player_vs_quality.json {player_id: {off: stats, team_id: str}}
"""

import pkce, requests, json, os, sys, time
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
import openpyxl

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR))
import synergy_functions as sf

load_dotenv(DIR / '.env')

BASE      = 'https://basketball.synergysportstech.com/api'
LEAGUE_ID = '54457dce300969b132fcfb41'
SEASON_ID = '684205c6d01c0c93c586dbf2'

TEAM_OUT   = DIR / 'data' / '2025' / 'team_vs_quality.json'
PLAYER_OUT = DIR / 'data' / '2025' / 'player_vs_quality.json'

ZERO_PR = {k: 0 for k in [
    'possessions','gp','pointMade','fgAttempt','fgMade',
    'shot2Attempt','shot2Made','shot2Miss','shot3Attempt','shot3Made','shot3Miss',
    'shotAttempt','shotMade','shotMiss','turnover',
    'ftAttempt','ftMade','ftTimes','ftmiss','score','plusOne','shotFoul',
    'shotQualityTotal','shotQualityAttempt',
    'lowShotQualityAttempt','highShotQualityAttempt',
    'lowShotQualityMade','lowShotQualityMiss','highShotQualityMade','highShotQualityMiss',
]}


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


def make_headers(token_type, access_token):
    return {
        'Authorization': f'{token_type} {access_token}',
        'Accept': 'application/json, text/plain, */*',
        'X-SYNERGY-CLIENT': 'ProductVersion=2026.02.25.10717; ProductName=Basketball.TeamSite',
        'Origin': 'https://apps.synergysports.com',
        'Referer': 'https://apps.synergysports.com/',
    }


def extract_pr(row):
    return {k: (row.get(k) or 0) for k in ZERO_PR}


def sum_pr(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in ZERO_PR}


def poss_report(session, h, expression, timeout=30):
    try:
        r = session.post(BASE + '/possessionreports',
            headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
            json={'expressions': [expression],
                  'includePartiallyLoggedGames': False,
                  'includePlayByPlayStats': False},
            timeout=timeout)
        if r.status_code == 401:
            return None, 'auth'
        data = r.json()
        return (data if isinstance(data, list) else []), None
    except Exception as e:
        return [], str(e)


def fetch_games(session, h):
    """Fetch complete game schedule from Synergy."""
    print('Fetching game schedule...')
    all_games = []
    skip = 0
    while True:
        r = session.post(BASE + '/games',
            headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
            json={'leagueIds': [LEAGUE_ID], 'seasonIds': [SEASON_ID],
                  'skip': skip, 'take': 500},
            timeout=60)
        data = r.json()
        games = data.get('result', data) if isinstance(data, dict) else data
        if not games or not isinstance(games, list):
            break
        all_games.extend(games)
        if len(games) < 500:
            break
        skip += 500
    print(f'  {len(all_games)} total games in competition')
    return all_games


def build_schedule(games, our_team_ids):
    """Build {team_id: set(opponent_ids)} for matchups within our 81 teams only."""
    schedule = defaultdict(set)
    for g in games:
        home = g.get('homeTeam', {}) or {}
        away = g.get('awayTeam', {}) or {}
        hid, aid = home.get('id'), away.get('id')
        if hid in our_team_ids and aid in our_team_ids:
            schedule[hid].add(aid)
            schedule[aid].add(hid)
    return schedule


def main():
    # ── Load team info + tiers ────────────────────────────────────────────────
    print('Loading team data...')
    teams_dir = DIR / 'data' / '2025' / 'teams'
    our_teams  = {}  # id -> name
    for f in teams_dir.glob('*.json'):
        d = json.loads(f.read_text())
        our_teams[d['team']['id']] = d['team']['name']

    wb = openpyxl.load_workbook('/Users/jordanngo/Downloads/fiba 5x5 teams.xlsx')
    tiers = {row[0]: row[1] for row in wb.active.iter_rows(min_row=2, values_only=True) if row[0]}

    quality_ids = {tid for tid, name in our_teams.items() if tiers.get(name, 3) <= 2}
    print(f'  {len(our_teams)} teams  |  {len(quality_ids)} T1+T2 teams')

    # ── Auth ──────────────────────────────────────────────────────────────────
    session, token_type, access_token = fresh_auth()
    h = make_headers(token_type, access_token)

    # ── Build schedule ────────────────────────────────────────────────────────
    games = fetch_games(session, h)
    schedule = build_schedule(games, set(our_teams.keys()))

    # For each team: which quality opponents did they actually play?
    quality_matchups = {}  # tid -> [opp_id, ...]
    for tid in our_teams:
        opps = sorted(schedule.get(tid, set()) & quality_ids - {tid})
        quality_matchups[tid] = opps

    total_pairs = sum(len(v) for v in quality_matchups.values())
    print(f'\nQuality matchup pairs (offense): {total_pairs}')
    print(f'Same for defense:                {total_pairs}')
    print(f'Player offense calls:            {total_pairs}')
    print(f'Total API calls estimate:        ~{total_pairs * 3}')

    # ── Phase 1: Team offense + defense vs quality opponents ─────────────────
    print(f'\n=== Phase 1: Team stats vs quality opponents ===')
    team_off = {tid: dict(ZERO_PR) for tid in our_teams}
    team_def = {tid: dict(ZERO_PR) for tid in our_teams}
    team_gp  = defaultdict(set)  # tid -> set of unique opponent games

    n_done = 0
    n_total = total_pairs * 2
    for tid, name in sorted(our_teams.items(), key=lambda x: x[1]):
        opps = quality_matchups[tid]
        if not opps:
            continue
        for opp_id in opps:
            opp_name = our_teams.get(opp_id, opp_id[:8])

            # Offense
            rows, err = poss_report(session, h,
                f'season eq oid({SEASON_ID}) and offensiveteam eq oid({tid}) and defensiveteam eq oid({opp_id}) and play eq 1 group offensiveteam')
            if err == 'auth':
                print('\nToken expired — re-run the script')
                sys.exit(1)
            if rows:
                team_off[tid] = sum_pr(team_off[tid], extract_pr(rows[0]))
                team_gp[tid].add(opp_id)
            n_done += 1
            time.sleep(0.15)

            # Defense
            rows, err = poss_report(session, h,
                f'season eq oid({SEASON_ID}) and defensiveteam eq oid({tid}) and offensiveteam eq oid({opp_id}) and play eq 1 group defensiveteam')
            if err == 'auth':
                print('\nToken expired — re-run the script')
                sys.exit(1)
            if rows:
                team_def[tid] = sum_pr(team_def[tid], extract_pr(rows[0]))
            n_done += 1
            time.sleep(0.15)

            if n_done % 20 == 0:
                print(f'  [{n_done}/{n_total}] {name} vs {opp_name}...')

    # ── Phase 2: Player offense vs quality opponents ──────────────────────────
    print(f'\n=== Phase 2: Player offense vs quality opponents ===')
    player_off = defaultdict(lambda: dict(ZERO_PR))
    player_meta = {}  # pid -> {name, team_id, team_name}
    n_done = 0

    for tid, name in sorted(our_teams.items(), key=lambda x: x[1]):
        opps = quality_matchups[tid]
        if not opps:
            continue
        for opp_id in opps:
            rows, err = poss_report(session, h,
                f'season eq oid({SEASON_ID}) and offensiveteam eq oid({tid}) and defensiveteam eq oid({opp_id}) and play eq 1 group offensiveplayer, offensiveteam')
            if err == 'auth':
                print('\nToken expired — re-run the script')
                sys.exit(1)
            for row in (rows or []):
                p = row.get('player', {}) or {}
                pid = p.get('id', '')
                if not pid:
                    continue
                player_off[pid] = sum_pr(player_off[pid], extract_pr(row))
                if pid not in player_meta:
                    player_meta[pid] = {
                        'name': p.get('name', ''),
                        'team_id': tid,
                        'team_name': name,
                    }
            n_done += 1
            time.sleep(0.15)

        if n_done % 10 == 0:
            print(f'  [{n_done}/{total_pairs}] {name}...')

    # ── Save ──────────────────────────────────────────────────────────────────
    team_out = {}
    for tid in our_teams:
        team_out[tid] = {
            'off': team_off[tid],
            'def': team_def[tid],
            'gp_quality': len(team_gp[tid]),
        }
    TEAM_OUT.write_text(json.dumps(team_out, indent=2))
    print(f'\nSaved team vs quality → {TEAM_OUT}')

    player_out = {}
    for pid, stats in player_off.items():
        player_out[pid] = {'off': stats, **player_meta.get(pid, {})}
    PLAYER_OUT.write_text(json.dumps(player_out, indent=2))
    print(f'Saved player vs quality → {PLAYER_OUT}  ({len(player_out)} players)')

    # Quick sanity check
    usa_id = '54457df7300969b132fd104f'
    if usa_id in team_out:
        u = team_out[usa_id]
        off_poss = u['off'].get('possessions', 0)
        off_pts  = u['off'].get('pointMade', 0)
        print(f'\nUSA sanity: {u["gp_quality"]} quality games, {off_poss} off poss, {off_pts/off_poss:.3f} PPP' if off_poss else '\nUSA: no quality poss')

    print('\nNext: python3 build_dashboard.py')


if __name__ == '__main__':
    main()
