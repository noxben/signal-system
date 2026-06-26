##run with `python3 -c`
import os
from dotenv import load_dotenv
import requests

load_dotenv()

ALPACA_DATA_URL   = os.getenv('ALPACA_DATA_URL', 'https://data.alpaca.markets')
ALPACA_API_KEY    = os.getenv('ALPACA_API_KEY', '')
ALPACA_API_SECRET = os.getenv('ALPACA_API_SECRET', '')

headers = {
    'APCA-API-KEY-ID': ALPACA_API_KEY,
    'APCA-API-SECRET-KEY': ALPACA_API_SECRET,
}

resp = requests.get(
    f'{ALPACA_DATA_URL}/v2/stocks/snapshots',
    headers=headers,
    params={'symbols': 'LMT', 'feed': 'iex'},
    timeout=15,
)
print(resp.status_code, resp.json())