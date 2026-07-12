#!/usr/bin/env python3
"""
Scrape team and player PLAY TYPE stats vs T1/T2 opponents only.

Uses possessionreports with compound expressions:
  offensiveteam eq oid(A) and defensiveteam eq oid(B) and play eq [expr_id] group offensiveteam

Outputs:
  data/2025/team_pt_vs_quality.json   {tid: {off: {pt_name: stats}, def: {pt_name: stats}}}
  data/2025/player_pt_vs_quality.json {pid: {pt_name: stats, team_id: str}}
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

TEAM_PT_OUT   = DIR / 'data' / '2025' / 'team_pt_vs_quality.json'
PLAYER_PT_OUT = DIR / 'data' / '2025' / 'player_pt_vs_quality.json'

# Confirmed by cross-referencing leaderboard poss against expression results
PLAY_TYPES = [
    ('Transition',          418),
    ('Spot Up',             400),
    ('P&R Ball Handler',    136),
    ('Miscellaneous Plays', 452),
    ('Cut',                   3),
    ('Offensive Rebounds',  415),
    ('Isolation',            50),
    ('Post-Up',             259),
    ('Off Screen',           85),
    ('P&R Roll Man',        235),
    ('Handoffs',             11),
]

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


def poss_report(session, h, expression):
    try:
        r = session.post(BASE + '/possessionreports',
            headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
            json={'expressions': [expression],
                  'includePartiallyLoggedGames': False,
                  'includePlayByPlayStats': False},
            timeout=30)
        if r.status_code == 401:
            return None, 'auth'
        data = r.json()
        return (data if isinstance(data, list) else []), None
    except Exception as e:
        return [], str(e)


def fetch_games(session, h):
    all_games = []
    skip = 0
    while True:
        r = session.post(BASE + '/games',
            headers={**h, 'Content-Type': 'application/json; charset=utf-8'},
            json={'leagueIds': [LEAGUE_ID], 'seasonIds': [SEASON_ID], 'skip': skip, 'take': 500},
            timeout=60)
        data = r.json()
        games = data.get('result', data) if isinstance(data, dict) else data
        if not games or not isinstance(games, list): break
        all_games.extend(games)
        if len(games) < 500: break
        skip += 500
    return all_games


def build_quality_pairs(games, our_team_ids, quality_ids):
    """Return list of (off_team_id, def_team_id) quality matchup pairs."""
    pairs = set()
    for g in games:
        home = g.get('homeTeam', {}) or {}
        away = g.get('awayTeam', {}) or {}
        hid, aid = home.get('id'), away.get('id')
        if not hid or not aid: continue
        if hid not in our_team_ids or aid not in our_team_ids: continue
        # Add both offensive directions for each game
        if aid in quality_ids:   # home offense vs quality (away) defense
            pairs.add((hid, aid))
        if hid in quality_ids:   # away offense vs quality (home) defense
            pairs.add((aid, hid))
    return sorted(pairs)


def main():
    # ── Load team info + tiers ────────────────────────────────────────────────
    print('Loading team data...')
    teams_dir = DIR / 'data' / '2025' / 'teams'
    our_teams = {}
    for f in teams_dir.glob('*.json'):
        d = json.loads(f.read_text())
        our_teams[d['team']['id']] = d['team']['name']

    wb = openpyxl.load_workbook('/Users/jordanngo/Downloads/fiba 5x5 teams.xlsx')
    tiers = {row[0]: row[1] for row in wb.active.iter_rows(min_row=2, values_only=True) if row[0]}
    quality_ids = {tid for tid, name in our_teams.items() if tiers.get(name, 3) <= 2}
    print(f'  {len(our_teams)} teams  |  {len(quality_ids)} T1+T2 quality teams')

    # ── Auth ──────────────────────────────────────────────────────────────────
    session, token_type, access_token = fresh_auth()
    h = make_headers(token_type, access_token)

    # ── Build quality pairs ───────────────────────────────────────────────────
    print('Fetching game schedule...')
    games = fetch_games(session, h)
    pairs = build_quality_pairs(games, set(our_teams.keys()), quality_ids)
    print(f'  {len(pairs)} quality (off_team, quality_opp) pairs')

    n_pt = len(PLAY_TYPES)
    total_calls = len(pairs) * n_pt * 2  # ×2 for players
    print(f'  Team calls:   {len(pairs) * n_pt * 2} ({n_pt} PT × {len(pairs)} pairs × 2 sides)')
    print(f'  Player calls: {len(pairs) * n_pt} ({n_pt} PT × {len(pairs)} pairs, offense only)')
    print(f'  Total:        ~{total_calls + len(pairs) * n_pt}  (~{(total_calls + len(pairs)*n_pt)*0.17/60:.0f} min)')

    # ── Phase 1: Team play type offense + defense ─────────────────────────────
    print(f'\n=== Phase 1: Team play types vs quality opponents ===')
    team_pt_off = {tid: {pt: dict(ZERO_PR) for pt, _ in PLAY_TYPES} for tid in our_teams}
    team_pt_def = {tid: {pt: dict(ZERO_PR) for pt, _ in PLAY_TYPES} for tid in our_teams}

    done = 0
    total_t = len(pairs) * n_pt * 2
    for off_tid, def_tid in pairs:
        off_name = our_teams.get(off_tid, '?')
        def_name = our_teams.get(def_tid, '?')
        for pt_name, expr_id in PLAY_TYPES:
            # Offense
            rows, err = poss_report(session, h,
                f'season eq oid({SEASON_ID}) and offensiveteam eq oid({off_tid}) and defensiveteam eq oid({def_tid}) and play eq {expr_id} group offensiveteam')
            if err == 'auth': print('\nToken expired'); sys.exit(1)
            if rows:
                team_pt_off[off_tid][pt_name] = sum_pr(team_pt_off[off_tid][pt_name], extract_pr(rows[0]))
            done += 1
            time.sleep(0.15)

            # Defense (flip: off=def_tid, def=off_tid)
            rows, err = poss_report(session, h,
                f'season eq oid({SEASON_ID}) and offensiveteam eq oid({def_tid}) and defensiveteam eq oid({off_tid}) and play eq {expr_id} group defensiveteam')
            if err == 'auth': print('\nToken expired'); sys.exit(1)
            if rows:
                team_pt_def[off_tid][pt_name] = sum_pr(team_pt_def[off_tid][pt_name], extract_pr(rows[0]))
            done += 1
            time.sleep(0.15)

            if done % 100 == 0:
                pct = done / total_t * 100
                print(f'  [{done}/{total_t}  {pct:.0f}%]  {off_name} vs {def_name} — {pt_name}')

    print(f'Team play types done.')

    # ── Phase 2: Player play type offense ─────────────────────────────────────
    print(f'\n=== Phase 2: Player play types vs quality opponents (offense) ===')
    player_pt_off = defaultdict(lambda: {pt: dict(ZERO_PR) for pt, _ in PLAY_TYPES})
    player_meta   = {}  # pid -> {name, team_id, team_name}

    done = 0
    total_p = len(pairs) * n_pt
    for off_tid, def_tid in pairs:
        off_name = our_teams.get(off_tid, '?')
        for pt_name, expr_id in PLAY_TYPES:
            rows, err = poss_report(session, h,
                f'season eq oid({SEASON_ID}) and offensiveteam eq oid({off_tid}) and defensiveteam eq oid({def_tid}) and play eq {expr_id} group offensiveplayer, offensiveteam')
            if err == 'auth': print('\nToken expired'); sys.exit(1)
            for row in (rows or []):
                p   = row.get('player', {}) or {}
                pid = p.get('id', '')
                if not pid: continue
                player_pt_off[pid][pt_name] = sum_pr(player_pt_off[pid][pt_name], extract_pr(row))
                if pid not in player_meta:
                    player_meta[pid] = {'name': p.get('name',''), 'team_id': off_tid, 'team_name': off_name}
            done += 1
            time.sleep(0.15)

            if done % 100 == 0:
                print(f'  [{done}/{total_p}  {done/total_p*100:.0f}%]  {off_name} — {pt_name}')

    print('Player play types done.')

    # ── Save ──────────────────────────────────────────────────────────────────
    TEAM_PT_OUT.write_text(json.dumps({
        tid: {'off': team_pt_off[tid], 'def': team_pt_def[tid]}
        for tid in our_teams
    }, indent=2))
    print(f'\nSaved team play types → {TEAM_PT_OUT}')

    PLAYER_PT_OUT.write_text(json.dumps({
        pid: {'pt_off': stats, **player_meta.get(pid, {})}
        for pid, stats in player_pt_off.items()
    }, indent=2))
    print(f'Saved player play types → {PLAYER_PT_OUT}  ({len(player_pt_off)} players)')

    # Sanity check: USA P&R BH vs quality
    usa_id = '54457df7300969b132fd104f'
    prb = team_pt_off.get(usa_id, {}).get('P&R Ball Handler', {})
    p = prb.get('possessions', 0)
    print(f'\nUSA P&R BH vs quality: {p} poss  PPP={prb.get("pointMade",0)/p:.3f}' if p else '\nUSA P&R BH: no data')
    print('\nNext: python3 build_dashboard.py')


if __name__ == '__main__':
    main()
