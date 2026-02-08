"""
chan_macd_1 - MACD 背离分仓滚动交易策略

=== 策略核心思想 ===
基于 MACD 底背离和顶背离进行分仓买卖：
- 底背离（价格创新低，MACD 未创新低）出现后，在金叉确认时买入部分仓位
- 顶背离（价格创新高，MACD 未创新高）出现后，在死叉确认时卖出部分仓位
- 每次只买入/卖出部分仓位，实现分仓滚动操作

=== MACD 背离原理 ===

底背离（Bullish Divergence）：
  - 在两段连续的 MACD < Signal 区间中（histogram < 0 的两段）
  - 价格低点越来越低（创新低），但 MACD 低点越来越高（未创新低）
  - 说明下跌动能在减弱，可能反弹
  - 当金叉出现时（MACD 上穿 Signal），确认底背离，触发买入

顶背离（Bearish Divergence）：
  - 在两段连续的 MACD > Signal 区间中（histogram > 0 的两段）
  - 价格高点越来越高（创新高），但 MACD 高点越来越低（未创新高）
  - 说明上涨动能在减弱，可能回调
  - 当死叉出现时（MACD 下穿 Signal），确认顶背离，触发卖出

=== 仓位管理 ===
- N_total：可买入的总次数（默认 10）
- 买入时：使用剩余资金的 1 / (N_total - N_bought)
- 卖出时：卖出持仓的 1 / N_bought

=== 风控 ===
- 不设止损
- 不设 ROI 止盈
- 完全依赖 MACD 背离信号决定买卖
"""

from datetime import datetime

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
from pandas import DataFrame

import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import logging


logger = logging.getLogger(__name__)


