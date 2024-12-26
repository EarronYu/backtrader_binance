import math
from binance.client import Client

from ConfigBinance.Config import Config

# Initialize the Binance client
api_key = Config.BINANCE_API_KEY
api_secret = Config.BINANCE_API_SECRET
client = Client(api_key, api_secret)

def get_symbol_precision(symbol):
    exchange_info = client.futures_exchange_info()
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    quantity_precision = int(round(-math.log10(float(f['stepSize']))))
                if f['filterType'] == 'PRICE_FILTER':
                    price_precision = int(round(-math.log10(float(f['tickSize']))))
            return quantity_precision, price_precision
    return None, None

# Example function to place a futures order
def place_futures_order(symbol, side, order_type, quantity, price=None):
    try:
        if order_type == 'LIMIT':
            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                timeInForce='GTC'
            )
        elif order_type == 'MARKET':
            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity
            )
        else:
            raise ValueError("Unsupported order type")
        
        print("Order placed successfully:", order)
    except Exception as e:
        print("An error occurred:", e)

# Example usage
symbol = 'BTCUSDT'
side = 'BUY'
order_type = 'LIMIT'
quantity = 0.0018
price = 90000


# Get precision for the symbol
quantity_precision, price_precision = get_symbol_precision(symbol)

# Adjust quantity and price to match precision
quantity = round(quantity, quantity_precision)
price = round(price, price_precision)

place_futures_order(symbol, side, order_type, quantity, price)