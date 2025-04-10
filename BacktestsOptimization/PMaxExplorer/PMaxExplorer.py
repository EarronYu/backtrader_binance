import backtrader as bt
import talib
import math
import numpy as np

class PMaxExplorer(bt.Strategy):
    params = (
        ('Periods', 10),         # ATR周期
        ('Multiplier', 3.0),     # ATR倍数
        ('mav', 'EMA'),          # 移动平均类型，可选：SMA, EMA, WMA, TMA, VAR, WWMA, ZLEMA, TSF
        ('length', 10),          # 移动平均周期
        ('changeATR', True),     # 是否采用内置 ATR 计算方式
    )
    
    def __init__(self):
        # ATR 指标：若 changeATR 为 True，用 TA-Lib.ATR，否则使用 TrueRange 的 SMA 平滑
        if self.p.changeATR:
            self.atr_ind = bt.talib.ATR(self.data, timeperiod=self.p.Periods)
        else:
            self.tr = bt.indicators.TrueRange(self.data)
            # 利用 TA-Lib.SMA 平滑 TrueRange（注：此处利用 talib.SMA 处理整个数据序列）
            self.atr_ind = bt.talib.SMA(self.tr, timeperiod=self.p.Periods)
        
        # 用于保存 (high+low)/2 的历史序列，供自定义 MA 计算使用
        self.custom_src = []
        # 保存前一 bar 的 MAvg 与 PMax 用于交叉检测
        self.prev_MAvg = None
        self.prev_PMax = None
        
        # 用于 PMax 递归计算的变量
        self.longStop = None
        self.shortStop = None
        self.dir = 1   # 初始方向设为多头（1）
        self.PMax = None
        
        # 用于自定义递归指标的存储（VAR, WWMA, ZLEMA）
        self.var_value = None   # VAR 指标
        self.wwma = None        # WWMA 指标
        self.zlema = None       # ZLEMA 指标
        # TSF 不需要递归存储，只用滚动窗口计算
        
    def next(self):
        # 计算当前 src = hl2
        current_src = (self.data.high[0] + self.data.low[0]) / 2
        self.custom_src.append(current_src)
        
        # ---------------------------
        # 计算移动平均 MAvg
        # ---------------------------
        mav_type = self.p.mav.upper()
        # 若使用 TA-Lib 内置指标，则将历史 src 转为数组进行计算
        if mav_type in ["EMA", "SMA", "WMA", "TMA"]:
            src_arr = np.array(self.custom_src, dtype=float)
            if len(src_arr) < self.p.length:
                MAvg = current_src
            else:
                if mav_type == "EMA":
                    mavg_series = talib.EMA(src_arr, timeperiod=self.p.length)
                elif mav_type == "SMA":
                    mavg_series = talib.SMA(src_arr, timeperiod=self.p.length)
                elif mav_type == "WMA":
                    mavg_series = talib.WMA(src_arr, timeperiod=self.p.length)
                elif mav_type == "TMA":
                    ceil_len = int(math.ceil(self.p.length / 2.0))
                    floor_len = int(math.floor(self.p.length / 2.0)) + 1
                    sma1 = talib.SMA(src_arr, timeperiod=ceil_len)
                    mavg_series = talib.SMA(sma1, timeperiod=floor_len)
                MAvg = mavg_series[-1] if not math.isnan(mavg_series[-1]) else current_src
        else:
            # 自定义计算 VAR、WWMA、ZLEMA、TSF
            if mav_type == "VAR":
                # 根据 PineScript：使用 9 bar 累加差分计算 CMO，再递归计算 VAR
                if len(self.custom_src) < 2:
                    MAvg = current_src
                    self.var_value = current_src
                else:
                    n = 9
                    start_idx = max(1, len(self.custom_src) - n)
                    vud_sum = 0.0
                    vdd_sum = 0.0
                    for i in range(start_idx, len(self.custom_src)):
                        diff = self.custom_src[i] - self.custom_src[i-1]
                        if diff > 0:
                            vud_sum += diff
                        elif diff < 0:
                            vdd_sum += -diff
                    denom = vud_sum + vdd_sum
                    vCMO = (vud_sum - vdd_sum) / denom if denom != 0 else 0
                    alpha = 2 / (self.p.length + 1)
                    if self.var_value is None:
                        self.var_value = current_src
                    MAvg = alpha * abs(vCMO) * current_src + (1 - alpha * abs(vCMO)) * self.var_value
                    self.var_value = MAvg
            elif mav_type == "WWMA":
                # WWMA = (1/length)*src + (1 - 1/length)*WWMA[1]
                alpha = 1 / self.p.length
                if self.wwma is None:
                    self.wwma = current_src
                MAvg = alpha * current_src + (1 - alpha) * self.wwma
                self.wwma = MAvg
            elif mav_type == "ZLEMA":
                # zxLag = if length even then length/2 else (length-1)/2；ZLEMA = EMA( src + (src - src[zxLag]) , length)
                if self.p.length % 2 == 0:
                    lag = int(self.p.length / 2)
                else:
                    lag = int((self.p.length - 1) / 2)
                if len(self.custom_src) <= lag:
                    zxed = current_src
                else:
                    # 注意：由于 Python 索引从 0 开始，取 -lag-1 对应 PineScript 的 src[zxLag]
                    zxed = current_src + (current_src - self.custom_src[-lag-1])
                alpha = 2 / (self.p.length + 1)
                if self.zlema is None:
                    self.zlema = zxed
                MAvg = alpha * zxed + (1 - alpha) * self.zlema
                self.zlema = MAvg
            elif mav_type == "TSF":
                # TSF = 2*linreg(src, length, 0) - linreg(src, length, 1)
                if len(self.custom_src) < self.p.length:
                    MAvg = current_src
                else:
                    n = self.p.length
                    y = np.array(self.custom_src[-n:], dtype=float)
                    x = np.arange(n, dtype=float)
                    # 线性回归
                    slope, intercept = np.polyfit(x, y, 1)
                    forecast0 = slope * (n - 1) + intercept
                    forecast1 = slope * n + intercept
                    MAvg = 2 * forecast0 - forecast1
            else:
                MAvg = current_src  # 默认回退
                
        # ---------------------------
        # PMax 计算：基于 MAvg 与 ATR
        # ---------------------------
        atr_value = self.atr_ind[0]
        mult = self.p.Multiplier
        comp_longStop = MAvg - mult * atr_value
        comp_shortStop = MAvg + mult * atr_value
        
        # 初始化（第一根K线）
        if self.longStop is None:
            self.longStop = comp_longStop
            self.shortStop = comp_shortStop
            self.dir = 1
            self.PMax = self.longStop
            # 无法产生交叉信号，保存并退出
            self.prev_MAvg = MAvg
            self.prev_PMax = self.PMax
            return
        
        # 递归更新 longStop 与 shortStop
        if MAvg > self.longStop:
            new_longStop = max(comp_longStop, self.longStop)
        else:
            new_longStop = comp_longStop
        if MAvg < self.shortStop:
            new_shortStop = min(comp_shortStop, self.shortStop)
        else:
            new_shortStop = comp_shortStop
        
        # 更新方向：若前方向为 -1 且当前 MAvg 大于前 shortStop 转为多头；若前方向为 1 且 MAvg 小于前 longStop 转为空头
        new_dir = self.dir
        if self.dir == -1 and MAvg > self.shortStop:
            new_dir = 1
        elif self.dir == 1 and MAvg < self.longStop:
            new_dir = -1
        
        new_PMax = new_longStop if new_dir == 1 else new_shortStop
        
        # ---------------------------
        # 交易信号：使用 MAvg 与 PMax 的交叉判断
        # 买入信号：前一bar MAvg <= PMax 且当前 MAvg > 当前 PMax
        # 卖出信号：前一bar MAvg >= PMax 且当前 MAvg < 当前 PMax
        # ---------------------------
        if self.prev_MAvg is not None and self.prev_PMax is not None:
            if (self.prev_MAvg <= self.prev_PMax) and (MAvg > new_PMax):
                # 多头信号，下单设定目标仓位为 100%
                self.order_target_percent(target=1.0)
            elif (self.prev_MAvg >= self.prev_PMax) and (MAvg < new_PMax):
                # 空头信号，下单设定目标仓位为 -100%
                self.order_target_percent(target=-1.0)
        
        # 更新递归变量以供下一bar使用
        self.longStop = new_longStop
        self.shortStop = new_shortStop
        self.dir = new_dir
        self.PMax = new_PMax
        
        self.prev_MAvg = MAvg
        self.prev_PMax = new_PMax
