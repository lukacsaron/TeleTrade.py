import logging
from trade import Trade
from metaapi_connection import connect_metaapi

async def place_limit_order(account, trade):
    try:
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        for entry in trade.entries:
            entry_price = entry['entry']
            tp = entry['tp']
            sl = entry['sl']
            volume = entry['volume']
            logging.info(f"Placing {trade.action} limit order: symbol={trade.symbol}, volume={volume}, entry_price={entry_price}, sl={sl}, tp={tp}")
            if trade.action == "buy":
                result = await connection.create_limit_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
            else:
                result = await connection.create_limit_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp)
            logging.info(f"Order placed successfully: {result['stringCode']}")
    except Exception as e:
        logging.error(f"Error placing trade: {e}")

async def place_immediate_market_order(account, trade):
    try:
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()

        symbol_price = await connection.get_symbol_price(trade.symbol)
        current_price = symbol_price['bid'] if trade.action.lower() == 'buy' else symbol_price['ask']
        sl = trade.sl
        tp1 = trade.tp1
        tp2 = trade.tp2
        volume = 0.01

        logging.info(f"Placing immediate market order: symbol={trade.symbol}, volume={volume}")
        if trade.action.lower() == "buy":
            result = await connection.create_market_buy_order(trade.symbol, volume, stop_loss=sl, take_profit=tp1)
        else:
            result = await connection.create_market_sell_order(trade.symbol, volume, stop_loss=sl, take_profit=tp1)
        logging.info(f"Placed market order: {result}")

        limit_distance = 0.1
        entry_prices = [current_price - limit_distance, current_price + limit_distance] if trade.action.lower() == "buy" else [current_price + limit_distance, current_price - limit_distance]

        for entry_price in entry_prices:
            if trade.action.lower() == "buy":
                result = await connection.create_limit_buy_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp2)
            else:
                result = await connection.create_limit_sell_order(trade.symbol, volume, entry_price, stop_loss=sl, take_profit=tp2)
            logging.info(f"Placed limit order at {entry_price}: {result}")
    except Exception as e:
        logging.error(f"Error placing immediate market order: {e}")

async def handle_trade(account, details, trade_id):
    action = details['action']
    symbol = "XAUUSD+"
    entry_price_low = details['entry_price_low']
    entry_price_high = details['entry_price_high']
    sl = details['sl']
    tp1 = details['tp1']
    tp2 = details['tp2']

    logging.info(f"Parsed trade message: action={action}, symbol={symbol}, entry_price_low={entry_price_low}, entry_price_high={entry_price_high}, sl={sl}, tp1={tp1}, tp2={tp2}")

    trade = Trade(trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2)
    step = (entry_price_high - entry_price_low) / 11

    volumes = [0.01] * 4 + [0.02] * 4 + [0.03] * 4 if action.lower() == "buy" else [0.03] * 4 + [0.02] * 4 + [0.01] * 4

    for i in range(12):
        price = entry_price_low + i * step
        volume = volumes[i]
        tp = tp1 if i < 4 else tp2
        trade.add_entry(price, tp, sl, volume)

    await place_limit_order(account, trade)
    await place_immediate_market_order(account, trade)
