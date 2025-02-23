# -*- coding: utf-8 -*-
"""
该脚本用于使用 backtesting 库回测 ConnorsReversal 策略，并输出回测结果和交易记录数据。
请确保数据文件 'data.csv' 存在，并且包含:
    Open, High, Low, Close, Volume 等列，
其中索引列为日期时间格式。
"""

import pandas as pd
import numpy as np
import talib as ta
import os
from backtesting import Backtest, Strategy
from ConnorsReversal import ConnorsReversal

def load_historical_data(symbol, start_date, end_date, data_path, source_timeframe='1m', agg_methods=None):
    """
    加载并合并指定日期范围内的历史数据，返回包含 Open, High, Low, Close, Volume 列的 DataFrame。

    Parameters:
    -----------
    symbol : str
        交易对名称
    start_date : str
        开始日期，格式 'YYYY-MM-DD'
    end_date : str
        结束日期，格式 'YYYY-MM-DD'
    data_path : str
        数据文件夹的路径，每天的数据存放在以日期命名的子文件夹内部
    source_timeframe : str
        数据的时间周期，例如 '1m'
    agg_methods : dict, optional
        聚合方法字典，默认为 None

    Returns:
    --------
    DataFrame : 历史数据合并后的 DataFrame，索引为 datetime，列包含 Open, High, Low, Close, Volume
    """
    if agg_methods is None:
        agg_methods = {
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }

    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    all_data = []

    formatted_symbol = symbol
    if not formatted_symbol.endswith('USDT'):
        formatted_symbol = f"{formatted_symbol}USDT"

    for date in date_range:
        date_str = date.strftime('%Y-%m-%d')
        # 假设文件命名格式： "YYYY-MM-DD_{symbol}_USDT_{source_timeframe}.csv"
        file_path = os.path.join(data_path, date_str, f"{date_str}_{formatted_symbol}_USDT_{source_timeframe}.csv")
        try:
            if os.path.exists(file_path):
                df = pd.read_csv(file_path)
                if 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime'])
                    df.set_index('datetime', inplace=True)
                else:
                    df.index = pd.to_datetime(df.index)
                # 将列名转换成首字母大写（Backtesting 库 默认要求）
                df.rename(columns=lambda x: x.capitalize(), inplace=True)
                all_data.append(df)
            else:
                print(f"文件不存在: {file_path}")
        except Exception as e:
            print(f"读取文件出错 {file_path}: {str(e)}")
            continue

    if not all_data:
        raise ValueError("未找到数据")
    combined_df = pd.concat(all_data, ignore_index=False)
    combined_df.sort_index(inplace=True)
    return combined_df

if __name__ == "__main__":
    # 使用历史数据文件夹方式加载数据。若需使用单一 CSV 文件，可将 use_data_folder 设置为 False
    use_data_folder = True
    if use_data_folder:
        symbol = "1000PEPEUSDT"
        start_date = "2024-01-01"
        end_date = "2024-12-31"
        data_folder = r"\\znas\Main\futures"  # 请根据实际情况修改数据文件夹路径
        try:
            backtesting_df = load_historical_data(symbol, start_date, end_date, data_folder, source_timeframe="1m")
        except Exception as e:
            print(f"无法加载历史数据: {e}")
            exit(1)
    else:
        data_file = "data.csv"
        try:
            backtesting_df = pd.read_csv(data_file, parse_dates=True, index_col=0)
        except Exception as e:
            print(f"无法读取数据文件 {data_file}: {e}")
            exit(1)

    # 初始化回测实例
    bt_obj = Backtest(
        backtesting_df,
        ConnorsReversal,
        commission=0.0004,
        trade_on_close=True,   # 模拟与 TradingView process_orders_on_close 一致
        exclusive_orders=True,
        hedging=False          # 禁止对冲
    )

    # 使用经过优化的参数运行回测
    stats = bt_obj.run(
        lowest_point_bars=23,   # 优化后，用于确定最低点的周期数
        rsi_length=42,          # 优化后，RSI 指标的计算周期
        sell_barrier=67,        # 优化后，RSI 的卖出阈值
        dca_parts=4             # 优化后，DCA 分批次数
    )

    # 打印回测统计结果
    print("\n=== Backtest Results ===")
    print(f"Total Return: {stats['Return [%]']:.2f}%")
    print(f"Sharpe Ratio: {stats['Sharpe Ratio']:.2f}")
    print(f"Max Drawdown: {stats['Max. Drawdown [%]']:.2f}%")
    print(f"Win Rate: {stats['Win Rate [%]']:.2f}%")
    print(f"Total Trades: {stats['# Trades']}")

    # 通过 stats['_trades'] 获取所有交易记录的 DataFrame
    trades_df = stats['_trades']

    # 输出前几条交易记录以检查
    print("所有交易记录：")
    print(trades_df.head())

    # 导出交易记录到 CSV 文件（便于后续分析）
    trades_df.to_csv("trade_records.csv", index=False)

    # 绘制回测图表
    bt_obj.plot(resample=False) 