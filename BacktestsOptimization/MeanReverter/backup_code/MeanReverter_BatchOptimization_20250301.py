# 导入必要的库...
import os
import pandas as pd
from datetime import datetime
from glob import glob
import backtrader as bt 
import optuna
import warnings
import quantstats as qs
warnings.filterwarnings('ignore')
from IPython.display import clear_output
from pathlib import Path  # 使用pathlib代替os

# 在此处添加全局缓存字典，用于缓存数据加载结果和数据完整性检查结果
_data_feed_cache = {}
_data_completeness_cache = {}

from MeanReverter import MeanReverter

# 在 CONFIG 中添加所有需要动态配置的参数
CONFIG = {
    # 策略相关配置
    'strategy': {
        'class': MeanReverter,
        'name': MeanReverter.__name__
    },
    
    # 数据相关配置（单币种、单时间周期）
    # 如果 selected_symbols 为空，则通过 get_all_symbols 自动获取所有交易对
    'selected_symbols': [],
    'data_path': r'..\\futures',
    'start_date': '2024-01-01',
    'end_date': '2025-02-08',
    'source_timeframe': '1m',
    # 针对批量优化使用多个目标时间周期
    'target_timeframes': ['1H', '30min', '15min'],
    
    # 文件保存配置
    'reports_path': 'reports',
    'results_filename_template': 'optimization_results_{strategy_name}_{start_date}-{end_date}.csv',
    
    # 回测参数配置
    'commission': 0.0004,
    'initial_capital': 10000,
    # 如果需要可以添加：
    # 'trade_on_close': True,
    # 'exclusive_orders': True,
    # 'hedging': False,
    
    # 优化参数配置，根据 MeanReverter 策略的参数进行优化
    'optimization_params': {
        'frequency': range(15, 31, 2),            # 用于计算慢速 RSI 均线的周期，步长为2
        'rsiFrequency': range(30, 46, 2),         # 计算 RSI 的周期，步长为2
        'buyZoneDistance': range(1, 8, 1),        # RSI 相对于慢速 RSI 均线的折扣比例，步长为1
        'avgDownATRSum': range(3, 8, 1),          # 用于计算 ATR 累积值的周期数，步长为1
        'useAbsoluteRSIBarrier': [True, False],   # 是否使用绝对 RSI 阈值进行平仓
        'barrierLevel': range(55, 66, 2),         # RSI 阻力水平，步长为2
        'pyramiding': range(2, 5, 1)              # 最大允许加仓次数，步长为1
    },
    
    # 优化设置
    'optimization_settings': {
        'n_trials': 240,       # 可根据需要调整试验次数
        'min_trades': 50,
        'timeout': 3600,
        'n_jobs': 80           # -1 表示使用所有 CPU 核心; 也可以设置为具体的数量
    },

}

def get_timeframe_params(timeframe_str):
    """
    将时间周期字符串转换为 backtrader 的 timeframe 和 compression 参数
    """
    if timeframe_str.endswith('min'):
        return (bt.TimeFrame.Minutes, int(timeframe_str.replace('min', '')))
    elif timeframe_str.endswith('H'):
        return (bt.TimeFrame.Minutes, int(timeframe_str.replace('H', '')) * 60)
    elif timeframe_str.endswith('D'):
        return (bt.TimeFrame.Days, 1)
    elif timeframe_str == '1m':
        return (bt.TimeFrame.Minutes, 1)
    else:
        raise ValueError(f"不支持的时间周期格式: {timeframe_str}")

