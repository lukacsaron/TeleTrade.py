# database/mongo_client.py
from pymongo import MongoClient
from config import MONGO_URI

def get_database():
    client = MongoClient(MONGO_URI)
    db = client['telegram_signals']
    return db
