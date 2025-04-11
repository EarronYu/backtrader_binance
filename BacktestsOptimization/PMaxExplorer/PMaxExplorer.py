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
        # ATR 部分：如果 changeATR 为 True，则调用 TA-Lib.ATR（需传入 high, low, close）
        if self.p.changeATR:
            self.atr_ind = bt.talib.ATR(self.data.high, self.data.low, self.data.close, timeperiod=self.p.Periods)
        else:
            # 否则用 TrueRange 后 SMA 平滑（注意，此处仅为替代方案）
            self.tr = bt.indicators.TrueRange(self.data)
            self.atr_ind = bt.talib.SMA(self.tr, timeperiod=self.p.Periods)
        
        # 存储 hl2 序列（即 (high+low)/2），用于指标计算
        self.custom_src = []        

        # 保存上一个 bar 的 MAvg 与 PMax，用于交叉检测（开仓/平仓信号）
        self.prev_MAvg = None
        self.prev_PMax = None

        # 用于 PMax 递归计算的变量：longStop、shortStop、方向（dir）、以及当前 PMax
        self.longStop = None
        self.shortStop = None
        self.dir = 1   # 初始方向设为 1（多头）
        self.PMax = None

        # 如果使用自定义 MA（VAR、WWMA、ZLEMA、TSF），需要保存上次的值：
        self.var_value = None   # VAR 指标
        self.wwma = None        # WWMA 指标
        self.zlema = None       # ZLEMA 指标
        # TSF 直接滚动计算，无需递归存储

    def next(self):
        # ---------------------------
        # 1. 计算指标源 src
        # ---------------------------
        current_src = (self.data.high[0] + self.data.low[0]) / 2
        self.custom_src.append(current_src)
        
        # ---------------------------
        # 2. 根据参数计算 MAvg
        # ---------------------------
        mav_type = self.p.mav.upper()
        if mav_type in ["EMA", "SMA", "WMA", "TMA"]:
            # 利用 TA-Lib 函数计算：需要把历史 src 转为 numpy 数组
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
            # 自定义计算：VAR、WWMA、ZLEMA、TSF
            if mav_type == "VAR":
                # 计算方法：先计算 9 个 bar 内正负差分累加得到 vCMO，再递归更新 VAR
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
                # ZLEMA：计算延迟 lag，然后用 EMA 平滑 (src + (src - src[zxLag]))
                if self.p.length % 2 == 0:
                    lag = int(self.p.length / 2)
                else:
                    lag = int((self.p.length - 1) / 2)
                if len(self.custom_src) <= lag:
                    zxed = current_src
                else:
                    zxed = current_src + (current_src - self.custom_src[-lag-1])
                alpha = 2 / (self.p.length + 1)
                if self.zlema is None:
                    self.zlema = zxed
                MAvg = alpha * zxed + (1 - alpha) * self.zlema
                self.zlema = MAvg
            elif mav_type == "TSF":
                # TSF 采用线性回归：TSF = 2*linreg(src, length, 0) - linreg(src, length, 1)
                if len(self.custom_src) < self.p.length:
                    MAvg = current_src
                else:
                    n = self.p.length
                    y = np.array(self.custom_src[-n:], dtype=float)
                    x = np.arange(n, dtype=float)
                    slope, intercept = np.polyfit(x, y, 1)
                    forecast0 = slope * (n - 1) + intercept
                    forecast1 = slope * n + intercept
                    MAvg = 2 * forecast0 - forecast1
            else:
                MAvg = current_src  # 默认回退到当前值

        # ---------------------------
        # 3. 根据 MAvg 与 ATR 计算 PMax 相关变量
        # ---------------------------
        atr_value = self.atr_ind[0]
        mult = self.p.Multiplier
        comp_longStop = MAvg - mult * atr_value
        comp_shortStop = MAvg + mult * atr_value
        
        # 第一根K线时，初始化 longStop、shortStop、dir 与 PMax
        if self.longStop is None:
            self.longStop = comp_longStop
            self.shortStop = comp_shortStop
            self.dir = 1
            self.PMax = self.longStop
            self.prev_MAvg = MAvg
            self.prev_PMax = self.PMax
            return
        
        # 根据前一bar数据进行递归更新（等同于 PineScript 中 nz() 和递归赋值）
        if MAvg > self.longStop:
            new_longStop = max(comp_longStop, self.longStop)
        else:
            new_longStop = comp_longStop
        if MAvg < self.shortStop:
            new_shortStop = min(comp_shortStop, self.shortStop)
        else:
            new_shortStop = comp_shortStop
        
        # 更新方向：原 PineScript 条件
        new_dir = self.dir
        if self.dir == -1 and MAvg > self.shortStop:
            new_dir = 1
        elif self.dir == 1 and MAvg < self.longStop:
            new_dir = -1

        new_PMax = new_longStop if new_dir == 1 else new_shortStop
        
        # ---------------------------
        # 4. 交易信号判断：使用 MAvg 与 PMax 的交叉检测  
        #    PineScript中用 crossover(MAvg, PMax) 作为多头信号，
        #    crossunder(MAvg, PMax) 作为空头信号
        #    即要求：前一bar MAvg ≤ PMax 且本bar MAvg > 新PMax，则视作向上交叉，开多仓；
        #         前一bar MAvg ≥ PMax 且本bar MAvg < 新PMax，则向下交叉，开空仓。
        # ---------------------------
        if self.prev_MAvg is not None and self.prev_PMax is not None:
            if (self.prev_MAvg <= self.prev_PMax) and (MAvg > new_PMax):
                # 多头信号：下单目标仓位设置为 100%
                self.order_target_percent(target=1.0)
            elif (self.prev_MAvg >= self.prev_PMax) and (MAvg < new_PMax):
                # 空头信号：下单目标仓位设置为 -100%
                self.order_target_percent(target=-1.0)
        
        # ---------------------------
        # 5. 更新递归变量，供下一个 bar 使用
        # ---------------------------
        self.longStop = new_longStop
        self.shortStop = new_shortStop
        self.dir = new_dir
        self.PMax = new_PMax
        
        self.prev_MAvg = MAvg
        self.prev_PMax = new_PMax
