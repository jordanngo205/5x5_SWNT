#!/usr/bin/env python3
"""
FIBA 5x5 Women 2025 - Team Scraper
Scrapes for each senior team:
  - overall offense + defense  (possession reports)
  - play type offense + defense (leaderboard, all 11 play types)
  - cumulative box              (player-level season offense totals)

Data saved to data/2025/teams/{team_id}.json
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

# Confirmed play type IDs (cross-checked against Angola screenshot)
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

REPORT_OFFENSE = 2   # Team Offensive
REPORT_DEFENSE = 3   # Team Defensive


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

def get_leaderboard(session, h, play_type, report_type):
    r = session.get(BASE + '/leaderboards/recordswithsparseranks',
        params={
            'leagueId': LEAGUE_ID, 'seasonId': SEASON_ID,
            'playType': play_type, 'reportType': report_type,
            'competitionDefinitionKey': COMP_KEY,
            'competitionType': 4, 'rankingType': 4,
            'perGame': 'false', 'minPossessions': 0,
            'minPossessionsPerGame': 'false', 'ascending': 'false',
            'skip': 0, 'take': 300,
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
    """Extract all raw fields from a possessionReport dict."""
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


def assign_ranks(records_by_tid):
    """
    Given a dict {team_id: pr_dict}, compute and inject pppRank and possRank.
    pppRank  — rank by PPP descending (higher PPP = better rank = lower number)
    possRank — rank by possessions descending (%TIME rank)
    """
    items = [(tid, d) for tid, d in records_by_tid.items() if d.get('possessions', 0) > 0]

    def safe_ppp(d):
        p = d.get('possessions', 0)
        return d.get('pointMade', 0) / p if p else 0

    sorted_ppp  = sorted(items, key=lambda x: safe_ppp(x[1]),         reverse=True)
    sorted_poss = sorted(items, key=lambda x: x[1].get('possessions', 0), reverse=True)

    ppp_ranks  = {tid: i + 1 for i, (tid, _) in enumerate(sorted_ppp)}
    poss_ranks = {tid: i + 1 for i, (tid, _) in enumerate(sorted_poss)}

    for tid, d in records_by_tid.items():
        d['pppRank']  = ppp_ranks.get(tid)
        d['possRank'] = poss_ranks.get(tid)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session, token_type, access_token = auth()
    h = make_headers(token_type, access_token)

    teams    = json.loads(Path('teams_senior_2025.json').read_text())['senior_teams']
    team_ids = {t['id'] for t in teams}
    n        = len(teams)

    out_dir = DIR / 'data' / '2025' / 'teams'
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: Play Type leaderboards (24 calls → all teams at once) ────────
    print(f'\n=== Phase 1: Play Type leaderboards (2 sides × {len(PLAY_TYPES)} play types) ===')
    lb = {tid: {'offense': {}, 'defense': {}} for tid in team_ids}

    for side, rt in [('offense', REPORT_OFFENSE), ('defense', REPORT_DEFENSE)]:
        for pt_name, pt_id in PLAY_TYPES:
            print(f'  {side:<8} {pt_name:<25}', end=' ', flush=True)
            records = get_leaderboard(session, h, pt_id, rt)

            # Collect this play type for all senior teams
            by_tid = {}
            for rec in records:
                pr  = rec.get('possessionReport', {})
                tid = pr.get('team', {}).get('id')
                if tid in team_ids:
                    by_tid[tid] = extract_pr(pr)

            # Inject PPP rank and POSS rank across all senior teams for this slice
            assign_ranks(by_tid)

            for tid, d in by_tid.items():
                lb[tid][side][pt_name] = d

            print(f'{len(by_tid)} teams')
            time.sleep(0.15)

    # ── Phase 2: Per-team possession reports (Overall + Cumulative Box) ───────
    print(f'\n=== Phase 2: Per-team possession reports (3 calls × {n} teams) ===')
    all_data = {}

    for i, team in enumerate(teams, 1):
        tid   = team['id']
        tname = team['name']
        print(f'  [{i:>2}/{n}] {tname:<35}', end=' ', flush=True)

        # Overall offense (all plays, grouped by team)
        off_rows = get_poss_report(session, h,
            f'season eq oid({SEASON_ID}) and offensiveteam eq oid({tid})'
            f' and play eq 1 group offensiveteam')
        off_pr = extract_pr(off_rows[0]) if off_rows else {}

        # Overall defense
        def_rows = get_poss_report(session, h,
            f'season eq oid({SEASON_ID}) and defensiveteam eq oid({tid})'
            f' and play eq 1 group defensiveteam')
        def_pr = extract_pr(def_rows[0]) if def_rows else {}

        # Cumulative box — player offensive totals for the season
        player_rows = get_poss_report(session, h,
            f'season eq oid({SEASON_ID}) and offensiveteam eq oid({tid})'
            f' and play eq 1 group offensiveteam, offensiveplayer')
        players = []
        for row in player_rows:
            p     = row.get('player', {})
            pdata = extract_pr(row)
            pdata['player'] = {
                'name': p.get('name', ''),
                'id':   p.get('id', ''),
                'iid':  p.get('iid', ''),
            }
            players.append(pdata)
        # Sort players by possessions desc
        players.sort(key=lambda x: x.get('possessions', 0), reverse=True)

        gp = off_pr.get('gp', team.get('gp', 0))
        all_data[tid] = {
            'team': {'name': tname, 'id': tid, 'gp': gp},
            'overall': {'offense': off_pr, 'defense': def_pr},
            'play_types': lb.get(tid, {'offense': {}, 'defense': {}}),
            'cumulative_box': {'players': players},
        }

        print(f'gp={gp} off={off_pr.get("possessions","?")} def={def_pr.get("possessions","?")} players={len(players)} ✓')
        time.sleep(0.2)

    # ── Save individual team files ─────────────────────────────────────────────
    print(f'\nSaving {n} team files...')
    for team in teams:
        tid = team['id']
        if tid in all_data:
            (out_dir / f'{tid}.json').write_text(json.dumps(all_data[tid], indent=2))

    # Save a summary index
    summary = [{
        'name': d['team']['name'],
        'id':   d['team']['id'],
        'gp':   d['team']['gp'],
    } for d in all_data.values()]
    summary.sort(key=lambda x: x['name'])
    (DIR / 'data' / '2025' / 'teams_index.json').write_text(json.dumps({
        'league_id': LEAGUE_ID, 'season_id': SEASON_ID, 'season': '2025',
        'teams': summary,
    }, indent=2))

    print(f'Done. Files in {out_dir}')


if __name__ == '__main__':
    main()
