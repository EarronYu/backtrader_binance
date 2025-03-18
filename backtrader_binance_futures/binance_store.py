import time
import logging
import functools
from functools import wraps
from math import floor

from backtrader.dataseries import TimeFrame
from binance import Client, ThreadedWebsocketManager
from binance.enums import *
from binance.exceptions import BinanceAPIException
from requests.exceptions import ConnectTimeout, ConnectionError, ReadTimeout

from .binance_broker import BinanceBroker
from .binance_feed import BinanceData

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('BinanceStore')

# 添加函数调试装饰器
def debug_func(func_id):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger.debug(f"[BS-{func_id}] 开始执行: {func.__name__}")
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.debug(f"[BS-{func_id}] 结束执行: {func.__name__}, 耗时: {elapsed:.4f}秒")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"[BS-{func_id}] 执行出错: {func.__name__}, 耗时: {elapsed:.4f}秒, 错误: {str(e)}")
                raise
        return wrapper
    return decorator

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

    @debug_func(1)
    def __init__(self, api_key, api_secret, coin_target, testnet=False, retries=5, tld='com', timeout=5):  # coin_refer, coin_target
        # 移除 timeout 参数，某些版本的 binance 库不支持在构造函数中设置 timeout
        self.binance = Client(api_key, api_secret, testnet=testnet, tld=tld)
        # 尝试设置 timeout 属性（如果支持）
        try:
            self.binance.timeout = timeout
            logger.debug(f"已设置 binance 客户端超时为 {timeout} 秒")
        except Exception as e:
            logger.warning(f"设置 binance 客户端超时失败: {str(e)}")
            
        self.binance_socket = ThreadedWebsocketManager(api_key, api_secret, testnet=testnet)
        self.binance_socket.daemon = True
        self.binance_socket.start()
        # self.coin_refer = coin_refer
        self.coin_target = coin_target  # USDT
        # self.symbol = coin_refer + coin_target
        self.symbols = []  # symbols
        self.retries = retries
        self.timeout = timeout

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

    @debug_func(2)
    def _format_value(self, value, step):
        precision = step.find('1') - 1
        if precision > 0:
            return '{:0.0{}f}'.format(float(value), precision)
        return floor(int(value))
        
    def retry(func):
        """只对K线获取添加重试，其他操作不重试"""
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start_time = time.time()
            is_kline_related = 'klines' in func.__name__ or 'historical' in func.__name__
            max_attempts = self.retries if is_kline_related else 1
            
            for attempt in range(1, max_attempts + 1):
                time.sleep(60 / 1200) # API Rate Limit
                try:
                    result = func(self, *args, **kwargs)
                    elapsed = time.time() - start_time
                    logger.info(f"API调用 {func.__name__} 成功完成，耗时: {elapsed:.2f}秒")
                    return result
                except (BinanceAPIException, ConnectTimeout, ConnectionError, ReadTimeout) as err:
                    elapsed = time.time() - start_time
                    logger.error(f"API调用 {func.__name__} 出错，尝试 {attempt}/{max_attempts}，耗时: {elapsed:.2f}秒, 错误: {str(err)}")
                    
                    if isinstance(err, BinanceAPIException) and err.code == -1021:
                        # 重新计算本地与Binance服务器的时间偏移
                        try:
                            res = self.binance.get_server_time()
                            self.binance.timestamp_offset = res['serverTime'] - int(time.time() * 1000)
                            logger.info(f"已重新同步服务器时间，偏移量: {self.binance.timestamp_offset}ms")
                        except Exception as e:
                            logger.error(f"同步服务器时间失败: {str(e)}")
                    
                    if attempt == max_attempts or not is_kline_related:
                        logger.error(f"API调用 {func.__name__} 最终失败")
                        raise
        return wrapper

    @debug_func(3)
    @retry
    def cancel_open_orders(self, symbol):
        orders = self.binance.futures_get_open_orders(symbol=symbol)
        if len(orders) > 0:
            self.binance._request_api('delete', 'openOrders', signed=True, data={ 'symbol': symbol })

    @debug_func(4)
    @retry
    def cancel_order(self, symbol, order_id):
        try:
            self.binance.futures_cancel_order(symbol=symbol, orderId=order_id)
        except BinanceAPIException as api_err:
            if api_err.code == -2011:  # Order filled
                return
            else:
                raise api_err
        except Exception as err:
            raise err
    
    @debug_func(5)
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
        logger.info(f"创建订单: {symbol} {side} {type} {size} {price}")
        # 为create_order特别设置10秒超时
        old_timeout = None
        try:
            old_timeout = getattr(self.binance, 'timeout', None)
            self.binance.timeout = 10
            logger.debug(f"临时设置订单超时为 10 秒")
        except Exception as e:
            logger.warning(f"设置临时订单超时失败: {str(e)}")
            
        try:
            return self.binance.futures_create_order(
                symbol=symbol,
                side=side,
                type=type,
                quantity=self.format_quantity(symbol, size),
                **params)
        finally:
            # 恢复原来的超时设置
            if old_timeout is not None:
                try:
                    self.binance.timeout = old_timeout
                    logger.debug(f"已恢复原超时设置: {old_timeout} 秒")
                except Exception as e:
                    logger.warning(f"恢复原超时设置失败: {str(e)}")

    @debug_func(6)
    @retry
    def close(self):
        logger.info("关闭所有持仓")
        positions = self.binance.futures_position_information()
        for position in positions:
            if float(position['positionAmt']) != 0:
                side = SIDE_SELL if float(position['positionAmt']) > 0 else SIDE_BUY
                self.create_order(
                    symbol=position['symbol'],
                    side=side,
                    type=ORDER_TYPE_MARKET,
                    size=abs(float(position['positionAmt'])),
                    price=None
                )
                
    @debug_func(7)
    def format_price(self, symbol, price):
        return self._format_value(price, self._tick_size[symbol])
    
    @debug_func(8)
    def format_quantity(self, symbol, size):
        return self._format_value(size, self._step_size[symbol])

    @debug_func(9)
    @retry
    def get_asset_balance(self, asset):
        balance = self.binance.futures_account_balance()
        
        for bal in balance:
            if bal['asset'] == asset:
                return float(bal['availableBalance'])
        return 0.0

    @debug_func(10)
    @retry
    def get_symbol_balance(self, symbol):
        """Get symbol balance in symbol"""
        balance = 0
        try:
            symbol = symbol[0:len(symbol)-len(self.coin_target)]
            mybalance = self.binance.futures_account_balance()
            for bal in mybalance:
                if bal['asset'] == symbol:
                    balance = float(bal['availableBalance'])
                    break
            
        except Exception as e:
            logger.error(f"获取币种余额出错: {str(e)}")
        return balance, symbol  # float(balance['locked'])

    @debug_func(11)
    @retry
    def get_balance(self, ):
        """Balance in USDT for example - in coin target"""
        free = self.get_asset_balance(self.coin_target)
        self._cash = free
        self._value = free

    @debug_func(12)
    def getbroker(self):
        return self._broker

    @debug_func(13)
    def getdata(self, **kwargs):  # timeframe, compression, start_date=None, LiveBars=True
        symbol = kwargs['dataname']
        tf = self.get_interval(kwargs['timeframe'], kwargs['compression'])
        self.symbols.append(symbol)
        self.get_filters(symbol=symbol)
        if symbol not in self._datas:
            self._datas[f"{symbol}{tf}"] = BinanceData(store=self, **kwargs)  # timeframe=timeframe, compression=compression, start_date=start_date, LiveBars=LiveBars
        return self._datas[f"{symbol}{tf}"]
        
    @debug_func(14)
    @retry
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

    @debug_func(15)
    def get_interval(self, timeframe, compression):
        return self._GRANULARITIES.get((timeframe, compression))

    @debug_func(16)
    @retry
    def get_symbol_info(self, symbol):
        exchange_info = self.binance.futures_exchange_info()
        for s in exchange_info['symbols']:
            if s['symbol'] == symbol:
                return s
        return None

    @debug_func(17)
    def stop_socket(self):
        logger.info("关闭Websocket连接")
        self.binance_socket.stop()
        self.binance_socket.join(5)
