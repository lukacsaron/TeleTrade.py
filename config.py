# config.py
import os
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGO_URI = os.getenv('MONGO_URI')
CHANNEL_IDS = os.getenv('CHANNEL_IDS', '').split(',')

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
