#!/usr/bin/env python3
"""
Build player and team ratings for T1 teams using quality-filtered stats.

Player OVR uses Hollinger's Game Score per 40 minutes (GS/40) mapped to a
fixed 40–99 scale via linear interpolation between these absolute breakpoints:

  GS/40   Rating  Level
  ≤ 0  →  40      Non-factor
    5  →  50      Fringe
   10  →  60      Role player
   15  →  70      Average starter
   20  →  80      Good starter
   25  →  90      All-star
   30  →  95      Elite
  ≥35  →  99      Best in world

  GS = PTS + 0.4*FGM - 0.7*FGA - 0.4*(FTA-FTM)
       + 0.7*ORB + 0.3*DRB + STL + 0.7*AST + 0.7*BLK - 0.4*PF - TOV

OVR = GS/40_rating × 0.70 + MPG_rating × 0.30
  — efficiency (GS/40) drives 70%, role/deployment (MPG) drives 30%
  — no players excluded: being on a T1 roster is the quality gate
  — minimum threshold: ≥2 quality games

Sub-ratings use the same breakpoint approach on individual stats.

Outputs:
  data/2025/player_ratings.json
  data/2025/team_ratings.json
"""

import json
from pathlib import Path
import openpyxl

DIR = Path(__file__).parent

# Fixed GS/40 → rating breakpoints (absolute, not relative)
GS_BREAKPOINTS = [(0, 40), (5, 50), (10, 60), (15, 70), (20, 80), (25, 90), (30, 95), (35, 99)]

def gs_to_rating(gs40):
    if gs40 <= GS_BREAKPOINTS[0][0]:  return GS_BREAKPOINTS[0][1]
    if gs40 >= GS_BREAKPOINTS[-1][0]: return GS_BREAKPOINTS[-1][1]
    for i in range(len(GS_BREAKPOINTS) - 1):
        x0, y0 = GS_BREAKPOINTS[i]
        x1, y1 = GS_BREAKPOINTS[i+1]
        if x0 <= gs40 <= x1:
            return round(y0 + (gs40 - x0) / (x1 - x0) * (y1 - y0))
    return 40

def stat_to_rating(value, breakpoints):
    """Generic breakpoint interpolation for any stat → rating."""
    return gs_to_rating.__wrapped__(value, breakpoints) if hasattr(gs_to_rating, '__wrapped__') else _interp(value, breakpoints)

def _interp(value, breakpoints):
    if value <= breakpoints[0][0]:  return breakpoints[0][1]
    if value >= breakpoints[-1][0]: return breakpoints[-1][1]
    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i+1]
        if x0 <= value <= x1:
            return round(y0 + (value - x0) / (x1 - x0) * (y1 - y0))
    return breakpoints[0][1]


def load_data():
    teams_dir = DIR / 'data' / '2025' / 'teams'
    our_teams = {}
    for f in teams_dir.glob('*.json'):
        d = json.loads(f.read_text())
        our_teams[d['team']['id']] = d['team']['name']

    wb = openpyxl.load_workbook('/Users/jordanngo/Downloads/fiba 5x5 teams.xlsx')
    tiers = {row[0]: row[1] for row in wb.active.iter_rows(min_row=2, values_only=True) if row[0]}
    t1_ids = {tid for tid, name in our_teams.items() if tiers.get(name, 3) == 1}

    box       = json.loads((DIR / 'data/2025/player_boxscores_vs_quality.json').read_text())
    qual      = json.loads((DIR / 'data/2025/player_vs_quality.json').read_text())
    team_qual = json.loads((DIR / 'data/2025/team_vs_quality.json').read_text())

    return our_teams, tiers, t1_ids, box, qual, team_qual


# Sub-rating breakpoints (stat → rating)
PPG_BP  = [(0, 40), (4, 50), (8, 60), (12, 70), (16, 80), (20, 90), (24, 95), (28, 99)]
RPG_BP  = [(0, 40), (1, 50), (2, 60), (4, 70),  (6, 80),  (8, 90),  (10, 95), (12, 99)]
APG_BP  = [(0, 40), (1, 50), (2, 60), (3, 70),  (5, 80),  (7, 90),  (9, 95),  (11, 99)]
DEF_BP  = [(0, 40), (0.5, 50), (1, 60), (1.5, 70), (2, 80), (2.5, 87), (3, 93), (4, 99)]
TS_BP   = [(0, 40), (40, 50), (48, 60), (54, 70), (58, 80), (63, 90), (68, 95), (75, 99)]
MPG_BP  = [(0, 40), (5, 50), (10, 60), (15, 68), (20, 76), (25, 85), (30, 93), (38, 99)]
# GP confidence: shrinks OVR toward 65 (neutral) the fewer quality games played
# 2 games = 70% trust, 4 = 85%, 6 = 93%, 8+ = 99%
GP_BP   = [(0, 0), (2, 70), (4, 85), (6, 93), (8, 99)]


