import backtrader as bt
import backtrader.indicators as btind
import math
from collections import deque

class ConnorsReversal(bt.Strategy):
    params = (
        ("symbol", "1000PEPEUSDT"),
        # 使用 backtrader 正确的时间周期常量（例如：bt.TimeFrame.Minutes）
        ("timeframe", bt.TimeFrame.Minutes),
        ("lowest_point_bars", 16),
        ("rsi_length", 4),
        ("sell_barrier", 73),
        ("dca_parts", 8),
        ("max_lookback", 50),
        ("sma_period", 55),
        ("only_buy_above_sma", False)
    )

    def __init__(self):
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
        self.debug_mode = False

    # 修改后的 log 函数，直接输出预先构造好的文本字符串
    def log(self, txt, dt=None, debug=False):
        if debug and not self.debug_mode:
            return
        dt = dt or self.data.datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

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
            # 确保当前价格也参与检测（避免因NaN而遗漏）
            if not valid_prices or current_price != valid_prices[-1]:
                valid_prices.append(current_price)
            min_price = min(valid_prices)
            return current_price <= min_price

        except Exception as e:
            self.log(f"最低点检查错误: {str(e)}", debug=True)
            return False

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

            # 卖出条件：持仓且 RSI 超过卖出阈值时平仓（使用目标百分比下单归零仓位）
            if self.position and self.rsi[0] > self.p.sell_barrier:
                self.order_target_percent(target=0.0)
                self.open_trades = 0
                self.log(f"卖出信号 - RSI: {self.rsi[0]:.6f}，目标仓位: 0.00", debug=True)
                return

            if is_lowest:
                # 检查买入条件
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

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"交易关闭: 毛利润={trade.pnl:.6f}, 净利润={trade.pnlcomm:.6f}", debug=True)