def load_and_resample_data(symbol, start_date, end_date, source_timeframe='1m', target_timeframe='30min', data_path=r'..\\futures'):
    """
    加载并重采样期货数据，并缓存已经重采样后的 DataFrame 以避免重复 I/O 操作
    """
    # 构造缓存键
    key = (symbol, start_date, end_date, source_timeframe, target_timeframe, data_path)
    if key in _data_feed_cache:
        # 如果缓存中有，返回新的数据馈送对象（注意拷贝，防止被修改）
        cached_df = _data_feed_cache[key]
        timeframe, compression = get_timeframe_params(target_timeframe)
        data_feed = bt.feeds.PandasData(
            dataname=cached_df.copy(),
            open='Open',
            high='High',
            low='Low',
            close='Close',
            volume='Volume',
            openinterest=-1,
            timeframe=timeframe,
            compression=compression,
            fromdate=pd.to_datetime(start_date),
            todate=pd.to_datetime(end_date)
        )
        
        # 添加clone方法，这样可以快速创建数据副本而不需要重新执行IO
        data_feed.clone = lambda: bt.feeds.PandasData(
            dataname=cached_df.copy(),
            open='Open',
            high='High',
            low='Low',
            close='Close',
            volume='Volume',
            openinterest=-1,
            timeframe=timeframe,
            compression=compression,
            fromdate=pd.to_datetime(start_date),
            todate=pd.to_datetime(end_date)
        )
        
        return data_feed
    
    # 生成日期范围
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    all_data = []
    
    # 标准化交易对名称
    formatted_symbol = symbol.replace('/', '_').replace(':', '_')
    if not formatted_symbol.endswith('USDT'):
        formatted_symbol = f"{formatted_symbol}USDT"
    
    # 遍历每一天
    for date in date_range:
        date_str = date.strftime('%Y-%m-%d')
        # 构建文件路径
        file_path = os.path.join(data_path, date_str, f"{date_str}_{formatted_symbol}_USDT_{source_timeframe}.csv")
        
        try:
            if os.path.exists(file_path):
                # 读取数据
                df = pd.read_csv(file_path)
                # 确保datetime列不带时区信息
                df['datetime'] = pd.to_datetime(df['datetime'], utc=False)
                all_data.append(df)
            else:
                print(f"文件不存在: {file_path}")
        except Exception as e:
            print(f"读取文件出错 {file_path}: {str(e)}")
            continue
    
    if not all_data:
        raise ValueError(f"未找到 {symbol} 在指定日期范围内的数据")
    
    # 合并、排序，以及重采样数据
    combined_df = pd.concat(all_data, ignore_index=True)
    combined_df = combined_df.sort_values('datetime')
    # 确保索引不带时区信息
    combined_df.set_index('datetime', inplace=True)
    # 移除任何时区信息
    if combined_df.index.tz is not None:
        combined_df.index = combined_df.index.tz_localize(None)
    
    resampled = combined_df.resample(target_timeframe).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()  # 立即删除NaN值
    
    backtesting_df = pd.DataFrame({
        'Open': resampled['open'],
        'High': resampled['high'],
        'Low': resampled['low'],
        'Close': resampled['close'],
        'Volume': resampled['volume']
    })
    
    # 确保所有数据都是数值类型并删除任何无效值
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        backtesting_df[col] = pd.to_numeric(backtesting_df[col], errors='coerce')
    backtesting_df = backtesting_df.dropna()
    
    # 将结果缓存在全局变量中（使用拷贝，以免后续被修改）
    _data_feed_cache[key] = backtesting_df.copy()
    
    timeframe, compression = get_timeframe_params(target_timeframe)
    data_feed = bt.feeds.PandasData(
        dataname=backtesting_df,
        open='Open',
        high='High',
        low='Low',
        close='Close',
        volume='Volume',
        openinterest=-1,
        timeframe=timeframe,
        compression=compression,
        fromdate=pd.to_datetime(start_date),
        todate=pd.to_datetime(end_date)
    )
    
    # 添加clone方法
    data_feed.clone = lambda: bt.feeds.PandasData(
        dataname=backtesting_df.copy(),
        open='Open',
        high='High',
        low='Low',
        close='Close',
        volume='Volume',
        openinterest=-1,
        timeframe=timeframe,
        compression=compression,
        fromdate=pd.to_datetime(start_date),
        todate=pd.to_datetime(end_date)
    )
    
    return data_feed

def get_all_symbols(data_path, date_str):
    """获取指定日期目录下的所有交易对"""
    daily_path = os.path.join(data_path, date_str)
    if not os.path.exists(daily_path):
        return []
    
    files = glob(os.path.join(daily_path, f"{date_str}_*_USDT_1m.csv"))
    symbols = set()  # 使用 set 进行去重
    for file in files:
        filename = os.path.basename(file)
        symbol = filename.split('_')[1]
        symbols.add(symbol)
    return list(symbols)

