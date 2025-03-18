# encoding: UTF-8
"""信号模式启动脚本 - 只发送信号到n8n，不实际进行Binance交易"""

import os
import sys

# 添加必要的路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 确保当前工作目录正确  
os.chdir(current_dir)

# 导入必要的模块
from run_mean_reverter_live import main

if __name__ == "__main__":
    print("===== 启动信号模式 - 只发送信号，不实际交易 =====")
    print(f"工作目录: {os.getcwd()}")
    print("按 Ctrl+C 可安全停止策略")
    
    # 运行主程序
    main() 