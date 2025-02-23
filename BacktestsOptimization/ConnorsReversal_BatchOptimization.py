# 导入必要的库
import os
import pandas as pd
from datetime import datetime
from glob import glob
import numpy as np
import backtrader as bt  # 替换 backtesting 为 backtrader
import optuna
import warnings
warnings.filterwarnings('ignore')
from IPython.display import clear_output


# 在文件开头，导入库之后添加全局配置
from ConnorsReversal import ConnorsReversal

CONFIG = {
    # 策略相关配置
    'strategy': {
        'class': ConnorsReversal,
        'name': ConnorsReversal.__name__
    },
    
    # 数据相关配置
    'data_path': r'\\znas\Main\futures',
    'start_date': '2024-01-01',
    'end_date': '2025-02-01',

    'source_timeframe': bt.TimeFrame.Minutes,  # 改用backtrader的时间周期定义
    'target_timeframes': {
        '30min': bt.TimeFrame.Minutes,
        '15min': bt.TimeFrame.Minutes,
        '5min': bt.TimeFrame.Minutes,
        '1min': bt.TimeFrame.Minutes
    },

    # 文件保存配置
    'reports_path': 'reports',
    'results_filename_template': 'optimization_results_{strategy_name}_{start_date}-{end_date}.xlsx',
    
    # 回测参数配置
    'commission': 0.0004,  # 佣金
    'margin': 0.5,        # 保证金比例（0.5 表示 50% 保证金）
    'initial_capital': 10000,
    
    # 优化参数配置
    'optimization_params': {
        'lowest_point_bars': range(5, 51, 5),
        'rsi_length': range(2, 51, 5),
        'sell_barrier': range(65, 86, 5),
        'dca_parts': range(4, 12, 2)
    },
    
    # 优化方法配置
    'optimization_settings': {
        'n_trials': 10  # Optuna优化的试验次数
    },
    
    # 自定义评分函数权重配置
    'score_weights': {
        'ret_weight': 0.6,
        'sqn_weight': 0.4,
        'sharpe_weight': 0.2,
        'win_rate_weight': 0.15,
        'dd_weight': 0.1,
        'min_trades': 50
    },

    # 交易对选择配置
    'symbols_selection': {
        'mode': 'specific',  # 'all' 或 'specific'
        'specific_symbols': [
            'BTC',
            'ETH'
            # 添加其他想要优化的交易对
        ]
    },

    # 数据文件格式配置
    'data_file_format': {
        'timeframe_suffix': '1m',  # 数据文件的时间周期后缀
        'template': '{date}_{symbol}_USDT_{timeframe}.csv'  # 文件名模板
    }
}


def load_and_resample_data(symbol, start_date, end_date, source_timeframe='1m', target_timeframe='30min', data_path=r'\\znas\Main\futures', 
                          agg_methods=None):
    """加载并重采样期货数据"""
    if agg_methods is None:
        agg_methods = {
            'open': 'first',
            'high': 'max', 
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }
    
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    all_data = []
    
    # 标准化交易对名称
    formatted_symbol = symbol.replace('/', '_').replace(':', '_')
    if not formatted_symbol.endswith('USDT'):
        formatted_symbol = f"{formatted_symbol}USDT"
    
    for date in date_range:
        date_str = date.strftime('%Y-%m-%d')
        file_path = os.path.join(
            data_path,
            date_str,
            f"{date_str}_{formatted_symbol}_USDT_1m.csv"
        )
        
        try:
            # 读取CSV时指定datetime列的解析
            df = pd.read_csv(
                file_path,
                parse_dates=['datetime'],  # 确保解析datetime列
                date_parser=lambda x: pd.to_datetime(x, format='%Y-%m-%d %H:%M:%S')
            )
            all_data.append(df)
        except FileNotFoundError:
            print(f"警告: 找不到文件 {file_path}")
            continue
        except Exception as e:
            print(f"错误: 处理文件 {file_path} 时发生异常: {str(e)}")
            continue
    
    if not all_data:
        raise ValueError(f"未找到 {symbol} 在指定日期范围内的数据")
    
    # 合并所有数据并按时间排序
    combined_df = pd.concat(all_data, ignore_index=True)
    combined_df = combined_df.sort_values('datetime')
    
    # 确保datetime列是正确的datetime类型
    if not pd.api.types.is_datetime64_any_dtype(combined_df['datetime']):
        combined_df['datetime'] = pd.to_datetime(combined_df['datetime'])
    
    # 设置datetime为索引
    combined_df.set_index('datetime', inplace=True)
    
    # 获取目标时间周期的参数
    timeframe, compression = get_timeframe_params(target_timeframe)
    
    # 使用backtrader的重采样功能
    data = bt.feeds.PandasData(
        dataname=combined_df,
        datetime=None,  # 使用索引作为日期时间
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        openinterest=-1,  # 不使用持仓量
        timeframe=timeframe,
        compression=compression,
        fromdate=pd.to_datetime(start_date),
        todate=pd.to_datetime(end_date)
    )
    
    return data

