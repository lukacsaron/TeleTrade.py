import json
import base64
import openai
import asyncio
from openai import AsyncOpenAI
from telethon import TelegramClient, events
from datetime import datetime
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from metaapi_cloud_sdk import MetaApi

class Trade:
    def __init__(self, trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2, tp3=None):
        self.trade_id = trade_id
        self.action = action
        self.symbol = symbol
        self.entry_price_low = entry_price_low
        self.entry_price_high = entry_price_high
        self.sl = sl
        self.tp1 = tp1
        self.tp2 = tp2
        self.tp3 = tp3
        self.entries = []

    def add_entry(self, entry, tp, sl, volume):
        self.entries.append({
            'entry': entry,
            'tp': tp,
            'sl': sl,
            'volume': volume
        })

    def to_dict(self):
        return {
            'trade_id': self.trade_id,
            'action': self.action,
            'symbol': self.symbol,
            'entry_price_low': self.entry_price_low,
            'entry_price_high': self.entry_price_high,
            'sl': self.sl,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'tp3': self.tp3,
            'entries': self.entries
        }

# Load configuration from config.json
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

api_id = int(config['api_id'])
api_hash = config['api_hash']
phone_number = config['phone_number']
target_channel = config['target_channel']
openai_api_key = config['openai_api_key']
metaapi_token = config['metaapi_token']
metaapi_account_id = config['metaapi_account_id']

# Initialize the Telegram client
client = TelegramClient('session_name', api_id, api_hash)

# Initialize OpenAI API client
aclient = AsyncOpenAI(api_key=openai_api_key)

async def connect_metaapi():
    try:
        print("Connecting to MetaApi...")
        metaapi = MetaApi(metaapi_token)
        account = await metaapi.metatrader_account_api.get_account(metaapi_account_id)
        await account.wait_connected()
        print("Connected to MetaApi")
        return account
    except Exception as e:
        print(f"Error connecting to MetaApi: {e}")
        return None

async def place_limit_order(account, trade):
    if not account:
        raise Exception("Account not connected")

    try:
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        for entry in trade.entries:
            entry_price = entry['entry']
            tp = entry['tp']
            sl = entry['sl']
            volume = entry['volume']
            print(f"Placing {trade.action} limit order: symbol={trade.symbol}, volume={volume}, entry_price={entry_price}, sl={sl}, tp={tp}")
            if trade.action == "buy":
                result = await connection.create_limit_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
            else:
                result = await connection.create_limit_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
            print(f"Order placed successfully: {result['stringCode']}")
        return True
    except AttributeError:
        print(f"Error placing trade: Method for placing {trade.action} limit order does not exist.")
    except Exception as e:
        print(f"Error placing trade: {e}")
        return False

def default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, MessageMediaPhoto):
        return 'MessageMediaPhoto'
    elif isinstance(obj, MessageMediaDocument):
        return 'MessageMediaDocument'
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode('utf-8')
    elif hasattr(obj, '__dict__'):
        return obj.__dict__
    else:
        raise TypeError(f"Type {type(obj)} not serializable")

def save_trade(trade):
    # Load existing trades
    try:
        with open('trades.json', 'r') as f:
            trades = json.load(f)
    except FileNotFoundError:
        trades = []

    # Append the new trade
    trades.append(trade.to_dict())

    # Save the updated list of trades
    with open('trades.json', 'w') as f:
        json.dump(trades, f, default=default, indent=4)

async def interpret_message(text):
    try:
        response = await aclient.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a trading assistant."},
                {"role": "user", "content": f"Classify this message as 'info' or 'trade'. Only respond with 'info' or 'trade': {text}"}
            ]
        )
        classification = response.choices[0].message.content.strip().lower()
        print(f"OpenAI classification response: {classification}")
        return classification
    except openai.error.RateLimitError as e:
        print("Rate limit exceeded. Waiting before retrying...")
        await asyncio.sleep(60)  # Wait for 1 minute before retrying
        return await interpret_message(text)
    except Exception as e:
        print(f"Error interpreting message: {e}")
        return "info"

