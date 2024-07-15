import asyncio
import json
from telethon import TelegramClient

# Load configuration from config.json
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

api_id = int(config['api_id'])
api_hash = config['api_hash']
phone_number = config['phone_number']

async def get_private_channel_id():
    async with TelegramClient('session_name', api_id, api_hash) as client:
        print("Logging in...")
        await client.start(phone_number)

        # Get all dialogs (conversations/chats)
        dialogs = await client.get_dialogs()
        
        # Print out all channels and their IDs
        for dialog in dialogs:
            if dialog.is_channel:
                print(f"Channel Name: {dialog.name}, Channel ID: {dialog.id}")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(get_private_channel_id())
