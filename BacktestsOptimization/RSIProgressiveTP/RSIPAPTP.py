import backtrader as bt
import backtrader.indicators as btind
from collections import OrderedDict

class RSIPAPTP(bt.Strategy):
    """
    RSI+PA+PTP策略（使用order_target_percent()下单方式）
    RSI超卖区域买入，使用价格平均和金字塔式加仓，渐进式止盈——每个仓位单独设定止盈水平
    """

    params = (
        # 风险参数：每个仓位对应的组合百分比
        ('port', 12.0),  # 每层仓位对应的百分比

        # 多头入场层级参数（用于计算各层入场价格）
        ('ps2', 2.0),    # 第2层多头入场百分比
        ('ps3', 3.0),    # 第3层多头入场百分比
        ('ps4', 5.0),    # 第4层多头入场百分比
        ('ps5', 10.0),   # 第5层多头入场百分比
        ('ps6', 16.0),   # 第6层多头入场百分比
        ('ps7', 25.0),   # 第7层多头入场百分比
        ('ps8', 40.0),   # 第8层多头入场百分比

        # 移动平均线过滤
        ('ma_length', 100),

        # RSI设置
        ('rsi_length', 14),
        ('oversold', 29),  # 超卖阈值，触发首次入场

        # 止盈设置（每层单独止盈百分比）
        ('profit_target_percent', 3.0),       # 每层仓位止盈百分比
        ('entry_on', True),                   # 新入场是否会影响止盈限制（本例暂不作调整）
    )

    def __init__(self):
        # 使用TA-Lib内置SMA指标
        self.ma = btind.SimpleMovingAverage(self.data.close, period=self.p.ma_length)
        # RSI指标
        self.rsi = btind.RSI(self.data.close, period=self.p.rsi_length)

        # 用于保存各层入场价格，共8层
        self.long_entries = [0.0] * 8

        # 记录目前已开仓层数（每加一仓，则 open_trades 自增）
        self.open_trades = 0

        # 当前持仓的平均价格（仅作参考）
        self.position_avg_price = 0.0

        # 标记首次入场信号
        self.first_entry = False

        # 跟踪各层是否已触发加仓，避免重复加仓
        self.triggered_levels = [False] * 8

        # 用于记录买卖信号（仅日志记录）
        self.buy_signal = OrderedDict()
        self.sell_signal = OrderedDict()

    def calculate_position_avg_price(self):
        """计算当前持仓的平均价格"""
        if self.position.size > 0:
            return self.position.price
        return 0.0

    def next(self):
        # 如果已有持仓，更新当前持仓均价
        if self.position.size > 0:
            self.position_avg_price = self.calculate_position_avg_price()

        # 计算入场信号：RSI指标刚从超卖区上穿，同时价格低于均线
        entry_signal = (self.rsi[0] > self.p.oversold and 
                        self.rsi[-1] <= self.p.oversold and 
                        self.data.close[0] < self.ma[0])

        # 若无持仓且入场条件满足，首次入场
        if entry_signal and self.position.size == 0:
            entry_price = self.data.close[0]

            # 记录各层入场价格：
            self.long_entries[0] = entry_price
            self.long_entries[1] = entry_price - entry_price * (self.p.ps2 / 100)
            self.long_entries[2] = entry_price - entry_price * (self.p.ps3 / 100)
            self.long_entries[3] = entry_price - entry_price * (self.p.ps4 / 100)
            self.long_entries[4] = entry_price - entry_price * (self.p.ps5 / 100)
            self.long_entries[5] = entry_price - entry_price * (self.p.ps6 / 100)
            self.long_entries[6] = entry_price - entry_price * (self.p.ps7 / 100)
            self.long_entries[7] = entry_price - entry_price * (self.p.ps8 / 100)

            # 重置加仓触发标记，标记第一层已触发
            self.triggered_levels = [False] * 8
            self.triggered_levels[0] = True

            # 初始建仓：目标仓位为 port/100
            target_percent = self.p.port / 100.0
            self.order_target_percent(target=target_percent)

            self.open_trades = 1
            self.first_entry = True

            self.buy_signal['Long1'] = True

        # 当已有持仓时，处理加仓及止盈
        elif self.position.size > 0:
            # ***********************
            # 加仓条件：检查从第2层开始的入场价
            for i in range(1, 8):
                if (self.open_trades == i and 
                    (not self.triggered_levels[i]) and 
                    self.data.close[0] <= self.long_entries[i]):
                    # 达到该层入场价则加仓，目标仓位更新为 (当前层数+1)*port/100
                    new_target = (self.open_trades + 1) * (self.p.port / 100.0)
                    self.order_target_percent(target=new_target)
                    self.open_trades += 1
                    self.triggered_levels[i] = True
                    self.buy_signal[f'Long{i+1}'] = True

            # ***********************
            # 止盈条件：改为每个仓位单独平仓
            # 对于每一层（0 到 open_trades-1），计算该层的止盈价格
            # 计算方法：该层入场价格 * (1 + profit_target_percent/100)
            for i in range(self.open_trades):
                individual_tp = self.long_entries[i] * (1 + self.p.profit_target_percent / 100)
                if self.data.close[0] >= individual_tp:
                    # 若当前价格达到这一层止盈目标，则减少一个入场层
                    new_target = (self.open_trades - 1) * (self.p.port / 100.0)
                    self.order_target_percent(target=new_target)
                    self.open_trades -= 1
                    self.sell_signal[f'TakeProfit_{i+1}'] = True
                    # 一旦触发某层止盈，就退出止盈检查（一次只平一层）
                    break
