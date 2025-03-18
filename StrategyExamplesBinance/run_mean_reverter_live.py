import datetime as dt
import backtrader as bt
from backtrader_binance_futures import BinanceStore
from backtrader_binance_futures.signal_only_broker import SignalOnlyBroker  # 导入新的broker
from MeanReverterLive import MeanReverterLive
from ConfigBinance.Config import Config  # 配置文件
import time
import sys
import signal
import traceback
import logging
import os
import threading

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"strategy_log_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    ]
)
logger = logging.getLogger("MeanReverterLive")

# 全局变量，用于存储cerebro实例和状态
cerebro = None
running = True
store = None
data = None
reconnect_attempts = 0
MAX_RECONNECT_ATTEMPTS = 5
last_data_update = 0  # 上次收到数据更新的时间戳
data_timeout = 180  # 数据超时时间（秒）
watchdog_active = True  # 看门狗状态

def signal_handler(sig, frame):
    """处理中断信号，安全停止策略"""
    global running, watchdog_active
    logger.info('接收到中断信号，正在安全停止策略...')
    running = False
    watchdog_active = False
    
    # 立即执行资源清理，确保程序能够退出
    cleanup_resources()
    
    # 如果程序仍未退出，5秒后强制退出
    def force_exit():
        logger.info("程序未能正常退出，正在强制退出...")
        os._exit(0)
    
    # 启动强制退出定时器
    force_exit_timer = threading.Timer(5.0, force_exit)
    force_exit_timer.daemon = True
    force_exit_timer.start()
    
    # 不立即退出，让主循环处理停止逻辑

def create_binance_connection(config):
    """创建Binance连接，只用于获取数据，不进行实际交易"""
    global store
    
    symbol = config['trading']['symbol']
    coin_target = symbol[-4:] if symbol.endswith('USDT') else symbol[-3:]

    logger.info(f"创建Binance连接: {symbol}, 基础货币: {coin_target}")
    
    try:
        # 创建Binance Store用于获取数据
        store = BinanceStore(
            api_key=config['binance']['api_key'],
            api_secret=config['binance']['api_secret'],
            coin_target=coin_target,
            testnet=config['binance']['testnet']
        )
        return True
    except Exception as e:
        logger.error(f"创建Binance连接失败: {e}")
        logger.error(traceback.format_exc())
        return False

def get_binance_data(config):
    """获取Binance数据"""
    global store, data, last_data_update
    
    if store is None:
        logger.error("无法获取数据: Binance连接不存在")
        return None
    
    symbol = config['trading']['symbol']
    
    try:
        # 获取实时数据
        from_date = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=config['data']['warmup_minutes'])
        logger.info(f"获取数据: {symbol}, 开始日期: {from_date}")
        
        # 修改数据获取逻辑，确保正确处理实时行情数据
        data = store.getdata(
            timeframe=config['trading']['timeframe'],
            compression=config['trading']['compression'],
            dataname=symbol,
            start_date=from_date,
            LiveBars=True
        )
        
        # 调试：添加一个数据通知回调
        def data_status_cb(data, status, *args, **kwargs):
            global last_data_update
            status_txt = "实时数据" if status == 0 else "历史数据" if status == 1 else "未知"
            logger.info(f"数据状态回调: {data._name} - {status_txt}")
            if status in [0, 1]:  # 只在有效数据时更新时间戳
                last_data_update = time.time()
                try:
                    logger.info(f"→ 价格: {data.close[0]}, 时间: {bt.num2date(data.datetime[0])}")
                except:
                    pass
        
        # 注册数据回调以监控数据流
        if hasattr(data, '_state'):
            data_status_cb(data, data._state)  # 立即调用一次检查初始状态
        
        if hasattr(data, 'set_cb_datanotify'):
            # Binance特定API调用
            logger.info("注册数据通知回调 set_cb_datanotify")
            data.set_cb_datanotify(data_status_cb)
        elif hasattr(data, '_register_callback'):
            logger.info("注册数据通知回调 _register_callback")
            data._register_callback(data_status_cb)
        else:
            # 使用更友好的消息
            logger.info("当前数据源不支持回调方法，这不影响策略运行")
        
        # 初始化最后数据更新时间
        last_data_update = time.time()
        
        return data
    except Exception as e:
        logger.error(f"获取Binance数据失败: {e}")
        logger.error(traceback.format_exc())
        return None

