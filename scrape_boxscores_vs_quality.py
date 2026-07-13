#!/usr/bin/env python3
"""
Scrape quality-filtered player box score stats for T1 teams only.
Only counts games vs T1+T2 opponents (using opponentTeamIds filter).

Output: data/2025/player_boxscores_vs_quality.json
  {player_id: {name, team_id, team_name, tier,
               gp, minutes, mpg, pts, ppg,
               offReb, defReb, totReb, rpg,
               steals, spg, blocks, bpg,
               fouls, turnovers, fgm, fga, fg_pct}}
"""

import pkce, requests, json, os, sys, time
from pathlib import Path
from dotenv import load_dotenv
import openpyxl

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR))
import synergy_functions as sf

load_dotenv(DIR / '.env')

BASE     = 'https://basketball.synergysportstech.com/api'
LEAGUE   = '54457dce300969b132fcfb41'
SEASON   = '684205c6d01c0c93c586dbf2'
COMP_KEY = f'{LEAGUE}:ALL'
OUT      = DIR / 'data' / '2025' / 'player_boxscores_vs_quality.json'

_session = None
_headers = {}

def fresh_auth():
    global _session, _headers
    if _session is None:
        _session = requests.Session()
    cv = pkce.generate_code_verifier(length=128)
    cc = pkce.get_code_challenge(cv)
    token_type, _, access_token = sf.get_access_token(
        _session, cv, cc, os.getenv('SYNERGY_USERNAME'), os.getenv('SYNERGY_PASSWORD'))
    if not access_token:
        sys.exit('Auth failed')
    _headers = {
        'Authorization': f'{token_type} {access_token}',
        'Accept': 'application/json, text/plain, */*',
        'X-SYNERGY-CLIENT': 'ProductVersion=2026.02.25.10717; ProductName=Basketball.TeamSite',
        'Origin': 'https://apps.synergysports.com',
        'Referer': 'https://apps.synergysports.com/',
        'Content-Type': 'application/json; charset=utf-8',
    }
    print('Auth OK', flush=True)

def fetch_team_boxscores(team_id, opponent_ids, retries=2):
    for attempt in range(retries + 1):
        try:
            r = _session.post(
                f'{BASE}/leagues/{LEAGUE}/seasons/{SEASON}/playerswithboxscore',
                headers=_headers,
                json={
                    'competitionDefinitionKey': COMP_KEY,
                    'teamId': team_id,
                    'opponentTeamIds': opponent_ids,
                },
                timeout=30)
            if r.status_code == 401:
                if attempt < retries:
                    print('  Token expired — re-authing...', flush=True)
                    fresh_auth()
                    time.sleep(1)
                    continue
                return []
            return r.json().get('result', [])
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
            else:
                print(f'  Error: {e}', flush=True)
                return []
    return []

