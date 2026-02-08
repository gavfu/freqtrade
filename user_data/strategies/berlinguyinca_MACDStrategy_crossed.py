"""
MACDStrategy_crossed - 基于 MACD 交叉和 CCI 指标的交易策略

=== 策略核心思想 ===
这是一个结合两个技术指标的策略：
1. MACD (Moving Average Convergence Divergence) - 移动平均收敛发散指标
2. CCI (Commodity Channel Index) - 商品通道指数

MACD 用于判断趋势方向和买卖时机，CCI 用于确认市场是否处于超买/超卖状态。
两个指标配合使用，可以过滤掉一些虚假信号。

=== 买入条件 ===
- MACD 线从下向上穿越信号线（金叉，表示上升趋势开始）
- 同时 CCI < -50（表示市场处于相对超卖区域，价格可能被低估）

=== 卖出条件 ===
- MACD 线从上向下穿越信号线（死叉，表示下降趋势开始）
- 同时 CCI > 100（表示市场处于超买区域，价格可能被高估）

=== MACD 指标简介 ===
MACD 由三部分组成：
- macd 线：快速 EMA(12) - 慢速 EMA(26)
- signal 信号线：macd 线的 EMA(9)
- histogram 柱状图：macd - signal

当 macd 线上穿 signal 线时，称为"金叉"，是买入信号；
当 macd 线下穿 signal 线时，称为"死叉"，是卖出信号。

=== CCI 指标简介 ===
CCI 衡量当前价格与历史平均价格的偏离程度：
- CCI > 100：超买区域，价格可能过高
- CCI < -100：超卖区域，价格可能过低
- CCI 在 -100 到 100 之间：正常波动区域

本策略使用 CCI < -50 作为买入条件（轻度超卖），CCI > 100 作为卖出条件（超买）。
"""

# --- 必要的库，请勿删除 ---
from freqtrade.strategy import IStrategy
from typing import Dict, List
from functools import reduce
from pandas import DataFrame
# --------------------------------

import talib.abstract as ta  # TA-Lib：技术分析指标库
import freqtrade.vendor.qtpylib.indicators as qtpylib  # freqtrade 内置的指标工具


class berlinguyinca_MACDStrategy_crossed(IStrategy):
    """
    MACD 交叉策略

    买入信号：MACD 金叉 + CCI 超卖
    卖出信号：MACD 死叉 + CCI 超买
    """

    # 策略接口版本，当前最新版本是 3
    INTERFACE_VERSION: int = 3

    # === 最小 ROI (Return on Investment) 配置 ===
    # 这是一个基于持仓时间的止盈策略
    # 格式：{"持仓分钟数": 目标收益率}
    # 
    # 解读：
    # - 持仓 0 分钟起：如果盈利达到 5%，就卖出
    # - 持仓 20 分钟后：如果盈利达到 4%，就卖出
    # - 持仓 30 分钟后：如果盈利达到 3%，就卖出
    # - 持仓 60 分钟后：如果盈利达到 1%，就卖出
    # 
    # 这种递减的止盈设计思想是：持仓越久，对收益的期望越低，
    # 尽早落袋为安，避免利润回吐。
    minimal_roi = {
        "60":  0.01,  # 60分钟后，1% 收益即卖出
        "30":  0.03,  # 30分钟后，3% 收益即卖出
        "20":  0.04,  # 20分钟后，4% 收益即卖出
        "0":  0.05    # 开仓即刻，5% 收益即卖出
    }

    # === 止损配置 ===
    # -0.3 表示亏损 30% 时强制卖出，防止更大损失
    # 注意：这是一个相对保守的止损设置，30% 的亏损已经比较大了
    # 实际使用中可能需要根据市场波动性调整
    stoploss = -0.3

    # === K线时间周期 ===
    # 5m 表示使用 5 分钟 K 线数据
    # 常见选项：1m, 5m, 15m, 30m, 1h, 4h, 1d
    # 时间周期越短，交易越频繁，手续费成本越高
    timeframe = '5m'

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        计算技术指标

        这个方法在每根 K 线更新时被调用，用于计算所有需要的技术指标。
        计算出的指标会被添加到 dataframe 中，供后续的买卖判断使用。

        参数:
            dataframe: 包含 OHLCV 数据的 DataFrame
                      (Open开盘价, High最高价, Low最低价, Close收盘价, Volume成交量)
            metadata: 包含交易对信息的字典，如 {'pair': 'BTC/USDT'}

        返回:
            添加了指标列的 DataFrame
        """
        # 计算 MACD 指标
        # ta.MACD 返回一个包含三列的 DataFrame：macd, macdsignal, macdhist
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']              # MACD 主线
        dataframe['macdsignal'] = macd['macdsignal']  # MACD 信号线
        dataframe['macdhist'] = macd['macdhist']      # MACD 柱状图（本策略未使用）

        # 计算 CCI 指标（默认周期为 14）
        dataframe['cci'] = ta.CCI(dataframe)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        定义买入（做多）信号

        当满足条件时，将 'enter_long' 列设为 1，表示产生买入信号。
        freqtrade 会在下一根 K 线开盘时执行买入操作。

        参数:
            dataframe: 包含 OHLCV 和指标数据的 DataFrame
            metadata: 交易对信息

        返回:
            添加了 enter_long 信号列的 DataFrame
        """
        dataframe.loc[
            (
                # 条件1：MACD 金叉（MACD 线从下向上穿越信号线）
                qtpylib.crossed_above(dataframe['macd'], dataframe['macdsignal']) &
                # 条件2：CCI 处于超卖区域（< -50）
                # 这意味着价格相对历史均值偏低，可能存在反弹机会
                (dataframe['cci'] <= -50.0)
            ),
            'enter_long'] = 1  # 设置买入信号

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        定义卖出（平多）信号

        当满足条件时，将 'exit_long' 列设为 1，表示产生卖出信号。
        注意：即使没有触发这里的卖出信号，minimal_roi 和 stoploss 也可能触发卖出。

        参数:
            dataframe: 包含 OHLCV 和指标数据的 DataFrame
            metadata: 交易对信息

        返回:
            添加了 exit_long 信号列的 DataFrame
        """
        dataframe.loc[
            (
                # 条件1：MACD 死叉（MACD 线从上向下穿越信号线）
                qtpylib.crossed_below(dataframe['macd'], dataframe['macdsignal']) &
                # 条件2：CCI 处于超买区域（> 100）
                # 这意味着价格相对历史均值偏高，可能存在回调风险
                (dataframe['cci'] >= 100.0)
            ),
            'exit_long'] = 1  # 设置卖出信号

        return dataframe