class ChanMacd1(IStrategy):
    """
    MACD 背离分仓滚动策略

    买入信号：MACD 底背离 + 金叉
    卖出信号：MACD 顶背离 + 死叉
    分仓操作：每次买入/卖出部分仓位
    """

    INTERFACE_VERSION: int = 3

    # === 不设止损（-0.99 表示价格跌去 99% 才触发，等于不设止损）===
    stoploss = -0.99

    # === 不使用 ROI 止盈（设为 100 即 10000% 收益才触发，等于不设止盈）===
    minimal_roi = {"0": 100}

    # === K线时间周期 ===
    timeframe = '30m'

    # === 市价单，确保第一时间成交 ===
    order_types = {
        'entry': 'market',
        'exit': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
    }

    # === 启用仓位调整（支持分仓买入和分仓卖出）===
    position_adjustment_enable = True

    # === 可买入总次数 ===
    n_total = 10

    # === 最大追加入场次数 = n_total - 1（第一次入场不算追加）===
    max_entry_position_adjustment = 9

    # === 需要足够的历史K线来计算 MACD 和检测背离 ===
    startup_candle_count = 100

    # === 不使用退出信号（通过 adjust_trade_position 管理卖出）===
    use_exit_signal = False

    # === 只在新K线产生时才重新计算指标 ===
    process_only_new_candles = True

    # === FreqUI 图表配置 ===
    plot_config = {
        'main_plot': {},
        'subplots': {
            'MACD': {
                'macd': {'color': 'blue'},
                'macdsignal': {'color': 'orange'},
            },
        }
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        计算技术指标：MACD + 背离检测

        参数:
            dataframe: 包含 OHLCV 数据的 DataFrame
            metadata: 交易对信息，如 {'pair': 'ETH/USDT'}
        """
        # 计算 MACD（默认参数：快线 EMA12，慢线 EMA26，信号线 EMA9）
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        # 在金叉/死叉处检测背离，生成买卖信号
        self._detect_divergence_signals(dataframe)

        return dataframe

    def _detect_divergence_signals(self, dataframe: DataFrame):
        """
        在每个金叉/死叉处，回溯检测是否存在 MACD 背离

        算法：
        1. 找到所有金叉点（MACD 上穿 Signal）
        2. 在每个金叉点，向前回溯找到刚结束的负 histogram 段（seg2）
        3. 继续回溯找到上一个负 histogram 段（seg1）
        4. 比较 seg1 和 seg2 的价格低点和 MACD 低点
        5. 如果价格创新低但 MACD 未创新低 → 底背离 → 买入信号

        死叉和顶背离的检测逻辑同理，方向相反。
        """
        macd_vals = dataframe['macd'].values
        hist = dataframe['macdhist'].values
        lows = dataframe['low'].values
        highs = dataframe['high'].values
        n = len(dataframe)

        # 检测金叉和死叉
        golden_cross = qtpylib.crossed_above(
            dataframe['macd'], dataframe['macdsignal']
        ).values
        death_cross = qtpylib.crossed_below(
            dataframe['macd'], dataframe['macdsignal']
        ).values

        buy_signal = np.zeros(n, dtype=bool)
        sell_signal = np.zeros(n, dtype=bool)

        for i in range(2, n):  # 从第3根K线开始（需要回溯空间）

            # === 在金叉处检测底背离 ===
            if golden_cross[i]:
                result = self._check_bullish_divergence(hist, macd_vals, lows, i)
                if result:
                    buy_signal[i] = True

            # === 在死叉处检测顶背离 ===
            if death_cross[i]:
                result = self._check_bearish_divergence(hist, macd_vals, highs, i)
                if result:
                    sell_signal[i] = True

        dataframe['buy_signal'] = buy_signal.astype(int)
        dataframe['sell_signal'] = sell_signal.astype(int)

    def _check_bullish_divergence(self, hist, macd_vals, lows, cross_idx):
        """
        在金叉点检查是否存在底背离

        回溯逻辑：
        golden_cross 发生在 cross_idx，意味着：
        - cross_idx:     hist > 0（MACD 上穿 Signal）
        - cross_idx - 1: hist <= 0（之前 MACD 在 Signal 下方）

        seg2: 从 cross_idx - 1 往前，连续 hist <= 0 的区间
        seg1: 跳过中间的正 histogram 段，找到前一个 hist <= 0 的区间
        """
        # 找到刚结束的负段 (seg2): 从 cross_idx - 1 往前找连续 hist <= 0
        seg2_end = cross_idx - 1
        if seg2_end < 0 or np.isnan(hist[seg2_end]):
            return False

        seg2_start = seg2_end
        while (seg2_start > 0
               and not np.isnan(hist[seg2_start - 1])
               and hist[seg2_start - 1] <= 0):
            seg2_start -= 1

        # 跳过中间的正段 (hist > 0)，找到前一个负段 (seg1)
        j = seg2_start - 1
        while j >= 0 and (np.isnan(hist[j]) or hist[j] > 0):
            j -= 1
        if j < 0:
            return False  # 没有找到前一个负段

        seg1_end = j
        seg1_start = seg1_end
        while (seg1_start > 0
               and not np.isnan(hist[seg1_start - 1])
               and hist[seg1_start - 1] <= 0):
            seg1_start -= 1

        # 比较两段的价格低点和 MACD 低点
        seg1_price_low = np.nanmin(lows[seg1_start:seg1_end + 1])
        seg2_price_low = np.nanmin(lows[seg2_start:seg2_end + 1])
        seg1_macd_low = np.nanmin(macd_vals[seg1_start:seg1_end + 1])
        seg2_macd_low = np.nanmin(macd_vals[seg2_start:seg2_end + 1])

        # 底背离：价格创新低，但 MACD 未创新低
        return seg2_price_low < seg1_price_low and seg2_macd_low > seg1_macd_low

    def _check_bearish_divergence(self, hist, macd_vals, highs, cross_idx):
        """
        在死叉点检查是否存在顶背离

        回溯逻辑：
        death_cross 发生在 cross_idx，意味着：
        - cross_idx:     hist < 0（MACD 下穿 Signal）
        - cross_idx - 1: hist >= 0（之前 MACD 在 Signal 上方）

        seg2: 从 cross_idx - 1 往前，连续 hist >= 0 的区间
        seg1: 跳过中间的负 histogram 段，找到前一个 hist >= 0 的区间
        """
        # 找到刚结束的正段 (seg2)
        seg2_end = cross_idx - 1
        if seg2_end < 0 or np.isnan(hist[seg2_end]):
            return False

        seg2_start = seg2_end
        while (seg2_start > 0
               and not np.isnan(hist[seg2_start - 1])
               and hist[seg2_start - 1] >= 0):
            seg2_start -= 1

        # 跳过中间的负段，找到前一个正段 (seg1)
        j = seg2_start - 1
        while j >= 0 and (np.isnan(hist[j]) or hist[j] < 0):
            j -= 1
        if j < 0:
            return False

        seg1_end = j
        seg1_start = seg1_end
        while (seg1_start > 0
               and not np.isnan(hist[seg1_start - 1])
               and hist[seg1_start - 1] >= 0):
            seg1_start -= 1

        # 比较两段的价格高点和 MACD 高点
        seg1_price_high = np.nanmax(highs[seg1_start:seg1_end + 1])
        seg2_price_high = np.nanmax(highs[seg2_start:seg2_end + 1])
        seg1_macd_high = np.nanmax(macd_vals[seg1_start:seg1_end + 1])
        seg2_macd_high = np.nanmax(macd_vals[seg2_start:seg2_end + 1])

        # 顶背离：价格创新高，但 MACD 未创新高
        return seg2_price_high > seg1_price_high and seg2_macd_high < seg1_macd_high

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        买入信号：MACD 底背离 + 金叉

        在金叉后的第1根K线开始时按市价买入
        （freqtrade 默认在信号K线的下一根K线开盘时执行）
        """
        dataframe.loc[
            dataframe['buy_signal'] == 1,
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        不使用常规退出信号
        卖出操作通过 adjust_trade_position 实现分仓卖出
        """
        return dataframe

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str,
                            **kwargs) -> float:
        """
        计算首次买入的资金量

        首次买入时 N_bought = 0，N_remaining_buy = N_total
        公式：C_current / N_remaining_buy = 可用资金 / 可买入总次数
        """
        available = self.wallets.get_free(self.config['stake_currency'])
        stake = available / self.n_total
        return stake

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float,
                              **kwargs) -> float | None | tuple[float | None, str | None]:
        """
        分仓滚动操作的核心逻辑

        在每根K线更新时被调用，检查是否需要追加买入或分批卖出。

        买入逻辑：
        - 当前K线有买入信号（底背离 + 金叉）
        - 且 N_bought < N_total
        - 买入金额 = C_current / N_remaining_buy

        卖出逻辑：
        - 当前K线有卖出信号（顶背离 + 死叉）
        - 且 N_bought > 0
        - 卖出金额（按 stake 计算）= trade.stake_amount / N_remaining_sell
          freqtrade 的部分卖出公式：
          实际卖出 token 数 = |返回值| * trade.amount / trade.stake_amount
          当返回 -trade.stake_amount / N 时，实际卖出 = trade.amount / N

        返回值：
        - 正数：追加买入的 stake 金额（USDT）
        - 负数：部分卖出的 stake 金额（USDT）
        - None：不操作
        """
        # 如果有未完成的订单，不操作（防止重复下单）
        if trade.has_open_orders:
            return None

        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if len(dataframe) < 1:
            return None

        last_candle = dataframe.iloc[-1]

        # 当前已买入次数 = 成功入场次数 - 成功离场次数
        n_bought = trade.nr_of_successful_entries - trade.nr_of_successful_exits

        # === 检查买入信号 ===
        if last_candle.get('buy_signal', 0) == 1 and n_bought < self.n_total:
            available = self.wallets.get_free(self.config['stake_currency'])
            n_remaining_buy = self.n_total - n_bought
            if n_remaining_buy > 0 and available > 0:
                stake = available / n_remaining_buy
                _min = min_stake if min_stake is not None else 0
                if stake >= _min:
                    logger.info(
                        f"分仓买入: {trade.pair} | "
                        f"N_bought={n_bought} → {n_bought + 1} | "
                        f"买入金额={stake:.2f} USDT"
                    )
                    return stake

        # === 检查卖出信号 ===
        if last_candle.get('sell_signal', 0) == 1 and n_bought > 0:
            n_remaining_sell = n_bought
            # 使用 trade.stake_amount 来计算卖出量
            # 返回 -trade.stake_amount / N_remaining_sell
            # freqtrade 会按公式计算实际卖出的 token 数:
            #   sell_amount = |return| * trade.amount / trade.stake_amount
            #              = (trade.stake_amount / N) * trade.amount / trade.stake_amount
            #              = trade.amount / N
            # 这正好是我们想要的：卖出当前持仓的 1/N
            sell_stake = trade.stake_amount / n_remaining_sell
            _min = min_stake if min_stake is not None else 0
            if sell_stake >= _min:
                logger.info(
                    f"分仓卖出: {trade.pair} | "
                    f"N_bought={n_bought} → {n_bought - 1} | "
                    f"卖出 stake={sell_stake:.2f} USDT | "
                    f"约 {trade.amount / n_remaining_sell:.6f} tokens"
                )
                return -sell_stake

        return None
