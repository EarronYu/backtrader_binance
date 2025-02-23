import pandas as pd
import numpy as np
import talib as ta
from backtesting import Strategy
# from record_trade import record_trade  # 导入独立的 record_trade 函数

class MeanReverter(Strategy):
    """
    均值回归策略：
      利用 TA Lib 计算的 RSI 和 ATR 指标判断入场、加仓和平仓时机，
      实现分批建仓。这里我们使用资金比例（dca）下单方式实现pyramiding加仓，
      从而去掉对cash参数的依赖（backtesting库中并没有该参数）。

    参数说明：
      frequency             : 用于计算慢速 RSI 均线的周期（默认 10），平滑 RSI 指标
      rsiFrequency          : 计算 RSI 的周期（默认 40），衡量市场动能
      buyZoneDistance       : RSI 低于慢速 RSI 的比例（默认 5%），认为处于超卖区域
      avgDownATRSum         : 累计 ATR 的周期个数（默认 3），用于加仓时判断价格跌幅
      useAbsoluteRSIBarrier : 是否使用绝对 RSI 障碍（默认 True），平仓时要求 RSI 超过 barrierLevel
      barrierLevel          : RSI 障碍水平（默认 50），当启用绝对障碍时，只有 RSI 超过该值才平仓
      pyramiding            : 最大允许加仓次数（例如：8，即最多允许 8 次买入/加仓）
    """
    frequency = 10
    rsiFrequency = 40
    buyZoneDistance = 5
    avgDownATRSum = 3
    useAbsoluteRSIBarrier = True
    barrierLevel = 50
    pyramiding = 8  # 最大允许加仓次数

    symbol = "1000PEPEUSDT"  # 定义交易对标识
    timeframe = "1m"         # 定义时间周期

    def init(self):
        # 初始化已加仓次数及单位资金比例（用来分批加仓）
        self.opentrades = 0
        self.unit_ratio = 1 / self.pyramiding

        # 使用self.I()计算指标
        self.rsi_series = self.I(ta.RSI, self.data.Close, self.rsiFrequency)
        self.sma_series = self.I(ta.SMA, self.rsi_series, self.frequency)
        self.atr_series = self.I(ta.ATR, self.data.High, self.data.Low, self.data.Close, timeperiod=20)

    def next(self):
        # 获取当前时间，并转换为字符串记录交易时间
        current_time = str(self.data.index[-1])
        # 获取当前最新价格
        price = self.data.Close[-1]

        # 获取当前 RSI 和 ATR 的值
        rsi_val = self.rsi_series[-1]
        rsi_slow = self.sma_series[-1]

        if len(self.atr_series) >= self.avgDownATRSum:
            atr_sum = np.sum(self.atr_series[-self.avgDownATRSum:])
        else:
            atr_sum = 0

        # -------------------------------
        # 开仓/加仓条件判断
        # -------------------------------
        # 条件1：RSI处于超卖区域：RSI < 慢速RSI均线*(1 - buyZoneDistance/100)
        cond_buy_zone = rsi_val < rsi_slow * (1 - self.buyZoneDistance / 100)
        # 条件2：价格确认。若已持仓，则需计算加权平均入场价格
        if self.position:
            trades = self._broker.trades  # 获取所有交易记录
            if trades:
                total_size = sum(abs(trade.size) for trade in trades)
                avg_price = sum(trade.entry_price * abs(trade.size) for trade in trades) / total_size
                # 这里要求当前价格低于调整后的平均价格
                price_below_avg = price < avg_price * (1 - 0.01 * self.opentrades)
            else:
                price_below_avg = True
        else:
            price_below_avg = True
        # 条件3：检查加仓次数是否未达到最大允许次数
        cond_max = self.opentrades < self.pyramiding

        isBuy = cond_buy_zone and price_below_avg and cond_max

        # -------------------------------
        # 平仓条件判断
        # -------------------------------
        isClose = (rsi_val > rsi_slow) and (rsi_val > self.barrierLevel or not self.useAbsoluteRSIBarrier)

        # -------------------------------
        # 执行交易信号并记录交易
        # -------------------------------
        if isBuy:
            # 计算当前应该使用的资金比例（累进式下单）
            current_ratio = self.unit_ratio * (self.opentrades + 1)
            # 直接使用资金比例下单，不依赖账户现金（backtesting策略中该参数不存在）
            self.buy(size=current_ratio)
            self.opentrades += 1
            # record_trade({
            #     "symbol": self.symbol,
            #     "timeframe": self.timeframe,
            #     "date": current_time,
            #     "signal": f"{self.__class__.__name__} enter_long"
            # })        
               
        if self.position and isClose:
            self.position.close()
            self.opentrades = 0
            # record_trade({
            #     "symbol": self.symbol,
            #     "timeframe": self.timeframe,
            #     "date": current_time,
            #     "signal": f"{self.__class__.__name__} exit_long"
            # })

