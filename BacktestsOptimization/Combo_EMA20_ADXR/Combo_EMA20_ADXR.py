import datetime
import backtrader as bt
import talib

class Combo_EMA20_ADXR(bt.Strategy):
    params = (
        # EMA20 参数：使用 talib.EMA 计算基准均线，原始 PineScript 中参数名称为 Length（默认14）
        ('ema_length', 14),
        # ADX/ADXR 参数：分别对应 LengthADX 与 LengthADXR（默认均为14）
        ('adx_length', 14),
        ('adxr_offset', 14),
        # ADXR 信号判断阈值
        ('signal1', 13.0),
        ('signal2', 45.0),
        # 是否反转信号
        ('reverse', False),
    )

    def __init__(self):
        # 使用 TA-Lib 计算 EMA 作为 xXA（指标平滑值）
        self.ema = bt.talib.EMA(self.data.close, timeperiod=self.params.ema_length)
        # 使用 TA-Lib 计算 ADX（后续用于构造 ADXR 信号）
        self.adx = bt.talib.ADX(self.data.high, self.data.low, self.data.close, timeperiod=self.params.adx_length)
        # 用于存储 EMA20 与 ADXR 的历史信号状态
        self.ema20_signal = 0
        self.adxr_signal = 0
        # 预计算交易开始时间，后续在 next() 中与当前 bar 日期做比较
        self.start_trade_dt = datetime.datetime(self.params.start_year,
                                                  self.params.start_month,
                                                  self.params.start_day)

    def next(self):
        # 时间过滤：只有当前 bar 时间>= start_trade_dt 时才允许产生信号
        current_dt = self.data.datetime.datetime(0)
        StartTrade = current_dt >= self.start_trade_dt

        # 确保至少有两根 bar，便于取前一 bar 数据，否则直接退出
        if len(self.data) < 2:
            return

        # ----- 计算 EMA20 信号 -----
        # 计算当前 EMA 值（xXA）
        ema_val = self.ema[0]

        # 获取当前与前一 bar 的 high、low 与前一 bar 的 close
        high_current = self.data.high[0]
        high_prev    = self.data.high[-1]
        low_current  = self.data.low[0]
        low_prev     = self.data.low[-1]
        prev_close   = self.data.close[-1]

        # 计算 nHH 与 nLL（分别为当前与上一 bar high 的最大值和 low 的最小值）
        nHH = max(high_current, high_prev)
        nLL = min(low_current, low_prev)

        # 根据 PineScript 逻辑：若 nLL 大于 EMA 或 nHH 小于 EMA，则取 nLL，否则取 nHH
        if (nLL > ema_val or nHH < ema_val):
            nXS = nLL
        else:
            nXS = nHH

        # 根据 nXS 与上一个 bar 的收盘价来决定 EMA20 信号：
        # 若 nXS > 前一 bar 的 close，则信号为 -1
        # 若 nXS < 前一 bar的 close，则信号为 1
        # 否则延续上一 bar 的信号
        if nXS > prev_close:
            ema20_signal_new = -1
        elif nXS < prev_close:
            ema20_signal_new = 1
        else:
            ema20_signal_new = self.ema20_signal  # 延续前信号

        self.ema20_signal = ema20_signal_new

        # ----- 计算 ADXR 信号 -----
        # 若数据长度不足 adxr_offset，则保持上一 bar 的 ADXR 信号
        if len(self.data) < self.params.adxr_offset:
            adxr_signal_new = self.adxr_signal
        else:
            # 取当前 ADX 值与 adxr_offset 根前的 ADX 值，计算 ADXR
            adx_current = self.adx[0]
            adx_offset  = self.adx[-self.params.adxr_offset]
            xADXR = (adx_current + adx_offset) / 2.0

            # 判断 ADXR 信号：若 xADXR 小于 signal1，则信号为 1，
            # 若 xADXR 大于 signal2，则信号为 -1，
            # 否则延续上一 bar 信号
            if xADXR < self.params.signal1:
                adxr_signal_new = 1
            elif xADXR > self.params.signal2:
                adxr_signal_new = -1
            else:
                adxr_signal_new = self.adxr_signal

        self.adxr_signal = adxr_signal_new

        # ----- 综合信号逻辑 -----
        # 根据 EMA20 与 ADXR 信号，同时满足且符合交易开始条件时：
        #   当两者均为 1 时视为多头信号，
        #   当两者均为 -1 时视为空头信号，
        # 否则信号为 0（平仓）
        if StartTrade:
            if self.ema20_signal == 1 and self.adxr_signal == 1:
                pos = 1
            elif self.ema20_signal == -1 and self.adxr_signal == -1:
                pos = -1
            else:
                pos = 0
        else:
            pos = 0

        # 若启用了反转交易，则多空信号调换
        if self.params.reverse:
            if pos == -1:
                possig = 1
            elif pos == 1:
                possig = -1
            else:
                possig = pos
        else:
            possig = pos

        # ----- 根据信号下单（使用 order_target_percent）
        # 多头信号：目标仓位 100%（1.0）
        # 空头信号：目标仓位 -100%（-1.0）
        # 平仓信号：目标仓位 0%
        if possig == 1:
            self.order_target_percent(target=1.0)
        elif possig == -1:
            self.order_target_percent(target=-1.0)
        else:
            self.order_target_percent(target=0.0)
