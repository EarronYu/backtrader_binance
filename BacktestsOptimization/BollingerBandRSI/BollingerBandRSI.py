import backtrader as bt
import talib
import numpy as np

class BollingerBandRSI(bt.Strategy):
    params = (
        ('len_rsi', 14),  # RSI周期
        ('bb_len', 20),  # Bollinger Bands周期
        ('bb_mult', 2.0),  # Bollinger Bands标准差倍数
        ('rsi_upper', 70),  # RSI超买水平
        ('rsi_lower', 30),  # RSI超卖水平
        ('long_tp', 0.1),  # 多头止盈百分比
        ('long_sl', 0.25),  # 多头止损百分比
        ('pyramiding', 10),  # 最大加仓次数
    )

    def __init__(self):
        # 当前仓位的开盘价
        self.long_take_level = None
        self.long_stop_level = None
        
        # 记录加仓次数
        self.add_count = 0

    def next(self):
        # 将LineBuffer数据转换为numpy数组，以便给TA-Lib处理
        close_data = np.array(self.data.close.get(size=len(self)))

        # 计算RSI
        rsi = talib.RSI(close_data, timeperiod=self.params.len_rsi)

        # 计算Bollinger Bands
        bb_basis = talib.SMA(close_data, timeperiod=self.params.bb_len)
        bb_dev = talib.STDDEV(close_data, timeperiod=self.params.bb_len)
        bb_upper = bb_basis + self.params.bb_mult * bb_dev
        bb_lower = bb_basis - self.params.bb_mult * bb_dev

        # 定义止盈和止损价格
        if self.position:
            self.long_take_level = self.position.price * (1 + self.params.long_tp)
            self.long_stop_level = self.position.price * (1 - self.params.long_sl)

        # 计算加仓和止损的条件
        entry_long = rsi[-1] < self.params.rsi_lower and self.data.close[0] < bb_lower[0]
        exit_long = rsi[-1] > self.params.rsi_upper
        
        # 如果没有持仓，检查开仓信号
        if not self.position:
            if entry_long:
                # 使用 order_target_percent 来开仓
                self.order_target_percent(target=1/self.params.pyramiding)  # 第一次开仓占仓位的1/pyramiding
                self.add_count += 1  # 记录加仓次数
        
        # 如果持有仓位，检查加仓信号
        elif self.position.size > 0 and self.add_count < self.params.pyramiding:  # 只有在加仓次数未达到最大值时才加仓
            if entry_long:
                # 使用 order_target_percent 来加仓，目标仓位递增
                self.order_target_percent(target=(self.add_count + 1) / self.params.pyramiding)  # 第n次加仓目标仓位为 n/pyramiding
                self.add_count += 1  # 增加加仓次数

            # 检查平仓条件：退出多头
            if exit_long or self.data.close[0] >= self.long_take_level or self.data.close[0] <= self.long_stop_level:
                # 使用 order_target_percent 来平仓
                self.order_target_percent(target=0.0)  # 平掉所有仓位
                self.add_count = 0  # 重置加仓次数
