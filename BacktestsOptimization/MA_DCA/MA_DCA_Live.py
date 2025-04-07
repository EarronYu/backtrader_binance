import backtrader as bt
import math
import threading
import aiohttp
import asyncio
import datetime

class MA_DCA_Live(bt.Strategy):
    # 在原有的策略参数基础上，添加与3commas和实盘相关的参数
    params = (
        ('ma_length', 47),        # MA长度
        ('initial_percent', 8),   # 首次订单的百分比
        ('percent_step', 1),      # 额外订单的百分比步长
        ('pyramiding', 3),        # 最大加仓次数

        # 以下为新增的实盘/3commas对接参数
        ('commas_secret', None),    # 3commas webhook secret
        ('commas_max_lag', None),   # 3commas webhook max lag
        ('commas_exchange', None),  # TV exchange名称
        ('commas_ticker', None),    # TV ticker/instrument
        ('commas_bot_uuid', None),  # 3commas bot uuid
        ('debug_mode', False),      # 调试模式开关（可在创建策略时覆盖）
        ('initial_cash', 1000),     # 初始资金，可自行使用或扩展
    )

    def __init__(self):
        """
        初始化策略，包括父类初始化（不使用super()）、检查3commas必需参数、设置异步事件循环等
        下面的逻辑与原策略保持一致，只在末尾添加了实盘支持部分。
        """
        # 显式调用父类init（避免使用super()）
        bt.Strategy.__init__(self)

        # 检查 3commas 必传参数
        if not all([
            self.p.commas_secret,
            self.p.commas_exchange,
            self.p.commas_ticker,
            self.p.commas_bot_uuid
        ]):
            raise ValueError("必须提供所有3commas参数（secret/exchange/ticker/bot_uuid）！")

        # 将参数debug_mode与原逻辑中的self.debug_mode关联
        self.debug_mode = self.p.debug_mode
        
        # ========== 以下为您原策略的初始化逻辑（保持不变） ==========
        # 计算简单移动平均线
        self.ma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.params.ma_length
        )
        # 跟踪最近买入和卖出价格
        self.last_buy_price = None
        self.last_sell_price = None
        
        # 用于跟踪当前持仓方向
        self.position_direction = None
        
        # 用于金字塔加仓
        self.opentrades = 0
        self.unit_ratio = 1.0 / self.params.pyramiding

        # ========== 以下为新增：异步事件循环与线程（实盘所需） ==========
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.start_loop, daemon=True)
        self.loop_thread.start()
    
    def start_loop(self):
        """后台线程运行异步事件循环"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def log(self, txt, dt=None, debug=False):
        """
        复用原策略的日志输出方法，仅在需要时才打印调试信息。
        """
        if debug and not self.debug_mode:
            return
        dt = dt or self.data.datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

    def price_percent_diff(self, price1, price2):
        """计算两个价格之间的绝对百分比差异（原样保留）"""
        return abs(price1 - price2) / price2 * 100
    
    def initial_entry_condition(self, price, ma, initial_percent):
        """检查是否满足初始入场条件（原样保留）"""
        return self.price_percent_diff(price, ma) >= initial_percent
    
    def next(self):
        """
        与原回测逻辑逐行一致：多头/空头的开仓、加仓、平仓逻辑完全相同
        """
        # 获取当前价格数据
        current_close = self.data.close[0]
        current_low = self.data.low[0]
        current_high = self.data.high[0]
        current_ma = self.ma[0]
        
        # 检查平仓条件
        if self.position.size > 0 and current_close >= current_ma:  # 多头平仓
            self.order_target_percent(target=0.0, comment="exit_long")
            self.last_buy_price = None
            self.position_direction = None
            self.opentrades = 0
            self.log(f"平仓多头: 价格={current_close:.2f}", debug=True)
            
        elif self.position.size < 0 and current_close <= current_ma:  # 空头平仓
            self.order_target_percent(target=0.0, comment="exit_short")
            self.last_sell_price = None
            self.position_direction = None
            self.opentrades = 0
            self.log(f"平仓空头: 价格={current_close:.2f}", debug=True)
        
        # 多头入场逻辑
        if current_low < current_ma:
            if self.last_buy_price is None:
                if self.initial_entry_condition(current_low, current_ma, self.params.initial_percent):
                    # 首次开仓
                    self.opentrades = 1
                    target_percent = self.unit_ratio * self.opentrades
                    self.order_target_percent(target=target_percent, comment="enter_long")
                    self.last_buy_price = current_low
                    self.position_direction = 'long'
                    self.log(f"首次买入: 价格={current_low:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
            else:
                if (current_low < self.last_buy_price
                    and self.price_percent_diff(current_low, self.last_buy_price) >= self.params.percent_step
                    and self.opentrades < self.params.pyramiding):
                    
                    # 加仓
                    self.opentrades += 1
                    target_percent = self.unit_ratio * self.opentrades
                    self.order_target_percent(target=target_percent, comment="add_long")
                    self.last_buy_price = current_low
                    self.log(f"多头加仓: 价格={current_low:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
        
        # 空头入场逻辑
        if current_high > current_ma:
            if self.last_sell_price is None:
                if self.initial_entry_condition(current_high, current_ma, self.params.initial_percent):
                    # 首次开仓
                    self.opentrades = 1
                    target_percent = self.unit_ratio * self.opentrades
                    self.order_target_percent(target=-target_percent, comment="enter_short")
                    self.last_sell_price = current_high
                    self.position_direction = 'short'
                    self.log(f"首次卖出: 价格={current_high:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
            else:
                if (current_high > self.last_sell_price
                    and self.price_percent_diff(current_high, self.last_sell_price) >= self.params.percent_step
                    and self.opentrades < self.params.pyramiding):
                    
                    # 加仓
                    self.opentrades += 1
                    target_percent = self.unit_ratio * self.opentrades
                    self.order_target_percent(target=-target_percent, comment="add_short")
                    self.last_sell_price = current_high
                    self.log(f"空头加仓: 价格={current_high:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)

    # ========== 异步信号发送部分 ==========
    async def _async_send_signal(self, action, trigger_price):
        """
        实际执行异步HTTP请求的函数
        :param action: 字符串，如 'enter_long' / 'exit_long' 等
        :param trigger_price: 触发价格
        """
        # 构建3commas所需Payload
        payload = {
            'secret': self.p.commas_secret,
            'max_lag': self.p.commas_max_lag,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            'trigger_price': str(trigger_price),
            'tv_exchange': self.p.commas_exchange,
            'tv_instrument': self.p.commas_ticker,
            'action': action,      # 与订单comment对应
            'bot_uuid': self.p.commas_bot_uuid
        }
        url = "http://localhost:5678/webhook/3commas"  # 替换为您的webhook地址

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        self.log(f"已发送 {action} 信号, 价格: {trigger_price}", debug=True)
                    else:
                        self.log(f"发送信号失败，状态码: {response.status}", debug=True)
            return True
        except Exception as e:
            self.log(f"异步发送信号异常: {e}", debug=True)
            return False

    def send_signal_async(self, action, trigger_price):
        """
        将异步发送请求提交到事件循环中，避免阻塞主线程
        """
        asyncio.run_coroutine_threadsafe(
            self._async_send_signal(action, trigger_price),
            self.loop
        )

    # ========== 订单与交易通知回调 ==========
    def notify_order(self, order):
        """
        当订单状态变动时（Submitted/Accepted/Completed等）回调这里。
        可在此时向3commas等平台发送交易信号。
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            comment = ''
            # 从 order.info 或 order.comment 中获取触发信号的关键字
            if hasattr(order, 'info') and isinstance(order.info, dict):
                comment = order.info.get('comment', '')
            if not comment:
                comment = getattr(order, 'comment', '')

            if comment:
                # 获取下单价格（对于市价单等可能是0）
                trigger_price = order.created.price if hasattr(order, 'created') else 0
                self.send_signal_async(comment, trigger_price)

    def notify_trade(self, trade):
        """
        交易完成时（开仓、平仓）会回调这里，可打印/记录盈亏信息
        """
        if trade.isclosed:
            self.log(f'已关闭仓位 {trade.getdataname()} 总盈亏={trade.pnl:.2f}, 净盈亏={trade.pnlcomm:.2f}', debug=True)
        else:
            if trade.justopened:
                self.log(f'开仓 {trade.getdataname()} 大小={trade.size}, 价格={trade.price}', debug=True)

    # ========== 策略停止时的资源清理 ==========
    def stop(self):
        """
        在策略终止（回测结束或实盘退出）时，关闭事件循环与后台线程
        """
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop_thread.join()
            self.log("异步事件循环已关闭", debug=True)
        except Exception as e:
            self.log(f"关闭事件循环异常: {e}", debug=True)