def build_players(box, qual, t1_ids, min_games=2):
    players = {}
    for pid, b in box.items():
        if b.get('team_id') not in t1_ids:
            continue
        if b.get('gp', 0) < min_games:
            continue

        q    = qual.get(pid, {}).get('off', {})
        poss = q.get('possessions', 0)
        sa   = q.get('shotAttempt', 0)

        ppp   = q.get('pointMade', 0) / poss if poss else 0
        s3m   = q.get('shot3Made', 0)
        sm    = q.get('shotMade', 0)
        efg   = (sm + 0.5 * s3m) / sa if sa else 0

        # True Shooting % uses box score FGA + FTA (quality-filtered)
        fga_b = b.get('fga', 0)
        fta_b = b.get('fta', 0)
        pts_b = b.get('pts', 0)
        ts    = pts_b / (2 * (fga_b + 0.44 * fta_b)) if (fga_b + fta_b) else 0

        tov_r = q.get('turnover', 0) / poss if poss else 0

        players[pid] = {
            **b,
            'ppp':   round(ppp, 3),
            'efg':   round(efg * 100, 1),
            'ts':    round(ts * 100, 1),
            'tov_r': round(tov_r * 100, 1),
            'poss':  poss,
            # raw values for rating computation
            '_gs40': b.get('gs_per40', 0),
            '_mpg':  b.get('mpg', 0),
            '_gp':   b.get('gp', 0),
            '_ppp':  ppp,
            '_ts':   round(ts * 100, 1),   # percentage, matches TS_BP scale
            '_rpg':  b.get('rpg', 0),
            '_apg':  b.get('apg', 0),
            '_def':  b.get('spg', 0) + b.get('bpg', 0),
            '_ppg':  b.get('ppg', 0),
        }
    return players


def rate_players(players):
    rated = {}
    for pid, p in players.items():
        gs_rtg     = gs_to_rating(p['_gs40'])
        mpg_rtg    = _interp(p['_mpg'], MPG_BP)
        raw_ovr    = round(gs_rtg * 0.70 + mpg_rtg * 0.30)
        # GP confidence: blend raw OVR toward 65 (neutral) for small samples
        gp_trust   = _interp(p['_gp'], GP_BP) / 100.0
        ovr        = round(raw_ovr * gp_trust + 65 * (1 - gp_trust))
        scoring    = _interp(p['_ppg'], PPG_BP)
        shooting   = _interp(p['_ts'],  TS_BP)
        rebounding = _interp(p['_rpg'], RPG_BP)
        playmaking = _interp(p['_apg'], APG_BP)
        defense    = _interp(p['_def'], DEF_BP)
        role       = mpg_rtg

        rated[pid] = {
            'name':       p['name'],
            'team_id':    p['team_id'],
            'team_name':  p['team_name'],
            'gp':         p['gp'],
            'mpg':        p['mpg'],
            'ppg':        p['ppg'],
            'rpg':        p['rpg'],
            'apg':        p['apg'],
            'spg':        p['spg'],
            'bpg':        p['bpg'],
            'tpg':        p['tpg'],
            'fg_pct':     p['fg_pct'],
            'p3_pct':     p['p3_pct'],
            'ft_pct':     p['ft_pct'],
            'ts':         p['ts'],
            'efg':        p['efg'],
            'ppp':        p['ppp'],
            'tov_r':      p['tov_r'],
            'poss':       p['poss'],
            'game_score': p['game_score'],
            'gs_per40':   p['gs_per40'],
            'ovr':        ovr,
            'scoring':    scoring,
            'shooting':   shooting,
            'rebounding': rebounding,
            'playmaking': playmaking,
            'defense':    defense,
            'role':       role,
        }
    return rated


