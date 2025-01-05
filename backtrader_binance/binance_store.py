import time

from functools import wraps
from math import floor

from backtrader.dataseries import TimeFrame
from binance import Client, ThreadedWebsocketManager
from binance.enums import *
from binance.exceptions import BinanceAPIException
from requests.exceptions import ConnectTimeout, ConnectionError

from .binance_broker import BinanceBroker
from .binance_feed import BinanceData


class BinanceStore(object):
    _GRANULARITIES = {
        (TimeFrame.Minutes, 1): KLINE_INTERVAL_1MINUTE,
        (TimeFrame.Minutes, 3): KLINE_INTERVAL_3MINUTE,
        (TimeFrame.Minutes, 5): KLINE_INTERVAL_5MINUTE,
        (TimeFrame.Minutes, 15): KLINE_INTERVAL_15MINUTE,
        (TimeFrame.Minutes, 30): KLINE_INTERVAL_30MINUTE,
        (TimeFrame.Minutes, 60): KLINE_INTERVAL_1HOUR,
        (TimeFrame.Minutes, 120): KLINE_INTERVAL_2HOUR,
        (TimeFrame.Minutes, 240): KLINE_INTERVAL_4HOUR,
        (TimeFrame.Minutes, 360): KLINE_INTERVAL_6HOUR,
        (TimeFrame.Minutes, 480): KLINE_INTERVAL_8HOUR,
        (TimeFrame.Minutes, 720): KLINE_INTERVAL_12HOUR,
        (TimeFrame.Days, 1): KLINE_INTERVAL_1DAY,
        (TimeFrame.Days, 3): KLINE_INTERVAL_3DAY,
        (TimeFrame.Weeks, 1): KLINE_INTERVAL_1WEEK,
        (TimeFrame.Months, 1): KLINE_INTERVAL_1MONTH,
    }

    def __init__(self, api_key, api_secret, coin_target, testnet=False, retries=5, tld='com'):  # coin_refer, coin_target
        self.binance = Client(api_key, api_secret, testnet=testnet, tld=tld)
        self.binance_socket = ThreadedWebsocketManager(api_key, api_secret, testnet=testnet)
        self.binance_socket.daemon = True
        self.binance_socket.start()
        # self.coin_refer = coin_refer
        self.coin_target = coin_target  # USDT
        # self.symbol = coin_refer + coin_target
        self.symbols = []  # symbols
        self.retries = retries

        self._cash = 0
        self._value = 0
        self.get_balance()

        self._step_size = {}
        self._min_order = {}
        self._min_order_in_target = {}
        self._tick_size = {}

        self._broker = BinanceBroker(store=self)
        self._data = None
        self._datas = {}

    def _format_value(self, value, step):
        precision = step.find('1') - 1
        if precision > 0:
            return '{:0.0{}f}'.format(float(value), precision)
        return floor(int(value))
        
    def retry(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            for attempt in range(1, self.retries + 1):
                time.sleep(60 / 1200) # API Rate Limit
                try:
                    return func(self, *args, **kwargs)
                except (BinanceAPIException, ConnectTimeout, ConnectionError) as err:
                    if isinstance(err, BinanceAPIException) and err.code == -1021:
                        # Recalculate timestamp offset between local and Binance's server
                        res = self.binance.get_server_time()
                        self.binance.timestamp_offset = res['serverTime'] - int(time.time() * 1000)
                    
                    if attempt == self.retries:
                        raise
        return wrapper

    @retry
    def cancel_open_orders(self, symbol):
        orders = self.binance.get_open_orders(symbol=symbol)
        if len(orders) > 0:
            self.binance._request_api('delete', 'openOrders', signed=True, data={ 'symbol': symbol })

    @retry
    def cancel_order(self, symbol, order_id):
        try:
            self.binance.cancel_order(symbol=symbol, orderId=order_id)
        except BinanceAPIException as api_err:
            if api_err.code == -2011:  # Order filled
                return
            else:
                raise api_err
        except Exception as err:
            raise err
    
    @retry
    def create_order(self, symbol, side, type, size, price):
        params = dict()
        if type in [ORDER_TYPE_LIMIT, ORDER_TYPE_STOP_LOSS_LIMIT]:
            params.update({
                'timeInForce': TIME_IN_FORCE_GTC
            })
        if type == ORDER_TYPE_STOP_LOSS:
            params.update({
                'stopPrice': self.format_price(symbol, price)
            })
        elif type != ORDER_TYPE_MARKET:
            params.update({
                'price': self.format_price(symbol, price)
            })

        return self.binance.create_order(
            symbol=symbol,
            side=side,
            type=type,
            quantity=self.format_quantity(symbol, size),
            newOrderRespType='RESULT',
            **params)

    def format_price(self, symbol, price):
        return self._format_value(price, self._tick_size[symbol])
    
    def format_quantity(self, symbol, size):
        return self._format_value(size, self._step_size[symbol])

    @retry
    def get_asset_balance(self, asset):
        balance = self.binance.get_asset_balance(asset)
        return float(balance['free']), float(balance['locked'])

    def get_symbol_balance(self, symbol):
        """Get symbol balance in symbol"""
        balance = 0
        try:
            symbol = symbol[0:len(symbol)-len(self.coin_target)]
            balance = self.binance.get_asset_balance(symbol)
            balance = float(balance['free'])
        except Exception as e:
            print("Error:", e)
        return balance, symbol  # float(balance['locked'])

    def get_balance(self, ):
        """Balance in USDT for example - in coin target"""
        free, locked = self.get_asset_balance(self.coin_target)
        self._cash = free
        self._value = free + locked

    def getbroker(self):
        return self._broker

    def getdata(self, **kwargs):  # timeframe, compression, start_date=None, LiveBars=True
        symbol = kwargs['dataname']
        tf = self.get_interval(kwargs['timeframe'], kwargs['compression'])
        self.symbols.append(symbol)
        self.get_filters(symbol=symbol)
        if symbol not in self._datas:
            self._datas[f"{symbol}{tf}"] = BinanceData(store=self, **kwargs)  # timeframe=timeframe, compression=compression, start_date=start_date, LiveBars=LiveBars
        return self._datas[f"{symbol}{tf}"]
    
    def prepare_local_data(self, symbol, start_date, end_date, datapath='D:/CryptoData/data/spot'):
        """合并指定日期范围内的数据文件"""
        import pandas as pd
        import datetime
        import os
        
        if end_date is None:
            end_date = datetime.datetime.now()
        
        current_date = start_date.date()
        end_date = end_date.date()
        merged_data = pd.DataFrame()
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            file_path = os.path.join(datapath, date_str, f"{symbol}.csv")
            
            try:
                df = pd.read_csv(file_path)
                if 'datetime' not in df.columns and 'candle_begin_time' in df.columns:
                    df['datetime'] = pd.to_datetime(df['candle_begin_time'])
                    df.drop('candle_begin_time', axis=1, inplace=True)
                else:
                    df['datetime'] = pd.to_datetime(df['datetime'])
                
                df.set_index('datetime', inplace=True)
                merged_data = pd.concat([merged_data, df])
                
            except FileNotFoundError:
                print(f"警告: 未找到数据文件 {file_path}")
            except Exception as e:
                print(f"处理 {date_str} 数据时出错: {str(e)}")
            
            current_date += datetime.timedelta(days=1)
        
        if merged_data.empty:
            raise ValueError(f"在指定日期范围内未找到任何数据: {start_date} 到 {end_date}")
        
        # 排序并删除重复数据
        merged_data = merged_data.sort_index()
        merged_data = merged_data[~merged_data.index.duplicated(keep='first')]
        
        # 保存合并后的数据
        output_dir = os.path.join(datapath, 'merged')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{symbol}_{start_date.date()}_{end_date.date()}.csv")
        merged_data.to_csv(output_path)
        
        return output_path

    def getlocaldata(self, **kwargs):
        symbol = kwargs['dataname']
        tf = self.get_interval(kwargs['timeframe'], kwargs['compression'])
        self.symbols.append(symbol)
        self.get_filters(symbol=symbol)
        
        try:
            local_data_path = self.prepare_local_data(
                symbol=symbol,
                start_date=kwargs.get('start_date'),
                end_date=kwargs.get('end_date'),  # 添加end_date参数
                datapath=kwargs.get('datapath', 'D:/CryptoData/data/spot')  # 可选的datapath参数
            )
            
            kwargs.update({
                'datapath': local_data_path,
                'local': True
            })
            
            if symbol not in self._datas:
                self._datas[f"{symbol}{tf}"] = BinanceData(store=self, **kwargs)
            return self._datas[f"{symbol}{tf}"]
        except Exception as e:
            print(f"读取本地数据失败: {str(e)}")
            return None
        
    def get_filters(self, symbol):
        symbol_info = self.get_symbol_info(symbol)
        for f in symbol_info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                self._step_size[symbol] = f['stepSize']
                self._min_order[symbol] = f['minQty']
            elif f['filterType'] == 'PRICE_FILTER':
                self._tick_size[symbol] = f['tickSize']
            elif f['filterType'] == 'NOTIONAL':
                self._min_order_in_target[symbol] = f['minNotional']

    def get_interval(self, timeframe, compression):
        return self._GRANULARITIES.get((timeframe, compression))

    @retry
    def get_symbol_info(self, symbol):
        return self.binance.get_symbol_info(symbol)

    def stop_socket(self):
        self.binance_socket.stop()
        self.binance_socket.join(5)
