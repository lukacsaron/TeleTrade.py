import json
import base64
import openai
import asyncio
from telethon import TelegramClient, events
from datetime import datetime
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from metaapi_cloud_sdk import MetaApi
from flask import Flask, render_template, request

app = Flask(__name__)

class Trade:
    def __init__(self, trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2, entries=None, filled_entries=None, status="open"):
        self.trade_id = trade_id
        self.action = action
        self.symbol = symbol
        self.entry_price_low = entry_price_low
        self.entry_price_high = entry_price_high
        self.sl = sl
        self.tp1 = tp1
        self.tp2 = tp2
        self.entries = entries if entries else []
        self.filled_entries = filled_entries if filled_entries else []
        self.status = status

    def add_entry(self, entry, tp, sl, volume, order_type="limit"):
        self.entries.append({
            'entry': entry,
            'tp': tp,
            'sl': sl,
            'volume': volume,
            'order_type': order_type,
            'order_id': None,
            'status': 'open'
        })

    def add_market_order(self, order_id, entry, tp, sl, volume):
        self.filled_entries.append({
            'order_id': order_id,
            'entry': entry,
            'tp': tp,
            'sl': sl,
            'volume': volume,
            'order_type': 'market',
            'status': 'filled'
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
            'entries': self.entries,
            'filled_entries': self.filled_entries,
            'status': self.status
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
openai.api_key = openai_api_key

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

async def get_current_price(account, symbol):
    try:
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()
        price = await connection.get_symbol_price(symbol)
        return price['bid'] if price else None
    except Exception as e:
        print(f"Error fetching current price: {e}")
        return None

async def place_orders(account, trade):
    if not account:
        raise Exception("Account not connected")

    try:
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()
        
        current_price = await get_current_price(account, trade.symbol)

        for entry in trade.entries:
            entry_price = entry['entry']
            tp = entry['tp']
            sl = entry['sl']
            volume = entry['volume']
            order_type = entry['order_type']

            if trade.action.lower() == "buy":
                if entry_price > current_price:
                    order_type = "stop"
                print(f"Placing Buy {order_type} order: symbol={trade.symbol}, volume={volume}, entry_price={entry_price}, sl={sl}, tp={tp}")
                if order_type == "limit":
                    result = await connection.create_limit_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
                else:
                    result = await connection.create_stop_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
            else:
                if entry_price < current_price:
                    order_type = "stop"
                print(f"Placing Sell {order_type} order: symbol={trade.symbol}, volume={volume}, entry_price={entry_price}, sl={sl}, tp={tp}")
                if order_type == "limit":
                    result = await connection.create_limit_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
                else:
                    result = await connection.create_stop_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
            
            if 'orderId' in result:
                order_id = result['orderId']
                entry['order_id'] = order_id
                print(f"Order placed successfully: {result['stringCode']} with order_id: {order_id}")
            else:
                print(f"Order placement failed: {result}")

        save_trade(trade)
        update_status(trade.trade_id)
        return True
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
        raise TypeError(f"Type {obj} not serializable")

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

def update_status(trade_id):
    with open('status.json', 'w') as f:
        json.dump({'latest_trade_id': trade_id}, f)

def get_latest_trade_id():
    try:
        with open('status.json', 'r') as f:
            status = json.load(f)
            return status.get('latest_trade_id')
    except (FileNotFoundError, json.JSONDecodeError):
        return None

async def interpret_message(text):
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Extract the trading details from this message and return the details as a JSON object with the keys: action, entry_price_low, entry_price_high, sl, tp1, tp2."},
                {"role": "user", "content": f"Message: {text}"}
            ]
        )
        details = json.loads(response.choices[0].message['content'].strip())
        print(f"OpenAI parsed response: {details}")
        return details
    except openai.error.RateLimitError:
        print("Rate limit exceeded. Waiting before retrying...")
        await asyncio.sleep(60)  # Wait for 1 minute before retrying
        return await interpret_message(text)
    except Exception as e:
        print(f"Error interpreting message: {e}")
        return None

