"""
修复backtrader时区问题的脚本

这个脚本提供了修复backtrader与pandas时区兼容性问题的解决方案。
主要问题是在使用PyFolio分析器时，'Lines_LineSeries_DataSeries_OHLC_OHLCDateTime_Abst' 
对象没有 '_tz' 属性导致的错误。
"""

import pandas as pd
import backtrader as bt
import os
import numpy as np

# 修改后的数据加载函数
def load_data_without_tz(symbol, start_date, end_date, source_timeframe='1m', target_timeframe='30min', data_path=None):
    """
    加载数据并确保没有时区信息
    """
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
                # 读取数据并确保datetime不带时区
                df = pd.read_csv(file_path)
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
    
    # 确保索引没有时区信息
    combined_df.set_index('datetime', inplace=True)
    if hasattr(combined_df.index, 'tz') and combined_df.index.tz is not None:
        combined_df.index = combined_df.index.tz_localize(None)
    
    # 重采样
    resampled = combined_df.resample(target_timeframe).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    # 创建适合backtrader的数据框
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
    
    return backtesting_df.dropna()

# 创建一个安全的PandasData类，处理时区问题
class SafePandasData(bt.feeds.PandasData):
    """
    扩展PandasData类，处理时区问题
    """
    def _load(self):
        if self.p.nocase:
            # 将列名称转换为小写
            self._mapping = {x.lower(): x for x in self._dataname.columns}
        
        # 确保索引没有时区信息
        if hasattr(self._dataname.index, 'tz') and self._dataname.index.tz is not None:
            self._dataname.index = self._dataname.index.tz_localize(None)
            
        # 调用父类的_load方法
        super(SafePandasData, self)._load()

# 包装PyFolio分析器防止时区错误
class SafePyFolio(bt.analyzers.PyFolio):
    """
    扩展PyFolio分析器，确保返回的Series没有时区信息
    """
    def get_pf_items(self):
        """
        重写get_pf_items方法，确保返回的Series没有时区信息
        """
        items = super(SafePyFolio, self).get_pf_items()
        returns, positions, transactions, gross_lev = items
        
        # 移除时区信息
        if hasattr(returns.index, 'tz') and returns.index.tz is not None:
            returns.index = returns.index.tz_localize(None)
        
        if positions is not None and hasattr(positions.index, 'tz') and positions.index.tz is not None:
            positions.index = positions.index.tz_localize(None)
            
        if transactions is not None and hasattr(transactions.index, 'tz') and transactions.index.tz is not None:
            transactions.index = transactions.index.tz_localize(None)
            
        if gross_lev is not None and hasattr(gross_lev.index, 'tz') and gross_lev.index.tz is not None:
            gross_lev.index = gross_lev.index.tz_localize(None)
            
        return returns, positions, transactions, gross_lev

# 辅助函数：安全地处理returns的时区
def safe_process_returns(returns):
    """
    安全地处理returns的时区问题
    """
    if returns is None:
        return None
        
    try:
        # 检查是否有时区信息，如果有则移除
        if hasattr(returns.index, 'tz') and returns.index.tz is not None:
            returns = pd.Series(returns.values, pd.DatetimeIndex(returns.index.astype('datetime64[ns]')))
        return returns
    except:
        # 最后的尝试：创建一个新的Series，完全没有时区信息
        try:
            index = pd.DatetimeIndex([pd.Timestamp(x).to_pydatetime().replace(tzinfo=None) for x in returns.index])
            return pd.Series(returns.values, index=index)
        except:
            print("警告：无法处理returns的时区信息")
            return returns

# 使用示例
"""
# 1. 使用SafePandasData替代普通的PandasData
data = SafePandasData(
    dataname=df,
    open='Open',
    high='High',
    low='Low',
    close='Close',
    volume='Volume',
    openinterest=-1,
    fromdate=pd.to_datetime(start_date),
    todate=pd.to_datetime(end_date)
)

# 2. 使用SafePyFolio替代普通的PyFolio分析器
cerebro.addanalyzer(SafePyFolio, _name='pyfolio')

# 3. 在获取PyFolio分析结果后使用safe_process_returns处理
portfolio_stats = strat.analyzers.pyfolio.get_pf_items()
returns = safe_process_returns(portfolio_stats[0])
""" 