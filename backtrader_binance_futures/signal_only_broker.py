import datetime as dt
import threading
import time

from collections import defaultdict, deque
from math import copysign

from backtrader.broker import BrokerBase
from backtrader.order import Order, OrderBase
from backtrader.position import Position
from binance.enums import *

# 添加导入
import requests
import datetime
import json
import traceback
import random
import logging

# 复制BinanceOrder类以保持兼容性
class SignalOnlyOrder(OrderBase):
    def __init__(self, owner, data, exectype, order_dict):
        self.owner = owner
        self.data = data
        self.exectype = exectype
        self.ordtype = self.Buy if order_dict['side'] == SIDE_BUY else self.Sell
        
        # 设置订单数据
        self.size = float(order_dict['executedQty'])
        self.price = float(order_dict['price'])
        self.binance_order = order_dict
        
        super(SignalOnlyOrder, self).__init__()
        self.accept()

# 创建只发送信号的broker
class SignalOnlyBroker(BrokerBase):
    _ORDER_TYPES = {
        Order.Limit: ORDER_TYPE_LIMIT,
        Order.Market: ORDER_TYPE_MARKET,
        Order.Stop: ORDER_TYPE_STOP_LOSS,
        Order.StopLimit: ORDER_TYPE_STOP_LOSS_LIMIT,
    }

    def __init__(self, store=None):
        super(SignalOnlyBroker, self).__init__()

        self.notifs = deque()
        self.positions = defaultdict(Position)

        self.startingcash = self.cash = 10000  # 设置模拟资金
        self.startingvalue = self.value = 10000

        self.open_orders = list()
    
        self._store = store
        self._order_condition = threading.Condition()
        self._order_status = {}
        
        # 信号发送相关的属性
        self.signal_params = {
            'commas_secret': None,
            'commas_max_lag': '30000',  # 默认值
            'commas_exchange': 'BINANCE',  # 默认值
            'commas_ticker': None,
            'commas_bot_uuid': None
        }
        self.send_signals = True  # 默认启用信号发送

    def start(self):
        self.startingcash = self.cash
        self.startingvalue = self.value

    def _execute_order(self, order, date, executed_size, executed_price, executed_value, executed_comm):
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

    # 添加信号发送功能
    def set_signal_params(self, commas_secret=None, commas_max_lag=None, 
                         commas_exchange=None, commas_ticker=None, commas_bot_uuid=None):
        """设置信号发送参数"""
        if commas_secret:
            self.signal_params['commas_secret'] = commas_secret
        if commas_max_lag:
            self.signal_params['commas_max_lag'] = commas_max_lag
        if commas_exchange:
            self.signal_params['commas_exchange'] = commas_exchange
        if commas_ticker:
            self.signal_params['commas_ticker'] = commas_ticker
        if commas_bot_uuid:
            self.signal_params['commas_bot_uuid'] = commas_bot_uuid
            
    def enable_signal_sending(self, enable=True):
        """启用或禁用信号发送"""
        self.send_signals = enable
    
    def send_trade_signal(self, signal, trigger_price):
        """发送交易信号到3commas"""
        # 获取参数
        commas_secret = self.signal_params['commas_secret']
        commas_max_lag = self.signal_params['commas_max_lag']
        commas_exchange = self.signal_params['commas_exchange']
        commas_ticker = self.signal_params['commas_ticker']
        commas_bot_uuid = self.signal_params['commas_bot_uuid']
        
        # 检查必要参数
        if not all([commas_secret, commas_ticker, commas_bot_uuid]):
            return "错误: 缺少必要的信号参数"
        
        # 设置信号发送完成事件
        signal_sent_event = threading.Event()
        signal_response = {"status": "未知", "message": "未开始"}
        
        # 创建线程函数
        def send_signal_thread():
            nonlocal signal_response
            
            # 重试机制
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                retry_count += 1
                
                try:
                    print(f"尝试发送信号 (第{retry_count}次): {signal} @ {trigger_price}")
                    
                    # 构建payload
                    payload = {
                        'secret': commas_secret,
                        'max_lag': commas_max_lag,
                        'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        'trigger_price': str(trigger_price),
                        'tv_exchange': commas_exchange,
                        'tv_instrument': commas_ticker,
                        'action': signal,
                        'bot_uuid': commas_bot_uuid
                    }
                    
                    # 先尝试n8n webhook
                    try:
                        # 设置较短的超时，防止长时间阻塞
                        url = "http://localhost:5678/webhook/3commas"
                        response = requests.post(
                            url,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=5  # 5秒超时
                        )
                        
                        # 检查响应
                        if response.status_code == 200:
                            response_text = response.text
                            print(f"交易信号 {commas_ticker} {signal} 已成功发送到n8n")
                            print(f"响应内容: {response_text}")
                            signal_response = {"status": "成功", "message": response_text}
                            # 标记成功并退出重试循环
                            break
                        elif response.status_code == 404 and "webhook" in response.text and "not registered" in response.text:
                            # n8n特定错误，尝试备用发送方式
                            print(f"n8n webhook未注册，尝试直接发送到日志文件...")
                            
                            # 将信号记录到文件中
                            log_filename = f"signal_{datetime.datetime.now().strftime('%Y%m%d')}.log"
                            with open(log_filename, "a") as log_file:
                                log_entry = {
                                    "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    "signal": signal,
                                    "price": trigger_price,
                                    "ticker": commas_ticker,
                                    "exchange": commas_exchange,
                                    "bot_id": commas_bot_uuid
                                }
                                log_file.write(json.dumps(log_entry) + "\n")
                            
                            print(f"信号已记录到文件: {log_filename}")
                            signal_response = {"status": "成功", "message": f"信号已记录到{log_filename}"}
                            break
                        else:
                            error_message = f"信号发送失败，状态码: {response.status_code}，响应: {response.text}"
                            print(error_message)
                            signal_response = {"status": "失败", "message": error_message}
                            # 继续重试
                    except Exception as e:
                        error_message = f"发送到n8n异常: {str(e)}"
                        print(error_message)
                        signal_response = {"status": "异常", "message": error_message}
                        # 继续重试
                except Exception as e:
                    error_message = f"信号发送异常: {str(e)}"
                    print(error_message)
                    print(traceback.format_exc())
                    signal_response = {"status": "异常", "message": error_message}
                    # 继续重试
                
                # 如果需要重试，增加延迟
                if retry_count < max_retries:
                    # 使用指数退避策略，逐渐增加重试间隔
                    retry_delay = (2 ** retry_count) + random.uniform(0, 1)
                    print(f"将在 {retry_delay:.2f} 秒后重试...")
                    time.sleep(retry_delay)
            
            # 所有尝试完成后，设置事件
            print(f"信号发送状态: {signal_response['status']}")
            signal_sent_event.set()
        
        # 创建并启动发送线程
        send_thread = threading.Thread(target=send_signal_thread)
        send_thread.daemon = True
        send_thread.start()
        
        # 等待信号发送完成，但设置超时
        timeout = 15  # 15秒超时
        if not signal_sent_event.wait(timeout):
            print(f"警告: 信号发送操作超时 ({timeout}秒)")
            return "超时等待响应"
        
        # 返回发送结果
        if signal_response["status"] == "成功":
            return signal_response["message"]
        else:
            return f"错误: {signal_response['message']}"
        
    def _map_side_to_signal(self, side, is_close=False):
        """将Binance的买卖方向映射为3Commas信号"""
        if is_close:
            if side == SIDE_SELL:
                return "exit_long"
            else:
                return "exit_short"
        else:
            if side == SIDE_BUY:
                return "enter_long"
            else:
                return "enter_short"

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
        """模拟下单并只发送信号到n8n"""
        symbol = data._name
        
        # 是否是平仓操作
        position = self.getposition(data, clone=False)
        is_close = (position.size > 0 and side == SIDE_SELL) or (position.size < 0 and side == SIDE_BUY)
        
        # 映射为3Commas信号
        signal = self._map_side_to_signal(side, is_close)
        
        # 使用当前价格作为触发价格
        trigger_price = data.close[0]
        print(f"模拟下单: {symbol} {side} {exectype} {size} {price}")
        print(f"发送信号: {signal} @ {trigger_price}")
        
        # 发送信号
        response = self.send_trade_signal(signal, trigger_price)
        print(f"信号发送结果: {response}")
        
        # 创建一个模拟订单对象，以保持策略逻辑正常工作
        # 注意：这里不会实际调用Binance API
        order_id = int(time.time() * 1000)  # 使用时间戳作为订单ID
        
        # 创建一个简单的模拟订单字典
        order_dict = {
            'orderId': order_id,
            'symbol': symbol,
            'side': side,
            'type': self._ORDER_TYPES.get(exectype, ORDER_TYPE_MARKET),
            'status': ORDER_STATUS_FILLED,  # 假设订单立即成交
            'executedQty': str(size),
            'price': str(price) if price else str(trigger_price),
            'stopPrice': '0',
            'fills': [{'price': str(trigger_price), 'commission': '0'}],
            'transactTime': int(time.time() * 1000)
        }
        
        # 创建订单对象
        order = SignalOnlyOrder(owner, data, exectype, order_dict)
        
        # 模拟订单执行
        self._execute_order(
            order, 
            dt.datetime.now(),
            float(size),
            float(trigger_price),
            float(trigger_price) * float(size),
            0.0  # 无佣金
        )
        
        # 设置订单状态
        order.completed()
        self.notify(order)
        
        # 同步订单条件
        with self._order_condition:
            self._order_status[order_id] = order_id
            self._order_condition.notify_all()
        
        return order

    def buy(self, owner, data, size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            **kwargs):
        return self._submit(owner, data, SIDE_BUY, exectype, size, price)

    def sell(self, owner, data, size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             **kwargs):
        return self._submit(owner, data, SIDE_SELL, exectype, size, price)

    def cancel(self, order):
        # 不执行实际取消
        order.cancel()
        self.notify(order)
        
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
        return self.value

    def getcash(self):
        return self.cash
        
    def notify(self, order):
        self.notifs.append(order) 