def initialize_cerebro(config):
    """初始化并配置Cerebro实例"""
    global cerebro, data
    
    # 创建新的Cerebro实例
    cerebro = bt.Cerebro(quicknotify=True)

    # 添加数据源
    if data is None:
        logger.error("无法初始化Cerebro: 没有数据")
        return False
    
    try:
        cerebro.adddata(data)

        # 添加策略，合并策略参数和3commas参数
        strategy_params = config['strategy']['params'].copy()
        strategy_params.update(config['trading']['commas_params'])
        
        # 添加日志配置和其他参数
        strategy_params['debug_mode'] = True  # 启用调试模式
        strategy_params['order_timeout'] = 120  # 增加订单超时时间，避免策略在订单执行时卡住
        
        cerebro.addstrategy(
            config['strategy']['class'],
            **strategy_params
        )
        
        logger.info(f"已初始化Cerebro实例，添加策略: {config['strategy']['name']}")

        # 使用专门的信号Broker，而不是Binance的实际交易Broker
        broker = SignalOnlyBroker()
        logger.info(f"创建信号专用Broker: {broker}")
        
        # 设置信号参数到broker
        if 'commas_params' in config['trading']:
            commas_params = config['trading']['commas_params']
            logger.info(f"设置信号参数: {commas_params}")
            broker.set_signal_params(
                commas_secret=commas_params.get('commas_secret'),
                commas_max_lag=commas_params.get('commas_max_lag'),
                commas_exchange=commas_params.get('commas_exchange'),
                commas_ticker=commas_params.get('commas_ticker'),
                commas_bot_uuid=commas_params.get('commas_bot_uuid')
            )
            logger.info("已启用信号发送功能")
        
        # 设置broker
        cerebro.setbroker(broker)
        logger.info("已设置信号专用Broker")
        
        return True
    except Exception as e:
        logger.error(f"初始化Cerebro失败: {e}")
        logger.error(traceback.format_exc())
        return False

def start_watchdog(config):
    """启动监控线程，用于检测数据更新超时或异常"""
    global watchdog_active, last_data_update, running
    
    def watchdog_thread():
        global last_data_update, running
        logger.info("监控线程已启动")
        
        # 故障计数器
        fault_counter = 0
        last_warning_time = 0
        
        while watchdog_active:
            try:
                current_time = time.time()
                time_since_last_update = current_time - last_data_update
                
                # 定期记录状态
                if int(time_since_last_update) % 60 == 0 and int(time_since_last_update) > 0:
                    logger.info(f"监控线程: 距离上次数据更新 {time_since_last_update:.1f} 秒")
                
                # 如果超过超时时间没有收到数据更新，尝试重新连接
                if time_since_last_update > data_timeout:
                    fault_counter += 1
                    # 限制警告频率，避免日志刷屏
                    if current_time - last_warning_time > 30:
                        logger.warning(f"数据流中断: {time_since_last_update:.1f} 秒没有收到更新，触发重连 (故障计数: {fault_counter})")
                        last_warning_time = current_time
                    
                    if fault_counter >= 3:
                        logger.error(f"多次检测到数据流中断，强制终止程序并重启")
                        # 强制清理资源并发送中断信号
                        running = False
                        # 直接执行资源清理
                        try:
                            cleanup_resources()
                        except Exception as e:
                            logger.error(f"清理资源失败: {e}")
                        
                        # 如果清理后程序仍在运行，强制退出
                        logger.warning("正在强制终止程序...")
                        time.sleep(1)  # 给日志一点时间刷新
                        os._exit(1)  # 使用非零退出码表示异常退出
                    
                    # 标记为需要重连，主循环将处理重连逻辑
                    running = False
                    break
                
                time.sleep(1)
            except Exception as e:
                logger.error(f"监控线程异常: {e}")
                logger.error(traceback.format_exc())
                time.sleep(5)  # 出错后等待较长时间
        
        logger.info("监控线程已退出")
    
    # 创建并启动监控线程
    thread = threading.Thread(target=watchdog_thread, name="Watchdog")
    thread.daemon = True
    thread.start()
    return thread

