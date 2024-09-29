# app.py
import asyncio
import logging
from telethon import TelegramClient, events
from config import API_ID, API_HASH, CHANNEL_IDS, LOG_LEVEL
from parsers.openai_parser import parse_signal_with_openai
from database.mongo_client import get_database
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

client = TelegramClient('session_name', API_ID, API_HASH)
db = get_database()
signals_collection = db['signals']

# Pending signals for multi-message handling
pending_signals = {}

async def main():
    await client.start()
    me = await client.get_me()
    logger.info(f"Logged in as {me.username}")

    # Convert CHANNEL_IDS to integers if they are numeric
    channel_ids = []
    for channel_id in CHANNEL_IDS:
        if channel_id.strip():
            try:
                channel_ids.append(int(channel_id.strip()))
            except ValueError:
                channel_ids.append(channel_id.strip())

    @client.on(events.NewMessage(chats=channel_ids))
    async def handler(event):
        message = event.message
        sender_id = message.sender_id
        chat_id = event.chat_id
        message_id = message.id
        text = message.message.strip()

        logger.info(f"Received message {message_id} from chat {chat_id}")

        # Check if there is an existing pending signal for this chat and sender
        key = f"{chat_id}_{sender_id}"
        if key in pending_signals:
            # Append message to existing pending signal
            pending_signals[key]['messages'].append(text)
            pending_signals[key]['last_update'] = datetime.utcnow()

            if is_signal_complete(pending_signals[key]['messages']):
                full_message = "\n".join(pending_signals[key]['messages'])
                await process_message(full_message, message_id, chat_id)
                del pending_signals[key]
        else:
            # Start new pending signal
            pending_signals[key] = {
                'messages': [text],
                'last_update': datetime.utcnow()
            }

            if is_signal_complete(pending_signals[key]['messages']):
                full_message = "\n".join(pending_signals[key]['messages'])
                await process_message(full_message, message_id, chat_id)
                del pending_signals[key]

        # Clean up old pending signals (optional)
        await clean_up_pending_signals()

    await client.run_until_disconnected()

def is_signal_complete(messages):
    """
    Determines if a multi-message signal is complete based on the content.
    For Signal Type 3, we might expect at least:
    - An action message (e.g., 'SHORT NQ')
    - A stop-loss message (e.g., 'STOP @20,326.25')
    - At least one take-profit message
    """
    actions = ['BUY', 'SELL', 'LONG', 'SHORT']
    has_action = any(any(action in msg.upper() for action in actions) for msg in messages)
    has_stop = any('STOP' in msg.upper() or 'SL' in msg.upper() for msg in messages)
    has_tp = any('TP' in msg.upper() or 'TAKE PROFIT' in msg.upper() for msg in messages)

    return has_action and has_stop and has_tp

async def clean_up_pending_signals():
    """
    Removes pending signals that have not been updated for a certain timeout period.
    """
    timeout = timedelta(minutes=5)
    now = datetime.utcnow()
    keys_to_delete = [key for key, value in pending_signals.items() if now - value['last_update'] > timeout]

    for key in keys_to_delete:
        logger.warning(f"Pending signal {key} timed out")
        del pending_signals[key]

async def process_message(text, message_id, chat_id):
    signal_data = parse_signal_with_openai(text)
    if signal_data:
        signal_data['message_id'] = message_id
        signal_data['chat_id'] = chat_id
        try:
            signals_collection.insert_one(signal_data)
            logger.info(f"Signal {signal_data['signal_id']} saved to database")
        except Exception as e:
            logger.error(f"Failed to save signal to database: {e}")
    else:
        logger.warning(f"Could not parse message: {text}")

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
