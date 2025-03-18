#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试Backtrader时区修复脚本的有效性
"""

# 首先导入修复脚本
import fix_backtrader_tz_issue

# 然后导入其他库
import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime
import os

# 创建一个简单的测试数据框
def create_test_dataframe():
    """创建一个带有时区信息的测试DataFrame"""
    # 创建日期范围
    dates = pd.date_range(start='2021-01-01', end='2021-01-30', freq='D')
    # 添加时区信息
    dates = dates.tz_localize('UTC')
    
    # 生成测试数据
    n = len(dates)
    data = {
        'Open': np.random.normal(100, 5, n),
        'High': np.random.normal(105, 5, n),
        'Low': np.random.normal(95, 5, n),
        'Close': np.random.normal(100, 5, n),
        'Volume': np.random.randint(1000, 10000, n)
    }
    
    # 创建DataFrame
    df = pd.DataFrame(data, index=dates)
    print("创建了测试DataFrame，带有UTC时区信息")
    print(f"DataFrame索引的时区: {df.index.tz}")
    return df

# 测试PandasData加载
def test_pandas_data():
    """测试PandasData加载带时区信息的DataFrame"""
    df = create_test_dataframe()
    
    # 从DataFrame创建PandasData
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=None,  # 使用索引作为日期时间
        open='Open',
        high='High',
        low='Low',
        close='Close',
        volume='Volume',
        openinterest=-1
    )
    
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    print("成功添加数据到Cerebro")
    
    # 添加一个简单的打印策略
    class PrintStrategy(bt.Strategy):
        def __init__(self):
            print("策略初始化")
        
        def next(self):
            dt = self.data.datetime.date(0)
            close = self.data.close[0]
            print(f"日期: {dt}, 收盘价: {close:.2f}")
    
    cerebro.addstrategy(PrintStrategy)
    
    # 添加PyFolio分析器
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')
    
    # 运行回测
    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]
    
    # 测试PyFolio分析器
    portfolio_stats = strat.analyzers.pyfolio.get_pf_items()
    returns = portfolio_stats[0]
    print("成功获取PyFolio回报")
    print(f"PyFolio returns时区: {returns.index.tz if hasattr(returns.index, 'tz') else '无时区信息'}")
    
    print("测试完成，没有遇到时区相关错误")
    
if __name__ == "__main__":
    print("开始测试Backtrader时区修复...")
    test_pandas_data()
    print("测试成功完成，修复有效!") 