def run_strategy():
    """
    运行策略
    """
    global cerebro, reconnect_attempts, last_data_update, watchdog_active
    
    # 全局配置
    CONFIG = {
        # 策略相关配置
        'strategy': {
            'class': MeanReverterLive,
            'name': MeanReverterLive.__name__,
            'params': {
                'frequency': 5,
                'rsiFrequency': 8,
                'buyZoneDistance': 1,
                'avgDownATRSum': 2,
                'useAbsoluteRSIBarrier': True,
                'barrierLevel': 30,
                'pyramiding': 3,
            }
        },
        
        # 交易配置
        'trading': {
            'symbol': '1000PEPEUSDT',
            'timeframe': bt.TimeFrame.Minutes,
            'compression': 1,
            'commas_params': {
                'commas_secret': 'eyJhbGciOiJIUzI1NiJ9.eyJzaWduYWxzX3NvdXJjZV9pZCI6MTEyOTUwfQ.E_ap0C5xhrkOsD4MMZb6TrGi1WO_gzoX3TTjvKqcneA',
                'commas_max_lag': '30000',
                'commas_exchange': 'BINANCE',
                'commas_ticker': '1000PEPEUSDT.P',
                'commas_bot_uuid': '7ea23635-1570-4b10-b3c4-425326496fc7'
            }
        },
        
        # Binance API配置
        'binance': {
            'api_key': Config.BINANCE_API_KEY,
            'api_secret': Config.BINANCE_API_SECRET,
            'testnet': Config.TESTNET  # Binance Storage
        },
        
        # 数据配置
        'data': {
            'warmup_minutes': 20  # 获取最近多少分钟的历史数据用于预热
        }
    }

    try:
        # 设置策略运行超时计时器
        strategy_timeout = threading.Timer(300, lambda: logger.error("策略启动超时，将在监控线程中处理"))
        strategy_timeout.daemon = True
        strategy_timeout.start()
        
        logger.info(f"开始设置策略 {CONFIG['strategy']['name']} 交易 {CONFIG['trading']['symbol']}...")
        
        # 1. 创建Binance连接
        if not create_binance_connection(CONFIG):
            logger.error("无法创建Binance连接，策略启动失败")
            return False
            
        # 2. 获取数据
        data_obj = get_binance_data(CONFIG)
        if data_obj is None:
            logger.error("无法获取交易数据，策略启动失败")
            return False
        
        # 3. 初始化Cerebro
        if not initialize_cerebro(CONFIG):
            logger.error("无法初始化Cerebro，策略启动失败")
            return False
        
        # 直接获取数据状态用于调试
        try:
            status_info = f"数据状态检查: {data_obj._name}, 长度: {len(data_obj)}"
            if hasattr(data_obj, '_state'):
                status_info += f", 状态: {data_obj._state}"
            if hasattr(data_obj, 'haslivedata'):
                status_info += f", 已加载: {data_obj.haslivedata()}"
            logger.info(status_info)
            
            # 尝试访问价格数据
            if len(data_obj) > 0:
                logger.info(f"当前价格: {data_obj.close[0]}")
        except Exception as e:
            logger.info(f"数据状态检查信息: {e} (这不影响策略运行)")
            
        # 4. 启动监控线程
        watchdog_thread = start_watchdog(CONFIG)
        
        # 5. 运行策略
        logger.info("开始运行策略...")
        
        # 取消超时计时器
        if strategy_timeout.is_alive():
            strategy_timeout.cancel()
        
        # 直接运行cerebro，简化执行流程，避免线程复杂性
        try:
            logger.info("执行cerebro.run()")
            cerebro.run()
            logger.info("cerebro.run()执行完成")
            reconnect_attempts = 0  # 重置重连计数
            return True
        except Exception as e:
            logger.error(f"策略执行异常: {e}")
            logger.error(traceback.format_exc())
            reconnect_attempts += 1
            return False
            
    except Exception as e:
        logger.error(f"策略运行过程中出现错误: {e}")
        logger.error(traceback.format_exc())
        reconnect_attempts += 1
        return False

