from collections import deque
import pandas as pd
import logging
import time
import functools

from backtrader.feed import DataBase
from backtrader.utils import date2num

from backtrader import TimeFrame as tf

# 配置日志
logger = logging.getLogger('BinanceData')

# 添加函数调试装饰器
def debug_func(func_id):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger.debug(f"[BF-{func_id}] 开始执行: {func.__name__}")
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.debug(f"[BF-{func_id}] 结束执行: {func.__name__}, 耗时: {elapsed:.4f}秒")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"[BF-{func_id}] 执行出错: {func.__name__}, 耗时: {elapsed:.4f}秒, 错误: {str(e)}")
                raise
        return wrapper
    return decorator

# 添加一个不输出日志的调试装饰器版本
def silent_debug_func(func_id):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"[BF-{func_id}] 执行出错: {func.__name__}, 错误: {str(e)}")
                raise
        return wrapper
    return decorator

class BinanceData(DataBase):
    params = (
        ('drop_newest', True),
    )
    
    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    @debug_func(1)
    def __init__(self, store, **kwargs):  # def __init__(self, store, timeframe, compression, start_date, LiveBars):
        # default values
        self.timeframe = tf.Minutes
        self.compression = 1
        self.start_date = None
        self.LiveBars = None

        self.symbol = self.p.dataname

        if hasattr(self.p, 'timeframe'): self.timeframe = self.p.timeframe
        if hasattr(self.p, 'compression'): self.compression = self.p.compression
        if 'start_date' in kwargs: self.start_date = kwargs['start_date']
        if 'LiveBars' in kwargs: self.LiveBars = kwargs['LiveBars']

        self._store = store
        self._data = deque()

        logger.info(f"初始化数据源: {self.symbol}, TF: {self.timeframe}, Compression: {self.compression}")

    @debug_func(2)
    def _handle_kline_socket_message(self, msg):
        """https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-streams"""
        try:
            if 'kline' in msg['e']:
                if msg['k']['x']:  # Is closed
                    # logger.debug("K线已关闭")
                    kline = self._parser_to_kline(msg['k']['t'], msg['k'])
                    self._data.extend(kline.values.tolist())
            elif 'error' in msg['e']:
                logger.error(f"K线socket错误: {msg}")
        except Exception as e:
            logger.error(f"处理K线消息时出错: {str(e)}")

    # 移除调试装饰器，使用不输出日志的版本
    @silent_debug_func(3)
    def _load(self):
        if self._state == self._ST_OVER:
            return False
        elif self._state == self._ST_LIVE:
            return self._load_kline()
        elif self._state == self._ST_HISTORBACK:
            if self._load_kline():
                return True
            else:
                self._start_live()

    # 移除调试装饰器，使用不输出日志的版本
    @silent_debug_func(4)
    def _load_kline(self):
        try:
            kline = self._data.popleft()
        except IndexError:
            return None

        timestamp, open_, high, low, close, volume = kline

        self.lines.datetime[0] = date2num(timestamp)
        self.lines.open[0] = open_
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = volume
        return True
    
    @debug_func(5)
    def _parser_dataframe(self, data):
        df = data.copy()
        df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        df['timestamp'] = df['timestamp'].values.astype(dtype='datetime64[ms]')
        df['open'] = df['open'].values.astype(float)
        df['high'] = df['high'].values.astype(float)
        df['low'] = df['low'].values.astype(float)
        df['close'] = df['close'].values.astype(float)
        df['volume'] = df['volume'].values.astype(float)
        # df.set_index('timestamp', inplace=True)
        return df
    
    @debug_func(6)
    def _parser_to_kline(self, timestamp, kline):
        df = pd.DataFrame([[timestamp, kline['o'], kline['h'],
                            kline['l'], kline['c'], kline['v']]])
        return self._parser_dataframe(df)
    
    @debug_func(7)
    def _start_live(self):
        # if live mode
        if self.LiveBars:
            self._state = self._ST_LIVE
            self.put_notification(self.LIVE)

            logger.info(f"启动实时数据模式: {self.symbol}")

            try:
                self._store.binance_socket.start_kline_futures_socket(
                    self._handle_kline_socket_message,
                    self.symbol_info['symbol'],
                    self.interval)
            except Exception as e:
                logger.error(f"启动K线socket失败: {str(e)}")
                self._state = self._ST_OVER
        else:
            self._state = self._ST_OVER
        
    # 移除调试装饰器，使用不输出日志的版本
    @silent_debug_func(8)
    def haslivedata(self):
        return self._state == self._ST_LIVE and self._data

    @debug_func(9)
    def islive(self):
        return True
        
    @debug_func(10)
    def start(self):
        DataBase.start(self)
        logger.info(f"开始数据源: {self.symbol}")
        
        start_time = time.time()
        
        self.interval = self._store.get_interval(self.timeframe, self.compression)
        if self.interval is None:
            self._state = self._ST_OVER
            self.put_notification(self.NOTSUPPORTED_TF)
            logger.error(f"不支持的时间框架: {self.timeframe}/{self.compression}")
            return
        
        self.symbol_info = self._store.get_symbol_info(self.symbol)
        if self.symbol_info is None:
            self._state = self._ST_OVER
            self.put_notification(self.NOTSUBSCRIBED)
            logger.error(f"未订阅的交易对: {self.symbol}")
            return

        if self.start_date:
            self._state = self._ST_HISTORBACK
            self.put_notification(self.DELAYED)

            try:
                logger.info(f"获取历史数据: {self.symbol}, 开始日期: {self.start_date}")
                klines = self._store.binance.futures_historical_klines(
                    self.symbol_info['symbol'],
                    self.interval,
                    self.start_date.strftime('%d %b %Y %H:%M:%S'))
                logger.info(f"历史数据已加载: {self.symbol}, 获取了{len(klines)}条K线")
                
                try:
                    if self.p.drop_newest:
                        klines.pop()

                    df = pd.DataFrame(klines)
                    df.drop(df.columns[[6, 7, 8, 9, 10, 11]], axis=1, inplace=True)  # Remove unnecessary columns
                    df = self._parser_dataframe(df)
                    self._data.extend(df.values.tolist())
                    elapsed = time.time() - start_time
                    logger.info(f"历史数据处理完成, 耗时: {elapsed:.2f}秒")
                except Exception as e:
                    logger.error(f"处理历史数据时出错(尝试以UTC格式设置start_date): {str(e)}")
            except Exception as e:
                logger.error(f"获取历史数据时出错: {str(e)}")
                self._state = self._ST_OVER
                return

        else:
            logger.info(f"直接启动实时模式: {self.symbol}")
            self._start_live()
