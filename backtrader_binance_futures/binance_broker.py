import datetime as dt
import threading
import logging
import time
import functools

from collections import defaultdict, deque
from math import copysign

from backtrader.broker import BrokerBase
from backtrader.order import Order, OrderBase
from backtrader.position import Position
from binance.enums import *

# 配置日志
logger = logging.getLogger('BinanceBroker')

# 添加函数调试装饰器
def debug_func(func_id):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger.debug(f"[BB-{func_id}] 开始执行: {func.__name__}")
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.debug(f"[BB-{func_id}] 结束执行: {func.__name__}, 耗时: {elapsed:.4f}秒")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"[BB-{func_id}] 执行出错: {func.__name__}, 耗时: {elapsed:.4f}秒, 错误: {str(e)}")
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
                logger.error(f"[BB-{func_id}] 执行出错: {func.__name__}, 错误: {str(e)}")
                raise
        return wrapper
    return decorator

class BinanceOrder(OrderBase):
    @debug_func(1)
    def __init__(self, owner, data, exectype, binance_order):
        self.owner = owner
        self.data = data
        self.exectype = exectype
        self.ordtype = self.Buy if binance_order['side'] == SIDE_BUY else self.Sell
        
        # Market order price is zero
        if self.exectype == Order.Market:
            self.size = float(binance_order['executedQty'])
            if 'fills' in binance_order and binance_order['fills']:
                self.price = sum(float(fill['price']) for fill in binance_order['fills']) / len(binance_order['fills'])  # Average price
            else:
                self.price = float(binance_order['stopPrice'])
        else:
            self.size = float(binance_order['origQty'])
            self.price = float(binance_order['price'])
        self.binance_order = binance_order
        
        super(BinanceOrder, self).__init__()
        self.accept()


