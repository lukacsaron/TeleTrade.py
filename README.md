# TeleTrade.py

Reads trading signals out of Telegram channels, parses the free text with an LLM, and tracks what happened to each trade.

> [!CAUTION]
> **Do not run this repo as-is.** Earlier commits contain a Telethon `.session` file, which is a live Telegram account credential. See [Security](#security) below. Nothing here is investment advice, and automated order placement against a live broker account loses money fast.

## The problem

Telegram signal channels post in prose, and every channel posts differently:

```
SHORT NQ
STOP @20,326.25
TP1 20286.25
TP2 20237.00
```

Another channel writes the same trade on one line with different words. Some split a single signal across four messages sent seconds apart. Regex parsers break on the next channel you subscribe to.

So the parsing is a language problem, handed to a language model. `parsers/openai_parser.py` sends the raw message text with a schema and gets structured JSON back:

```json
{
  "instrument": "NQ",
  "action": "Sell",
  "entry_price_range": null,
  "stop_loss": 20326.25,
  "take_profits": [20286.25, 20237.00, 20190.00],
  "notes": []
}
```

## Multi-message signals

A signal split across messages needs reassembly. `app.py` buffers incoming messages per `chat_id + sender_id` and holds them until it sees an action word, a stop and at least one take-profit, then parses the joined text. Anything still incomplete after five minutes gets dropped with a warning.

Crude, and it worked well enough on the channels I was watching.

## Tracking execution

Each parsed signal gets a UUID `signal_id`, and every order placed against it carries that id. The schema in `models/signal_models.py` tracks `orders_placed`, `entry_fulfilled`, per-target `tp_fulfilled`, `sl_fulfilled` and `trade_closed`, so you can ask afterwards which channels actually produced trades that hit target.

That was the real point of the project. Signal channels advertise win rates. This measures them.

## Two generations in one repo

**`app.py` + `config.py` + `parsers/` + `models/` + `database/`** is v1 from September 2024. Telethon listener, OpenAI parsing, MongoDB storage, pydantic models. Signal capture only.

**`TeleTrade.py(0.1).py/`** is the earlier prototype from July 2024: one 41KB `main.py` doing everything, SQLite instead of Mongo, a Flask status page, and live order placement through [MetaApi](https://metaapi.cloud/) into MetaTrader. It placed real orders, split entries across a price range, and polled order status.

The rewrite dropped execution and kept capture, because getting the parsing right mattered more than automating the losing.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env
python app.py
```

```
API_ID=            # my.telegram.org
API_HASH=
OPENAI_API_KEY=
MONGO_URI=
CHANNEL_IDS=       # comma-separated
LOG_LEVEL=INFO
```

Telethon writes `session_name.session` on first login. **That file is a credential. Keep it out of git.**

The OpenAI call still targets the Completions API with `text-davinci-003`, retired in January 2024. Porting it to the Chat Completions API is the first thing to fix.

## Security

This repo was private while I was building it and went public later. A cleanup is outstanding:

- `TeleTrade.py(0.1).py/session_name.session` sits in the current tree, and 23 session blobs across at least three distinct auth keys sit in the history. A Telethon session authenticates as the account without a phone code or a password. Anyone with a clone can use it.
- The session files cache the channels the account subscribed to.
- `trades.db`, `trades.json` and `db_log.txt` hold real order history from a live account.

No API keys are hardcoded. `config.py` and `main.py` both read from the environment.

**If you cloned this: delete it.** The sessions are being revoked.

## License

MIT. Educational use. Trade your own money at your own risk.
