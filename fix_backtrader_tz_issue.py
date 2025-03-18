#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Backtrader时区问题修复脚本

这个脚本通过修改Backtrader内部类和方法来解决常见的时区相关错误，
特别是'_tz'属性缺失的问题。在导入Backtrader之前运行这个脚本。

使用方法:
1. 将此脚本放在您的项目目录中
2. 在导入backtrader之前导入此脚本: `import fix_backtrader_tz_issue`
3. 然后正常导入和使用backtrader

示例:
```
import fix_backtrader_tz_issue  # 必须在导入backtrader之前运行
import backtrader as bt
```
"""

import sys
import warnings
import importlib

# 尝试修复pandas高版本与backtrader的兼容问题
def patch_pandas():
    """修复pandas与backtrader的兼容性问题"""
    import pandas as pd
    
    # 检查是否需要修复
    if not hasattr(pd.Series, "iteritems"):
        # 增加iteritems作为items的别名
        pd.Series.iteritems = pd.Series.items
        print("已修复: 添加了pandas.Series.iteritems作为items的别名")
    
    # 如果DataFrame没有ix属性，则添加ix作为loc的别名
    if not hasattr(pd.DataFrame, "ix"):
        pd.DataFrame.ix = property(lambda self: self.loc)
        print("已修复: 添加了pandas.DataFrame.ix作为loc的别名")

# 修复backtrader的时区处理
def patch_backtrader():
    """修复backtrader的时区处理问题"""
    import backtrader as bt
    from backtrader import AbstractDataBase
    from backtrader.utils.py3 import with_metaclass
    
    # 保存原始的_load方法
    original_load = bt.feeds.PandasData._load
    
    # 定义新的_load方法处理时区问题
    def _load_with_tz_fix(self):
        if hasattr(self._dataname.index, "tz") and self._dataname.index.tz is not None:
            print(f"正在移除DataFrame索引的时区信息")
            self._dataname.index = self._dataname.index.tz_localize(None)
        return original_load(self)
    
    # 替换原始方法
    bt.feeds.PandasData._load = _load_with_tz_fix
    print("已修复: backtrader.feeds.PandasData._load方法")
    
    # 修复PyFolio分析器
    if hasattr(bt.analyzers, "PyFolio"):
        original_get_pf_items = bt.analyzers.PyFolio.get_pf_items
        
        def get_pf_items_with_tz_fix(self):
            # 调用原始方法
            returns, positions, transactions, gross_lev = original_get_pf_items(self)
            
            # 移除时区信息
            if returns is not None and hasattr(returns.index, "tz") and returns.index.tz is not None:
                returns.index = returns.index.tz_localize(None)
            
            if positions is not None and hasattr(positions.index, "tz") and positions.index.tz is not None:
                positions.index = positions.index.tz_localize(None)
                
            if transactions is not None and hasattr(transactions.index, "tz") and transactions.index.tz is not None:
                transactions.index = transactions.index.tz_localize(None)
                
            if gross_lev is not None and hasattr(gross_lev.index, "tz") and gross_lev.index.tz is not None:
                gross_lev.index = gross_lev.index.tz_localize(None)
                
            return returns, positions, transactions, gross_lev
            
        bt.analyzers.PyFolio.get_pf_items = get_pf_items_with_tz_fix
        print("已修复: backtrader.analyzers.PyFolio.get_pf_items方法")
    
    # 修复Lines类，确保它有_tz属性
    def ensure_tz_attr(cls):
        original_init = cls.__init__
        
        def __init_with_tz(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            if not hasattr(self, '_tz'):
                self._tz = None
                
        cls.__init__ = __init_with_tz
        return cls
    
    # 应用到关键类
    if hasattr(bt, "LineRoot"):
        ensure_tz_attr(bt.LineRoot)
        print("已修复: backtrader.LineRoot类")
        
    if hasattr(bt, "LineSeries"):
        ensure_tz_attr(bt.LineSeries)
        print("已修复: backtrader.LineSeries类")
    
    if hasattr(bt, "Line"):
        ensure_tz_attr(bt.Line)
        print("已修复: backtrader.Line类")
        
    # 修复DataSeries类
    if hasattr(bt, "AbstractDataBase"):
        ensure_tz_attr(bt.AbstractDataBase)
        print("已修复: backtrader.AbstractDataBase类")

# 主要修复函数
def apply_fixes():
    """应用所有修复"""
    try:
        # 检查backtrader是否已导入
        if "backtrader" in sys.modules:
            print("警告: backtrader已经导入，修复可能不完全有效")
            patch_backtrader()
        else:
            # 导入并修复pandas
            patch_pandas()
            
            # 为以后导入backtrader做准备
            original_import = __import__
            
            def custom_import(name, *args, **kwargs):
                module = original_import(name, *args, **kwargs)
                if name == "backtrader":
                    print("检测到backtrader导入，正在应用修复...")
                    patch_backtrader()
                return module
            
            __builtins__["__import__"] = custom_import
            print("已设置backtrader导入钩子，将在导入时自动修复")
            
        print("所有修复成功应用")
    except Exception as e:
        print(f"应用修复时出错: {e}")
        
# 自动应用修复
print("正在应用Backtrader时区问题修复...")
apply_fixes() 