def cleanup_resources():
    """清理资源，为重新连接做准备"""
    global cerebro, store, data
    
    logger.info("清理资源，准备退出...")
    
    try:
        # 设置资源清理超时
        cleanup_start_time = time.time()
        
        # 先尝试停止策略
        if cerebro is not None:
            try:
                # 检查cerebro是否已经有策略实例
                if hasattr(cerebro, 'runstrats') and cerebro.runstrats:
                    for strat in cerebro.runstrats:
                        if hasattr(strat, 'emergency_stop'):
                            logger.info("尝试紧急停止策略...")
                            strat.emergency_stop()
                            logger.info("策略已紧急停止")
                            # 短暂等待，让资源释放
                            time.sleep(0.5)
            except Exception as e:
                logger.error(f"停止策略时出错: {e}")
        
        # 强制结束所有非守护线程
        import threading
        active_threads = threading.enumerate()
        logger.info(f"当前活动线程数: {len(active_threads)}")
        for thread in active_threads:
            if thread != threading.current_thread() and not thread.daemon:
                logger.info(f"尝试停止线程: {thread.name}")
                # 无法直接停止线程，但可以标记为守护线程
                # 这样在主线程退出时它们会被强制终止
                try:
                    thread.daemon = True
                except Exception as e:
                    logger.error(f"无法将线程 {thread.name} 设置为守护线程: {e}")

        # 清理数据源
        if data:
            try:
                logger.info("正在停止数据源...")
                if hasattr(data, '_stop'):
                    data._stop()
                    logger.info("数据源已停止")
                elif hasattr(data, 'close'):
                    data.close()
                    logger.info("数据源已关闭")
                else:
                    logger.warning("数据源没有停止或关闭方法")
            except Exception as e:
                logger.error(f"停止数据源时出错: {e}")
                logger.error(traceback.format_exc())
        
        # 清理store
        if store:
            try:
                logger.info("正在关闭Binance连接...")
                
                # 先尝试关闭feeds
                if hasattr(store, 'feeds'):
                    for feed in list(store.feeds):
                        try:
                            logger.info(f"关闭feed: {feed}")
                            feed._stop()
                        except Exception as e:
                            logger.error(f"关闭feed失败: {e}")
                
                # 再关闭store
                if hasattr(store, 'close'):
                    store.close()
                    logger.info("Binance连接已关闭")
                elif hasattr(store, 'stop'):
                    store.stop()
                    logger.info("Binance连接已停止")
                else:
                    logger.warning("Binance连接没有关闭或停止方法")
                    
            except Exception as e:
                logger.error(f"关闭Binance连接时出错: {e}")
                logger.error(traceback.format_exc())
        
        # 检查资源清理是否超时
        cleanup_duration = time.time() - cleanup_start_time
        if cleanup_duration > 5:
            logger.warning(f"资源清理耗时较长: {cleanup_duration:.1f}秒")
        
        # 重置全局变量
        cerebro = None
        store = None
        data = None
        
        # 手动请求垃圾回收
        import gc
        gc.collect()
        
        logger.info("资源清理完成")
    except Exception as e:
        logger.error(f"清理资源时发生错误: {e}")
        logger.error(traceback.format_exc())