def get_timeframe_params(timeframe_str):
    """
    将时间周期字符串转换为backtrader的timeframe和compression参数
    
    Parameters:
    -----------
    timeframe_str : str
        时间周期字符串, 如 '1min', '5min', '30min', '1H', '4H', '1D'
        
    Returns:
    --------
    tuple : (timeframe, compression)
        timeframe: bt.TimeFrame 对象
        compression: int, 压缩因子
    """
    # 解析时间周期字符串
    if timeframe_str.endswith('min'):
        return (bt.TimeFrame.Minutes, int(timeframe_str.replace('min', '')))
    elif timeframe_str.endswith('H'):
        return (bt.TimeFrame.Minutes, int(timeframe_str.replace('H', '')) * 60)
    elif timeframe_str.endswith('D'):
        return (bt.TimeFrame.Days, 1)
    elif timeframe_str == '1m':  # 处理1分钟特殊情况
        return (bt.TimeFrame.Minutes, 1)
    else:
        raise ValueError(f"不支持的时间周期格式: {timeframe_str}")
    

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
            f"{date_str}_{formatted_symbol}_USDT_1m.csv"  # 修改这里的文件名格式
        )
        if not os.path.exists(file_path):
            print(f"文件不存在: {file_path}")
            return False
    return True


def optimize_strategy(symbol, start_date, end_date, data_path, results_file, 
                     strategy_cls, optimization_params, source_timeframe, target_timeframe,
                     backtest_config, optimization_settings, custom_score_fn, data_cache, reports_path):
    """使用Optuna对单个交易对进行策略优化"""
    try:
        print(f"开始优化 {symbol} 在 {target_timeframe} 上的策略...")
        data = data_cache[(symbol, target_timeframe)]
        
        # 预先创建基础Cerebro实例（仅用于初始化配置，此实例不直接用于每个试验）
        cerebro_base = bt.Cerebro()
        cerebro_base.adddata(data)
        cerebro_base.broker.setcash(backtest_config['initial_capital'])
        cerebro_base.broker.setcommission(
            commission=backtest_config['commission'],
            margin=backtest_config['margin'],
            mult=1.0
        )
        cerebro_base.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro_base.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro_base.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        cerebro_base.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro_base.addanalyzer(bt.analyzers.SQN, _name='sqn')
        cerebro_base.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn')
        
        # 用于每个试验重新创建 cerebro 实例的辅助函数
        def get_trial_cerebro():
            cerebro = bt.Cerebro()
            cerebro.adddata(data)
            cerebro.broker.setcash(backtest_config['initial_capital'])
            cerebro.broker.setcommission(
                commission=backtest_config['commission'],
                margin=backtest_config['margin'],
                mult=1.0
            )
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
            cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
            cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
            cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn')
            return cerebro
        
        # 存储试验结果
        trial_results = []
        failed_trials = []
        
        def objective(trial):
            try:
                # 使用辅助函数创建一个新的 cerebro 实例
                cerebro = get_trial_cerebro()
                
                # 使用Optuna建议的参数
                params = {}
                for param_name, param_range in optimization_params.items():
                    if isinstance(param_range, range):
                        params[param_name] = trial.suggest_int(
                            param_name,
                            param_range.start,
                            param_range.stop - 1,
                            param_range.step
                        )
                    else:
                        params[param_name] = trial.suggest_categorical(param_name, param_range)
                
                # 添加策略及参数
                cerebro.addstrategy(strategy_cls, **params)
                
                # 运行回测
                results = cerebro.run()
                strat = results[0]
                
                # 获取交易统计
                trade_stats = strat.analyzers.trades.get_analysis()
                total_trades = trade_stats.get('total', {}).get('total', 0)
                if total_trades < optimization_settings.get('min_trades', 50):
                    return -500
                
                # 获取其他指标
                returns_series = pd.Series(strat.analyzers.timereturn.get_analysis())
                total_return = (strat.analyzers.returns.get_analysis()['rtot'] * 100 
                                if returns_series.size > 0 else 0)
                annual_return = (0 if returns_series.size == 0 
                                 else (1 + total_return/100)**(252/returns_series.size) - 1)
                sharpe = strat.analyzers.sharpe.get_analysis()['sharperatio'] or 0
                drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
                sqn = strat.analyzers.sqn.get_analysis()['sqn'] or 0
                won = trade_stats.get('won', {}).get('total', 0)
                win_rate = (won / total_trades * 100) if total_trades > 0 else 0
                
                # 存储试验结果
                result = {
                    'Symbol': symbol,
                    'Target Timeframe': target_timeframe,
                    'Total Return (%)': total_return,
                    'Annual Return (%)': annual_return * 100,
                    'Sharpe Ratio': sharpe,
                    'Max Drawdown (%)': drawdown,
                    'SQN': sqn,
                    'Win Rate (%)': win_rate,
                    'Total Trades': total_trades,
                    **params
                }
                trial_results.append(result)
                
                # 返回自定义目标分数
                score = custom_score_fn(strat)
                return score
                
            except Exception as e:
                error_info = {
                    'params': trial.params,
                    'error': str(e),
                    'timestamp': pd.Timestamp.now()
                }
                failed_trials.append(error_info)
                print(f"试验失败: {error_info}")
                return -1000
        
        # 创建Optuna study，使用SQLite存储，并进行优化
        storage_name = f"sqlite:///{reports_path}/optuna_{symbol}_{target_timeframe}.db"
        study = optuna.create_study(
            study_name=f"{symbol}_{target_timeframe}",
            storage=storage_name,
            direction="maximize",
            load_if_exists=True
        )
        n_trials = optimization_settings.get('n_trials', 100)
        n_jobs = optimization_settings.get('n_jobs', -1)
        
        try:
            study.optimize(
                objective, 
                n_trials=n_trials,
                n_jobs=n_jobs,
                show_progress_bar=True
            )
        except KeyboardInterrupt:
            print("\n优化被用户中断")
        except Exception as e:
            print(f"\n优化过程出错: {str(e)}")
            if failed_trials:
                print("\n失败的试验记录:")
                for trial in failed_trials:
                    print(f"参数: {trial['params']}")
                    print(f"错误: {trial['error']}")
                    print(f"时间: {trial['timestamp']}")
            return None
        
        # 批量保存结果的代码保持不变
        if trial_results:
            try:
                results_df = pd.DataFrame(trial_results)
                parquet_file = results_file.replace('.xlsx', '.parquet')
                results_df.to_parquet(
                    parquet_file,
                    engine='fastparquet',
                    append=True
                )
                best_trials = sorted(trial_results,
                                     key=lambda x: x['Total Return (%)'],
                                     reverse=True)[:5]
                best_df = pd.DataFrame(best_trials)
                try:
                    with pd.ExcelWriter(results_file, mode='a', 
                                          if_sheet_exists='overlay') as writer:
                        best_df.to_excel(writer, index=False, 
                                          header=not os.path.exists(results_file))
                except FileNotFoundError:
                    best_df.to_excel(results_file, index=False)
                
                print(f"成功保存结果到 {results_file}")
                print(f"详细结果已保存到 {parquet_file}")
                
                return best_trials
                
            except Exception as e:
                print(f"保存结果时出错: {str(e)}")
                return trial_results
        
        return None
        
    except Exception as e:
        print(f"优化过程发生错误: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None
    

def main():
    config = CONFIG
    
    def custom_score(strat, weights=config['score_weights']):
        """自定义评分函数，适配backtrader的分析器结果"""
        # 获取分析器结果
        sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0)
        drawdown = strat.analyzers.drawdown.get_analysis()
        max_dd = drawdown['max']['drawdown'] if 'max' in drawdown else 0
        returns = strat.analyzers.returns.get_analysis()
        total_return = returns.get('rtot', 0) * 100
        trades = strat.analyzers.trades.get_analysis()
        total_trades = trades.get('total', {}).get('total', 0)
        won_trades = trades.get('won', {}).get('total', 0)
        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0
        sqn = strat.analyzers.sqn.get_analysis().get('sqn', 0)

        dd_penalty = 1 / (1 + abs(max_dd/100))
        trade_penalty = 1 if total_trades >= weights['min_trades'] else total_trades / weights['min_trades']

        score = (
            weights['ret_weight'] * (total_return/100) +
            weights['sqn_weight'] * sqn +
            weights['sharpe_weight'] * sharpe +
            weights['win_rate_weight'] * (win_rate/100) +
            weights['dd_weight'] * dd_penalty
        ) * trade_penalty

        return score

    # 确保报告目录存在
    os.makedirs(config['reports_path'], exist_ok=True)
    
    # 根据配置获取要处理的交易对列表
    start_date_obj = datetime.strptime(config['start_date'], '%Y-%m-%d')
    all_symbols = get_all_symbols(config['data_path'], start_date_obj.strftime('%Y-%m-%d'))
    
    if config['symbols_selection']['mode'] == 'specific':
        # 过滤出指定的交易对
        selected_symbols = [
            symbol for symbol in all_symbols 
            if any(symbol.startswith(s) for s in config['symbols_selection']['specific_symbols'])
        ]
        if not selected_symbols:
            raise ValueError("未找到指定的交易对")
        symbols = selected_symbols
    else:
        symbols = all_symbols
        
    print(f"将优化 {len(symbols)} 个交易对")

    print("\n开始逐个处理交易对...")
    
    for symbol in symbols:
        print(f"\n正在处理交易对: {symbol}")
        print("=" * 50)
        
        # 为当前交易对创建数据缓存
        current_symbol_cache = {}
        
        # 加载当前交易对的所有时间周期数据
        print(f"\n加载 {symbol} 的数据...")
        for tf in config['target_timeframes'].keys():
            print(f"加载 {tf} 时间周期...")
            try:
                data = load_and_resample_data(
                    symbol=symbol,
                    start_date=config['start_date'],
                    end_date=config['end_date'],
                    source_timeframe=config['source_timeframe'],
                    target_timeframe=tf,
                    data_path=config['data_path']
                )
                current_symbol_cache[(symbol, tf)] = data
            except Exception as e:
                print(f"警告: 加载 {symbol}-{tf} 数据失败: {str(e)}")
                continue
        
        if not current_symbol_cache:
            print(f"跳过 {symbol}: 没有成功加载任何数据")
            continue
            
        print(f"\n成功加载 {symbol} 的 {len(current_symbol_cache)} 个时间周期数据")
        
        # 检查已完成的优化组合
        results_filename = config['results_filename_template'].format(
            strategy_name=config['strategy']['name'],
            start_date=config['start_date'].replace("-", ""),
            end_date=config['end_date'].replace("-", "")
        )
        base, ext = os.path.splitext(results_filename)
        file_suffix = "_specific" if config['symbols_selection']['mode'] == 'specific' else "_all"
        master_file = os.path.join(config['reports_path'], f"{base}{file_suffix}{ext}")
        
        try:
            global_df = pd.read_excel(master_file)
            optimized_combinations = set(
                (row['Symbol'], row['Target Timeframe'])
                for _, row in global_df.groupby(['Symbol', 'Target Timeframe']).size().reset_index().iterrows()
                if row[0] >= 5  # 如果该组合已有5个或更多结果
            )
        except FileNotFoundError:
            global_df = pd.DataFrame()
            optimized_combinations = set()
        
        # 对当前交易对的每个时间周期进行优化
        for tf in config['target_timeframes'].keys():
            if (symbol, tf) in optimized_combinations:
                print(f"\n跳过 {symbol}-{tf}: 已完成优化")
                continue
                
            print(f"\n开始优化 {symbol}-{tf}")
            try:
                results = optimize_strategy(
                    symbol=symbol,
                    start_date=config['start_date'],
                    end_date=config['end_date'],
                    data_path=config['data_path'],
                    results_file=master_file,
                    strategy_cls=config['strategy']['class'],
                    optimization_params=config['optimization_params'],
                    source_timeframe=config['source_timeframe'],
                    target_timeframe=tf,
                    backtest_config={
                        'commission': config['commission'],
                        'margin': config['margin'],
                        'initial_capital': config['initial_capital']
                    },
                    optimization_settings=config['optimization_settings'],
                    custom_score_fn=custom_score,
                    data_cache=current_symbol_cache,
                    reports_path=config['reports_path']
                )
                
                if results:
                    print(f"\n{symbol}-{tf} 优化完成!")
                    print("最佳结果:")
                    best_result = results[0]
                    print(f"总收益率: {best_result['Total Return (%)']:.2f}%")
                    print(f"夏普比率: {best_result['Sharpe Ratio']:.2f}")
                    print(f"最大回撤: {best_result['Max Drawdown (%)']:.2f}%")
                    print(f"胜率: {best_result['Win Rate (%)']:.2f}%")
                else:
                    print(f"警告: {symbol}-{tf} 优化失败")
                    
            except Exception as e:
                print(f"错误: 优化 {symbol}-{tf} 时发生异常: {str(e)}")
                continue
        
        # 清理当前交易对的数据缓存
        print(f"\n清理 {symbol} 的数据缓存...")
        current_symbol_cache.clear()
        
        print(f"\n完成处理交易对: {symbol}")
        print("=" * 50)

    print("\n所有交易对处理完成!")
    
    # 显示最终统计信息
    if os.path.exists(master_file):
        final_df = pd.read_excel(master_file)
        print("\n优化结果统计:")
        print(f"总结果数: {len(final_df)}")
        print(f"优化过的交易对数: {final_df['Symbol'].nunique()}")
        print(f"平均总收益率: {final_df['Total Return (%)'].mean():.2f}%")
        print(f"平均夏普比率: {final_df['Sharpe Ratio'].mean():.2f}")
        print(f"平均最大回撤: {final_df['Max Drawdown (%)'].mean():.2f}%")
        print(f"平均胜率: {final_df['Win Rate (%)'].mean():.2f}%")


if __name__ == '__main__':
    main()
