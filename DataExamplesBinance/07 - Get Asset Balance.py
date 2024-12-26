from binance.client import Client
from ConfigBinance.Config import Config

client = Client(Config.BINANCE_API_KEY, Config.BINANCE_API_SECRET, testnet=Config.TESTNET)

asset = 'BTC'

balance = client.futures_account_balance(asset=asset)

print(f" - Balance for {asset} is {balance['free']}")