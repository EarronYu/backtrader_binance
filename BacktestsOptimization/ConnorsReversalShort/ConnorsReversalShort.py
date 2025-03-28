import numpy as np
import talib as ta
from backtesting import Strategy
from backtesting.lib import crossover
# from record_trade import record_trade  # 导入独立的 record_trade 函数

class ConnorsReversalShort(Strategy):
    symbol = "1000PEPEUSDT"  # 添加交易对标识
    timeframe = "1m"         # 添加时间周期

    # 定义策略参数
    highest_point_bars = 16    # 用于确定最高点的周期数
    rsi_length = 4             # RSI指标的计算周期 
    buy_barrier = 27           # 当RSI低于此值时，认为市场超卖，触发买入平空
    dca_parts = 8              # DCA分批次数
    
    def init(self):
        # 计算RSI
        self.rsi = self.I(ta.RSI, self.data.Close, self.rsi_length)
        
        # 记录当前空仓加仓次数
        self.open_trades = 0
        
        # 计算每次下单使用的资金比例
        self.unit_ratio = 1 / self.dca_parts
        
    def next(self):
        # 获取当前时间，用于记录交易信号
        current_time = str(self.data.index[-1])
        
        # 根据当前加仓次数计算回溯周期
        lookback = self.highest_point_bars * (self.open_trades + 1)
        if len(self.data.Close) < lookback:
            return
            
        # 计算最近回溯周期内的最高价
        recent_high = np.max(self.data.High[-lookback:])
        is_highest = self.data.High[-1] == recent_high
        
        # 判断做空条件中价格是否高于加权平均入场价格（用于分批加仓）
        price_above_avg = True
        if self.position:
            # 获取所有交易并计算加权平均空仓入场价格
            trades = self._broker.trades  
            if trades:
                total_size = sum(abs(trade.size) for trade in trades)
                avg_price = sum(trade.entry_price * abs(trade.size) for trade in trades) / total_size
                price_above_avg = (self.data.Close[-1] > avg_price * (1 + 0.01 * self.open_trades))
            
        # 当当前价格达到近期最高，或为首单时，满足开空条件
        is_short = (is_highest and (price_above_avg or self.open_trades == 0))
        
        # 平仓条件：RSI低于买入阈值，认为市场超卖，触发买入平空
        is_cover = self.rsi[-1] < self.buy_barrier
        
        # 执行交易逻辑
        if is_short and self.open_trades < self.dca_parts:
            # 计算当前使用的资金比例（累进式）
            current_ratio = self.unit_ratio * (self.open_trades + 1)
            # 下卖单开空，使用分批资金比例进行做空
            self.sell(size=current_ratio)
            # record_trade({
            #     "symbol": self.symbol,
            #     "timeframe": self.timeframe,
            #     "date": current_time,
            #     "signal": f"{self.__class__.__name__} enter_short"
            # })
            self.open_trades += 1
            
        if is_cover and self.position:
            self.position.close()
            # record_trade({
            #     "symbol": self.symbol,
            #     "timeframe": self.timeframe,
            #     "date": current_time,
            #     "signal": f"{self.__class__.__name__} exit_short"
            # })
            self.open_trades = 0 