import backtrader as bt


class TestDCALive(bt.Strategy):
    """
    价格比较DCA策略
    - 当当前K线价格低于上一根K线价格时买入（最多买入3次）
    - 当当前K线价格高于上一根K线价格时平仓
    - 使用DCA方式进行买入（分批买入）
    """
    
    params = (
        ('pyramiding', 3),             # 最大加仓次数
        ('initial_cash', 1000),        # 初始资金，用于计算仓位
        # 3commas必传参数
        ('commas_secret', None),       # 3commas webhook secret
        ('commas_max_lag', None),      # 3commas webhook max lag
        ('commas_exchange', None),     # TV exchange名称
        ('commas_ticker', None),       # TV ticker/instrument
        ('commas_bot_uuid', None),     # 3commas bot uuid
    )

    def __init__(self):
        # 检查必传参数
        if not all([self.p.commas_secret, self.p.commas_exchange, 
                    self.p.commas_ticker, self.p.commas_bot_uuid]):
            raise ValueError("必须提供所有3commas参数！")

        # 初始化变量
        self.opentrades = 0
        self.unit_ratio = 1.0 / self.p.pyramiding
        self.debug_mode = True
        self.orders = {}  # 存储所有订单
        
        # 使用设置的初始资金，而不是实时获取
        self.initial_cash = self.p.initial_cash
        
        # 初始化每个数据源的订单
        for d in self.datas:
            self.orders[d._name] = None

    def log(self, txt, dt=None, debug=False):
        if debug and not self.debug_mode:
            return
        dt = dt or self.data.datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

    def next(self):
        # 确保有足够的K线数据进行比较
        if len(self.data) < 2:
            return
            
        current_price = self.data.close[0]
        previous_price = self.data.close[-1]
        
        self.log(f"当前价格: {current_price:.2f}, 上一根K线价格: {previous_price:.2f}", debug=True)
        
        # 遍历所有数据，打印每个ticker的价格信息
        for data in self.datas:
            ticker = data._name
            # 尝试获取数据状态，默认为0（实时数据）
            status = getattr(data, '_state', 0)
            if status in [0, 1]:
                if status:
                    _state = "False - History data"
                else:
                    _state = "True - Live data"
                self.log(f"\t - {ticker} 价格: {data.close[0]}", debug=True)
                
                # 使用broker.getcash()获取可用资金，而不是查询API余额
                self.log(f"\t - 可用资金: {self.broker.getcash()}", debug=True)

        signal = ""
        
        # 当价格下跌时买入（如果未达到最大加仓次数）
        if current_price < previous_price and self.opentrades < self.p.pyramiding:
            signal = "enter_long"
            
            # 计算本次买入金额 - 基于初始资金而不是实时余额
            buy_amount = self.initial_cash * self.unit_ratio
            size = buy_amount / current_price
            
            # 实际执行买入操作
            for data in self.datas:
                ticker = data._name
                self.log(f"买入第{self.opentrades+1}次: 价格={current_price:.2f}, 数量={size:.6f}, 仓位比例={self.unit_ratio:.2f}", debug=True)
                self.orders[ticker] = self.buy(data=data, size=size)
            
            self.opentrades += 1
        
        # 当价格上涨时平仓（如果有持仓）
        elif current_price > previous_price and self.position:
            signal = "exit_long"
            self.log(f"平仓: 价格={current_price:.2f}, 总交易次数={self.opentrades}", debug=True)
            
            # 实际执行平仓操作
            for data in self.datas:
                ticker = data._name
                if self.getposition(data).size > 0:
                    self.log(f"关闭{ticker}仓位", debug=True)
                    self.orders[ticker] = self.close(data=data)
            
            self.opentrades = 0
        
        # 发送信号
        if signal:
            from send_signal import send_trade_signal
            send_trade_signal(
                signal,
                current_price,
                self.p.commas_secret,
                self.p.commas_max_lag,
                self.p.commas_exchange,
                self.p.commas_ticker,
                self.p.commas_bot_uuid
            )
    
    def notify_order(self, order):
        """订单状态变化的通知"""
        order_data_name = order.data._name  # 订单对应的ticker名称
        self.log(f'订单编号 {order.ref} {order.getstatusname()} {"买入" if order.isbuy() else "卖出"} {order_data_name} {order.size} @ {order.price}')
        
        if order.status == bt.Order.Completed:  # 如果订单已完全执行
            if order.isbuy():  # 买入订单
                self.log(f'买入 {order_data_name} @{order.executed.price:.2f}, 金额 {order.executed.value:.2f}, 手续费 {order.executed.comm:.2f}')
            else:  # 卖出订单
                self.log(f'卖出 {order_data_name} @{order.executed.price:.2f}, 金额 {order.executed.value:.2f}, 手续费 {order.executed.comm:.2f}')
            
            self.orders[order_data_name] = None  # 重置订单状态
    
    def notify_trade(self, trade):
        """仓位状态变化的通知"""
        if trade.isclosed:  # 如果仓位已关闭
            self.log(f'已关闭仓位 {trade.getdataname()} 总盈亏={trade.pnl:.2f}, 净盈亏={trade.pnlcomm:.2f}') 