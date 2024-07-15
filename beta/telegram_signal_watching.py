from telethon import TelegramClient, events
import asyncio
import json
import logging
from openai_signal_parsing import interpret_message
from order_placement import handle_trade

async def start_telegram_client(api_id, api_hash, phone_number, target_channel, metaapi_account, openai_api_key):
    client = TelegramClient('session_name', api_id, api_hash)
    await client.start(phone_number)

    @client.on(events.NewMessage(chats=target_channel))
    async def handler(event):
        message = event.message
        text = message.message or ""
        if not text and message.media and hasattr(message.media, 'caption'):
            text = message.media.caption or ""

        if not text and message.grouped_id:
            async for grouped_message in client.iter_messages(target_channel, limit=50):
                if grouped_message.grouped_id == message.grouped_id:
                    text += grouped_message.message or grouped_message.media.caption or ""

        details = await interpret_message(text, openai_api_key)
        if details:
            await handle_trade(metaapi_account, details, message.id)

    logging.info(f'Listening to new messages in {target_channel}...')
    await client.run_until_disconnected()
