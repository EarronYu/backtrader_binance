import backtrader as bt
import math

class MA_DCA(bt.Strategy):
    params = (
        ('ma_length', 47),          # MA长度
        ('initial_percent', 8),      # 首次订单的百分比
        ('percent_step', 1),         # 额外订单的百分比步长
        ('pyramiding', 3),           # 最大加仓次数
    )
    
    def __init__(self):
        # 计算简单移动平均线
        self.ma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.params.ma_length
        )
        
        # 跟踪最近买入和卖出价格
        self.last_buy_price = None
        self.last_sell_price = None
        
        # 用于跟踪当前持仓方向
        self.position_direction = None
        
        # 用于金字塔加仓
        self.opentrades = 0
        self.unit_ratio = 1.0 / self.params.pyramiding
        
        # 调试模式开关
        self.debug_mode = False
    
    def log(self, txt, dt=None, debug=False):
        # 如果为debug日志但调试模式关闭，则不输出日志
        if debug and not self.debug_mode:
            return
        dt = dt or self.data.datetime.date(0)
        print(f'{dt.isoformat()} {txt}')
        
    def price_percent_diff(self, price1, price2):
        """计算两个价格之间的绝对百分比差异"""
        return abs(price1 - price2) / price2 * 100
    
    def initial_entry_condition(self, price, ma, initial_percent):
        """检查是否满足初始入场条件"""
        return self.price_percent_diff(price, ma) >= initial_percent
    
    def next(self):
        # 获取当前价格数据
        current_close = self.data.close[0]
        current_low = self.data.low[0]
        current_high = self.data.high[0]
        current_ma = self.ma[0]
        
        # 检查平仓条件
        if self.position.size > 0 and current_close >= current_ma:  # 多头平仓
            self.order_target_percent(target=0.0, comment="exit_long")
            self.last_buy_price = None
            self.position_direction = None
            self.opentrades = 0
            self.log(f"平仓多头: 价格={current_close:.2f}", debug=True)
            
        elif self.position.size < 0 and current_close <= current_ma:  # 空头平仓
            self.order_target_percent(target=0.0, comment="exit_short")
            self.last_sell_price = None
            self.position_direction = None
            self.opentrades = 0
            self.log(f"平仓空头: 价格={current_close:.2f}", debug=True)
        
        # 多头入场逻辑
        if current_low < current_ma:
            if self.last_buy_price is None:
                if self.initial_entry_condition(current_low, current_ma, self.params.initial_percent):
                    # 首次开仓
                    self.opentrades = 1
                    target_percent = self.unit_ratio * self.opentrades
                    self.order_target_percent(target=target_percent, comment="enter_long")
                    self.last_buy_price = current_low
                    self.position_direction = 'long'
                    self.log(f"首次买入: 价格={current_low:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
            else:
                if (current_low < self.last_buy_price and 
                    self.price_percent_diff(current_low, self.last_buy_price) >= self.params.percent_step and
                    self.opentrades < self.params.pyramiding):
                    # 加仓
                    self.opentrades += 1
                    target_percent = self.unit_ratio * self.opentrades
                    self.order_target_percent(target=target_percent, comment="add_long")
                    self.last_buy_price = current_low
                    self.log(f"多头加仓: 价格={current_low:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
        
        # 空头入场逻辑
        if current_high > current_ma:
            if self.last_sell_price is None:
                if self.initial_entry_condition(current_high, current_ma, self.params.initial_percent):
                    # 首次开仓
                    self.opentrades = 1
                    target_percent = self.unit_ratio * self.opentrades
                    self.order_target_percent(target=-target_percent, comment="enter_short")
                    self.last_sell_price = current_high
                    self.position_direction = 'short'
                    self.log(f"首次卖出: 价格={current_high:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
            else:
                if (current_high > self.last_sell_price and 
                    self.price_percent_diff(current_high, self.last_sell_price) >= self.params.percent_step and
                    self.opentrades < self.params.pyramiding):
                    # 加仓
                    self.opentrades += 1
                    target_percent = self.unit_ratio * self.opentrades
                    self.order_target_percent(target=-target_percent, comment="add_short")
                    self.last_sell_price = current_high
                    self.log(f"空头加仓: 价格={current_high:.2f}, 仓位比例={target_percent*100:.1f}%", debug=True)
