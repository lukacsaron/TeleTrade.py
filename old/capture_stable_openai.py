import json
import base64
import openai
import asyncio
from telethon import TelegramClient, events
from datetime import datetime
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from metaapi_cloud_sdk import MetaApi

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
metaapi_region = config.get('metaapi_region', 'london')  # Default to london if not set

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

async def place_orders(account, trade):
    if not account:
        raise Exception("Account not connected")

    try:
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        # Place the limit orders in the zone
        for entry in trade.entries:
            entry_price = entry['entry']
            tp = entry['tp']
            sl = entry['sl']
            volume = entry['volume']
            order_type = entry['order_type']
            print(f"Placing {trade.action} {order_type} order: symbol={trade.symbol}, volume={volume}, entry_price={entry_price}, sl={sl}, tp={tp}")
            if trade.action.lower() == "buy":
                if order_type == "limit":
                    result = await connection.create_limit_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
                else:
                    result = await connection.create_market_buy_order(trade.symbol, volume, stop_loss=sl, take_profit=tp)
            else:
                if order_type == "limit":
                    result = await connection.create_limit_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
                else:
                    result = await connection.create_market_sell_order(trade.symbol, volume, stop_loss=sl, take_profit=tp)
            
            if 'orderId' in result:
                order_id = result['orderId']
                entry['order_id'] = order_id
                print(f"Order placed successfully: {result['stringCode']} with order_id: {order_id}")
            else:
                print(f"Order placement failed: {result}")

        # Save updated trade with order_ids
        save_trade(trade)

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
    except (FileNotFoundError, json.JSONDecodeError):
        trades = []

    # Ensure trades is a list
    if not isinstance(trades, list):
        trades = []

    # Find and update the existing trade or append a new one
    for i, t in enumerate(trades):
        if 'trade_id' in t and t['trade_id'] == trade.trade_id:
            trades[i] = trade.to_dict()
            break
    else:
        trades.append(trade.to_dict())

    # Save the updated list of trades
    with open('trades.json', 'w') as f:
        json.dump(trades, f, default=default, indent=4)

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
    except openai.error.RateLimitError as e:
        print("Rate limit exceeded. Waiting before retrying...")
        await asyncio.sleep(60)  # Wait for 1 minute before retrying
        return await interpret_message(text)
    except Exception as e:
        print(f"Error interpreting message: {e}")
        return None

def parse_trade_message(details, trade_id):
    try:
        action = details['action']
        symbol = "XAUUSD"  # Always use XAUUSD
        entry_price_low = details['entry_price_low']
        entry_price_high = details['entry_price_high']
        sl = details['sl']
        tp1 = details['tp1']
        tp2 = details['tp2']

        print(f"Parsed trade message: action={action}, symbol={symbol}, entry_price_low={entry_price_low}, entry_price_high={entry_price_high}, sl={sl}, tp1={tp1}, tp2={tp2}")

        trade = Trade(trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2)

        step = (entry_price_high - entry_price_low) / 11  # Step between entries to evenly distribute within the zone

        if action.lower() == "buy":
            volumes = [0.01] * 4 + [0.02] * 4 + [0.03] * 4  # Buy: Top -> 0.01, Middle -> 0.02, Bottom -> 0.03
        else:
            volumes = [0.03] * 4 + [0.02] * 4 + [0.01] * 4  # Sell: Top -> 0.03, Middle -> 0.02, Bottom -> 0.01

        for i in range(12):
            price = entry_price_low + i * step
            volume = volumes[i]
            if i < 4:
                tp = tp1
            else:
                tp = tp2
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

    # Use OpenAI to interpret the message
    details = await interpret_message(text)
    message_dict['parsed_details'] = details

    # If it's a trade message, parse and execute the trade
    if details:
        trade_id = message.id  # Use the message ID as the trade ID
        trade = parse_trade_message(details, trade_id)
        if trade:
            # Close all previous open trades
            account = await connect_metaapi()
            if account:
                await close_all_open_trades(account)

            save_trade(trade)
            if account:
                await place_orders(account, trade)

                # Place the immediate market order with 0.01 volume
                await place_immediate_market_order(account, trade)
                
                print("Trade placed successfully in MetaAPI")

    # Save the latest message to the JSON file
    with open('messages.json', 'w') as f:
        json.dump(message_dict, f, default=default, indent=4)

    print(f"New message: {message_dict}")

