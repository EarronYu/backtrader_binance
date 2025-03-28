import backtrader as bt
import backtrader.indicators as btind
from collections import OrderedDict

class RSIPAPTP(bt.Strategy):
    """
    RSI+PA+PTP策略
    RSI超卖区域买入，使用价格平均和金字塔式加仓，渐进式止盈
    """
    
    params = (
        # 风险参数
        ('port', 12.0),  # 用于开仓的投资组合百分比
        
        # 多头入场层级参数
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
        
        # 止盈设置
        ('profit_target_percent', 3.0),        # 每个仓位的止盈百分比
        ('profit_target_percent_all', 4.0),    # 总体止盈百分比
        ('take_profit_progression', 12.0),     # 止盈递进
        ('entry_on', True),                    # 新入场会影响止盈限制
    )
    
    def __init__(self):
        # 移动平均线
        self.ma = btind.SimpleMovingAverage(self.data.close, period=self.p.ma_length)
        
        # RSI指标
        self.rsi = btind.RSI(self.data.close, period=self.p.rsi_length)
        
        # 记录各层级入场价格
        self.long_entries = [0.0] * 8  # 存储8个入场价格层级
        
        # 止盈相关变量
        self.end_val = 0.0
        self.start_val = 0.0
        self.tp_limit = 0.0
        
        # 交易状态变量
        self.open_trades = 0  # 开放交易数量
        self.position_avg_price = 0.0  # 平均持仓价格
        
        # 首次入场信号标记
        self.first_entry = False
        
        # 跟踪已触发的入场层级
        self.triggered_levels = [False] * 8
        
        # 创建用于存储信号的变量
        self.buy_signal = OrderedDict()
        self.sell_signal = OrderedDict()
        
    def calculate_position_avg_price(self):
        """计算当前持仓的平均价格"""
        if self.position.size > 0:
            return self.position.price
        return 0.0
        
    def next(self):
        # 更新平均持仓价格
        if self.position.size > 0:
            self.position_avg_price = self.calculate_position_avg_price()
            
        # 计算入场信号 - RSI从超卖区域向上穿越且价格低于MA
        entry_signal = (self.rsi[0] > self.p.oversold and 
                        self.rsi[-1] <= self.p.oversold and 
                        self.data.close[0] < self.ma[0])
        
        # 如果没有持仓且有入场信号，计算各层级入场价格并首次入场
        if entry_signal and self.position.size == 0:
            entry_price = self.data.close[0]
            
            # 计算各层级入场价格
            self.long_entries[0] = entry_price
            self.long_entries[1] = entry_price - entry_price / 100 * self.p.ps2
            self.long_entries[2] = entry_price - entry_price / 100 * self.p.ps3
            self.long_entries[3] = entry_price - entry_price / 100 * self.p.ps4
            self.long_entries[4] = entry_price - entry_price / 100 * self.p.ps5
            self.long_entries[5] = entry_price - entry_price / 100 * self.p.ps6
            self.long_entries[6] = entry_price - entry_price / 100 * self.p.ps7
            self.long_entries[7] = entry_price - entry_price / 100 * self.p.ps8
            
            # 重置触发层级标记
            self.triggered_levels = [False] * 8
            self.triggered_levels[0] = True  # 第一层已触发
            
            # 计算首次入场数量
            cash = self.broker.getcash()
            total_value = self.broker.getvalue()
            q = total_value / 100 * self.p.port / self.data.close[0]
            
            # 首次入场
            self.buy(size=q)
            self.open_trades = 1
            self.first_entry = True
            
            # 设置初始止盈限制
            self.tp_limit = entry_price + (entry_price / 100 * self.p.profit_target_percent_all)
            self.end_val = self.tp_limit
            
            # 记录买入信号
            self.buy_signal['Long1'] = True
        
        # 处理加仓逻辑
        if self.position.size > 0:
            # 计算当前的止盈水平
            tpn = ((self.position_avg_price + (self.position_avg_price / 100 * self.p.profit_target_percent_all)) - 
                  (self.position_avg_price + (self.position_avg_price / 100 * self.p.profit_target_percent_all) - self.end_val))
            
            # 计算各层级的止盈价格
            tp_prices = []
            for i in range(self.open_trades):  # 只为当前开放的交易计算止盈价格
                if self.data.close[0] < tpn:
                    tp_price = self.long_entries[i] + self.data.close[0] * (self.p.profit_target_percent / 100)
                else:
                    tp_price = tpn
                tp_prices.append(tp_price)
            
            # 检查加仓条件
            cash = self.broker.getcash()
            total_value = self.broker.getvalue()
            q = total_value / 100 * self.p.port / self.data.close[0]
            
            # 检查各层级加仓条件
            for i in range(1, 8):  # 从第2层开始
                if (self.open_trades == i and 
                    not self.triggered_levels[i] and 
                    self.data.close[0] <= self.long_entries[i]):
                    
                    # 触发加仓
                    self.buy(size=q)
                    self.open_trades += 1
                    self.triggered_levels[i] = True
                    
                    # 更新止盈限制（如果启用了entry_on选项）
                    if self.p.entry_on:
                        prev_tp = self.tp_limit
                        self.tp_limit = self.position_avg_price + (self.position_avg_price / 100 * self.p.profit_target_percent_all)
                        self.start_val = self.end_val
                        self.end_val = self.start_val - (prev_tp - self.tp_limit)
                    
                    # 记录买入信号
                    self.buy_signal[f'Long{i+1}'] = True
            
            # 检查止盈条件
            if self.data.close[0] >= tpn:
                # 如果价格达到总体止盈水平，平掉所有仓位
                self.close()
                self.open_trades = 0
                self.first_entry = False
                self.sell_signal['TakeProfit_All'] = True
            else:
                # 检查个别仓位的止盈条件
                for i in range(min(len(tp_prices), self.open_trades)):  # 使用较小的值作为循环范围
                    if self.data.close[0] >= tp_prices[i]:
                        # 平掉一部分仓位
                        portion = 1.0 / self.open_trades
                        self.close(size=self.position.size * portion)
                        self.open_trades -= 1
                        
                        # 更新止盈限制
                        self.start_val = self.end_val
                        profit_deduction = (self.p.take_profit_progression / 100 * self.data.close[0] / 100 * self.p.profit_target_percent)
                        self.end_val = self.start_val - profit_deduction
                        
                        # 记录卖出信号
                        self.sell_signal[f'TakeProfit_{i+1}'] = True
                        break
