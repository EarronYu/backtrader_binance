import pandas as pd

# 读取CSV文件
file_path = r"C:\Users\x7498\Downloads\optimization_results_MeanReverter_20240101-20250208.csv"
df = pd.read_csv(file_path)

# 创建一个标识字符串，将Symbol和Target Timeframe组合在一起作为唯一键
df['组合'] = df['Symbol'] + '-' + df['Target Timeframe']

# 对于每个组合，只保留Rank=1的行
rank1_df = df[df['Rank'] == 1]

# 按Score降序排序
sorted_df = rank1_df.sort_values(by='Score', ascending=False)

# 获取前25个最佳参数组合
top25 = sorted_df.head(25)

# 打印结果
print(f"找到了{len(top25)}个最佳参数组合，按Score排序如下：\n")
pd.set_option('display.max_columns', None)  # 显示所有列
pd.set_option('display.width', None)  # 确保所有列都能显示出来
print(top25[['Symbol', 'Target Timeframe', 'Score', 'frequency', 'rsiFrequency', 
             'buyZoneDistance', 'avgDownATRSum', 'useAbsoluteRSIBarrier', 
             'barrierLevel', 'pyramiding']])

# 保存结果到CSV
output_file = "top25_best_parameters.csv"
top25.to_csv(output_file, index=False)
print(f"\n结果已保存到 {output_file}") 