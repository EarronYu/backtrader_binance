import datetime as dt
import backtrader as bt
from backtrader_binance_futures import BinanceStore
from ConfigBinance.Config import Config  # Configuration file


# Trading System
class RSIStrategy(bt.Strategy):
    """
    Live strategy demonstration with SMA, RSI indicators
    """
    params = (  # Parameters of the trading system
        ('coin_target', ''),
    )

    def __init__(self):
        """Initialization, adding indicators for each ticker"""
        
        self.orders = {}  # All orders as a dict, for this particularly trading strategy one ticker is one order
        for d in self.datas:  # Running through all the tickers
            print("2=======Init")
            self.orders[d._name] = None  # There is no order for ticker yet

        # creating indicators for each ticker
        self.sma1 = {}
        self.sma2 = {}
        self.rsi = {}
        for i in range(len(self.datas)):
            ticker = list(self.dnames.keys())[i]    # key name is ticker name
            self.sma1[ticker] = bt.indicators.SMA(self.datas[i], period=8)  # SMA indicator
            self.sma2[ticker] = bt.indicators.SMA(self.datas[i], period=16)  # SMA indicator
            self.rsi[ticker] = bt.indicators.RSI(self.datas[i], period=14)  # RSI indicator
        self.buy_once = {}
        self.sell_once = {}
        self.bought = False
        
        print("1=======Init")

    def start(self):
        for d in self.datas:  # Running through all the tickers
            self.buy_once[d._name] = False
            self.sell_once[d._name] = False

    def next(self):
        print("3=======Next")
        """Arrival of a new ticker candle"""
        for data in self.datas:  # Running through all the requested bars of all tickers
            ticker = data._name
            status = data._state  # 0 - Live data, 1 - History data, 2 - None

            if status in [0, 1]:
                if status: _state = "False - History data"
                else: _state = "True - Live data"

                # print('{} / {} [{}] - Open: {}, High: {}, Low: {}, Close: {}, Volume: {} - Live: {}'.format(
                #     bt.num2date(data.datetime[0]),
                #     data._name,
                #     _interval,  # ticker timeframe
                #     data.open[0],
                #     data.high[0],
                #     data.low[0],
                #     data.close[0],
                #     data.volume[0],
                #     _state,
                # ))
                # print(f'\t - {ticker} RSI : {self.rsi[ticker][0]}')

                # if status != 0: continue  # if not live - do not enter to position!

                # coin_target = self.p.coin_target
                # print(f"\t - Free balance: {self.broker.getcash()} {coin_target}")

                # Very slow function! Because we are going through API to get those values...
                symbol_balance, short_symbol_name = self.broker._store.get_symbol_balance(ticker)
                print(f"\t - {ticker} current balance = {symbol_balance} {short_symbol_name}")
                print(f'\t - {ticker} Price : {data.close[0]}')

                
                # print(f"\t - {ticker} position = {self.getposition(data)}")
                
                if not self.getposition(data):

                    if not self.buy_once[ticker]:  # Enter long
                        print(f"\t - Buy it by the market {data._name}... {(self.broker.getcash()-10)} - {self.data.close[0]}")
                        self.orders[data._name] = self.buy(size=(self.broker.getcash()-10) / self.data.close[0])
                        
                        self.buy_once[ticker] = len(self)  # prevent from second buy... writing the number of bar
                        # self.bought = True
                if self.bought:
                    print(f"\t - Sell it by the market {data._name}...")
                    self.close()  # close position

                # else:  # If there is a position
                    # print(self.sell_once[ticker], self.buy_once[ticker], len(self), len(self) > self.buy_once[ticker] + 3)
                    # if not self.sell_once[ticker]:  # if we are selling first time
                    #     if self.buy_once[ticker] and len(self) > self.buy_once[ticker] + 3:  # if we have position sell after 3 bars by market
                    #         print("sell")
                    #         print(f"\t - Sell it by the market {data._name}...")
                    #         self.orders[data._name] = self.close()  # Request to close a position at the market price

                    #         self.sell_once[ticker] = True  # to prevent sell second time

    def notify_order(self, order):
        """Changing the status of the order"""
        print("4=======Notify Order")
        print(order.size)
        order_data_name = order.data._name  # Name of ticker from order
        self.log(f'Order number {order.ref} {order.info["order_number"]} {order.getstatusname()} {"Buy" if order.isbuy() else "Sell"} {order_data_name} {order.size} @ {order.price}')
        if order.status == bt.Order.Completed:  # If the order is fully executed
            if order.isbuy():  # The order to buy
                print("Buy order completed")
                print(self.orders[data._name].binance_order)  # order.executed.price, order.executed.value, order.executed.comm - you can get from here
                self.log(f'Buy {order_data_name} @{order.executed.price:.2f}, Price {order.executed.value:.2f}, Commission {order.executed.comm:.2f}')
                # self.bought = True
            else:  # The order to sell
                print("Sell order completed")
                self.log(f'Sell {order_data_name} @{order.executed.price:.2f}, Price {order.executed.value:.2f}, Commission {order.executed.comm:.2f}')
                self.orders[order_data_name] = None  # Reset the order to enter the position - in case of linked buy
            # self.orders[order_data_name] = None  # Reset the order to enter the position

    def notify_trade(self, trade):
        """Changing the position status"""
        print("5=======Notify Trade")
        if trade.isclosed:  # If the position is closed
            self.log(f'Profit on a closed position {trade.getdataname()} Total={trade.pnl:.2f}, No commission={trade.pnlcomm:.2f}')

    def log(self, txt, dt=None):
        """Print string with date to the console"""
        dt = bt.num2date(self.datas[0].datetime[0]) if not dt else dt  # date or date of the current bar
        print(f'{dt.strftime("%d.%m.%Y %H:%M")}, {txt}')  # Print the date and time with the specified text to the console


if __name__ == '__main__':
    cerebro = bt.Cerebro(quicknotify=True)

    coin_target = 'USDT'  # the base ticker in which calculations will be performed
    symbol = 'BTC' + coin_target  # the ticker by which we will receive data in the format <CodeTickerBaseTicker>

    store = BinanceStore(
        api_key=Config.BINANCE_API_KEY,
        api_secret=Config.BINANCE_API_SECRET,
        coin_target=coin_target,
        testnet=Config.TESTNET)  # Binance Storage

    # live connection to Binance - for Offline comment these two lines
    broker = store.getbroker()
    cerebro.setbroker(broker)

    # Historical 1-minute bars for the last hour + new live bars / timeframe M1
    from_date = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=20)
    data = store.getdata(timeframe=bt.TimeFrame.Minutes, compression=1, dataname=symbol, start_date=from_date, LiveBars=True)

    cerebro.adddata(data)  # Adding data

    cerebro.addstrategy(RSIStrategy, coin_target=coin_target)  # Adding a trading system

    cerebro.run()  # Launching a trading system
    # cerebro.plot()  # Draw a chart
