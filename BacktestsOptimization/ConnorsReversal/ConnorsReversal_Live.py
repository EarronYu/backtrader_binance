import backtrader as bt
import backtrader.indicators as btind
import math
from collections import deque

import time
import threading  # 添加线程支持
import concurrent.futures  # 添加线程池支持
import queue  # 添加队列支持
import datetime
import traceback  # 用于详细异常信息
import aiohttp  # 替换 requests 为 aiohttp
import asyncio

class ConnorsReversal_Live(bt.Strategy):
    params = (
        ("lowest_point_bars", 16),
        ("rsi_length", 4),
        ("sell_barrier", 73),
        ("dca_parts", 8),
        ("max_lookback", 50),
        ("sma_period", 55),
        ("only_buy_above_sma", False)

        ('initial_cash', 1000),     # 初始资金，用于计算仓位
        # 3commas必传参数
        ('commas_secret', None),    # 3commas webhook secret
        ('commas_max_lag', None),   # 3commas webhook max lag
        ('commas_exchange', None),  # TV exchange名称
        ('commas_ticker', None),    # TV ticker/instrument
        ('commas_bot_uuid', None),  # 3commas bot uuid
        ('debug_mode', True),       # 调试模式，默认开启
    )

    def __init__(self):
        # 检查必传参数
        if not all([self.p.commas_secret, self.p.commas_exchange, self.p.commas_ticker, self.p.commas_bot_uuid]):
            raise ValueError("必须提供所有3commas参数！")

        # 使用设置的初始资金
        self.initial_cash = self.p.initial_cash
        
        # 初始化信号类型字典 - 只记录信号类型，不记录订单对象
        self.signal_types = {d._name: None for d in self.datas}
        
        # 创建全局异步事件循环
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.start_loop, daemon=True)
        self.loop_thread.start()
        
        # 初始化指标
        self.rsi = btind.RSI(self.data.close, period=self.p.rsi_length)
        self.sma = btind.SimpleMovingAverage(self.data.close, period=self.p.sma_period)
        
        # 初始化交易变量
        self.open_trades = 0
        self.unit_ratio = 1 / self.p.dca_parts
        
        # 数据窗口
        self.max_window = min(self.p.lowest_point_bars * self.p.dca_parts, self.p.max_lookback)
        self.closes = deque(maxlen=self.max_window)
        self.min_price_window = deque(maxlen=self.p.lowest_point_bars)
        
        # 状态标志 - 简化初始化逻辑
        self.debug_mode = False

    def start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def log(self, txt, dt=None, debug=False):
        if debug and not self.debug_mode:
            return
        
        try:
            if dt is None and len(self.datas) > 0:
                try:
                    _ = self.datas[0].datetime[0]
                    dt = self.datas[0].datetime.datetime(0)
                except (IndexError, AttributeError):
                    dt = datetime.datetime.now()
            else:
                dt = dt or datetime.datetime.now()
        except Exception:
            dt = datetime.datetime.now()
            
        print(f'{dt.strftime("%Y-%m-%d %H:%M:%S")} {txt}')

    def is_local_minimum(self):
        """检查当前价格是否为局部最低点"""
        try:
            # 只有窗口填满时才进行检测
            if len(self.min_price_window) < self.p.lowest_point_bars:
                return False

            current_price = self.data.close[0]
            if math.isnan(current_price):
                return False

            # 直接遍历队列副本，过滤 NaN
            valid_prices = [p for p in list(self.min_price_window) if not math.isnan(p)]
            # 确保当前价格也参与检测（避免因NaN而遗漏）
            if not valid_prices or current_price != valid_prices[-1]:
                valid_prices.append(current_price)
            min_price = min(valid_prices)
            return current_price <= min_price

        except Exception as e:
            self.log(f"最低点检查错误: {str(e)}", debug=True)
            return False

    def next(self):
        # 遍历所有数据源
        for i, data in enumerate(self.datas):
            status = data._state  # 0 - Live data, 1 - History data, 2 - None
            ticker = data._name
            
            # 日志记录K线类型和价格
            if status == 0:
                data_type = "实时K线"
            elif status == 1:
                data_type = "历史K线"
            else:
                data_type = "未知状态"
                
            # 打印K线的OHLCV数据
            self.log(f"处理{data_type} - {ticker} OHLCV: 开={data.open[0]:.2f} 高={data.high[0]:.2f} 低={data.low[0]:.2f} 收={data.close[0]:.2f} 量={data.volume[0]:.2f}")
            
            # 只有实时K线才进行交易操作
            if status != 0:  # 如果不是实时数据，跳过交易信号处理
                self.log(f"跳过非实时K线的交易信号处理 - {ticker}")
                continue
                
            try:
                # 使用主数据进行策略判断
                current_price = data.close[0]
                
                # 检查是否有持仓
                has_position = any(self.getposition(d).size > 0 for d in self.datas)
                if has_position:
                    for d in self.datas:
                        pos = self.getposition(d)
                        if pos.size > 0:
                            self.log(f"当前持仓: {d._name} 数量={pos.size:.6f} 价格={pos.price:.2f}")

                # 如果当前价格无效或为0，则直接返回
                if math.isnan(current_price) or current_price == 0:
                    self.log("警告: 当前价格无效（为0或NaN），跳过此bar", debug=True)
                    return

                self.closes.append(current_price)
                self.min_price_window.append(current_price)

                
                try:
                    is_lowest = self.is_local_minimum()

                    signal = ""
                
                    # 卖出条件：持仓且 RSI 超过卖出阈值时平仓（使用目标百分比下单归零仓位）
                    if self.position and self.rsi[0] > self.p.sell_barrier:
                        self.order_target_percent(target=0.0)
                        self.open_trades = 0

                        signal = "exit_long"
                        # 执行平仓操作：对所有持仓数据源平仓
                        for d in self.datas:
                            d_ticker = d._name
                            position = self.getposition(d)
                            if position.size > 0:
                                self.log(f"📉 执行平仓: {d_ticker}, 价格={current_price:.2f}, 数量={position.size:.6f}, RSI={rsi_val:.2f}")
                                self.order_target_percent(data=d, target=0.0)
                                self.signal_types[d_ticker] = signal  # 记录信号类型

                        self.log(f"卖出信号 - RSI: {self.rsi[0]:.6f}，目标仓位: 0.00", debug=True)
                        return

                    if is_lowest:
                        # 检查买入条件
                        price_below_avg = True
                        if self.position:
                            avg_price = self.position.price
                            price_below_avg = current_price < avg_price * (1 - 0.01 * self.open_trades)

                        above_sma = current_price > self.sma[0]
                        sma_condition = above_sma or not self.p.only_buy_above_sma

                        if (price_below_avg or self.open_trades == 0) and sma_condition and self.open_trades < self.p.dca_parts:
                            # 计算当前目标仓位比例
                            target_percent = self.unit_ratio * (self.open_trades + 1)
                            self.order_target_percent(target=target_percent)
                            self.open_trades += 1

                            signal = "enter_long"
                            # 执行买入操作：对所有数据源下单
                            for d in self.datas:
                                d_ticker = d._name
                                self.log(f"📈 执行买入: {d_ticker} 价格={current_price:.2f}, 仓位比例={target_percent*100:.1f}%")
                                self.order_target_percent(data=d, target=target_percent)
                                self.signal_types[d_ticker] = signal  # 记录信号类型

                except Exception as e:
                    self.log(f"策略执行错误: {str(e)}", debug=True)

                else:
                    self.log(f"📊 本次K线无交易操作", debug=True)
                    
            except Exception as e:
                # 捕获并记录任何异常
                self.log(f"策略执行异常: {e}")
                self.log(f"异常详情: {traceback.format_exc()}")

    async def _async_send_signal(self, signal, trigger_price):
        """异步发送交易信号"""
        try:
            # 构建payload
            payload = {
                'secret': self.p.commas_secret,
                'max_lag': self.p.commas_max_lag,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                'trigger_price': str(trigger_price),
                'tv_exchange': self.p.commas_exchange,
                'tv_instrument': self.p.commas_ticker,
                'action': signal,
                'bot_uuid': self.p.commas_bot_uuid
            }
            
            # 使用aiohttp异步发送请求
            url = "http://localhost:5678/webhook/3commas"
            
            # 使用上下文管理器确保会话正确关闭
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=1)  # 设置1秒超时
                ) as response:
                    # 不等待或处理响应内容
                    pass
                    
            self.log(f"已发送 {signal} 信号, 价格: {trigger_price}")
            return True
            
        except Exception as e:
            self.log(f"异步发送信号异常: {e}")
            return False
    
    def send_signal(self, signal, trigger_price):
        """非阻塞地启动异步信号发送"""
        try:
            # 提交异步任务到全局事件循环
            asyncio.run_coroutine_threadsafe(
                self._async_send_signal(signal, trigger_price),
                self.loop
            )
            
            # 不等待结果返回
            return True
            
        except Exception as e:
            self.log(f"启动信号发送异常: {e}")
            return False
    
    def notify_order(self, order):
        """订单状态变化的通知，只用于发送信号，不处理订单状态"""
        try:
            # 只在订单刚提交或接受时发送信号
            if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
                data_name = order.data._name
                signal_type = self.signal_types.get(data_name)
                
                if signal_type:
                    # 获取当前价格
                    try:
                        current_price = order.data.close[0]
                    except (IndexError, AttributeError):
                        current_price = getattr(order, 'price', 0) or 0
                    
                    # 异步发送信号到n8n，不阻塞
                    self.send_signal(signal_type, current_price)
                    
                    # 信号发送后清除，防止重复发送
                    self.signal_types[data_name] = None
            
        except Exception as e:
            self.log(f"发送信号异常: {e}")
    
    def notify_trade(self, trade):
        """仓位状态变化的通知"""
        try:
            if trade.isclosed:
                self.log(f'已关闭仓位 {trade.getdataname()} 总盈亏={trade.pnl:.2f}, 净盈亏={trade.pnlcomm:.2f}')
            else:
                self.log(f'开仓 {trade.getdataname()} 大小={trade.size}, 价格={trade.price}')
        except Exception as e:
            self.log(f"处理交易通知异常: {e}")
    
    def stop(self):
        """策略停止时清理资源"""
        try:
            # 关闭全局事件循环
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop_thread.join()
            self.log("异步事件循环已关闭")
        except Exception as e:
            self.log(f"关闭事件循环异常: {e}")