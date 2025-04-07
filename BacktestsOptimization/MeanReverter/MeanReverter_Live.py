import backtrader as bt
import math
import time
import threading  # 添加线程支持
import concurrent.futures  # 添加线程池支持
import queue  # 添加队列支持
import datetime
import traceback  # 用于详细异常信息
import aiohttp  # 替换 requests 为 aiohttp
import asyncio


class MeanReverterLive(bt.Strategy):
    # 参数设置
    params = (
        ('frequency', 22),          # 调整平滑RSI的周期
        ('rsiFrequency', 36),       # RSI周期
        ('buyZoneDistance', 3),     # 买入区域距离百分比
        ('avgDownATRSum', 5),       # ATR求和周期
        ('useAbsoluteRSIBarrier', True),
        ('barrierLevel', 60),       # 障碍水平
        ('pyramiding', 3),          # 最大加仓次数
        
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

        # 初始化交易次数和单次下单比例
        self.opentrades = 0
        self.unit_ratio = 1.0 / self.p.pyramiding
        self.debug_mode = self.p.debug_mode
        
        # 初始化指标
        self.rsi = bt.talib.RSI(self.data.close, timeperiod=self.p.rsiFrequency)
        self.rsi_slow = bt.talib.SMA(self.rsi, timeperiod=self.p.frequency)
        self.atr = bt.talib.ATR(self.data.high, self.data.low, self.data.close, timeperiod=20)


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

                # 确保指标已经准备好
                if not (len(self.rsi) > 0 and len(self.rsi_slow) > 0 and len(self.atr) > 0):
                    self.log("指标数据尚未准备好，跳过本次交易信号判断")
                    continue
                    
                rsi_val = self.rsi[0]
                rsi_slow_val = self.rsi_slow[0]
                
                # 输出指标值
                self.log(f"技术指标: RSI={rsi_val:.2f}, 慢速RSI={rsi_slow_val:.2f}, ATR={self.atr[0]:.4f}")
                


                # 计算ATR总和
                atr_sum = sum(self.atr.get(size=self.p.avgDownATRSum)) if len(self.atr) >= self.p.avgDownATRSum else 0

                # 买入条件
                if self.position:
                    avg_price = self.position.price
                    # Pine Script逻辑：avg_price - (atr_sum * opentrades) > current_price
                    price_condition = (avg_price - (atr_sum * self.opentrades)) > current_price
                    self.log(f"价格条件: 持仓均价({avg_price:.2f}) - (ATR总和({atr_sum:.4f}) * 开仓次数({self.opentrades})) > 当前价格({current_price:.2f}) = {price_condition}")
                else:
                    price_condition = True  # 无持仓时允许首次买入
                    self.log(f"价格条件: 无持仓，允许首次买入")

                cond_buy_zone = rsi_val < rsi_slow_val * (1 - self.p.buyZoneDistance / 100.0)
                cond_max = self.opentrades < self.p.pyramiding
                
                # 详细输出各条件的计算
                buy_zone_threshold = rsi_slow_val * (1 - self.p.buyZoneDistance / 100.0)
                self.log(f"买入区域条件: RSI({rsi_val:.2f}) < 阈值({buy_zone_threshold:.2f}) = {cond_buy_zone}")
                self.log(f"加仓次数条件: 当前({self.opentrades}) < 最大({self.p.pyramiding}) = {cond_max}")
                
                isBuy = cond_buy_zone and price_condition and cond_max

                # 平仓条件
                isClose = has_position and (rsi_val > rsi_slow_val) and (rsi_val > self.p.barrierLevel or not self.p.useAbsoluteRSIBarrier)
                
                if has_position:
                    condition1 = rsi_val > rsi_slow_val
                    condition2 = rsi_val > self.p.barrierLevel or not self.p.useAbsoluteRSIBarrier
                    self.log(f"平仓条件: RSI({rsi_val:.2f}) > 慢速RSI({rsi_slow_val:.2f}) = {condition1}, RSI > 障碍水平({self.p.barrierLevel}) = {condition2}")

                # 输出交易信号
                self.log(f"交易信号: {'✅买入' if isBuy else '❌不买入'}, {'✅平仓' if isClose else '❌不平仓'}, 持仓: {'✅有' if has_position else '❌无'}")

                signal = ""
                if isBuy:
                    signal = "enter_long"
                    # 计算目标仓位比例
                    target_percent = self.unit_ratio * (self.opentrades + 1)
                    
                    # 执行买入操作：对所有数据源下单
                    for d in self.datas:
                        d_ticker = d._name
                        self.log(f"📈 执行买入: {d_ticker} 价格={current_price:.2f}, 仓位比例={target_percent*100:.1f}%")
                        self.order_target_percent(data=d, target=target_percent)
                        self.signal_types[d_ticker] = signal  # 记录信号类型
                    
                    self.opentrades += 1

                elif self.position and isClose:
                    signal = "exit_long"
                    # 执行平仓操作：对所有持仓数据源平仓
                    for d in self.datas:
                        d_ticker = d._name
                        position = self.getposition(d)
                        if position.size > 0:
                            self.log(f"📉 执行平仓: {d_ticker}, 价格={current_price:.2f}, 数量={position.size:.6f}, RSI={rsi_val:.2f}")
                            self.order_target_percent(data=d, target=0.0)
                            self.signal_types[d_ticker] = signal  # 记录信号类型
                    
                    self.opentrades = 0
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