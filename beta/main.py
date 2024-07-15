import asyncio
import json
from metaapi_connection import connect_metaapi
from telegram_signal_watching import start_telegram_client
import logging_util

def load_config():
    with open('config.json', 'r') as config_file:
        return json.load(config_file)

async def main():
    config = load_config()
    account = await connect_metaapi(config['metaapi_token'], config['metaapi_account_id'])
    if account:
        await start_telegram_client(
            config['api_id'], 
            config['api_hash'], 
            config['phone_number'], 
            config['target_channel'], 
            account, 
            config['openai_api_key']
        )

if __name__ == "__main__":
    asyncio.run(main())
