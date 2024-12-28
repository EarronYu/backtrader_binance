# backtrader_binance_futures
Binance API integration with [Backtrader](https://github.com/mementum/backtrader).

With this integration you can do:
 - Backtesting your strategy on historical data from the exchange [Binance](https://accounts.binance.com/register?ref=200640624 ) + [Backtrader](https://github.com/mementum/backtrader )  // Backtesting 
 - Launch trading systems for automatic trading on the exchange [Binance](https://accounts.binance.com/register?ref=200640624) + [Backtrader](https://github.com/mementum/backtrader ) // Live trading
 - Download historical data for cryptocurrencies from the exchange [Binance](https://accounts.binance.com/register?ref=200640624)

For API connection we are using library [python-binance](https://github.com/sammchardy/python-binance).

**You can say Thanks:**

USDT (Tron TRC20): TUCBDgNBt8VwRjS5fWhx8bfKxqgNN1hRmF

or by [**Binance**](https://accounts.binance.com/register?ref=200640624 ) **ID** **200640624** through the exchange (no commission)

## Installation
1) The simplest way:
```shell
pip install backtrader_binance_futures
```
or
```shell
git clone https://github.com/alimohyudin/backtrader_binance_futures
```
or
```shell
pip install git+https://github.com/alimohyudin/backtrader_binance_futures.git
```

2) Please use backtrader from my repository (as your can push your commits in it). Install it:
```shell
pip install git+https://github.com/mementum/backtrader.git
```
-- Can I use your binance interface with original backtrader?

-- Yes, you can use original backtrader, as the author of original backtrader had approved all my changes. 

Here is the link: [mementum/backtrader#472](https://github.com/mementum/backtrader/pull/472)

3) We have some dependencies, you need to install them: 
```shell
pip install python-binance backtrader pandas matplotlib
```

or

```shell
pip install -r requirements.txt
```

### Getting started
To make it easier to figure out how everything works, many examples have been made in the folders **DataExamplesBinance** and **StrategyExamplesBinance**.

Before running the example, you need to get your API key and Secret key, and put them in the file **ConfigBinance\Config.py:**

```python
# content of ConfigBinance\Config.py 
class Config:
    BINANCE_API_KEY = "YOUR_API_KEY"
    BINANCE_API_SECRET = "YOUR_SECRET_KEY"
```

#### How to get a Binance API token:
1. Register your account on [Binance](https://accounts.binance.com/register?ref=200640624 )
2. Go to the ["API Management"](https://www.binance.com/en/my/settings/api-management?ref=CPA_004RZBKQWK ) 
3. Then click the "Create API" button and select "System Generated".
4. In the "API Restrictions" section, enable "Enable Spot and Margin Trading".
5. Copy and paste to the file **ConfigBinance\Config.py ** received **"API key"** and **"Secret key"**

#### Now you can run examples

The **DataExamplesBinance** folder contains the code of examples for working with exchange data via the [Binance](https://accounts.binance.com/register?ref=200640624 ) API.

* **01 - Symbol.py** - trading strategy for obtaining historical and "live" data of one ticker for one timeframe
* **02 - Symbol data to DF.py** - export to csv file of historical data of one ticker for one timeframe
* **03 - Symbols.py** - trading strategy for multiple tickers on the same timeframe
* **04 - Resample.py** - trading strategy for obtaining data from one ticker for different timeframes by converting a smaller timeframe into a larger one
* **05 - Replay.py** - launching a trading strategy on a smaller timeframe, with processing on a larger one and displaying a larger interval chart
* **06 - Rollover.py** - launch of a trading strategy based on gluing data from a file with historical data and the last downloaded history from the broker
* **07 - Get Asset Balance.py** - getting the ticker balance directly through the Binance API
* **08 - Timeframes.py** - trading strategy is running on different timeframes.
* **09 - Get Asset Info.py** - getting info about asset: balance, lot size, min price step, min value to buy and etc.
* **09 - Get Asset Info - no Decimal.py** - getting info about asset: balance, lot size, min price step, min value to buy and etc.
* **09 - Get Asset Info - through client.py** - getting info about asset: balance, lot size, min price step, min value to buy and etc.
* **10 - Get Historical Data.py** - getting historical data through binance client for asset.
* **Strategy.py** - An example of a trading strategy that only outputs data of the OHLCV for ticker/tickers

The **StrategyExamplesBinance** folder contains the code of sample strategies.

* **01 - Live Trade - Just Buy and Sell.py** - An example of a live trading strategy for ETH ticker on the base USDT ticker.
  * The strategy shows how to Buy at Market or Limit order and how to Cancel order.
  * Example of placing and cancel orders on the Binance exchange.
    * Please be aware! This is Live order - if market has a big change down in value of price more than 5% - the order will be completed....
    * Please be aware! For Market order - it will be completed!
    * **Do not forget to cancel the submitted orders from the exchange after the test!**

 
* **01 - Live Trade.py** - An example of a live trading strategy for two BTC and ETH tickers on the base USDT ticker.
  * The strategy shows how to apply indicators (SMA, RSI) to several tickers at the same time.
  * Example of placing and cancel orders on the Binance exchange.
    * Please be aware! This is Live order - if market has a big change down in value of price more than 5% - the order will be completed.... 
    * **Do not forget to cancel the submitted orders from the exchange after the test!**


* **02 - Live Trade MultiPortfolio.py** - An example of a live trading strategy for a set of tickers that can be transferred to the strategy in a list (BTC, ETH, BNB) on the base USDT ticker.
  * The strategy shows how to apply indicators (SMA, RSI) to several tickers at the same time.
  * Example of placing and cancel orders on the Binance exchange.
    * Please be aware! This is Live order - if market has a big change down in value of price more than 5% - the order will be completed.... 
    * **Do not forget to cancel the submitted orders from the exchange after the test!**


* **03 - Live Trade ETH.py** - An example of a live trading strategy for two BNB and XMR tickers on the basic ETH ticker.
  * The strategy shows how to apply indicators (SMA, RSI) to several tickers at the same time.
  * Example of placing and cancel orders on the Binance exchange.
    * Please be aware! This is Live order - if market has a big change down in value of price more than 5% - the order will be completed.... 
    * **Do not forget to cancel the submitted orders from the exchange after the test!**


* **04 - Offline Backtest.py** - An example of a trading strategy on a historical data - not live mode - for two BTC and ETH tickers on the base USDT ticker.
  * The strategy shows how to apply indicators (SMA, RSI) to several tickers at the same time.
    * Not a live mode - for testing strategies without sending orders to the exchange!


* **05 - Offline Backtest MultiPortfolio.py** - An example of a trading strategy on a historical data - not live mode - for a set of tickers that can be transferred to the strategy in a list (BTC, ETH, BNB) on the base USDT ticker.
  * The strategy shows how to apply indicators (SMA, RSI) to several tickers at the same time.
    * Not a live mode - for testing strategies without sending orders to the exchange!


* **06 - Live Trade Just Buy and Close by Market.py** - An example of a live trading strategy for ETH ticker on the base USDT ticker.
  * The strategy shows how to buy by close price and sell by market a little value of ETH after 3 bars.
  * Example of placing orders on the Binance exchange.
    * **Do not forget to cancel the submitted orders from the exchange after the test!**


* **07 - Offline Backtest Indicators.py** - An example of a trading strategy for a history test using SMA and RSI indicators - not live mode - for two BTC and ETH tickers on the base USDT ticker.
  * The strategy shows how to apply indicators (SMA, RSI) to several tickers at the same time.
    * generates 177% of revenue at the time of video recording))
    * Non-live mode - for testing strategies without sending orders to the exchange!


* **08 - Offline Backtest Margin Trade with Leverage 50x - Linear Trade.py** - An example of a trading strategy with the use of margin Leverage 50x for a history backtest using SMA indicators - not live mode - for two BTC and ETH tickers on the base of USDT ticker.
  * The strategy shows how to apply indicators SMA to several tickers at the same time.
    * generates 792% of revenue at the time of file publishing
    * Non-live mode - for testing strategies without sending orders to the exchange!
  * The strategy shows how to use margin with Leverage 50x for backtest on history market data for cryptocurrencies.
```commandline
$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
Was money: 2000.00
Ending Portfolio Value: 17853.46
Remaining available funds: 4887.38
Assets in the amount of: 12966.08

2000.00 ==> 17853.46 ==> +792.67%

SQN:  AutoOrderedDict([('sqn', 1.0031776139642996), ('trades', 4)])
VWR:  OrderedDict([('vwr', 25.613023915870777)])
TDD:  OrderedDict([('maxdrawdown', 65.77087178559279), ('maxdrawdownperiod', 304)])
DD:  AutoOrderedDict([('len', 6), ('drawdown', 20.46618403019286), ('moneydown', 229.70872494394746), ('max', AutoOrderedDict([('len', 304), ('drawdown', 65.77087178559279), ('moneydown', 295.8359186842)]))])
AR:  OrderedDict([(2021, 0.0), (2022, -0.42822236821405035), (2023, 4.540830244681184), (2024, 1.8176719585784271)])
Profitability:  OrderedDict([('rtot', 2.1890502317806253), ('ravg', 0.0022178827069712515), ('rnorm', 0.7487590850582526), ('rnorm100', 74.87590850582527)])
$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$
```

## Thanks
- backtrader: Very simple and cool library!
- [python-binance](https://github.com/sammchardy/python-binance): For creating Binance API wrapper, shortening a lot of work.
- lindomar-oliveira for some code

## License
[MIT](https://choosealicense.com/licenses/mit)

## Important
Error correction, revision and development of the library is carried out by the author and the community!

**Push your commits!**

## Terms of Use
The backtrader_binance_futures library, which allows you to integrate Backtrader and Binance API, is the **Program** created solely for the convenience of work.
When using the **Program**, the User is obliged to comply with the provisions of the current legislation of his country.
Using the **Program** are offered on an "AS IS" basis. No guarantees, either oral or written, are attached and are not provided.
The author and the community does not guarantee that all errors of the **Program** have been eliminated, respectively, the author and the community do not bear any responsibility for
the consequences of using the **Program**, including, but not limited to, any damage to equipment, computers, mobile devices,
User software caused by or related to the use of the **Program**, as well as for any financial losses
incurred by the User as a result of using the **Program**.
No one is responsible for data loss, losses, damages, including accidental or indirect, lost profits, loss of revenue or any other losses
related to the use of the **Program**.

The **Program** is distributed under the terms of the [MIT](https://choosealicense.com/licenses/mit ) license.

## Star History

Please put a Star 🌟 for this code

[![Star History Chart](https://api.star-history.com/svg?repos=WISEPLAT/backtrader_binance&type=Timeline)](https://star-history.com/#WISEPLAT/backtrader_binance&Timeline)