def rate_teams(team_qual, our_teams, t1_ids):
    teams = {}
    for tid in t1_ids:
        t    = team_qual.get(tid)
        name = our_teams.get(tid, '?')
        if not t:
            continue
        off    = t.get('off', {})
        def_   = t.get('def', {})
        poss_o = off.get('possessions', 0)
        poss_d = def_.get('possessions', 0)
        if not poss_o or not poss_d:
            continue

        off_ppp = off['pointMade'] / poss_o
        def_ppp = def_['pointMade'] / poss_d
        net     = off_ppp - def_ppp

        fga_o = off.get('fgAttempt', 0)
        fga_d = def_.get('fgAttempt', 0)
        efg_o = (off.get('shotMade', 0) + 0.5 * off.get('shot3Made', 0)) / off.get('shotAttempt', 1)
        efg_d = (def_.get('shotMade', 0) + 0.5 * def_.get('shot3Made', 0)) / def_.get('shotAttempt', 1)
        tov_o = off.get('turnover', 0) / poss_o
        tov_d = def_.get('turnover', 0) / poss_d

        teams[tid] = {
            'name':    name,
            'gp':      off.get('gp', 0),
            'off_ppp': round(off_ppp, 3),
            'def_ppp': round(def_ppp, 3),
            'net':     round(net, 3),
            'efg_o':   round(efg_o * 100, 1),
            'efg_d':   round(efg_d * 100, 1),
            'tov_o':   round(tov_o * 100, 1),
            'tov_d':   round(tov_d * 100, 1),
            '_off':    off_ppp,
            '_def':    def_ppp,
            '_net':    net,
        }

    # Fixed breakpoints for team PPP (quality-filtered FIBA senior women's level)
    OFF_BP  = [(0.70, 40), (0.80, 55), (0.87, 65), (0.92, 75), (0.97, 85), (1.02, 93), (1.10, 99)]
    DEF_BP_T = [(0.65, 99), (0.72, 93), (0.78, 85), (0.83, 75), (0.88, 65), (0.93, 55), (1.00, 40)]
    NET_BP  = [(-0.10, 40), (0.00, 55), (0.05, 65), (0.10, 73), (0.15, 80), (0.20, 87), (0.30, 94), (0.40, 99)]

    rated = {}
    for tid, t in teams.items():
        off_rtg = _interp(t['_off'], OFF_BP)
        def_rtg = _interp(t['_def'], DEF_BP_T)
        net_rtg = _interp(t['_net'], NET_BP)
        ovr     = round(net_rtg * 0.55 + off_rtg * 0.25 + def_rtg * 0.20)
        rated[tid] = {
            'name':    t['name'],
            'gp':      t['gp'],
            'off_ppp': t['off_ppp'],
            'def_ppp': t['def_ppp'],
            'net':     t['net'],
            'efg_o':   t['efg_o'],
            'efg_d':   t['efg_d'],
            'tov_o':   t['tov_o'],
            'tov_d':   t['tov_d'],
            'ovr':     ovr,
            'off_rtg': off_rtg,
            'def_rtg': def_rtg,
            'net_rtg': net_rtg,
        }
    return rated


def main():
    our_teams, tiers, t1_ids, box, qual, team_qual = load_data()

    print('Building player features...')
    players = build_players(box, qual, t1_ids, min_games=2)
    print(f'  {len(players)} T1 players with ≥2 quality games')

    player_ratings = rate_players(players)
    out_p = DIR / 'data/2025/player_ratings.json'
    out_p.write_text(json.dumps(player_ratings, indent=2))
    print(f'Saved → {out_p}')

    team_ratings = rate_teams(team_qual, our_teams, t1_ids)
    out_t = DIR / 'data/2025/team_ratings.json'
    out_t.write_text(json.dumps(team_ratings, indent=2))
    print(f'Saved → {out_t}')

    ranked = sorted(player_ratings.values(), key=lambda x: x['ovr'], reverse=True)
    print('\n=== TOP 20 PLAYERS — GS/40-based OVR (vs T1-2 opponents) ===')
    print(f'{"#":<3} {"Name":<26} {"Team":<10} {"OVR":<5} {"SC":<4} {"SH":<4} {"RB":<4} {"PM":<4} {"DF":<4} '
          f'{"GP":<4} {"GS/40":<7} {"PPG":<6} {"RPG":<5} {"APG":<5} {"SPG":<5} {"BPG":<5} {"TS%":<6} {"PPP":<6}')
    for i, p in enumerate(ranked[:20], 1):
        print(f'{i:<3} {p["name"]:<26} {p["team_name"]:<10} {p["ovr"]:<5} '
              f'{p["scoring"]:<4} {p["shooting"]:<4} {p["rebounding"]:<4} {p["playmaking"]:<4} {p["defense"]:<4} '
              f'{p["gp"]:<4} {p["gs_per40"]:<7} {p["ppg"]:<6} {p["rpg"]:<5} {p["apg"]:<5} {p["spg"]:<5} {p["bpg"]:<5} '
              f'{p["ts"]:<6} {p["ppp"]:<6}')

    print('\n=== T1 TEAM RATINGS (vs quality opponents) ===')
    print(f'{"#":<3} {"Team":<20} {"OVR":<5} {"OFF":<5} {"DEF":<5} {"NET":<5} {"GP":<4} '
          f'{"OffPPP":<8} {"DefPPP":<8} {"Net":<7} {"EFG%O":<7} {"EFG%D":<7}')
    for i, t in enumerate(sorted(team_ratings.values(), key=lambda x: x['ovr'], reverse=True), 1):
        print(f'{i:<3} {t["name"]:<20} {t["ovr"]:<5} {t["off_rtg"]:<5} {t["def_rtg"]:<5} {t["net_rtg"]:<5} '
              f'{t["gp"]:<4} {t["off_ppp"]:<8} {t["def_ppp"]:<8} {t["net"]:<7} {t["efg_o"]:<7} {t["efg_d"]:<7}')


if __name__ == '__main__':
    main()