async def place_immediate_market_order(account, trade):
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    symbol_price = await connection.get_symbol_price(trade.symbol)
    current_price = symbol_price['bid'] if trade.action.lower() == 'buy' else symbol_price['ask']
    sl = trade.sl
    tp1 = trade.tp1
    tp2 = trade.tp2
    volume = 0.01

    # Place the market order
    print(f"Placing immediate market order: symbol={trade.symbol}, volume={volume}")
    if trade.action.lower() == "buy":
        result = await connection.create_market_buy_order(trade.symbol, volume, stop_loss=sl, take_profit=tp1)
    else:
        result = await connection.create_market_sell_order(trade.symbol, volume, stop_loss=sl, take_profit=tp1)

    print(f"Placed market order: {result}")

    # Place two limit orders above and below the current price at 0.1 distance each
    limit_distance = 0.1

    if trade.action.lower() == "buy":
        entry_prices = [current_price - limit_distance, current_price + limit_distance]
    else:
        entry_prices = [current_price + limit_distance, current_price - limit_distance]

    for entry_price in entry_prices:
        if trade.action.lower() == "buy":
            result = await connection.create_limit_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp2)
        else:
            result = await connection.create_limit_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp2)

        print(f"Placed limit order at {entry_price}: {result}")

async def close_all_open_trades(account):
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    open_positions = await connection.get_positions()

    for position in open_positions:
        symbol = position['symbol']
        volume = position['volume']
        action = 'sell' if position['type'] == 'buy' else 'buy'
        print(f"Closing open position: symbol={symbol}, volume={volume}")
        if action == 'buy':
            await connection.create_market_buy_order(symbol, volume)
        else:
            await connection.create_market_sell_order(symbol, volume)

async def manage_trades(account):
    while True:
        try:
            try:
                with open('trades.json', 'r') as f:
                    trades = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                trades = []

            connection = account.get_rpc_connection()
            await connection.connect()
            await connection.wait_synchronized()
            open_orders = await connection.get_orders()
            positions = await connection.get_positions()
            server_time = await connection.get_server_time()

            for trade in trades:
                if trade['status'] == 'closed':
                    continue
                all_closed = True
                for entry in trade['entries']:
                    order_id = entry.get('order_id')
                    if order_id and entry['status'] != 'closed':
                        all_closed = False
                        try:
                            order_status = await connection.get_order(order_id)
                            if order_status and order_status['state'] == 'CLOSED':
                                entry['status'] = 'closed'
                                print(f"Order manually closed: {order_id}")
                        except Exception as e:
                            if 'Order with specified id not found' in str(e):
                                entry['status'] = 'closed'
                                print(f"Order with specified id not found: {order_id}. Marking as closed.")
                            else:
                                print(f"Error retrieving order status for {order_id}: {e}")

                if all_closed:
                    trade['status'] = 'closed'

                # Update trades.json with order status
                trade_obj = Trade(**trade)
                save_trade(trade_obj)

                # Check for filled orders and update filled entries
                for entry in trade['entries']:
                    if entry['status'] == 'open':
                        for order in open_orders:
                            if order['id'] == entry['order_id'] and order['currentPrice'] == entry['entry']:
                                entry['status'] = 'filled'
                                trade['filled_entries'].append(entry)
                                print(f"Order filled: {order}")

                # Manage trades based on filled entries
                for filled_entry in trade['filled_entries']:
                    if filled_entry['status'] == 'filled':
                        # Move SL to BE if TP1 is reached
                        if filled_entry['tp'] == trade['tp1']:
                            filled_entry['sl'] = filled_entry['entry']
                            await connection.modify_order(filled_entry['order_id'], stop_loss=filled_entry['sl'])
                            print(f"SL moved to BE for entry: {filled_entry}")

                        # Close half of the entries when TP1 is reached
                        if filled_entry['tp'] == trade['tp1']:
                            half_volume = filled_entry['volume'] / 2
                            await connection.create_market_order(trade['symbol'], 'sell' if trade['action'].lower() == 'buy' else 'buy', half_volume)
                            print(f"Closed half of the entries for TP1: {filled_entry}")

                        # Close remaining entries at TP2
                        if filled_entry['tp'] == trade['tp2']:
                            await connection.create_market_order(trade['symbol'], 'sell' if trade['action'].lower() == 'buy' else 'buy', filled_entry['volume'])
                            print(f"Closed remaining entries at TP2: {filled_entry}")

            await asyncio.sleep(5)  # Adjust the frequency of monitoring as needed

        except Exception as e:
            print(f"Error managing trades: {e}")
            await asyncio.sleep(5)  # Retry after a short delay

async def main():
    print("Starting Telegram client...")
    await client.start(phone_number)  # Start the client and authenticate if needed
    print(f'Listening to new messages in {target_channel}...')

    account = await connect_metaapi()
    if account:
        asyncio.create_task(manage_trades(account))

    await client.run_until_disconnected()

def run():
    asyncio.run(main())

if __name__ == "__main__":
    run()
