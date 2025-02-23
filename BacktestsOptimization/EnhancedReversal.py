import numpy as np
import pandas as pd
import talib
from backtesting import Strategy
from backtesting.lib import crossover

class EnhancedReversalStrategy(Strategy):
    """
    基于Larry Connors的简单反转交易策略,加入OBV和VWMA指标
    """
    # 定义策略参数
    initial_balance = 1000  # 初始资金
    lowest_point_bars = 7  # 寻找最低点的周期数
    rsi_length = 2        # RSI周期
    sell_barrier = 75     # RSI卖出阈值
    vwma_period = 55     # VWMA周期
    max_dca_times = 8    # 最大DCA次数

    def volume_weighted_rsi(self, close, volume, length=14):
        """计算成交量加权RSI"""
        delta = pd.Series(close).diff()
        gain = (delta.where(delta > 0, 0) * volume).rolling(window=length).sum()
        loss = (-delta.where(delta < 0, 0) * volume).rolling(window=length).sum()
        rs = gain / loss
        vw_rsi = 100 - (100 / (1 + rs))
        return vw_rsi
    
    def init(self):
        # 计算成交量加权RSI
        self.vw_rsi = self.I(self.volume_weighted_rsi, 
                            self.data.Close,
                            self.data.Volume,
                            length=self.rsi_length)
        
        # 计算VWAP
        typical_price = (self.data.High + self.data.Low + self.data.Close) / 3
        self.vwap = self.I(lambda: (typical_price * self.data.Volume).cumsum() / self.data.Volume.cumsum())
        
        # 计算VWMA（使用TA-Lib的MA函数）
        self.vwma = self.I(lambda: talib.SMA(self.vwap, timeperiod=self.vwma_period))
        
        # 计算OBV（使用TA-Lib的OBV函数）
        self.obv = self.I(lambda: talib.OBV(self.data.Close, self.data.Volume))
        
        # 计算最低点
        self.lowest = self.I(lambda: pd.Series(self.data.Close).rolling(self.lowest_point_bars).min())

        self.buy_count = 0  # 初始化买入计数器

    def calculate_avg_price(self):
        """计算当前持仓的平均价格"""
        # 使用绝对持仓量计算加权平均价格（参考Connors策略的持仓计算方式）
        total_size = sum(abs(trade.size) for trade in self.trades)
        total_cost = sum(trade.entry_price * abs(trade.size) for trade in self.trades)
        return total_cost / total_size if total_size != 0 else 0.0

    def check_obv_divergence(self):
        """检查OBV背离"""
        # 价格创新低但OBV没有创新低，表示正向背离
        price_new_low = self.data.Close[-1] < min(self.data.Close[-5:-1])
        obv_not_new_low = self.obv[-1] > min(self.obv[-5:-1])
        return price_new_low and obv_not_new_low

    def next(self):
        # 计算是否是最低点
        is_period_low = self.data.Close[-1] == self.lowest[-1]
        
        # 检查OBV背离
        is_obv_divergence = self.check_obv_divergence()
        
        # 检查价格是否低于VWMA
        price_below_vwma = self.data.Close[-1] < self.vwma[-1]
        
        # 计算是否达到卖出条件
        is_highest = self.vw_rsi[-1] > self.sell_barrier
        
        # 计算买入条件
        avg_price = self.calculate_avg_price() if self.position else float('inf')
        
        # 修改买入条件逻辑
        can_buy = (
            (is_period_low or is_obv_divergence) and  # 放宽买入条件
            price_below_vwma and  # 价格低于VWMA
            self.buy_count < self.max_dca_times and  # 买入次数限制
            (not self.position or  # 没有持仓
             self.data.Close[-1] < avg_price * (1 - 0.01 * self.buy_count))  # 当前价格低于调整后的平均价格
        )
        # 执行买入
        if can_buy:
            # 使用累进式资金管理 (参考Connors策略的DCA方式)
            unit_ratio = 1 / self.max_dca_times
            current_ratio = unit_ratio * (self.buy_count + 1)
            # 根据当前资金比例计算买入数量
            size = max(1, int((current_ratio * self.equity) / self.data.Close[-1]))
            self.buy(size=size)
            self.buy_count += 1
            
        # 执行卖出
        elif is_highest and self.position:
            self.position.close()
            self.buy_count = 0  # 重置买入计数器