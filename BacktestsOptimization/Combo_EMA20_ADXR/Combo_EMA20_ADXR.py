import datetime
import backtrader as bt
import talib

class Combo_EMA20_ADXR(bt.Strategy):
    params = (
        # EMA20 参数：使用 talib.EMA 计算基准均线（原 PineScript 中的 Length，默认14）
        ('ema_length', 14),
        # ADX/ADXR 参数：分别对应 LengthADX 和 LengthADXR（默认均为14）
        ('adx_length', 14),
        ('adxr_offset', 14),
        # ADXR 信号判断阈值
        ('signal1', 13.0),
        ('signal2', 45.0),
        # 是否反转信号
        ('reverse', False),
    )

    def __init__(self):
        # 使用 TA-Lib 计算 EMA 作为中间指标
        self.ema = bt.talib.EMA(self.data.close, timeperiod=self.params.ema_length)
        # 使用 TA-Lib 计算 ADX，用于后续构造 ADXR 信号
        self.adx = bt.talib.ADX(self.data.high, self.data.low, self.data.close, timeperiod=self.params.adx_length)
        
        # 用于记录 EMA20 与 ADXR 的历史信号状态
        self.ema20_signal = 0
        self.adxr_signal = 0

    def next(self):
        # 确保至少存在2根 bar，便于取前一 bar 数据
        if len(self.data) < 2:
            return

        # ----- 计算 EMA20 信号 -----
        ema_val = self.ema[0]

        # 获取当前 bar 与前一 bar 的 high、low 和前一 bar 的 close
        high_current = self.data.high[0]
        high_prev    = self.data.high[-1]
        low_current  = self.data.low[0]
        low_prev     = self.data.low[-1]
        prev_close   = self.data.close[-1]

        # 计算当前与前一 bar 的 high 的最大值和 low 的最小值
        nHH = max(high_current, high_prev)
        nLL = min(low_current, low_prev)

        # 若 nLL 大于 EMA 或 nHH 小于 EMA，则取 nLL，否则取 nHH
        if (nLL > ema_val or nHH < ema_val):
            nXS = nLL
        else:
            nXS = nHH

        # 若 nXS 大于前一 bar 的 close，则信号为 -1；若 nXS 小于前一 bar 的 close，则信号为 1；
        # 否则保持上一 bar 信号
        if nXS > prev_close:
            ema20_signal_new = -1
        elif nXS < prev_close:
            ema20_signal_new = 1
        else:
            ema20_signal_new = self.ema20_signal

        self.ema20_signal = ema20_signal_new

        # ----- 计算 ADXR 信号 -----
        # 当数据长度不足 adxr_offset 时，保持上一 bar 的 ADXR 信号
        if len(self.data) < self.params.adxr_offset:
            adxr_signal_new = self.adxr_signal
        else:
            # 当前 ADX 值与 adxr_offset 根前的 ADX 值均值作为 ADXR
            adx_current = self.adx[0]
            adx_offset  = self.adx[-self.params.adxr_offset]
            xADXR = (adx_current + adx_offset) / 2.0

            # 判断 ADXR 信号：若 xADXR 小于 signal1，则为 1；大于 signal2，则为 -1；否则延续上一状态
            if xADXR < self.params.signal1:
                adxr_signal_new = 1
            elif xADXR > self.params.signal2:
                adxr_signal_new = -1
            else:
                adxr_signal_new = self.adxr_signal

        self.adxr_signal = adxr_signal_new

        # ----- 信号综合逻辑 -----
        # 同时满足：EMA20 信号和 ADXR 信号均为 1 → 多头信号
        # 同时满足：EMA20 信号和 ADXR 信号均为 -1 → 空头信号
        # 其他情况视为平仓信号（0）
        if self.ema20_signal == 1 and self.adxr_signal == 1:
            pos = 1
        elif self.ema20_signal == -1 and self.adxr_signal == -1:
            pos = -1
        else:
            pos = 0

        # 处理反转交易参数，将多空信号互换（如果启用了 reverse）
        if self.params.reverse:
            if pos == -1:
                possig = 1
            elif pos == 1:
                possig = -1
            else:
                possig = pos
        else:
            possig = pos

        # ----- 根据信号下单（使用 order_target_percent 方法）-----
        # 多头信号：目标仓位 100%（1.0）
        # 空头信号：目标仓位 -100%（-1.0）
        # 平仓信号：目标仓位 0%
        if possig == 1:
            self.order_target_percent(target=1.0)
        elif possig == -1:
            self.order_target_percent(target=-1.0)
        else:
            self.order_target_percent(target=0.0)