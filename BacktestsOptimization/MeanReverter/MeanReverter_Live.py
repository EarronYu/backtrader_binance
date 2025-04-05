import backtrader as bt
import math
import threading
import aiohttp
import asyncio
import datetime
from MeanReverter import MeanReverter

class MeanReverter_Live(MeanReverter):
    # 参数设置，保留原有参数，同时添加实盘所需的参数
    params = (
        ('frequency', 22),          # 平滑RSI的周期
        ('rsiFrequency', 36),       # RSI周期
        ('buyZoneDistance', 3),     # 买入区域距离百分比
        ('avgDownATRSum', 5),       # ATR求和周期
        ('useAbsoluteRSIBarrier', True),
        ('barrierLevel', 60),       # 障碍水平
        ('pyramiding', 3),          # 最大加仓次数
        ('initial_cash', 1000),     # 初始资金
        # 3commas必传参数
        ('commas_secret', None),    # 3commas webhook secret
        ('commas_max_lag', None),   # 3commas webhook max lag
        ('commas_exchange', None),  # TV exchange名称
        ('commas_ticker', None),    # TV ticker/instrument
        ('commas_bot_uuid', None),  # 3commas bot uuid
        ('debug_mode', True),       # 调试模式
    )

    def __init__(self):
        # 调用父类的 __init__ 方法来初始化原策略
        super().__init__()

        # 检查 3commas 参数
        if not all([self.p.commas_secret, self.p.commas_exchange, self.p.commas_ticker, self.p.commas_bot_uuid]):
            raise ValueError("必须提供所有3commas参数！")

        # 初始化一些特定的实盘交易设置
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.start_loop, daemon=True)
        self.loop_thread.start()

    def start_loop(self):
        # 启动异步事件循环
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def send_signal(self, signal, trigger_price):
        """异步发送交易信号"""
        try:
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
            
            url = "http://localhost:5678/webhook/3commas"  # 3commas的Webhook地址

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        self.log(f"已发送 {signal} 信号, 价格: {trigger_price}")
                    else:
                        self.log(f"发送信号失败，状态码: {response.status}")
            return True
        except Exception as e:
            self.log(f"发送信号异常: {e}")
            return False

    def send_signal_async(self, signal, trigger_price):
        """非阻塞地启动异步信号发送"""
        asyncio.run_coroutine_threadsafe(self.send_signal(signal, trigger_price), self.loop)

    def next(self):
        # 调用父类的 next 方法，保持原有的交易决策逻辑
        super().next()

        # 在原有逻辑基础上，添加实盘交易信号的发送
        current_price = self.data.close[0]
        
        # 判断买入信号
        if self.position:  # 如果有持仓
            if self.rsi[0] > self.rsi_slow[0]:
                self.send_signal_async('sell', current_price)
        else:  # 如果没有持仓
            if self.rsi[0] < self.rsi_slow[0]:
                self.send_signal_async('buy', current_price)

    def stop(self):
        """策略停止时清理资源"""
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop_thread.join()
            self.log("异步事件循环已关闭")
        except Exception as e:
            self.log(f"关闭事件循环异常: {e}")
