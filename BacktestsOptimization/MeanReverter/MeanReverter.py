import backtrader as bt
import math

class MeanReverter(bt.Strategy):
    params = (
        ('frequency', 20),          # 与Pine Script一致
        ('rsiFrequency', 50),       # RSI周期
        ('buyZoneDistance', 5),     # 买入区域距离百分比
        ('avgDownATRSum', 2),       # ATR求和周期
        ('useAbsoluteRSIBarrier', True),
        ('barrierLevel', 50),       # RSI阈值
        ('pyramiding', 6),          # 最大加仓次数
    )

    def __init__(self):
        self.opentrades = 0
        self.unit_ratio = 1.0 / self.p.pyramiding

        self.rsi = bt.talib.RSI(self.data.close, timeperiod=self.p.rsiFrequency)
        self.rsi_slow = bt.talib.SMA(self.rsi, timeperiod=self.p.frequency)
        self.atr = bt.talib.ATR(self.data.high, self.data.low, self.data.close, timeperiod=20)

    def next(self):
        if len(self) < self.p.avgDownATRSum:
            return  # 等待足够的数据点

        current_price = self.data.close[0]
        rsi_val = self.rsi[0]
        rsi_slow_val = self.rsi_slow[0]
        atr_sum = sum(self.atr.get(size=self.p.avgDownATRSum))

        price_condition = True
        if self.position:
            avg_price = self.position.price
            price_condition = (avg_price - atr_sum * self.opentrades) > current_price

        cond_buy_zone = rsi_val < rsi_slow_val * (1 - self.p.buyZoneDistance / 100.0)
        cond_max = self.opentrades < self.p.pyramiding
        isBuy = cond_buy_zone and price_condition and cond_max

        # 平仓条件
        isClose = (rsi_val > rsi_slow_val) and (rsi_val > self.p.barrierLevel or not self.p.useAbsoluteRSIBarrier)

        if isBuy:
            target_percent = self.unit_ratio * (self.opentrades + 1)
            self.order_target_percent(target=target_percent)
            self.opentrades += 1

        if self.position and isClose:
            self.order_target_percent(target=0.0)
            self.opentrades = 0
