import json
import base64
import openai
import asyncio
import sqlite3
from sqlite3 import OperationalError
from telethon import TelegramClient, events
from datetime import datetime
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from metaapi_cloud_sdk import MetaApi
from flask import Flask, render_template, request, jsonify
from asyncio import ensure_future, sleep
import os

app = Flask(__name__)

DATABASE = 'trades.db'

def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS trades (
                        trade_id INTEGER PRIMARY KEY,
                        action TEXT,
                        symbol TEXT,
                        entry_price_low REAL,
                        entry_price_high REAL,
                        sl REAL,
                        tp1 REAL,
                        tp2 REAL,
                        status TEXT
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id INTEGER,
                        entry REAL,
                        tp REAL,
                        sl REAL,
                        volume REAL,
                        order_type TEXT,
                        order_id TEXT,
                        status TEXT,
                        FOREIGN KEY(trade_id) REFERENCES trades(trade_id)
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS status (
                        latest_trade_id INTEGER
                      )''')
    conn.commit()
    conn.close()

class Trade:
    def __init__(self, trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2, entries=None, status="open"):
        self.trade_id = trade_id
        self.action = action
        self.symbol = symbol
        self.entry_price_low = round(entry_price_low, 2)
        self.entry_price_high = round(entry_price_high, 2)
        self.sl = round(sl, 2)
        self.tp1 = round(tp1, 2)
        self.tp2 = round(tp2, 2)
        self.entries = entries if entries else []
        self.status = status

    def add_entry(self, entry, tp, sl, volume, order_type="limit"):
        self.entries.append({
            'entry': round(entry, 2),
            'tp': round(tp, 2),
            'sl': round(sl, 2),
            'volume': round(volume, 2),
            'order_type': order_type,
            'order_id': None,
            'status': 'open'
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
market_value = config['market_value']

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
        return round(price['bid'], 2) if price else None
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
        
        for entry in trade.entries:
            entry_price = entry['entry']
            tp = entry['tp']
            sl = entry['sl']
            volume = entry['volume']
            order_type = entry['order_type']
            
            def switch_order_type(order_type):
                return "stop" if order_type == "limit" else "limit"

            def print_order_info(order_type, result):
                print(f"Placing {trade.action.capitalize()} {order_type} order: symbol={trade.symbol}, volume={volume}, entry_price={entry_price}, sl={sl}, tp={tp}")
                if 'orderId' in result:
                    order_id = result['orderId']
                    entry['order_id'] = order_id
                    print(f"Order placed successfully: {result['stringCode']} with order_id: {order_id}")
                else:
                    print(f"Order placement failed: {result}")

            try:
                if trade.action.lower() == "buy":
                    print_order_info(order_type, await (connection.create_limit_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp) if order_type == "limit" else connection.create_stop_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)))
                else:
                    print_order_info(order_type, await (connection.create_limit_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp) if order_type == "limit" else connection.create_stop_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)))
            except Exception as e:
                print(f"{order_type.capitalize()} order failed, retrying with {switch_order_type(order_type)} order: {e}")
                try:
                    if trade.action.lower() == "buy":
                        print_order_info(switch_order_type(order_type), await (connection.create_stop_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp) if order_type == "limit" else connection.create_limit_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)))
                    else:
                        print_order_info(switch_order_type(order_type), await (connection.create_stop_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp) if order_type == "limit" else connection.create_limit_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)))
                except Exception as e:
                    print(f"Order placement failed on retry: {e}")

        await save_trade(trade)
        await update_status(trade.trade_id)
        return True
    except Exception as e:
        print(f"Error placing trade: {e}")
        return False

async def check_orders_and_positions(account):
    while True:
        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM trades ORDER BY trade_id DESC LIMIT 5')
            recent_trades = cursor.fetchall()

            for trade_row in recent_trades:
                trade_id = trade_row['trade_id']
                cursor.execute('SELECT * FROM entries WHERE trade_id = ?', (trade_id,))
                entries = cursor.fetchall()

                connection = account.get_rpc_connection()
                await connection.connect()
                await connection.wait_synchronized()

                for entry in entries:
                    order_id = entry['order_id']
                    if order_id:
                        try:
                            print(f"Checking order {order_id}")
                            order_status = await connection.get_order(order_id)
                            print(f"Order status for {order_id}: {order_status}")
                            if order_status:
                                entry_status = 'filled' if 'filledVolume' in order_status and order_status['filledVolume'] > 0 else 'open'
                                cursor.execute('UPDATE entries SET status = ? WHERE id = ?', (entry_status, entry['id']))
                                print(f"Updated entry status for {order_id} to {entry_status}")
                            else:
                                cursor.execute('UPDATE entries SET status = ? WHERE id = ?', ('closed', entry['id']))
                                print(f"Order {order_id} is closed")
                        except Exception as e:
                            if "Order with specified id not found" in str(e):
                                cursor.execute('UPDATE entries SET status = ? WHERE id = ?', ('closed', entry['id']))
                                print(f"Order {order_id} not found, marking as closed")
                            else:
                                print(f"Error checking order {order_id}: {e}")

                conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error checking orders and positions: {e}")

        await sleep(2.5)

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

async def execute_with_retry(sql, params):
    conn = get_db()
    cursor = conn.cursor()
    retries = 5
    for attempt in range(retries):
        try:
            cursor.execute(sql, params)
            conn.commit()
            return
        except OperationalError as e:
            if 'database is locked' in str(e) and attempt < retries - 1:
                print(f"Database is locked, retrying... ({attempt + 1}/{retries})")
                await sleep(0.5)
            else:
                raise
    conn.close()

async def save_trade(trade):
    await execute_with_retry('''INSERT OR REPLACE INTO trades (trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2, status)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (trade.trade_id, trade.action, trade.symbol, trade.entry_price_low, trade.entry_price_high, trade.sl, trade.tp1, trade.tp2, trade.status))

    await execute_with_retry('DELETE FROM entries WHERE trade_id = ?', (trade.trade_id,))
    for entry in trade.entries:
        await execute_with_retry('''INSERT INTO entries (trade_id, entry, tp, sl, volume, order_type, order_id, status)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                           (trade.trade_id, entry['entry'], entry['tp'], entry['sl'], entry['volume'], entry['order_type'], entry['order_id'], entry['status']))

async def update_status(trade_id):
    await execute_with_retry('DELETE FROM status', ())
    await execute_with_retry('INSERT INTO status (latest_trade_id) VALUES (?)', (trade_id,))

def get_latest_trade_id():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT latest_trade_id FROM status LIMIT 1')
    result = cursor.fetchone()
    conn.close()
    return result['latest_trade_id'] if result else None

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
        await asyncio.sleep(60)
        return await interpret_message(text)
    except Exception as e:
        print(f"Error interpreting message: {e}")
        return None

def parse_trade_message(details, trade_id):
    try:
        action = details['action']
        symbol = "XAUUSD+"
        entry_price_low = details['entry_price_low']
        entry_price_high = details['entry_price_high']
        sl = details['sl']
        tp1 = details['tp1']
        tp2 = details['tp2']

        print(f"Parsed trade message: action={action}, symbol={symbol}, entry_price_low={entry_price_low}, entry_price_high={entry_price_high}, sl={sl}, tp1={tp1}, tp2={tp2}")

        trade = Trade(trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2)

        step = (entry_price_high - entry_price_low) / 11

        if action.lower() == "buy":
            volumes = [0.03] * 4 + [0.02] * 4 + [0.01] * 4
        else:
            volumes = [0.01] * 4 + [0.02] * 4 + [0.03] * 4

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
        trade_id = message.id
        trade = parse_trade_message(details, trade_id)
        if trade:
            account = await connect_metaapi()
            if account:
                await save_trade(trade)
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

    try:
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
            trade.add_entry(current_price, tp, sl, volume, order_type='market')
            await save_trade(trade)
            print(f"Placed additional market order: {result}")
    except metaapi_cloud_sdk.clients.error_handler.ValidationException as e:
        print(f"Error placing additional market order: {e}")
        

async def close_all_orders(account, trade_id):
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,))
        trade_row = cursor.fetchone()

        if not trade_row:
            print(f"No trade found with trade_id: {trade_id}")
            return

        trade = Trade(
            trade_id=trade_row['trade_id'],
            action=trade_row['action'],
            symbol=trade_row['symbol'],
            entry_price_low=trade_row['entry_price_low'],
            entry_price_high=trade_row['entry_price_high'],
            sl=trade_row['sl'],
            tp1=trade_row['tp1'],
            tp2=trade_row['tp2'],
            status=trade_row['status']
        )

        cursor.execute('SELECT * FROM entries WHERE trade_id = ?', (trade_id,))
        trade.entries = cursor.fetchall()

        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        for entry in trade.entries:
            order_id = entry['order_id']
            if order_id:
                print(f"Closing order: {order_id}")
                await connection.cancel_order(order_id)
                entry['status'] = 'closed'

        trade.status = 'closed'
        await save_trade(trade)
        
        print(f"All orders for trade_id {trade_id} closed successfully")
    except Exception as e:
        print(f"Error closing orders: {e}")

async def fetch_positions(account):
    try:
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        positions = []
        open_positions = await connection.get_positions()
        for pos in open_positions:
            symbol = pos['symbol']
            order_id = pos['id']
            volume = pos['volume']
            entry_price = pos['openPrice']
            sl = pos.get('stopLoss', 'N/A')
            tp = pos.get('takeProfit', 'N/A')
            current_price = await get_current_price(account, symbol)
            current_pl = pos['unrealizedProfit']
            comment = "Gold Trader Ben"
            positions.append({
                'order_id': order_id,
                'symbol': symbol,
                'time': pos['brokerTime'],
                'entry_price': entry_price,
                'current_pl': current_pl,
                'volume': volume,
                'sl': sl,
                'tp': tp,
                'comment': comment
            })
        return positions
    except Exception as e:
        print(f"Error fetching positions: {e}")
        return []

async def fetch_open_orders(account):
    try:
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        open_orders = []
        open_orders_data = await connection.get_orders()
        for order in open_orders_data:
            try:
                symbol = order['symbol']
                order_id = order['id']
                volume = order['volume']
                entry_price = order.get('price', 'N/A')
                sl = order.get('stopLoss', 'N/A')
                tp = order.get('takeProfit', 'N/A')
                comment = "Gold Trader Ben"
                current_pl = 'N/A'
                open_orders.append({
                    'order_id': order_id,
                    'symbol': symbol,
                    'time': order['brokerTime'],
                    'entry_price': entry_price,
                    'current_pl': current_pl,
                    'volume': volume,
                    'sl': sl,
                    'tp': tp,
                    'comment': comment
                })
            except KeyError as e:
                print(f"Error processing order data: missing key {e}")
        return open_orders
    except Exception as e:
        print(f"Error fetching open orders: {e}")
        return []

async def update_trade_status(account, trade_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM entries WHERE trade_id = ?', (trade_id,))
    entries = cursor.fetchall()
    
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()
    
    for entry in entries:
        if entry['status'] == 'open':
            order = await connection.get_order(entry['order_id'])
            if order:
                if 'filledVolume' in order and order['filledVolume'] > 0:
                    entry['status'] = 'filled'
                elif order['state'] == 'cancelled':
                    entry['status'] = 'closed'
    
    for entry in entries:
        cursor.execute('UPDATE entries SET status = ? WHERE id = ?', (entry['status'], entry['id']))
    
    conn.commit()
    conn.close()

async def update_recent_trades(account):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT trade_id FROM trades ORDER BY trade_id DESC LIMIT 5')
    recent_trades = cursor.fetchall()
    
    for trade in recent_trades:
        await update_trade_status(account, trade['trade_id'])

@app.route('/')
async def index():
    return render_template('index.html')

@app.route('/trades_and_orders', methods=['GET'])
async def trades_and_orders():
    account = await connect_metaapi()
    if not account:
        return jsonify({'ongoing_trades': [], 'open_orders': []})
    
    await update_recent_trades(account)
    
    ongoing_trades = await fetch_positions(account)
    open_orders = await fetch_open_orders(account)
    return jsonify({
        'ongoing_trades': ongoing_trades,
        'open_orders': open_orders
    })

@app.route('/close_orders', methods=['POST'])
async def close_orders():
    trade_id = get_latest_trade_id()
    if trade_id:
        account = await connect_metaapi()
        if account:
            await close_all_orders(account, trade_id)
    return jsonify({'message': 'All orders closed successfully'})

@app.route('/close_order/<order_id>', methods=['POST'])
async def close_specific_order(order_id):
    try:
        account = await connect_metaapi()
        if not account:
            return jsonify({'error': 'Failed to connect to MetaApi'}), 500

        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        print(f"Closing specific order: {order_id}")
        await connection.cancel_order(order_id)
        print(f"Order {order_id} closed successfully")

        return jsonify({'message': f'Order {order_id} closed successfully'})
    except Exception as e:
        print(f"Error closing order: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/close_position/<position_id>', methods=['POST'])
async def close_specific_position(position_id):
    try:
        account = await connect_metaapi()
        if not account:
            return jsonify({'error': 'Failed to connect to MetaApi'}), 500

        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        print(f"Closing specific position: {position_id}")
        await connection.close_position(position_id)
        print(f"Position {position_id} closed successfully")

        return jsonify({'message': f'Position {position_id} closed successfully'})
    except Exception as e:
        print(f"Error closing position: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return 'Server shutting down...'

async def main():
    print("Starting Telegram client...")
    await client.start(phone_number)
    print(f'Listening to new messages in {target_channel}...')

    await client.run_until_disconnected()

def run():
    loop = asyncio.get_event_loop()
    app_task = loop.run_in_executor(None, app.run, '0.0.0.0', 8888)
    telegram_task = ensure_future(main())

    account = loop.run_until_complete(connect_metaapi())
    if account:
        checker_task = ensure_future(check_orders_and_positions(account))
        loop.run_until_complete(asyncio.gather(app_task, telegram_task, checker_task))
    else:
        loop.run_until_complete(asyncio.gather(app_task, telegram_task))

if __name__ == "__main__":
    if os.path.exists(DATABASE):
        os.remove(DATABASE)
    init_db()
    run()
