#!/usr/bin/env python3
"""
Scrape per-player cumulative box score stats (rebounds, steals, blocks, minutes, fouls)
for all 81 teams via /leagues/{league}/seasons/{season}/playerswithboxscore.

Output: data/2025/player_boxscores.json
  {player_id: {name, team_id, team_name, gp, minutes, pts, offReb, defReb, totReb,
               steals, blocks, fouls, turnovers, fgm, fga, fg_pct}}
"""

import pkce, requests, json, os, sys, time
from pathlib import Path
from dotenv import load_dotenv

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR))
import synergy_functions as sf

load_dotenv(DIR / '.env')

BASE     = 'https://basketball.synergysportstech.com/api'
LEAGUE   = '54457dce300969b132fcfb41'
SEASON   = '684205c6d01c0c93c586dbf2'
COMP_KEY = f'{LEAGUE}:ALL'
OUT      = DIR / 'data' / '2025' / 'player_boxscores.json'

def auth():
    session = requests.Session()
    cv = pkce.generate_code_verifier(length=128)
    cc = pkce.get_code_challenge(cv)
    token_type, _, access_token = sf.get_access_token(
        session, cv, cc, os.getenv('SYNERGY_USERNAME'), os.getenv('SYNERGY_PASSWORD'))
    if not access_token:
        sys.exit('Auth failed')
    headers = {
        'Authorization': f'{token_type} {access_token}',
        'Accept': 'application/json, text/plain, */*',
        'X-SYNERGY-CLIENT': 'ProductVersion=2026.02.25.10717; ProductName=Basketball.TeamSite',
        'Origin': 'https://apps.synergysports.com',
        'Referer': 'https://apps.synergysports.com/',
        'Content-Type': 'application/json; charset=utf-8',
    }
    print('Auth OK', flush=True)
    return session, headers

def fetch_team_boxscores(session, headers, team_id, retries=2):
    for attempt in range(retries + 1):
        try:
            r = session.post(
                f'{BASE}/leagues/{LEAGUE}/seasons/{SEASON}/playerswithboxscore',
                headers=headers,
                json={'competitionDefinitionKey': COMP_KEY, 'teamId': team_id},
                timeout=30)
            if r.status_code == 401:
                return None, 'auth'
            return r.json().get('result', []), None
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
            else:
                return [], str(e)
    return [], None

def aggregate(players_data, team_name):
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
        gs = (pts + 0.4*fgm - 0.7*fga - 0.4*(fta-ftm)
              + 0.7*oreb + 0.3*dreb + stl + 0.7*ast + 0.7*blk - 0.4*foul - tov)
        out[pid] = {
            'name':      name,
            'team_name': team_name,
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
    # Load team list
    teams_dir = DIR / 'data' / '2025' / 'teams'
    teams = []
    for f in teams_dir.glob('*.json'):
        d = json.loads(f.read_text())
        teams.append({'id': d['team']['id'], 'name': d['team']['name']})
    teams.sort(key=lambda x: x['name'])
    print(f'{len(teams)} teams to scrape', flush=True)

    session, headers = auth()

    all_players = {}
    for i, team in enumerate(teams, 1):
        tid, tname = team['id'], team['name']
        players_data, err = fetch_team_boxscores(session, headers, tid)

        if err == 'auth':
            print('  Token expired — re-authing...', flush=True)
            session, headers = auth()
            players_data, err = fetch_team_boxscores(session, headers, tid)

        agg = aggregate(players_data or [], tname)
        all_players.update(agg)

        print(f'  [{i:>2}/{len(teams)}] {tname:<35} {len(agg)} players', flush=True)
        time.sleep(0.2)

    OUT.write_text(json.dumps(all_players, indent=2))
    print(f'\nSaved {len(all_players)} players → {OUT}')

    # Sanity check — Aaliyah Edwards
    ae = next((v for v in all_players.values() if 'Edwards' in v.get('name','')), None)
    if ae:
        print(f"\nAaliyah Edwards: {ae['gp']} GP  {ae['mpg']} MPG  {ae['ppg']} PPG  {ae['rpg']} RPG  {ae['spg']} SPG  {ae['bpg']} BPG")

if __name__ == '__main__':
    main()
