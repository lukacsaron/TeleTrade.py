import json
import openai
from datetime import datetime

async def interpret_message(text, openai_api_key):
    openai.api_key = openai_api_key
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Extract the trading details from this message and return the details as a JSON object with the keys: action, entry_price_low, entry_price_high, sl, tp1, tp2."},
                {"role": "user", "content": f"Message: {text}"}
            ]
        )
        details = json.loads(response.choices[0].message['content'].strip())
        return details
    except openai.error.RateLimitError:
        await asyncio.sleep(60)
        return await interpret_message(text, openai_api_key)
    except Exception as e:
        print(f"Error interpreting message: {e}")
        return None

def parse_trade_message(details, trade_id):
    action = details['action']
    symbol = "XAUUSD"
    entry_price_low = details['entry_price_low']
    entry_price_high = details['entry_price_high']
    sl = details['sl']
    tp1 = details['tp1']
    tp2 = details['tp2']

    trade = Trade(trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2)
    step = (entry_price_high - entry_price_low) / 11
    volumes = [0.01] * 4 + [0.02] * 4 + [0.03] * 4 if action.lower() == "buy" else [0.03] * 4 + [0.02] * 4 + [0.01] * 4

    for i in range(12):
        price = entry_price_low + i * step
        volume = volumes[i]
        tp = tp1 if i < 4 else tp2
        trade.add_entry(price, tp, sl, volume)

    return trade

def save_trade(trade):
    try:
        with open('trades.json', 'r') as f:
            trades = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        trades = []

    if not isinstance(trades, list):
        trades = []

    for i, t in enumerate(trades):
        if 'trade_id' in t and t['trade_id'] == trade.trade_id:
            trades[i] = trade.to_dict()
            break
    else:
        trades.append(trade.to_dict())

    with open('trades.json', 'w') as f:
        json.dump(trades, f, default=default, indent=4)
