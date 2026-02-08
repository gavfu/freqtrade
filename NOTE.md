
# Initialize configuration and start trade
```sh
# activate virtual environment
source ./.venv/bin/activate

# initialize user folder
freqtrade create-userdir --userdir user_data

# create a new configuration file
freqtrade new-config --config user_data/config.json

# run SampleStrategy
freqtrade trade --config user_data/config.json --strategy SampleStrategy
```

# 下载历史数据（用于回测）
```sh
# 下载 ETH/USDT 的 5m、30m、4h K线数据，时间范围 2017-08-01 至 2026-02-06
freqtrade download-data --exchange binance --pairs ETH/USDT --timeframes 5m 30m 4h --timerange 20170801-20260206

# 查看已下载的数据
freqtrade list-data --exchange binance
```

> 注：每个时间周期的数据会单独下载并保存，例如 `ETH_USDT-5m.feather`、`ETH_USDT-30m.feather` 等。
> 数据默认保存在 `user_data/data/binance/` 目录下。

# 回测策略
```sh
# 回测 MACDStrategy_crossed 策略（使用 30m 时间周期）
# --timeframe 会覆盖策略中定义的 timeframe
freqtrade backtesting --strategy MACDStrategy_crossed \
    --strategy-path user_data/strategies/berlinguyinca \
    --timeframe 30m \
    --timerange 20250101-20260206 \
    -p ETH/USDT

# cp user_data/strategies/berlinguyinca/MACDStrategy_crossed.py user_data/strategies/berlinguyinca_MACDStrategy_crossed.py
freqtrade backtesting --strategy berlinguyinca_MACDStrategy_crossed \
    --timeframe 30m \
    --timerange 20250101-20260206 \
    -p ETH/USDT
```

# 启动 Web UI 查看回测结果
```sh
# 启动 webserver 模式（推荐方式）
# 启动后访问 http://127.0.0.1:8080，可在 UI 中：
# - Load Results
# - 运行回测
# - 查看每笔交易的买卖点和持仓详情
# - 查看 K 线图和指标

# 注意：http://127.0.0.1:8080/backtest 只支持从 user_data/strategies 加载 strategy，不支持子目录。可以将子目录中的 strategy 拷贝到 user_data/strategies
freqtrade webserver
```

> 注：首次使用需要在 config.json 中配置 api_server，参考 docs/rest-api.md

# 回测 ChanMacd1 策略（MACD 背离分仓滚动）
```sh
# ChanMacd1 策略说明：
# - 底背离 + 金叉 → 买入部分仓位
# - 顶背离 + 死叉 → 卖出部分仓位
# - 分 10 次买入/卖出，滚动操作
# - 不设止损，不设 ROI 止盈

freqtrade backtesting --strategy ChanMacd1 \
    --timerange 20250101-20260206 \
    -p ETH/USDT
```
