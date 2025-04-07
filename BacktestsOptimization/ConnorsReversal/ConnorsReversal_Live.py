import backtrader as bt
import backtrader.indicators as btind
import math
import asyncio
import aiohttp
import threading
import datetime

from collections import deque

class ConnorsReversal_Live(bt.Strategy):
    """
    实盘版 ConnorsReversal
    1. init 和 next 等核心逻辑与原策略一模一样
    2. 新增异步发单到外部平台（3commas / Webhook）
    3. notify_order 中触发发送信号
    4. stop 中清理异步事件循环
    """

    params = (
        # ========== 原策略所有参数，一字不差 ========== 
        ("lowest_point_bars", 16),
        ("rsi_length", 4),
        ("sell_barrier", 73),
        ("dca_parts", 8),
        ("max_lookback", 50),
        ("sma_period", 55),
        ("only_buy_above_sma", False),

        # ========== 新增实盘必需参数 ========== 
        ('commas_secret', None),     # 3commas/Webhook secret
        ('commas_max_lag', None),
        ('commas_exchange', None),
        ('commas_ticker', None),
        ('commas_bot_uuid', None),

        # 仅做演示，可与真实资金对接
        ('initial_cash', 1000),
        # 打印调试日志
        ('debug_mode', True),
    )

    # -------------------------------
    # 1) init 与原策略一致 + 实盘初始化
    # -------------------------------
    def __init__(self):
        # ========== 以下为原策略的 init 逻辑，保持不变 ========== 
        # 初始化指标
        self.rsi = btind.RSI(self.data.close, period=self.p.rsi_length)
        self.sma = btind.SimpleMovingAverage(self.data.close, period=self.p.sma_period)

        # 初始化交易变量
        self.open_trades = 0
        self.unit_ratio = 1 / self.p.dca_parts

        # 数据窗口
        self.max_window = min(self.p.lowest_point_bars * self.p.dca_parts, self.p.max_lookback)
        self.closes = deque(maxlen=self.max_window)
        self.min_price_window = deque(maxlen=self.p.lowest_point_bars)

        # 状态标志 - 简化初始化逻辑
        # （原策略固定 debug_mode=False，这里改为使用参数值, 以便你可切换调试）
        self.debug_mode = self.p.debug_mode

        # ========== 以下为实盘新增的初始化部分 ========== 
        # 检查外部接口(3commas/Webhook)必需参数
        if not all([
            self.p.commas_secret,
            self.p.commas_exchange,
            self.p.commas_ticker,
            self.p.commas_bot_uuid
        ]):
            raise ValueError("必须提供3commas/Webhook必需参数: commas_secret, commas_exchange, commas_ticker, commas_bot_uuid")

        # 创建事件循环与线程，避免阻塞主策略
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._start_loop, daemon=True)
        self.loop_thread.start()

    def _start_loop(self):
        """后台线程中的事件循环"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    # -------------------------------
    # 2) 保留原策略的 log
    # -------------------------------
    def log(self, txt, dt=None, debug=False):
        if debug and not self.debug_mode:
            return
        dt = dt or self.data.datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

    # -------------------------------
    # 3) 保留原策略的 is_local_minimum
    # -------------------------------
    def is_local_minimum(self):
        """检查当前价格是否为局部最低点"""
        try:
            # 只有窗口填满时才进行检测
            if len(self.min_price_window) < self.p.lowest_point_bars:
                return False

            current_price = self.data.close[0]
            if math.isnan(current_price):
                return False

            # 直接遍历队列副本，过滤 NaN
            valid_prices = [p for p in list(self.min_price_window) if not math.isnan(p)]
            # 确保当前价格也参与检测
            if not valid_prices or current_price != valid_prices[-1]:
                valid_prices.append(current_price)
            min_price = min(valid_prices)
            return current_price <= min_price

        except Exception as e:
            self.log(f"最低点检查错误: {str(e)}", debug=True)
            return False

    # -------------------------------
    # 4) next 与原策略一模一样
    # -------------------------------
    def next(self):
        """主要策略逻辑，使用 order_target_percent 进行下单管理"""
        current_price = self.data.close[0]
        # 如果当前价格无效或为0，则直接返回
        if math.isnan(current_price) or current_price == 0:
            self.log("警告: 当前价格无效（为0或NaN），跳过此bar", debug=True)
            return

        self.closes.append(current_price)
        self.min_price_window.append(current_price)

        try:
            is_lowest = self.is_local_minimum()

            # 卖出条件：持仓且 RSI 超过卖出阈值时平仓
            if self.position and self.rsi[0] > self.p.sell_barrier:
                self.order_target_percent(target=0.0)
                self.open_trades = 0
                self.log(f"卖出信号 - RSI: {self.rsi[0]:.6f}，目标仓位: 0.00", debug=True)
                return

            # 检查买入条件
            if is_lowest:
                price_below_avg = True
                if self.position:
                    avg_price = self.position.price
                    price_below_avg = current_price < avg_price * (1 - 0.01 * self.open_trades)

                above_sma = current_price > self.sma[0]
                sma_condition = above_sma or not self.p.only_buy_above_sma

                if (price_below_avg or self.open_trades == 0) and sma_condition and self.open_trades < self.p.dca_parts:
                    # 计算当前目标仓位比例
                    target_percent = self.unit_ratio * (self.open_trades + 1)
                    self.order_target_percent(target=target_percent)
                    self.open_trades += 1
                    self.log(f"买入信号 - 价格: {current_price:.6f}, 目标仓位比例: {target_percent:.4f}, 加仓次数: {self.open_trades}", debug=True)

        except Exception as e:
            self.log(f"策略执行错误: {str(e)}", debug=True)

    # -------------------------------
    # 5) 保留原策略的 notify_trade
    # -------------------------------
    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"交易关闭: 毛利润={trade.pnl:.6f}, 净利润={trade.pnlcomm:.6f}", debug=True)

    # ---------------------------------
    # ========== 以下为实盘新增部分 ==========
    # ---------------------------------

    async def _async_send_signal(self, signal, trigger_price):
        """
        使用 aiohttp 异步发送交易信号到 Webhook (如3commas)
        """
        payload = {
            'secret': self.p.commas_secret,
            'max_lag': self.p.commas_max_lag,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            'trigger_price': str(trigger_price),
            'tv_exchange': self.p.commas_exchange,
            'tv_instrument': self.p.commas_ticker,
            'action': signal,        # buy / sell / exit
            'bot_uuid': self.p.commas_bot_uuid
        }
        url = "http://localhost:5678/webhook/3commas"  # 示例地址，需自行修改

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=2)  # 可调
                ) as resp:
                    if resp.status == 200:
                        self.log(f"已发送{signal}信号, 价格:{trigger_price}", debug=True)
                    else:
                        self.log(f"信号发送失败, 状态码:{resp.status}", debug=True)
            return True
        except Exception as e:
            self.log(f"异步发送信号异常: {e}", debug=True)
            return False

    def send_signal(self, signal, trigger_price):
        """
        在主线程中使用 run_coroutine_threadsafe 提交异步任务，不会阻塞策略执行
        """
        try:
            asyncio.run_coroutine_threadsafe(
                self._async_send_signal(signal, trigger_price),
                self.loop
            )
            return True
        except Exception as e:
            self.log(f"启动信号发送异常: {e}", debug=True)
            return False

    def notify_order(self, order):
        """
        当订单被提交/接受时，认为产生交易信号，异步发送给外部平台
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            signal_type = 'buy' if order.isbuy() else 'sell'
            # 若取不到 data.close[0]，可回退到 order.price
            try:
                trigger_price = order.data.close[0]
            except:
                trigger_price = getattr(order, 'price', 0) or 0

            self.send_signal(signal_type, trigger_price)

        # 附加状态打印
        if order.status in [bt.Order.Completed]:
            self.log(f'订单完成 - 执行价格:{order.executed.price:.2f}', debug=True)

        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f"订单失败 - Status: {order.getstatusname()}", debug=True)

    def stop(self):
        """
        策略结束时关闭异步事件循环和线程，防止资源泄露
        """
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop_thread.join()
            self.log("异步事件循环已关闭", debug=True)
        except Exception as e:
            self.log(f"关闭事件循环异常: {e}", debug=True)
