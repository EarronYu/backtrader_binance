import requests
import datetime
import threading
import json
import time
import traceback
import random
import logging


def send_trade_signal(signal, trigger_price, commas_secret, commas_max_lag, commas_exchange, commas_ticker, commas_bot_uuid):
    """
    发送交易信号到3commas
    
    Args:
        signal: 信号类型 (enter_long, exit_long等)
        trigger_price: 触发价格
        commas_secret: 3commas webhook密钥
        commas_max_lag: 最大延迟时间
        commas_exchange: 交易所名称
        commas_ticker: 交易对名称
        commas_bot_uuid: 3commas机器人UUID
        
    Returns:
        响应内容或错误信息
    """
    # 设置信号发送完成事件
    signal_sent_event = threading.Event()
    signal_response = {"status": "未知", "message": "未开始"}
    
    # 创建线程函数
    def send_signal_thread():
        nonlocal signal_response
        
        # 重试机制
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            retry_count += 1
            
            try:
                print(f"尝试发送信号 (第{retry_count}次): {signal} @ {trigger_price}")
                
                # 构建payload
                payload = {
                    'secret': commas_secret,
                    'max_lag': commas_max_lag,
                    'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    'trigger_price': str(trigger_price),
                    'tv_exchange': commas_exchange,
                    'tv_instrument': commas_ticker,
                    'action': signal,
                    'bot_uuid': commas_bot_uuid
                }
                
                # 先尝试n8n webhook
                try:
                    # 设置较短的超时，防止长时间阻塞
                    url = "http://localhost:5678/webhook/3commas"
                    response = requests.post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=5  # 5秒超时
                    )
                    
                    # 检查响应
                    if response.status_code == 200:
                        response_text = response.text
                        print(f"交易信号 {commas_ticker} {signal} 已成功发送到n8n")
                        print(f"响应内容: {response_text}")
                        signal_response = {"status": "成功", "message": response_text}
                        # 标记成功并退出重试循环
                        break
                    elif response.status_code == 404 and "webhook" in response.text and "not registered" in response.text:
                        # n8n特定错误，尝试备用发送方式
                        print(f"n8n webhook未注册，尝试直接发送到日志文件...")
                        
                        # 将信号记录到文件中
                        log_filename = f"signal_{datetime.datetime.now().strftime('%Y%m%d')}.log"
                        with open(log_filename, "a") as log_file:
                            log_entry = {
                                "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                "signal": signal,
                                "price": trigger_price,
                                "ticker": commas_ticker,
                                "exchange": commas_exchange,
                                "bot_id": commas_bot_uuid
                            }
                            log_file.write(json.dumps(log_entry) + "\n")
                        
                        print(f"信号已记录到文件: {log_filename}")
                        signal_response = {"status": "成功", "message": f"信号已记录到{log_filename}"}
                        break
                    else:
                        error_message = f"信号发送失败，状态码: {response.status_code}，响应: {response.text}"
                        print(error_message)
                        signal_response = {"status": "失败", "message": error_message}
                        # 继续重试
                except Exception as e:
                    error_message = f"发送到n8n异常: {str(e)}"
                    print(error_message)
                    signal_response = {"status": "异常", "message": error_message}
                    # 继续重试
            except Exception as e:
                error_message = f"信号发送异常: {str(e)}"
                print(error_message)
                print(traceback.format_exc())
                signal_response = {"status": "异常", "message": error_message}
                # 继续重试
            
            # 如果需要重试，增加延迟
            if retry_count < max_retries:
                # 使用指数退避策略，逐渐增加重试间隔
                retry_delay = (2 ** retry_count) + random.uniform(0, 1)
                print(f"将在 {retry_delay:.2f} 秒后重试...")
                time.sleep(retry_delay)
        
        # 所有尝试完成后，设置事件
        print(f"信号发送状态: {signal_response['status']}")
        signal_sent_event.set()
    
    # 创建并启动发送线程
    send_thread = threading.Thread(target=send_signal_thread)
    send_thread.daemon = True
    send_thread.start()
    
    # 等待信号发送完成，但设置超时
    timeout = 15  # 15秒超时
    if not signal_sent_event.wait(timeout):
        print(f"警告: 信号发送操作超时 ({timeout}秒)")
        return "超时等待响应"
    
    # 返回发送结果
    if signal_response["status"] == "成功":
        return signal_response["message"]
    else:
        return f"错误: {signal_response['message']}"

# 用于直接测试
if __name__ == "__main__":
    # 测试参数
    test_signal = "enter_long"
    test_price = 0.01234
    test_secret = "your_secret_here"
    test_max_lag = "30000"
    test_exchange = "BINANCE"
    test_ticker = "BTCUSDT"
    test_bot_uuid = "your_bot_uuid_here"
    
    # 测试发送
    print(f"测试发送信号: {test_signal} @ {test_price}")
    response = send_trade_signal(
        test_signal,
        test_price,
        test_secret,
        test_max_lag,
        test_exchange,
        test_ticker,
        test_bot_uuid
    )
    print(f"响应: {response}")