def verify_data_completeness(symbol, start_date, end_date, data_path):
    """验证数据完整性"""
    # 构造缓存键
    key = (symbol, start_date, end_date, data_path)
    if key in _data_completeness_cache:
        return _data_completeness_cache[key]
    
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    
    # 标准化交易对名称
    formatted_symbol = symbol.replace('/', '_').replace(':', '_')
    if not formatted_symbol.endswith('USDT'):
        formatted_symbol = f"{formatted_symbol}USDT"
    
    for date in date_range:
        date_str = date.strftime('%Y-%m-%d')
        file_path = os.path.join(
            data_path,
            date_str,
            f"{date_str}_{formatted_symbol}_USDT_1m.csv"  # 文件名格式保持不变
        )
        if not os.path.exists(file_path):
            print(f"文件不存在: {file_path}")
            _data_completeness_cache[key] = False
            return False
    _data_completeness_cache[key] = True
    return True

# 添加自定义评分函数
def custom_score(strat):
    """
    自定义评分函数 - 以最大化回报率为主要目标
    保留最低交易次数要求作为基本约束
    """
    # 获取交易次数
    trades = strat.analyzers.trades.get_analysis()
    total_trades = trades.get('total', {}).get('total', 0)
    
    # 从returns分析器获取总回报率
    returns = strat.analyzers.returns.get_analysis()
    total_return = returns.get('rtot', 0) * 100  # 转为百分比
    
    # 交易次数惩罚 - 确保策略至少有足够的交易
    min_trades = CONFIG['optimization_settings'].get('min_trades', 50)
    trade_penalty = 1.0 if total_trades >= min_trades else (total_trades / min_trades) ** 2
    
    # 最终得分简单地使用调整后的回报率
    # 交易次数不足的策略会受到严厉惩罚
    score = total_return * trade_penalty
    
    return score

def optimize_strategy(symbol, timeframe):
    """
    使用 Optuna 优化策略参数，并返回最优的前 5 个参数组合
    """
    # 1. 预加载数据，只执行一次IO操作
    preloaded_data = load_and_resample_data(
        symbol, CONFIG['start_date'], CONFIG['end_date'],
        target_timeframe=timeframe
    )
    
    # 使用内存存储而非SQLite数据库
    study = optuna.create_study(
        study_name=f"{symbol}_{timeframe}",
        direction="maximize",
        storage=None  # 使用内存存储
    )
    
    def objective(trial):
        try:
            params = {}
            for param_name, param_range in CONFIG['optimization_params'].items():
                if isinstance(param_range, range):
                    params[param_name] = trial.suggest_int(
                        param_name,
                        param_range.start,
                        param_range.stop - 1,
                        param_range.step
                    )
                else:
                    params[param_name] = trial.suggest_categorical(param_name, param_range)
            
            cerebro = bt.Cerebro(
                        optdatas=True,    # 启用数据优化
                        optreturn=True,   # 仅返回必要结果
                        runonce=True,     # 批处理模式
                        preload=True      # 预加载数据
            )
            # 2. 使用预加载数据的克隆而不是重新加载数据
            data = preloaded_data.clone()
            cerebro.adddata(data)
            cerebro.addstrategy(CONFIG['strategy']['class'], **params)
            
            # 只使用基本分析器，跳过PyFolio分析器避免时区问题
            # cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
            # cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
            cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
            # cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
            
            results = cerebro.run()
            strat = results[0]
            score = custom_score(strat)
            return score
        except Exception as e:
            print(f"Trial encountered an error: {e}")
            # 返回极低的分数，确保该试验不会被选中
            return float('-inf')
    
    # 添加异常捕获
    study.optimize(
        objective,
        n_trials=CONFIG['optimization_settings']['n_trials'],
        timeout=CONFIG['optimization_settings']['timeout'],
        n_jobs=CONFIG['optimization_settings'].get('n_jobs', 1),
        catch=(Exception,)  # 捕获所有异常
    )
    
    # 过滤无效试验
    completed_trials = [
        t for t in study.trials
        if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None and t.value > float('-inf')
    ]
    top_trials = sorted(completed_trials, key=lambda t: t.value, reverse=True)[:5]
    
    top_results = []
    for t in top_trials:
        result = t.params.copy()
        result['score'] = t.value
        top_results.append(result)
    
    return top_results