def aggregate(players_data, team_id, team_name, tier):
    out = {}
    for p in players_data:
        pid  = p.get('id', '')
        name = p.get('name', '')
        if not pid:
            continue
        games = p.get('boxscore', [])
        gp = len(games)
        secs = pts = fgm = fga = p3m = p3a = ftm = fta = 0
        oreb = dreb = ast = stl = blk = blk_fga = foul = tov = 0
        for g in games:
            secs    += g.get('secondsPlayed', 0) or 0
            pts     += g.get('points', 0) or 0
            fgm     += g.get('fieldGoalsMade', 0) or 0
            fga     += g.get('fieldGoalsAttempted', 0) or 0
            p3m     += g.get('threePtsMade', 0) or 0
            p3a     += g.get('threePtsAttempted', 0) or 0
            ftm     += g.get('freeThrowsMade', 0) or 0
            fta     += g.get('freeThrowsAttempted', 0) or 0
            oreb    += g.get('offReb', 0) or 0
            dreb    += g.get('defReb', 0) or 0
            ast     += g.get('assists', 0) or 0
            stl     += g.get('steals', 0) or 0
            blk     += g.get('blocks', 0) or 0
            blk_fga += g.get('blockedFGAs', 0) or 0
            foul    += g.get('fouls', 0) or 0
            tov     += g.get('turnovers', 0) or 0
        mins = round(secs / 60, 1)
        treb = oreb + dreb
        # Game Score (Hollinger): PTS + 0.4*FGM - 0.7*FGA - 0.4*(FTA-FTM)
        #   + 0.7*ORB + 0.3*DRB + STL + 0.7*AST + 0.7*BLK - 0.4*PF - TOV
        gs = (pts + 0.4*fgm - 0.7*fga - 0.4*(fta-ftm)
              + 0.7*oreb + 0.3*dreb + stl + 0.7*ast + 0.7*blk - 0.4*foul - tov)
        out[pid] = {
            'name':      name,
            'team_id':   team_id,
            'team_name': team_name,
            'tier':      tier,
            'gp':        gp,
            'minutes':   mins,
            'mpg':       round(mins / gp, 1) if gp else 0,
            'pts':       pts,
            'ppg':       round(pts / gp, 1) if gp else 0,
            'fgm':       fgm,
            'fga':       fga,
            'fg_pct':    round(fgm / fga * 100, 1) if fga else 0,
            'p3m':       p3m,
            'p3a':       p3a,
            'p3_pct':    round(p3m / p3a * 100, 1) if p3a else 0,
            'ftm':       ftm,
            'fta':       fta,
            'ft_pct':    round(ftm / fta * 100, 1) if fta else 0,
            'offReb':    oreb,
            'defReb':    dreb,
            'totReb':    treb,
            'rpg':       round(treb / gp, 1) if gp else 0,
            'ast':       ast,
            'apg':       round(ast / gp, 1) if gp else 0,
            'steals':    stl,
            'spg':       round(stl / gp, 1) if gp else 0,
            'blocks':    blk,
            'bpg':       round(blk / gp, 1) if gp else 0,
            'blk_fga':   blk_fga,
            'fouls':     foul,
            'turnovers': tov,
            'tpg':       round(tov / gp, 1) if gp else 0,
            'game_score': round(gs, 1),
            'gs_per40':   round(gs / mins * 40, 1) if mins else 0,
        }
    return out

def main():
    # Load tiers
    teams_dir = DIR / 'data' / '2025' / 'teams'
    our_teams = {}
    for f in teams_dir.glob('*.json'):
        d = json.loads(f.read_text())
        our_teams[d['team']['id']] = d['team']['name']

    wb = openpyxl.load_workbook('/Users/jordanngo/Downloads/fiba 5x5 teams.xlsx')
    tiers = {row[0]: row[1] for row in wb.active.iter_rows(min_row=2, values_only=True) if row[0]}

    t1_teams = sorted(
        [(tid, name) for tid, name in our_teams.items() if tiers.get(name, 3) == 1],
        key=lambda x: x[1])
    quality_ids = [tid for tid, name in our_teams.items() if tiers.get(name, 3) <= 2]

    print(f'T1 teams: {len(t1_teams)}  |  Quality opponents: {len(quality_ids)}', flush=True)

    fresh_auth()

    all_players = {}
    for i, (tid, tname) in enumerate(t1_teams, 1):
        players_data = fetch_team_boxscores(tid, quality_ids)
        agg = aggregate(players_data, tid, tname, tier=1)
        all_players.update(agg)
        total_gp = sum(p['gp'] for p in agg.values())
        print(f'  [{i:>2}/{len(t1_teams)}] {tname:<25} {len(agg)} players  {total_gp} player-games', flush=True)
        time.sleep(0.3)

    OUT.write_text(json.dumps(all_players, indent=2))
    print(f'\nSaved {len(all_players)} players → {OUT}')

    # Sanity check — Aaliyah Edwards
    ae = next((v for k, v in all_players.items() if 'Edwards' in v.get('name', '')), None)
    if ae:
        print(f"\nAaliyah Edwards: {ae['gp']} GP vs quality  {ae['mpg']} MPG  {ae['ppg']} PPG  {ae['rpg']} RPG  {ae['spg']} SPG  {ae['bpg']} BPG")

if __name__ == '__main__':
    main()
