from flask import Flask, request, jsonify
import logging
from datetime import datetime
import requests
import os
import json

app = Flask(__name__)

# 确保日志目录存在
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# 生成日志文件名（按日期）
log_file = os.path.join(log_dir, f'trading_signal_{datetime.now().strftime("%Y%m%d")}.log')

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 记录启动信息
logging.info("交易信号服务启动")
logging.info(f"日志文件路径: {log_file}")

def process_trading_signal(signal_data):
    """处理交易信号"""
    try:
        logging.info(f"开始处理信号: {signal_data}")
        
        # 转换action
        if signal_data['action'] == 'buy':
            signal_data['action'] = 'enter_long'
        elif signal_data['action'] == 'sell':
            signal_data['action'] = 'exit_long'
            
        logging.info(f"信号处理完成: {signal_data}")
        
        # 发送信号到3commas
        try:
            headers = {'Content-Type': 'application/json'}
            response = requests.post(
                'https://api.3commas.io/signal_bots/webhooks',
                json=signal_data,
                headers=headers
            )
            logging.info(f"信号发送完成 - 状态码: {response.status_code}")
            logging.info(f"服务器响应: {response.text}")
            
            if response.status_code == 200:
                logging.info("信号发送成功")
                return True
            else:
                logging.warning(f"服务器返回非200状态码: {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"发送信号失败: {str(e)}")
            logging.error("错误详情: ", exc_info=True)
            return False
            
    except Exception as e:
        logging.error(f"处理信号时发生错误: {str(e)}")
        return False

@app.route('/', methods=['POST'])
def receive_signal():
    try:
        # 获取 POST 请求数据
        data = request.get_json()
        logging.info(f"收到新的交易信号请求")
        logging.info(f"原始信号内容: {data}")

        # 处理并发送交易信号
        if process_trading_signal(data):
            response_data = {
                "status": "success",
                "signal": data,
                "timestamp": datetime.now().isoformat()
            }
            logging.info(f"信号处理成功: {response_data}")
            return jsonify(response_data), 200
        else:
            error_msg = "信号处理失败"
            logging.warning(error_msg)
            return jsonify({"status": "error", "error": error_msg}), 400

    except Exception as e:
        error_msg = f"处理信号时发生错误: {str(e)}"
        logging.error(error_msg, exc_info=True)
        return jsonify({"status": "error", "error": error_msg}), 500

if __name__ == "__main__":
    logging.info("策略信号接收服务启动")
    app.run(host="0.0.0.0", port=80)