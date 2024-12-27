import datetime as dt
import threading

from collections import defaultdict, deque
from math import copysign

from backtrader.broker import BrokerBase
from backtrader.order import Order, OrderBase
from backtrader.position import Position
from binance.enums import *


class BinanceOrder(OrderBase):
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

    def start(self):
        self.startingcash = self.cash = self.getcash()  # Стартовые и текущие свободные средства по счету. Подписка на позиции для портфеля/биржи
        self.startingvalue = self.value = self.getvalue()  # Стартовая и текущая стоимость позиций

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

    def _handle_user_socket_message(self, msg):
        """https://binance-docs.github.io/apidocs/spot/en/#payload-order-update"""
        # print(5555, msg)
        #{'e': 'ORDER_TRADE_UPDATE', 'T': 1735320380465, 'E': 1735320380471, 'o': {'s': 'BTCUSDT', 'c': 'x-Cb7ytekJc78682727188d656ceb524', 'S': 'BUY', 'o': 'MARKET', 'f': 'GTC', 'q': '0.002', 'p': '0', 'ap': '0', 'sp': '0', 'x': 'NEW', 'X': 'NEW', 'i': 4073226536, 'l': '0', 'z': '0', 'L': '0', 'n': '0', 'N': 'USDT', 'T': 1735320380465, 't': 0, 'b': '0', 'a': '0', 'm': False, 'R': False, 'wt': 'CONTRACT_PRICE', 'ot': 'MARKET', 'ps': 'BOTH', 'cp': False, 'rp': '0', 'pP': False, 'si': 0, 'ss': 0, 'V': 'NONE', 'pm': 'NONE', 'gtd': 0}}

        # {'e': 'ORDER_TRADE_UPDATE', 'T': 1735320870042, 'E': 1735320870048, 'o': {'s': 'BTCUSDT', 'c': 'x-Cb7ytekJ1953676356434b1f9c7e7a', 'S': 'BUY', 'o': 'MARKET', 'f': 'GTC', 'q': '0.002', 'p': '0', 'ap': '98010', 'sp': '0', 'x': 'TRADE', 'X': 'FILLED', 'i': 4073228429, 'l': '0.002', 'z': '0.002', 'L': '98010', 'n': '0.07840800', 'N': 'USDT', 'T': 1735320870042, 't': 293934075, 'b': '0', 'a': '0', 'm': False, 'R': False, 'wt': 'CONTRACT_PRICE', 'ot': 'MARKET', 'ps': 'BOTH', 'cp': False, 'rp': '0', 'pP': False, 'si': 0, 'ss': 0, 'V': 'NONE', 'pm': 'NONE', 'gtd': 0}}

        if msg['e'] == 'ORDER_TRADE_UPDATE':
            # print(6666, msg)
            if msg['o']['s'] in self._store.symbols:
                # print(7777, msg)
                # print(77777, self.open_orders)
                
                with self._order_condition:
                    self._order_condition.wait_for(lambda: msg['o']['i'] in self._order_status)
                # print(77778, self.open_orders)
                
                for o in self.open_orders:
                    # print(8888, o)
                    if o.binance_order['orderId'] == msg['o']['i']:
                        if msg['o']['X'] in [ORDER_STATUS_FILLED, ORDER_STATUS_PARTIALLY_FILLED]:
                            _dt = dt.datetime.fromtimestamp(int(msg['o']['T']) / 1000)
                            executed_size = float(msg['o']['l'])
                            executed_price = float(msg['o']['L'])
                            executed_value = float(executed_price) * float(executed_size)
                            executed_comm = float(msg['o']['n'])
                            print(_dt, executed_size, executed_price)
                            self._execute_order(o, _dt, executed_size, executed_price, executed_value, executed_comm)
                        self._set_order_status(o, msg['o']['X'])

                        if o.status not in [Order.Accepted, Order.Partial]:
                            self.open_orders.remove(o)
                        self.notify(o)
        elif msg['e'] == 'error':
            raise msg
        
    
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

    def _submit(self, owner, data, side, exectype, size, price):
        # print(1111, owner, data, side, exectype, size, price)
        type = self._ORDER_TYPES.get(exectype, ORDER_TYPE_MARKET)
        symbol = data._name
        binance_order = self._store.create_order(symbol, side, type, size, price)
        # print(22222, binance_order)

        # print(3333, self._order_status)
        order_id = binance_order['orderId']
        

        # print(3333, self._order_status)
        # binance_order = self._order_status[order_id]
        order = BinanceOrder(owner, data, exectype, binance_order)
        if binance_order['status'] in [ORDER_STATUS_FILLED, ORDER_STATUS_PARTIALLY_FILLED]:
            avg_price =0.0
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
        

        # this is for when we need to allow thread to move on
        with self._order_condition:
            self._order_status[order_id] = order_id
            self._order_condition.notify_all()
        # print(4444, "allow thread to move on")
        #this is for when we need to wait for a condition to be filled somewhere else
        # with self._order_condition:
        #     self._order_condition.wait_for(lambda: order_id in self._order_status)
        return order

    def buy(self, owner, data, size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            **kwargs):
        return self._submit(owner, data, SIDE_BUY, exectype, size, price)

    def cancel(self, order):
        order_id = order.binance_order['orderId']
        symbol = order.binance_order['symbol']
        self._store.cancel_order(symbol=symbol, order_id=order_id)
        
    def close(self):
        self._store.close()
        
    def format_price(self, value):
        return self._store.format_price(value)

    def get_asset_balance(self, asset):
        return self._store.get_asset_balance(asset)

    def getcash(self):
        self.cash = self._store._cash
        return self.cash

    def get_notification(self):
        if not self.notifs:
            return None

        return self.notifs.popleft()

    def getposition(self, data, clone=True):
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    def getvalue(self, datas=None):
        self.value = self._store._value
        return self.value

    def notify(self, order):
        self.notifs.append(order)

    def sell(self, owner, data, size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             **kwargs):
        return self._submit(owner, data, SIDE_SELL, exectype, size, price)
