class Trade:
    def __init__(self, trade_id, action, symbol, entry_price_low, entry_price_high, sl, tp1, tp2):
        self.trade_id = trade_id
        self.action = action
        self.symbol = symbol
        self.entry_price_low = entry_price_low
        self.entry_price_high = entry_price_high
        self.sl = sl
        self.tp1 = tp1
        self.tp2 = tp2
        self.entries = []

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