def run_backtest_with_params(params, symbol, timeframe):
    """
    使用指定参数运行策略的回测并计算收益指标（利用 quantstats）。
    返回一个包含基础回测指标和所有 quantstats 指标的字典。
    """
    # 过滤掉不属于策略参数部分的键（如 'score', 'symbol', 'timeframe'等）
    valid_keys = set(CONFIG["optimization_params"].keys())
    strategy_params = {k: v for k, v in params.items() if k in valid_keys}

    cerebro = bt.Cerebro(
                optdatas=True,    # 启用数据优化
                optreturn=True,   # 仅返回必要结果
                runonce=True,     # 批处理模式
                preload=True      # 预加载数据
    )
    data = load_and_resample_data(symbol, CONFIG['start_date'], CONFIG['end_date'],
                                  target_timeframe=timeframe)
    cerebro.adddata(data)
    # 只传入过滤后的策略参数
    cerebro.addstrategy(CONFIG['strategy']['class'], **strategy_params)

    initial_capital = CONFIG['initial_capital']
    cerebro.broker.setcash(initial_capital)
    cerebro.broker.setcommission(commission=CONFIG['commission'])

    # 添加常用分析器，包括 PyFolio 用于后续量化指标计算
    # cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    # cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')

    results = cerebro.run()
    strat = results[0]
    final_value = cerebro.broker.getvalue()
    profit = final_value - initial_capital
    roi = (profit / initial_capital) * 100

    # 获取 PyFolio 的回测收益率数据
    portfolio_stats = strat.analyzers.pyfolio.get_pf_items()
    returns = portfolio_stats[0]
    
    # 修改这里：确保索引没有时区信息，避免使用tz_convert
    # 首先检查是否有时区信息再进行处理
    try:
        if hasattr(returns.index, 'tz') and returns.index.tz is not None:
            returns.index = returns.index.tz_localize(None)
    except:
        # 如果无法处理时区，创建一个新的无时区索引
        try:
            returns = pd.Series(returns.values, index=pd.DatetimeIndex(returns.index.astype('datetime64[ns]')))
        except:
            # 如果依然失败，使用更简单的方法
            returns = pd.Series(returns.values, index=pd.DatetimeIndex([str(idx) for idx in returns.index]))

    # 计算量化指标（完整的收益指标）
    qs_stats = {}
    try:
        qs_stats["Sharpe Ratio"] = qs.stats.sharpe(returns)
        qs_stats["Sortino Ratio"] = qs.stats.sortino(returns)
        qs_stats["Calmar Ratio"] = qs.stats.calmar(returns)
        qs_stats["Max Drawdown"] = qs.stats.max_drawdown(returns)
        qs_stats["Win Rate"] = qs.stats.win_rate(returns)
        qs_stats["Profit Factor"] = qs.stats.profit_factor(returns)
        qs_stats["Expected Return (M)"] = qs.stats.expected_return(returns, aggregate='M')
        qs_stats["Kelly Criterion"] = qs.stats.kelly_criterion(returns)
        qs_stats["Risk of Ruin"] = qs.stats.risk_of_ruin(returns)
        qs_stats["Tail Ratio"] = qs.stats.tail_ratio(returns)
        qs_stats["Common Sense Ratio"] = qs.stats.common_sense_ratio(returns)
        qs_stats["Average Win"] = qs.stats.avg_win(returns)
        qs_stats["Average Loss"] = qs.stats.avg_loss(returns)
        qs_stats["Annualized Volatility"] = qs.stats.volatility(returns, periods=252)
        qs_stats["Skew"] = qs.stats.skew(returns)
        qs_stats["Kurtosis"] = qs.stats.kurtosis(returns)
        qs_stats["Value at Risk"] = qs.stats.value_at_risk(returns)
        qs_stats["Conditional VaR"] = qs.stats.conditional_value_at_risk(returns)
        qs_stats["Payoff Ratio"] = qs.stats.payoff_ratio(returns)
        qs_stats["Gain to Pain Ratio"] = qs.stats.gain_to_pain_ratio(returns)
        qs_stats["Ulcer Index"] = qs.stats.ulcer_index(returns)
        qs_stats["Consecutive Wins"] = qs.stats.consecutive_wins(returns)
        qs_stats["Consecutive Losses"] = qs.stats.consecutive_losses(returns)
        # ----------------- 新增指标 -----------------
        qs_stats["Avg Return"] = qs.stats.avg_return(returns)
        qs_stats["CAGR"] = qs.stats.cagr(returns)
        qs_stats["Expected Shortfall"] = qs.stats.expected_shortfall(returns)
        qs_stats["Information Ratio"] = qs.stats.information_ratio(returns)
        qs_stats["Profit Ratio"] = qs.stats.profit_ratio(returns)
        qs_stats["R2"] = qs.stats.r2(returns)
        qs_stats["R Squared"] = qs.stats.r_squared(returns)
        qs_stats["Recovery Factor"] = qs.stats.recovery_factor(returns)
        qs_stats["Risk-Return Ratio"] = qs.stats.risk_return_ratio(returns)
        qs_stats["Win/Loss Ratio"] = qs.stats.win_loss_ratio(returns)
        qs_stats["Worst"] = qs.stats.worst(returns)
        # ------------------------------------------------
    except Exception as e:
        qs_stats["error"] = str(e)

    # 整合基础回测指标与量化收益指标
    backtest_results = {
        "Initial Capital": initial_capital,
        "Final Value": final_value,
        "Profit": profit,
        "ROI (%)": roi,
    }
    backtest_results.update(qs_stats)

    return backtest_results

