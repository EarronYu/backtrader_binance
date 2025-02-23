import pandas as pd
import numpy as np
import talib as ta
from backtesting import Strategy
# from record_trade import record_trade  # 导入独立的 record_trade 函数

class MeanReverterShort(Strategy):
    """
    均值回归策略：做空版
      利用 TA Lib 计算的 RSI 和 ATR 指标判断开空、加仓和平仓时机，
      实现分批开空。这里我们使用资金比例（dca）下单方式实现 pyramiding 加仓，
      去掉对 cash 参数的依赖（backtesting 库中并没有该参数）。

    参数说明：
      frequency             : 用于计算慢速 RSI 均线的周期（默认 10），平滑 RSI 指标
      rsiFrequency          : 计算 RSI 的周期（默认 40），衡量市场动能
      sellZoneDistance      : RSI 高于慢速RSI均线的比例（默认 5%），认为处于超买区域，作为做空入场条件
      avgUpATRSum           : 累计 ATR 的周期个数（默认 3），用于加仓时判断价格涨幅（做空时要求价格高于加权均价）
      useAbsoluteRSIBarrier : 是否使用绝对 RSI 障碍（默认 True），平仓时要求 RSI 低于 barrierLevel
      barrierLevel          : RSI 障碍水平（默认 50），当启用绝对障碍时，只有 RSI 低于该值才平仓
      pyramiding            : 最大允许加仓次数（例如：8，即最多允许 8 次卖空/加仓）
    """
    frequency = 10
    rsiFrequency = 40
    sellZoneDistance = 5
    avgUpATRSum = 3
    useAbsoluteRSIBarrier = True
    barrierLevel = 50
    pyramiding = 8  # 最大允许加仓次数

    symbol = "1000PEPEUSDT"  # 添加交易对标识
    timeframe = "1m"         # 添加时间周期

    def init(self):
        # 初始化已加仓次数及单位资金比例（用来分批加仓）
        self.opentrades = 0
        self.unit_ratio = 1 / self.pyramiding

        # 使用self.I()计算指标
        self.rsi_series = self.I(ta.RSI, self.data.Close, self.rsiFrequency)
        self.sma_series = self.I(ta.SMA, self.rsi_series, self.frequency)
        self.atr_series = self.I(ta.ATR, self.data.High, self.data.Low, self.data.Close, timeperiod=20)

    def next(self):
        # 获取当前时间作为记录用
        current_time = str(self.data.index[-1])
        # 获取当前最新价格
        price = self.data.Close[-1]

        # 获取当前 RSI 和 ATR 的值
        rsi_val = self.rsi_series[-1]
        rsi_slow = self.sma_series[-1]

        if len(self.atr_series) >= self.avgUpATRSum:
            atr_sum = np.sum(self.atr_series[-self.avgUpATRSum:])
        else:
            atr_sum = 0

        # -------------------------------
        # 开空/加空条件判断
        # -------------------------------
        # 条件1：RSI 处于超买区域：RSI > 慢速RSI均线*(1 + sellZoneDistance/100)
        cond_sell_zone = rsi_val > rsi_slow * (1 + self.sellZoneDistance / 100)

        # 条件2：价格确认。若已有空仓，则需计算加权平均入场价格，
        # 对做空来说，要求当前价格高于调整后的平均价格（有利于获得更高的卖空均价）
        if self.position:
            trades = self._broker.trades  # 获取所有交易记录
            if trades:
                total_size = sum(abs(trade.size) for trade in trades)
                avg_price = sum(trade.entry_price * abs(trade.size) for trade in trades) / total_size
                price_above_avg = price > avg_price * (1 + 0.01 * self.opentrades)
            else:
                price_above_avg = True
        else:
            price_above_avg = True

        # 条件3：检查加仓次数是否未达到最大允许次数
        cond_max = self.opentrades < self.pyramiding

        isShort = cond_sell_zone and price_above_avg and cond_max

        # -------------------------------
        # 平仓条件判断（买回平仓）
        # -------------------------------
        # 当 RSI 回落：RSI < 慢速RSI均线，且在启用绝对障碍时 RSI 必须低于 barrierLevel
        isCover = (rsi_val < rsi_slow) and (rsi_val < self.barrierLevel or not self.useAbsoluteRSIBarrier)

        # -------------------------------
        # 执行交易信号
        # -------------------------------
        if isShort:
            # 计算当前应使用的资金比例（累进式下单）
            current_ratio = self.unit_ratio * (self.opentrades + 1)
            # 直接使用资金比例下单，不依赖账户现金
            self.sell(size=current_ratio)
            self.opentrades += 1
            # record_trade({
            #     "symbol": self.symbol,
            #     "timeframe": self.timeframe,
            #     "date": current_time,
            #     "signal": f"{self.__class__.__name__} enter_short"
            # })

        if self.position and isCover:
            self.position.close()
            self.opentrades = 0
            # record_trade({
            #     "symbol": self.symbol,
            #     "timeframe": self.timeframe,
            #     "date": current_time,
            #     "signal": f"{self.__class__.__name__} exit_short"
            # })

