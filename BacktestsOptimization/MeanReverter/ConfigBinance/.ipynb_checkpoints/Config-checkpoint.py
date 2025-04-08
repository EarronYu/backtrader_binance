import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY") if os.getenv("TESTNET") == '1' else os.getenv("BINANCE_API_KEY_LIVE")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET") if os.getenv("TESTNET") == '1' else os.getenv("BINANCE_API_SECRET_LIVE")
    TESTNET = os.getenv("TESTNET") == '1'