def main():
    """主程序入口"""
    global running, watchdog_active
    
    # 注册信号处理函数
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("===== 启动均值回归策略脚本版本 =====")
    logger.info(f"当前工作目录: {os.getcwd()}")
    
    # 添加全局异常钩子
    def global_exception_handler(exctype, value, tb):
        logger.critical(f"未捕获的异常: {exctype.__name__}: {value}")
        logger.critical("".join(traceback.format_tb(tb)))
        
        # 确保资源被清理
        cleanup_resources()
        
        # 设置退出标志
        global running, watchdog_active
        running = False
        watchdog_active = False
        
        # 确保程序退出
        logger.critical("发生致命错误，程序将在5秒后退出...")
        time.sleep(5)  # 给时间让日志完全写入
        os._exit(1)
    
    # 设置全局异常处理器
    sys.excepthook = global_exception_handler
    
    try:
        # 设置一个主程序看门狗计时器，如果超过10分钟没有进展就强制退出
        program_watchdog = threading.Timer(600, lambda: os._exit(2))
        program_watchdog.daemon = True
        program_watchdog.start()
        logger.info("已启动程序看门狗计时器 (10分钟)")
        
        # 重置状态
        running = True
        watchdog_active = True

    # 运行策略
        logger.info("开始运行策略...")
        success = run_strategy()
        
        # 策略启动成功，取消主程序看门狗
        if program_watchdog.is_alive():
            program_watchdog.cancel()
            logger.info("已取消程序看门狗")
        
        if success:
            logger.info("策略已成功启动，按Ctrl+C停止...")
            
            # 主循环，保持程序运行直到收到中断信号或发生错误
            loop_counter = 0
            
            # 计算主循环开始时间，用于检测长时间无响应
            main_loop_start = time.time()
            last_heartbeat = time.time()
            
            while running:
                try:
                    time.sleep(1)
                    loop_counter += 1
                    now = time.time()
                    
                    # 每60秒输出一次心跳信息
                    if now - last_heartbeat >= 60:
                        loop_minutes = (now - main_loop_start) / 60
                        logger.info(f"主程序心跳 - 策略运行中... ({loop_minutes:.1f}分钟)")
                        last_heartbeat = now
                    
                    # 如果程序运行超过4小时，自动退出并重启
                    if now - main_loop_start > 14400:  # 4小时 = 14400秒
                        logger.warning("程序已运行超过4小时，准备重启以防止资源泄漏")
                        break
                except KeyboardInterrupt:
                    # 捕获键盘中断以防止异常堆栈跟踪
                    logger.info("接收到键盘中断...")
                    break
                except Exception as e:
                    logger.error(f"主循环异常: {e}")
                    logger.error(traceback.format_exc())
                    # 出现异常，但不要立即退出，继续尝试运行
                    time.sleep(5)
            
            logger.info("主循环结束，开始清理...")
        else:
            logger.error("策略启动失败，准备退出...")
    except Exception as e:
        logger.error(f"主程序发生异常: {e}")
        logger.error(traceback.format_exc())
    finally:
        # 确保资源被清理
        logger.info("主程序退出，执行最终资源清理...")
        running = False
        watchdog_active = False
        
        # 设置强制退出定时器，确保程序不会卡住
        force_exit_timer = threading.Timer(30.0, lambda: os._exit(0))
        force_exit_timer.daemon = True
        force_exit_timer.start()
        logger.info("已设置30秒强制退出定时器")
        
        try:
            cleanup_resources()
        except Exception as e:
            logger.error(f"最终清理时发生异常: {e}")
            logger.error(traceback.format_exc())
        
        logger.info("===== 策略已完全退出 =====")
        
        # 取消强制退出定时器（如果清理成功完成）
        if force_exit_timer.is_alive():
            force_exit_timer.cancel()
            logger.info("已取消强制退出定时器")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        # 捕获最外层的键盘中断
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常: {e}")
        logger.error(traceback.format_exc())
    finally:
        # 确保最终清理
        cleanup_resources()
        
        # 再次尝试终止所有线程，这是最后的保障
        try:
            # 获取所有线程，并将其标记为守护线程
            all_threads = list(threading.enumerate())
            main_thread = threading.current_thread()
            
            logger.info(f"最终线程清理: 当前有 {len(all_threads)} 个活动线程")
            for thread in all_threads:
                if thread != main_thread:
                    try:
                        thread_name = thread.name
                        if not thread.daemon:
                            logger.info(f"设置线程为守护线程: {thread_name}")
                            thread.daemon = True
                        logger.debug(f"线程状态: {thread_name} (daemon={thread.daemon})")
                    except Exception as e:
                        logger.error(f"处理线程时出错: {e}")
        except Exception as e:
            logger.error(f"最终线程清理失败: {e}")
        
        # 短暂停顿以让日志刷新
        time.sleep(0.5)
        logger.info("程序已终止")
        # 确保完全退出
        sys.exit(0) 