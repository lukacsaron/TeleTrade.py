import asyncio
from metaapi_cloud_sdk import MetaApi
import logging

async def connect_metaapi(metaapi_token, metaapi_account_id):
    try:
        logging.info("Connecting to MetaApi...")
        metaapi = MetaApi(metaapi_token)
        account = await metaapi.metatrader_account_api.get_account(metaapi_account_id)
        await account.wait_connected()
        logging.info("Connected to MetaApi")
        return account
    except Exception as e:
        logging.error(f"Error connecting to MetaApi: {e}")
        return None