def parse_trade_message(details, trade_id):
    try:
        action = details['action']
        symbol = "XAUUSD+"  # Always use XAUUSD+
        entry_price_low = details['entry_price_low']
        entry_price_high = details['entry_price_high']
        sl = details['sl']
        tp1 = details['tp1']
        tp2 = details['tp2']

        print(f"Parsed trade message: action={action}, symbol={symbol}, entry_price_low={entry_price_low}, entry_price_high={entry_price_high}, sl={sl}, tp1={tp1}, tp2={tp2}")

        trade = Trade(trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2)

        step = (entry_price_high - entry_price_low) / 11  # Step between entries to evenly distribute within the zone

        if action.lower() == "buy":
            volumes = [0.03] * 4 + [0.02] * 4 + [0.01] * 4  # Buy: Top -> 0.01, Middle -> 0.02, Bottom -> 0.03
        else:
            volumes = [0.01] * 4 + [0.02] * 4 + [0.03] * 4  # Sell: Top -> 0.03, Middle -> 0.02, Bottom -> 0.01

        for i in range(12):
            price = entry_price_low + i * step
            volume = volumes[i]
            tp = tp1 if i < 4 else tp2
            trade.add_entry(price, tp, sl, volume)

        return trade
    except Exception as e:
        print(f"Error parsing trade message: {e}")
        return None

@client.on(events.NewMessage(chats=target_channel))
async def handler(event):
    message = event.message
    text = message.message or (message.media.caption if message.media and hasattr(message.media, 'caption') else "")

    if not text and message.grouped_id:
        grouped_messages = []
        async for grouped_message in client.iter_messages(target_channel, limit=50):
            if grouped_message.grouped_id == message.grouped_id:
                grouped_messages.append(grouped_message)

        for grouped_message in grouped_messages:
            text += grouped_message.message or (grouped_message.media.caption if grouped_message.media and hasattr(grouped_message.media, 'caption') else "")

    details = await interpret_message(text)

    if details:
        trade_id = message.id  # Use the message ID as the trade ID
        trade = parse_trade_message(details, trade_id)
        if trade:
            account = await connect_metaapi()
            if account:
                save_trade(trade)
                await place_orders(account, trade)
                await place_additional_market_order(account, trade)
                print("Trade placed successfully in MetaAPI")

    print(f"New message processed: {message.id}")

async def place_additional_market_order(account, trade):
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    current_price = await get_current_price(account, trade.symbol)

    if current_price is None:
        print("Error fetching current price, cannot place market order")
        return

    volume = 0.04

    if trade.action.lower() == "buy":
        sl = current_price - 6
        tp = current_price + 4
        print(f"Placing additional market buy order: symbol={trade.symbol}, volume={volume}, sl={sl}, tp={tp}")
        result = await connection.create_market_buy_order(trade.symbol, volume, stop_loss=sl, take_profit=tp)
    else:
        sl = current_price + 6
        tp = current_price - 4
        print(f"Placing additional market sell order: symbol={trade.symbol}, volume={volume}, sl={sl}, tp={tp}")
        result = await connection.create_market_sell_order(trade.symbol, volume, stop_loss=sl, take_profit=tp)

    if 'orderId' in result:
        order_id = result['orderId']
        trade.add_market_order(order_id, current_price, tp, sl, volume)
        save_trade(trade)
        print(f"Placed additional market order: {result}")

async def close_all_orders(account, trade_id):
    try:
        with open('trades.json', 'r') as f:
            trades = json.load(f)

        trade = next((t for t in trades if t['trade_id'] == trade_id), None)
        if not trade:
            print(f"No trade found with trade_id: {trade_id}")
            return

        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        for entry in trade['entries']:
            order_id = entry['order_id']
            if order_id:
                print(f"Closing order: {order_id}")
                await connection.cancel_order(order_id)
                entry['status'] = 'closed'

        for filled_entry in trade['filled_entries']:
            order_id = filled_entry['order_id']
            if order_id:
                print(f"Closing filled order: {order_id}")
                await connection.close_position(order_id)
                filled_entry['status'] = 'closed'

        trade['status'] = 'closed'
        with open('trades.json', 'w') as f:
            json.dump(trades, f, default=default, indent=4)
        
        print(f"All orders for trade_id {trade_id} closed successfully")
    except Exception as e:
        print(f"Error closing orders: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/close_orders', methods=['POST'])
def close_orders():
    trade_id = get_latest_trade_id()
    if trade_id:
        account = asyncio.run(connect_metaapi())
        if account:
            asyncio.run(close_all_orders(account, trade_id))
    return "All orders closed successfully"

async def main():
    print("Starting Telegram client...")
    await client.start(phone_number)  # Start the client and authenticate if needed
    print(f'Listening to new messages in {target_channel}...')

    await client.run_until_disconnected()

def run():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, app.run, '0.0.0.0', 8888)
    loop.run_until_complete(main())

if __name__ == "__main__":
    run()