class BinanceBroker(BrokerBase):
    _ORDER_TYPES = {
        Order.Limit: ORDER_TYPE_LIMIT,
        Order.Market: ORDER_TYPE_MARKET,
        Order.Stop: ORDER_TYPE_STOP_LOSS,
        Order.StopLimit: ORDER_TYPE_STOP_LOSS_LIMIT,
    }

    @debug_func(2)
    def __init__(self, store):
        super(BinanceBroker, self).__init__()

        self.notifs = deque()
        self.positions = defaultdict(Position)

        self.startingcash = self.cash = 0 
        self.startingvalue = self.value = 0

        self.open_orders = list()
    
        self._store = store
        self._store.binance_socket.start_futures_user_socket(self._handle_user_socket_message)
        self._order_condition = threading.Condition()
        self._order_status = {}

    @debug_func(3)
    def start(self):
        self.startingcash = self.cash = self.getcash()  # Стартовые и текущие свободные средства по счету. Подписка на позиции для портфеля/биржи
        self.startingvalue = self.value = self.getvalue()  # Стартовая и текущая стоимость позиций

    @debug_func(4)
    def _execute_order(self, order, date, executed_size, executed_price, executed_value, executed_comm):
        # print("order data")
        # print(order.data)
        order.execute(
            date,
            executed_size,
            executed_price,
            0, executed_value, executed_comm,
            0, 0.0, 0.0,
            0.0, 0.0,
            0, 0.0)
        pos = self.getposition(order.data, clone=False)
        pos.update(copysign(executed_size, order.size), executed_price)

    @debug_func(5)
    def _handle_user_socket_message(self, msg):
        """https://binance-docs.github.io/apidocs/spot/en/#payload-order-update"""
        if msg['e'] == 'ORDER_TRADE_UPDATE':
            if msg['o']['s'] in self._store.symbols:
                try:
                    with self._order_condition:
                        # 添加5秒超时机制
                        success = self._order_condition.wait_for(
                            lambda: msg['o']['i'] in self._order_status, 
                            timeout=5
                        )
                        
                        if not success:
                            logger.warning(f"等待订单状态超时: {msg['o']['i']}，继续处理")
                            # 即使未找到订单状态，也继续处理
                            self._order_status[msg['o']['i']] = msg['o']['i']
                except Exception as e:
                    logger.error(f"处理订单状态时出错: {str(e)}")
                    return
                
                for o in self.open_orders:
                    if o.binance_order['orderId'] == msg['o']['i']:
                        if msg['o']['X'] in [ORDER_STATUS_FILLED, ORDER_STATUS_PARTIALLY_FILLED]:
                            _dt = dt.datetime.fromtimestamp(int(msg['o']['T']) / 1000)
                            executed_size = float(msg['o']['l'])
                            executed_price = float(msg['o']['L'])
                            executed_value = float(executed_price) * float(executed_size)
                            executed_comm = float(msg['o']['n'])
                            logger.info(f"订单执行: {_dt}, 数量: {executed_size}, 价格: {executed_price}")
                            self._execute_order(o, _dt, executed_size, executed_price, executed_value, executed_comm)
                        self._set_order_status(o, msg['o']['X'])

                        if o.status not in [Order.Accepted, Order.Partial]:
                            self.open_orders.remove(o)
                        self.notify(o)
        elif msg['e'] == 'error':
            logger.error(f"Websocket错误: {msg}")
            
    
    @debug_func(6)
    def _set_order_status(self, order, binance_order_status):
        if binance_order_status == ORDER_STATUS_CANCELED:
            order.cancel()
        elif binance_order_status == ORDER_STATUS_EXPIRED:
            order.expire()
        elif binance_order_status == ORDER_STATUS_FILLED:
            order.completed()
        elif binance_order_status == ORDER_STATUS_PARTIALLY_FILLED:
            order.partial()
        elif binance_order_status == ORDER_STATUS_REJECTED:
            order.reject()

    @debug_func(7)
    def _submit(self, owner, data, side, exectype, size, price):
        logger.info(f"提交订单: {data._name} {side} {exectype} {size} {price}")
        start_time = time.time()
        
        try:
            type = self._ORDER_TYPES.get(exectype, ORDER_TYPE_MARKET)
            symbol = data._name
            binance_order = self._store.create_order(symbol, side, type, size, price)
            order_id = binance_order['orderId']
            
            # 设置订单状态让websocket回调能够找到
            with self._order_condition:
                self._order_status[order_id] = order_id
                self._order_condition.notify_all()
                
            order = BinanceOrder(owner, data, exectype, binance_order)
            if binance_order['status'] in [ORDER_STATUS_FILLED, ORDER_STATUS_PARTIALLY_FILLED]:
                avg_price = 0.0
                comm = 0.0
                for f in binance_order['fills']:
                    comm += float(f['commission'])
                    avg_price += float(f['price'])
                avg_price = self._store.format_price(symbol, avg_price/len(binance_order['fills']))
                self._execute_order(
                    order,
                    dt.datetime.fromtimestamp(binance_order['transactTime'] / 1000),
                    float(binance_order['executedQty']),
                    float(avg_price),
                    float(binance_order['cummulativeQuoteQty']),
                    float(comm))
            self._set_order_status(order, binance_order['status'])
            if order.status == Order.Accepted:
                self.open_orders.append(order)
            self.notify(order)
            
            elapsed = time.time() - start_time
            logger.info(f"订单提交完成, 耗时: {elapsed:.2f}秒, 订单ID: {order_id}")
            return order
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"订单提交失败, 耗时: {elapsed:.2f}秒, 错误: {str(e)}")
            
            # 确保即使出错也能解除线程阻塞
            with self._order_condition:
                self._order_condition.notify_all()
            
            # 创建一个拒绝的订单返回
            order = OrderBase(owner=owner, data=data, 
                           size=size if side == SIDE_BUY else -size,
                           price=price, 
                           exectype=exectype)
            order.reject()
            self.notify(order)
            return order

    @debug_func(8)
    def buy(self, owner, data, size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            **kwargs):
        return self._submit(owner, data, SIDE_BUY, exectype, size, price)

    @debug_func(9)
    def cancel(self, order):
        try:
            order_id = order.binance_order['orderId']
            symbol = order.binance_order['symbol']
            logger.info(f"取消订单: {symbol} {order_id}")
            self._store.cancel_order(symbol=symbol, order_id=order_id)
        except Exception as e:
            logger.error(f"取消订单失败: {str(e)}")
        
    @debug_func(10)
    def close(self):
        logger.info("关闭所有持仓...")
        self._store.close()
        
    @debug_func(11)
    def format_price(self, value):
        return self._store.format_price(value)

    @debug_func(12)
    def get_asset_balance(self, asset):
        return self._store.get_asset_balance(asset)

    @silent_debug_func(13)
    def getcash(self):
        self.cash = self._store._cash
        return self.cash

    @silent_debug_func(14)
    def get_notification(self):
        if not self.notifs:
            return None

        return self.notifs.popleft()

    @silent_debug_func(15)
    def getposition(self, data, clone=True):
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    @silent_debug_func(16)
    def getvalue(self, datas=None):
        self.value = self._store._value
        return self.value

    @silent_debug_func(17)
    def notify(self, order):
        self.notifs.append(order)

    @debug_func(18)
    def sell(self, owner, data, size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             **kwargs):
        return self._submit(owner, data, SIDE_SELL, exectype, size, price)
