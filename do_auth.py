#!/usr/bin/env python3
"""
Run this ONCE interactively to save your Synergy token.
After this, the scrapers can reuse the token without 2FA.

Usage:  python3 do_auth.py
"""
import pkce, requests, json, os, sys
from pathlib import Path
from dotenv import load_dotenv

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR))
import synergy_functions as sf

load_dotenv(DIR / '.env')

session = requests.Session()
cv = pkce.generate_code_verifier(length=128)
cc = pkce.get_code_challenge(cv)

token_type, _, access_token = sf.get_access_token(
    session, cv, cc,
    os.getenv('SYNERGY_USERNAME'), os.getenv('SYNERGY_PASSWORD'))

if not access_token:
    sys.exit('Auth failed')

token_file = DIR / '.synergy_token'
token_file.write_text(json.dumps({'token_type': token_type, 'access_token': access_token}))
print(f'Token saved to {token_file}')
print('You can now run:  python3 scrape_player_def_pt.py')