def parse_trade_message(text, trade_id):
    try:
        # Extract trade details from the message text
        # Example message: "Buy XAUUSD @2366.5-2362.5 SI:2360.5 Tp1:2368 Tp2:2370.5"
        lines = text.split('\n')
        action = "buy" if "buy" in lines[0].lower() else "sell"
        symbol = "XAUUSD"
        entry_range = lines[0].split('@')[1].strip().split('-')
        entry_price_low = float(entry_range[0])
        entry_price_high = float(entry_range[1])
        sl = float([line.split(':')[1] for line in lines if line.startswith("SI")][0])
        tp1 = float([line.split(':')[1] for line in lines if line.startswith("Tp1")][0])
        tp2 = float([line.split(':')[1] for line in lines if line.startswith("Tp2")][0])
        tp3 = None
        for line in lines:
            if line.startswith("Tp3"):
                tp3 = float(line.split(':')[1])
                break
        print(f"Parsed trade message: action={action}, symbol={symbol}, entry_price_low={entry_price_low}, entry_price_high={entry_price_high}, sl={sl}, tp1={tp1}, tp2={tp2}, tp3={tp3}")

        trade = Trade(trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2, tp3)

        step = (entry_price_high - entry_price_low) / 12  # Step between entries to evenly distribute within the zone

        if action == "buy":
            volumes = [0.01] * 4 + [0.02] * 4 + [0.03] * 4  # Buy: Top -> 0.01, Middle -> 0.02, Bottom -> 0.03
        else:
            volumes = [0.03] * 4 + [0.02] * 4 + [0.01] * 4  # Sell: Top -> 0.03, Middle -> 0.02, Bottom -> 0.01

        for i in range(12):
            price = entry_price_low + i * step
            volume = volumes[i]
            if i < 4:
                tp = tp1
            elif i < 8:
                tp = tp2 if tp3 is None else (tp1 + tp2) / 2
            else:
                tp = tp2 if tp3 is None else tp3
            trade.add_entry(price, tp, sl, volume)

        return trade
    except Exception as e:
        print(f"Error parsing trade message: {e}")
        return None

@client.on(events.NewMessage(chats=target_channel))
async def handler(event):
    message = event.message

    # Process the latest message
    message_dict = message.to_dict()

    # Extract text from the message or its media caption
    text = message.message or ""
    if message.media and hasattr(message.media, 'caption'):
        text = message.media.caption or ""

    if not text and message.grouped_id:
        # If the message is part of a media group, fetch all messages in the group
        grouped_messages = []
        async for grouped_message in client.iter_messages(target_channel, limit=50):
            if grouped_message.grouped_id == message.grouped_id:
                grouped_messages.append(grouped_message)

        for grouped_message in grouped_messages:
            if grouped_message.message:
                text += grouped_message.message
            if grouped_message.media and hasattr(grouped_message.media, 'caption'):
                text += grouped_message.media.caption

    message_dict['extracted_text'] = text

    # Use OpenAI to classify the message
    classification = await interpret_message(text)
    message_dict['classification'] = classification

    # If it's a trade message, parse and execute the trade
    if classification == "trade":
        trade_id = message.id  # Use the message ID as the trade ID
        trade = parse_trade_message(text, trade_id)
        if trade:
            save_trade(trade)
            account = await connect_metaapi()
            if account:
                result = await place_limit_order(account, trade)
                if result:
                    print("Trade placed successfully in MetaAPI")

    # Save the latest message to the JSON file
    with open('messages.json', 'w') as f:
        json.dump(message_dict, f, default=default, indent=4)

    print(f"New message: {message_dict}")

async def main():
    print("Starting Telegram client...")
    await client.start(phone_number)  # Start the client and authenticate if needed
    print(f'Listening to new messages in {target_channel}...')
    await client.run_until_disconnected()

def run():
    asyncio.run(main())

if __name__ == "__main__":
    run()