def load_master_results(config):
    """
    加载全局优化结果文件，并提取已完成优化的组合（基于 'Symbol', 'Target Timeframe', 'Rank' 列）。
    """
    # 构造 master 文件路径
    start_clean = config['start_date'].replace("-", "")
    end_clean = config['end_date'].replace("-", "")
    master_file = os.path.join(
        config['reports_path'], 
        config['results_filename_template'].format(
            strategy_name=config['strategy']['name'],
            start_date=start_clean,
            end_date=end_clean
        )
    )
    
    if os.path.exists(master_file):
        try:
            master_df = pd.read_excel(master_file)
        except Exception as e:
            master_df = pd.read_csv(master_file)
    else:
        master_df = pd.DataFrame()
    
    optimized_combinations = set()
    if not master_df.empty:
        if {'Target Timeframe', 'Symbol', 'Rank'}.issubset(master_df.columns):
            for symbol in master_df['Symbol'].unique():
                for tf in master_df['Target Timeframe'].unique():
                    rows = master_df[(master_df['Symbol'] == symbol) & (master_df['Target Timeframe'] == tf)]
                    ranks = rows['Rank'].tolist()
                    # 当存在 5 个排名且排名为 1 到 5 时认为该组合已完成优化
                    if len(ranks) == 5 and set(ranks) == set(range(1, 6)):
                        optimized_combinations.add((symbol, tf))
        else:
            print("警告: 结果文件缺少必要的列，将重新开始优化")
    else:
        print("优化结果文件为空")
        
    return master_file, master_df, optimized_combinations

def save_master_results(new_results, master_file):
    """
    将新的优化结果合并到全局结果文件中，并保存为 CSV 文件。
    """
    if os.path.exists(master_file):
        try:
            existing_df = pd.read_csv(master_file)
        except Exception as e:
            existing_df = pd.DataFrame()
        combined_df = pd.concat([existing_df, pd.DataFrame(new_results)], ignore_index=True)
    else:
        combined_df = pd.DataFrame(new_results)
    
    combined_df.to_csv(master_file, index=False)  # 修改为 CSV 写入
    print(f"优化结果保存到: {master_file}")

def process_symbol_tf(symbol, tf, config):
    """
    针对单个交易对和指定时间周期执行策略参数优化与回测，并赋予 1~5 的排名。
    """
    print(f"\n开始针对 {symbol} 时间周期 {tf} 优化...")
    # 使用已有的 optimize_strategy 函数
    top_results = optimize_strategy(symbol, tf)
    if not top_results:
        print(f"警告: {symbol} 在 {tf} 时间周期下优化失败")
        return []
    
    processed_results = []
    # 为每个参数组合运行回测并获取量化指标，同时赋予排名
    for idx, res in enumerate(top_results, start=1):
        res['Symbol'] = symbol
        res['Target Timeframe'] = tf
        res['Rank'] = idx
        metrics = run_backtest_with_params(res, symbol, tf)
        res.update(metrics)
        processed_results.append(res)
        
    print(f"完成 {symbol} 在 {tf} 时间周期下的优化，获得 {len(processed_results)} 个结果")
    return processed_results

