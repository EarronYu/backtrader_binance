import backtrader as bt
import talib
import numpy as np

class BollingerBandRSI(bt.Strategy):
    params = (
        ('len_rsi', 14),
        ('bb_len', 20),
        ('bb_mult', 2.0),
        ('rsi_upper', 70),
        ('rsi_lower', 30),
        ('long_tp', 0.1),
        ('long_sl', 0.25),
        ('pyramiding', 10),
        ('initial_percent', 8),
        ('percent_step', 1),
    )

    def __init__(self):
        # 计算 RSI
        self.rsi = bt.indicators.RSI(self.data.close, period=self.params.len_rsi)

        # 计算 Bollinger Bands (如果想用 Backtrader 自带的 BollingerBands 可以直接用 bt.indicators.BollingerBands)
        self.bb_basis = bt.indicators.SMA(self.data.close, period=self.params.bb_len)
        self.bb_std = bt.indicators.StandardDeviation(self.data.close, period=self.params.bb_len)
        self.bb_upper = self.bb_basis + self.params.bb_mult * self.bb_std
        self.bb_lower = self.bb_basis - self.params.bb_mult * self.bb_std
        
        # 多头止盈 / 止损
        self.long_take_level = None
        self.long_stop_level = None

        # 空头止盈 / 止损
        self.short_take_level = None
        self.short_stop_level = None

        # 记录加仓次数
        self.add_count = 0

        self.unit_ratio = 1.0 / self.params.pyramiding  # 每次加仓的仓位比例
        self.last_buy_price = None
        self.last_sell_price = None
        self.position_direction = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

    def price_percent_diff(self, price1, price2):
        """计算两个价格之间的百分比差异"""
        return abs(price1 - price2) / price2 * 100

    def initial_entry_condition(self, current_price, bb_band, initial_percent):
        """检查是否满足初始入场条件"""
        return self.price_percent_diff(current_price, bb_band) >= initial_percent

    def next(self):
        current_close = self.data.close[0]
        current_low = self.data.low[0]
        current_high = self.data.high[0]

        # 最新的布林带上下轨、基础线和 RSI
        bb_lower = self.bb_lower[0]
        bb_upper = self.bb_upper[0]
        bb_basis = self.bb_basis[0]
        rsi_value = self.rsi[0]

        # 如果已经有多头持仓，则计算止盈止损
        if self.position.size > 0:
            self.long_take_level = self.position.price * (1 + self.params.long_tp)
            self.long_stop_level = self.position.price * (1 - self.params.long_sl)
            
            # 如果价格触及到止盈价或止损价，也可以选择平仓
            if current_close >= self.long_take_level or current_close <= self.long_stop_level:
                self.log(f"多头止盈止损平仓: 价格={current_close:.2f}")
                self.order_target_percent(target=0.0, comment="exit_long")
                self.last_buy_price = None
                self.position_direction = None
                self.add_count = 0
        
        # 如果已经有空头持仓，则计算止盈止损
        if self.position.size < 0:
            self.short_take_level = self.position.price * (1 - self.params.long_tp)  # 空头获利在下方
            self.short_stop_level = self.position.price * (1 + self.params.long_sl)  # 空头止损在上方
            if current_close <= self.short_take_level or current_close >= self.short_stop_level:
                self.log(f"空头止盈止损平仓: 价格={current_close:.2f}")
                self.order_target_percent(target=0.0, comment="exit_short")
                self.last_sell_price = None
                self.position_direction = None
                self.add_count = 0

        # RSI + Bollinger 平仓条件：例如“价格回到中轨”或“RSI 回到 50 上下”，你可以自行修改
        # 这里示例：如果是多头持仓，当价格 >= BB中轨，就平多头。
        if self.position.size > 0 and current_close >= bb_basis:
            self.log(f"平仓多头: 价格={current_close:.2f}")
            self.order_target_percent(target=0.0, comment="exit_long")
            self.last_buy_price = None
            self.position_direction = None
            self.add_count = 0

        if self.position.size < 0 and current_close <= bb_basis:
            self.log(f"平仓空头: 价格={current_close:.2f}")
            self.order_target_percent(target=0.0, comment="exit_short")
            self.last_sell_price = None
            self.position_direction = None
            self.add_count = 0

        # -----------------------
        # 多头入场逻辑 (结合 RSI)
        # -----------------------
        # 仅当 RSI < rsi_lower（超卖区）且当前最低价 < 下轨时，考虑开多
        if (rsi_value < self.params.rsi_lower) and (current_low < bb_lower):
            # 如果尚无多头仓位，检查“初始入场条件”
            if self.last_buy_price is None:
                if self.initial_entry_condition(current_low, bb_lower, self.params.initial_percent):
                    # 首次开多仓
                    self.add_count = 1
                    target_percent = self.unit_ratio * self.add_count
                    self.order_target_percent(target=target_percent, comment="enter_long")
                    self.last_buy_price = current_low
                    self.position_direction = 'long'
                    # self.log(f"首次买入: 价格={current_low:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
            else:
                # 如果已买过，且新的价格比上次还要低、且跌幅大于加仓步长，并未超过最大加仓次数
                if (current_low < self.last_buy_price 
                    and self.price_percent_diff(current_low, self.last_buy_price) >= self.params.percent_step
                    and self.add_count < self.params.pyramiding):
                    self.add_count += 1
                    target_percent = self.unit_ratio * self.add_count
                    self.order_target_percent(target=target_percent, comment="add_long")
                    self.last_buy_price = current_low
                    # self.log(f"多头加仓: 价格={current_low:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)

        # -----------------------
        # 空头入场逻辑 (结合 RSI)
        # -----------------------
        # 仅当 RSI > rsi_upper（超买区）且当前最高价 > 上轨时，考虑开空
        if (rsi_value > self.params.rsi_upper) and (current_high > bb_upper):
            # 如果尚无空头仓位，检查“初始入场条件”
            if self.last_sell_price is None:
                if self.initial_entry_condition(current_high, bb_upper, self.params.initial_percent):
                    # 首次开空仓
                    self.add_count = 1
                    target_percent = self.unit_ratio * self.add_count
                    self.order_target_percent(target=-target_percent, comment="enter_short")
                    self.last_sell_price = current_high
                    self.position_direction = 'short'
                    # self.log(f"首次卖出: 价格={current_high:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
            else:
                # 如果已卖出，且新的价格比上次更高、且涨幅大于加仓步长，并未超过最大加仓次数
                if (current_high > self.last_sell_price 
                    and self.price_percent_diff(current_high, self.last_sell_price) >= self.params.percent_step
                    and self.add_count < self.params.pyramiding):
                    self.add_count += 1
                    target_percent = self.unit_ratio * self.add_count
                    self.order_target_percent(target=-target_percent, comment="add_short")
                    self.last_sell_price = current_high
                    # self.log(f"空头加仓: 价格={current_high:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
