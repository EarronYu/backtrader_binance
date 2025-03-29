import backtrader as bt
import talib
import math

class CespanolSR(bt.Strategy):
    params = (
        ('pivot_length', 1),         # Number of bars to calculate pivot
        ('max_breaks', 1),           # Max breaks before invalidating S/R levels
        ('max_safe_orders', 0),      # Max number of safety orders
        ('price_deviation', 0.01),   # Price deviation for safety orders
        ('safe_order_scale', 1),     # Safety order volume scale
        ('safe_order_step_scale', 1),# Safety order step scale
        ('atr_period', 20),         # ATR计算周期
        ('tp_atr', 3.0),            # 止盈ATR倍数
        ('sl_atr', 2.0),            # 止损ATR倍数
        ('initial_capital', 10000),  # Initial capital
    )

    def __init__(self):
        self.sr_levels = []         # List to store support/resistance levels
        self.breaks = []            # Break count for each S/R level
        self.safety_orders = []     # Store safety orders for averaging
        self.entry_price = None     # Store entry price
        self.deal_counter = 0       # Track the number of deals
        self.latest_price = None    # Latest close price
        
        # 添加ATR指标
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

    def next(self):
        # Get the current close price
        close = self.data.close[0]

        # Step 1: Calculate Support/Resistance (S/R) levels using pivot logic
        pivot = self.calculate_pivot()
        if pivot is not None:
            self.sr_levels.append(pivot)
            self.breaks.append(0)

        # Step 2: Check for level tests (Support/Resistance tests)
        if not self.position:  # Only check for entry if no position exists
            self.check_level_tests()

        # Step 3: Manage exits based on stop loss and take profit
        if self.position and self.position.size > 0:
            self.check_exit_conditions()

    def calculate_pivot(self):
        # 计算动态ATR阈值
        high = self.data.high.get(size=self.p.pivot_length)
        low = self.data.low.get(size=self.p.pivot_length) 
        close = self.data.close.get(size=self.p.pivot_length)
        
        atr20 = talib.ATR(high, low, close, timeperiod=20)
        fo = ((atr20[-1] / close[-1]) * 100) / 2  # 动态前冲/回撤阈值
        md = fo * 30  # 动态最大距离
        
        # 计算枢轴点
        pivot = (max(high) + min(low) + close[-1]) / 3
        
        # 检查是否为有效的S/R点
        if self.is_valid_sr(pivot, fo, md):
            return pivot
        return None

    def is_valid_sr(self, level, fo, md):
        # 检查价格是否在有效范围内
        current_price = self.data.close[0]
        price_diff_pct = abs(level - current_price) / current_price * 100
        
        # 如果价格偏离太大,则无效
        if price_diff_pct > md:
            return False
            
        # 检查是否突破次数超过限制
        for i, sr_level in enumerate(self.sr_levels):
            if abs(level - sr_level) / sr_level * 100 < fo:
                if self.breaks[i] >= self.p.max_breaks:
                    return False
        return True

    def check_level_tests(self):
        # 只在支撑位做多
        for level in self.sr_levels:
            if self.data.close[0] > level:  # 价格在支撑位上方
                if self.data.low[0] <= level:  # 测试支撑位
                    self.entry_price = self.data.close[0]
                    self.buy()  # 做多

    def check_exit_conditions(self):
        if not self.position or not self.entry_price:
            return
            
        current_atr = self.atr[0]
        
        # 基于ATR的止损价格
        stop_loss_price = self.entry_price - (current_atr * self.p.sl_atr)
        if self.data.close[0] <= stop_loss_price:
            self.close()  # 触发止损

        # 基于ATR的止盈价格
        take_profit_price = self.entry_price + (current_atr * self.p.tp_atr)
        if self.data.close[0] >= take_profit_price:
            self.close()  # 触发止盈