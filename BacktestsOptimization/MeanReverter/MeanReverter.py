import backtrader as bt
import math

class MeanReverter(bt.Strategy):
    params = (
        ('frequency', 26),          # 与Pine Script的22周期对齐
        ('rsiFrequency', 4),       # RSI周期调整为36
        ('buyZoneDistance', 8),     # 买入区域距离3%
        ('avgDownATRSum', 8),       # ATR求和周期改为5
        ('useAbsoluteRSIBarrier', True),
        ('barrierLevel', 32),       # 障碍水平调整为60
        ('pyramiding', 3),          # 最大加仓次数3次
    )


    def __init__(self):
        self.opentrades = 0
        self.unit_ratio = 1.0 / self.p.pyramiding  # 恢复比例计算
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
        
        # 计算ATR总和（过去avgDownATRSum个周期）
        atr_sum = sum(self.atr.get(size=self.p.avgDownATRSum)) if len(self.atr) >= self.p.avgDownATRSum else 0

        # 买入条件
        if self.position:
            avg_price = self.position.price
            # Pine Script逻辑：avg_price - (atr_sum * opentrades) > current_price
            price_condition = (avg_price - (atr_sum * self.opentrades)) > current_price
        else:
            price_condition = True  # 无持仓时允许首次买入

        cond_buy_zone = rsi_val < rsi_slow_val * (1 - self.p.buyZoneDistance / 100.0)
        cond_max = self.opentrades < self.p.pyramiding
        isBuy = cond_buy_zone and price_condition and cond_max

        # 平仓条件
        isClose = (rsi_val > rsi_slow_val) and (rsi_val > self.p.barrierLevel or not self.p.useAbsoluteRSIBarrier)

        # 执行交易
        if isBuy:
            # 恢复按比例下单逻辑
            target_percent = self.unit_ratio * (self.opentrades + 1)
            self.order_target_percent(target=target_percent)
            self.opentrades += 1
            self.log(f"买入: 价格={current_price:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)

        if self.position and isClose:
            # 使用order_target_percent平仓，确保图表中交易标记正常显示
            self.order_target_percent(target=0.0)
            self.log(f"平仓: 价格={current_price:.2f}, RSI={rsi_val:.2f}", debug=True)
            self.opentrades = 0