# 新增清理函数：清理不在最终结果 CSV 中的 optuna 数据库文件
def clean_incomplete_optuna_db_files(config):
    """
    清理不在最终优化结果 CSV 中的 optuna 数据库文件。
    该函数会读取最终结果 CSV（如果存在），提取已完成优化的 (Symbol, Target Timeframe) 组合，
    然后删除 reports 目录下不在该列表中的 optuna 数据库文件。
    """
    import os
    from glob import glob

    # 从最终结果 CSV 中加载已完成优化组合
    master_file, master_df, optimized_combinations = load_master_results(config)
    print(f"已完成优化组合: {optimized_combinations}")
    
    # 匹配与当前策略相关的 optuna 数据库文件
    pattern = os.path.join(config['reports_path'], f"optuna_{config['strategy']['name']}_*.db")
    db_files = glob(pattern)
    for db_file in db_files:
        filename = os.path.basename(db_file)
        prefix = f"optuna_{config['strategy']['name']}_"
        # 确保文件名格式正确
        if filename.startswith(prefix) and filename.endswith(".db"):
            # 去掉前缀和后缀，得到 "symbol_timeframe"
            core = filename[len(prefix):-3]  # 去掉后面的 ".db"
            parts = core.rsplit("_", 1)
            if len(parts) != 2:
                continue
            symbol, timeframe = parts
            # 如果此组合不在最终结果中，则删除该数据库文件
            if (symbol, timeframe) not in optimized_combinations:
                try:
                    os.remove(db_file)
                    print(f"已删除未完成优化的数据库文件：{db_file}")
                except Exception as e:
                    print(f"删除文件 {db_file} 出错：{e}")
    print("数据库清理完成。")

def batch_optimize(config):
    """
    批量优化所有交易对和指定多个时间周期：
    1. 根据配置中的 selected_symbols 获取交易对列表（如果为空则自动获取）。
    2. 验证每个交易对在指定时间段内数据完整性，跳过数据不完整的。
    3. 对每个（交易对, 时间周期）组合，若已存在完整5个排名则跳过，否则运行优化与回测。
    4. 每完成一个交易对-时间周期组合的前五个优化结果，立刻保存到全局结果文件中。
    """
    os.makedirs(config['reports_path'], exist_ok=True)
    
    master_file, master_df, optimized_combinations = load_master_results(config)
    
    # 获取交易对列表
    if config.get('selected_symbols'):
        symbols = config['selected_symbols']
    else:
        symbols = get_all_symbols(config['data_path'], config['start_date'])
        print(f"总共找到 {len(symbols)} 个交易对")
    
    total_combinations = [(s, tf) for s in symbols for tf in config['target_timeframes']]
    remaining_combinations = [combo for combo in total_combinations if combo not in optimized_combinations]
    print(f"剩余需要优化的组合数量: {len(remaining_combinations)} 个")
    
    # 新增变量跟踪已处理组合数
    processed_count = 0
    total_remaining = len(remaining_combinations)
    
    # 遍历每个交易对
    for i, symbol in enumerate(symbols, 1):
        # 更新进度显示，使用剩余组合数作为分母
        print(f"\n进度: {processed_count}/{total_remaining} ({processed_count/total_remaining*100:.1f}%) - 当前处理: {symbol}")
        
        print(f"验证 {symbol} 的数据完整性...")
        if not verify_data_completeness(symbol, config['start_date'], config['end_date'], config['data_path']):
            print(f"警告: 跳过 {symbol} - 数据不完整")
            continue
        print(f"{symbol} 数据完整性验证通过")
        
        # 对每个目标时间周期进行优化
        for tf in config['target_timeframes']:
            if (symbol, tf) in optimized_combinations:
                print(f"组合 {symbol}-{tf} 已完成优化，跳过")
                continue
                
            # 显示更详细的进度信息
            print(f"\n处理组合: {symbol}-{tf} (进度: {processed_count}/{total_remaining}, 剩余: {total_remaining-processed_count})")
            
            results = process_symbol_tf(symbol, tf, config)
            if results:
                clear_output(wait=True)
                save_master_results(results, master_file)
                optimized_combinations.add((symbol, tf))
                # 递增已处理计数并更新进度显示
                processed_count += 1
                print(f"完成组合 {symbol}-{tf} 的优化，总进度: {processed_count}/{total_remaining} ({processed_count/total_remaining*100:.1f}%)")
            else:
                print(f"警告: {symbol} 在 {tf} 时间周期下没有获得优化结果")
    
    # 显示最终完成消息
    print(f"批量优化完成。共处理 {processed_count}/{total_remaining} 个组合。")

if __name__ == '__main__':
    # 先清理不完整的 Optuna 数据库文件（不在最终结果 CSV 中的组合）
    # clean_incomplete_optuna_db_files(CONFIG)
    batch_optimize(CONFIG)