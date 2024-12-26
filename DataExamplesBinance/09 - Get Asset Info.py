from binance.client import Client
from ConfigBinance.Config import Config
from decimal import Decimal

client = Client(Config.BINANCE_API_KEY, Config.BINANCE_API_SECRET, testnet=Config.TESTNET)

asset = 'USDT'

balance = client.futures_account_balance()

print(f" - Balance for {asset} is {balance}")
