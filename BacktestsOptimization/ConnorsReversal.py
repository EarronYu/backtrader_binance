import backtrader as bt
import backtrader.indicators as btind
import numpy as np
from collections import deque
import math

class ConnorsReversal(bt.Strategy):
    params = (
        ("symbol", "1000PEPEUSDT"),
        ("timeframe", "1m"),
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
        
        # 计算 warm-up 周期
        self.warmup = max(
            self.p.rsi_length * 2,  # RSI需要更多数据来稳定
            self.p.sma_period * 2,  # SMA需要更多数据来稳定
            self.max_window,        # 价格窗口需求
            self.p.lowest_point_bars * 2  # 最低点检测需求
        )
        
        # 状态标志
        self.ready = False
        self.initialized = False
        
        # 调试信息
        self.debug_mode = False

    def log(self, txt, dt=None, debug=False):
        if debug and not self.debug_mode:
            return
        dt = dt or self.data.datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

    def start(self):
        self.initialized = True
        self.log(f"策略启动 - Warmup: {self.warmup}, MaxWindow: {self.max_window}", debug=True)

    def prenext(self):
        """在数据预热阶段调用"""
        if not self.initialized:
            return
            
        current_price = self.data.close[0]
        if not math.isnan(current_price):
            self.closes.append(current_price)
            self.min_price_window.append(current_price)
            
        if self.debug_mode and len(self.data) % 100 == 0:
            self.log(f"预热中 - Bar: {len(self.data)}, Closes: {len(self.closes)}", debug=True)

    def is_local_minimum(self):
        """检查当前价格是否是局部最低点"""
        try:
            if len(self.min_price_window) < self.p.lowest_point_bars:
                return False
                
            current_price = self.data.close[0]
            if math.isnan(current_price):
                return False
                
            valid_prices = [p for p in self.min_price_window if not math.isnan(p)]
            if not valid_prices:
                return False
                
            min_price = min(valid_prices)
            return current_price <= min_price and current_price == valid_prices[-1]
            
        except Exception as e:
            self.log(f"最低点检查错误: {str(e)}")
            return False

    def next(self):
        """主要策略逻辑"""
        if not self.initialized:
            return
            
        current_price = self.data.close[0]
        if math.isnan(current_price):
            return
            
        # 更新数据窗口
        self.closes.append(current_price)
        self.min_price_window.append(current_price)
        
        # 检查数据预热
        current_bar = len(self.data)
        if current_bar < self.warmup:
            if self.debug_mode and current_bar % 100 == 0:
                self.log(f"等待预热完成 - Bar: {current_bar}/{self.warmup}", debug=True)
            return
            
        # 检查指标和数据是否就绪
        if not self.ready:
            if (len(self.closes) >= self.max_window and
                not math.isnan(self.rsi[0]) and 
                not math.isnan(self.sma[0])):
                self.ready = True
                self.log("策略就绪，开始交易", debug=True)
            else:
                return

        try:
            # 检查是否是局部最低点
            is_lowest = self.is_local_minimum()
            
            # 执行交易逻辑
            if self.position and self.rsi[0] > self.p.sell_barrier:
                self.close()
                self.open_trades = 0
                self.log(f"卖出信号 - RSI: {self.rsi[0]:.2f}")
                return
                
            if is_lowest:
                # 检查买入条件
                price_below_avg = True
                if self.position:
                    avg_price = self.position.price
                    price_below_avg = (current_price < avg_price * (1 - 0.01 * self.open_trades))
                
                above_sma = current_price > self.sma[0]
                sma_condition = above_sma or not self.p.only_buy_above_sma
                
                if ((price_below_avg or self.open_trades == 0) and 
                    sma_condition and 
                    self.open_trades < self.p.dca_parts):
                    
                    # 执行买入
                    cash = self.broker.getcash()
                    if cash > 0:
                        current_ratio = self.unit_ratio * (self.open_trades + 1)
                        size = cash * current_ratio / current_price
                        
                        if size > 0:
                            self.buy(size=size)
                            self.open_trades += 1
                            self.log(f'买入: 价格={current_price:.2f}, 数量={size:.2f}, 加仓次数={self.open_trades}')
                            
        except Exception as e:
            self.log(f'策略执行错误: {str(e)}')
            return

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'交易关闭: 毛利润={trade.pnl:.2f}, 净利润={trade.pnlcomm:.2f}')