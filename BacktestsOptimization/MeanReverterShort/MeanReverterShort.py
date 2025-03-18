import backtrader as bt
import math

class MeanReverterShort(bt.Strategy):
    params = (
        ('frequency', 10),          # 用于计算慢速RSI均线的周期（默认10）
        ('rsiFrequency', 40),       # RSI周期调整为40
        ('sellZoneDistance', 5),    # 卖出区域距离5%
        ('avgUpATRSum', 3),         # ATR求和周期改为3
        ('useAbsoluteRSIBarrier', True),
        ('barrierLevel', 50),       # 障碍水平调整为50
        ('pyramiding', 8),          # 最大加仓次数8次
    )


    def __init__(self):
        self.opentrades = 0
        self.unit_ratio = 1.0 / self.p.pyramiding  # 分批加仓比例计算
        # 调试模式开关，False时不显示debug日志
        self.debug_mode = False
        
        # 初始化指标，并开启绘图显示
        self.rsi = bt.talib.RSI(self.data.close, timeperiod=self.p.rsiFrequency)
        self.rsi.plotinfo.plot = True  # 确保 RSI 指标绘制在图表上
        self.rsi_slow = bt.talib.SMA(self.rsi, timeperiod=self.p.frequency)
        self.rsi_slow.plotinfo.plot = True  # 绘制平滑RSI线
        self.atr = bt.talib.ATR(self.data.high, self.data.low, self.data.close, timeperiod=20)

    def log(self, txt, dt=None, debug=False):
        # 如果为debug日志但调试模式关闭，则不输出日志
        if debug and not self.debug_mode:
            return
        dt = dt or self.data.datetime.date(0)
        print(f'{dt.isoformat()} {txt}')


    def next(self):
        current_price = self.data.close[0]
        rsi_val = self.rsi[0]
        rsi_slow_val = self.rsi_slow[0]
        
        # 计算ATR总和（过去avgUpATRSum个周期）
        atr_sum = sum(self.atr.get(size=self.p.avgUpATRSum)) if len(self.atr) >= self.p.avgUpATRSum else 0

        # 做空条件
        if self.position:
            avg_price = self.position.price
            # 做空逻辑：avg_price + (atr_sum * opentrades) < current_price
            price_condition = (avg_price + (atr_sum * self.opentrades)) < current_price
        else:
            price_condition = True  # 无持仓时允许首次做空

        # 做空区域：RSI > 慢速RSI均线*(1 + sellZoneDistance/100)
        cond_sell_zone = rsi_val > rsi_slow_val * (1 + self.p.sellZoneDistance / 100.0)
        cond_max = self.opentrades < self.p.pyramiding
        isShort = cond_sell_zone and price_condition and cond_max

        # 平仓条件
        isCover = (rsi_val < rsi_slow_val) and (rsi_val < self.p.barrierLevel or not self.p.useAbsoluteRSIBarrier)

        # 执行交易
        if isShort:
            # 按比例做空逻辑
            target_percent = -self.unit_ratio * (self.opentrades + 1)  # 负数表示做空
            self.order_target_percent(target=target_percent)
            self.opentrades += 1
            self.log(f"做空: 价格={current_price:.2f}, 仓位比例={abs(target_percent)*100:.1f}%", debug=True)

        if self.position and isCover:
            # 使用order_target_percent平仓，确保图表中交易标记正常显示
            self.order_target_percent(target=0.0)
            self.log(f"平仓: 价格={current_price:.2f}, RSI={rsi_val:.2f}", debug=True)
            self.opentrades = 0