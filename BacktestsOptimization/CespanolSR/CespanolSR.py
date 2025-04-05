import backtrader as bt
import talib
import numpy as np  # Import NumPy

class CespanolSR(bt.Strategy):
    params = (
        ('pivot_length', 1),         # Number of bars to calculate pivot
        ('max_breaks', 1),           # Max breaks before invalidating S/R levels
        ('max_safe_orders', 0),      # Max number of safety orders
        ('price_deviation', 0.01),   # Price deviation for safety orders
        ('safe_order_scale', 1),     # Safety order volume scale
        ('safe_order_step_scale', 1),# Safety order step scale
        ('take_profit', 0.1),        # Take Profit percentage
        ('initial_capital', 10000),  # Initial capital
        ('max_dev', 0.0),            # Max deviation for safety orders
    )

    def __init__(self):
        self.sr_levels = []         # List to store support/resistance levels
        self.breaks = []            # Break count for each S/R level
        self.safety_orders = []     # Store safety orders for averaging
        self.entry_price = None     # Store entry price (initialized to None)
        self.deal_counter = 0       # Track the number of deals
        self.latest_price = None    # Latest close price
        self.bar_entry = None       # Bar index for entry
        self.safety_orders_level = None  # Last safety order price

    def next(self):
        # Get the current close price
        close = self.data.close[0]

        # Step 1: Calculate Support/Resistance (S/R) levels using pivot logic
        pivot = self.calculate_pivot()
        if pivot is not None:
            self.sr_levels.append(pivot)
            self.breaks.append(0)

        # Step 2: Evaluate entry conditions (Support/Resistance Test)
        if not self.position:  # If there's no existing position, set entry price
            self.entry_price = close  # Initialize entry price when opening a position

        if self.position:  # If there's an existing position
            if self.position.size > 0:  # Long position
                # Check if take profit should trigger
                self.check_take_profit()
            elif self.position.size < 0:  # Short position
                # Check for similar logic for short
                self.check_take_profit()

        # Step 3: Check for level tests (Support/Resistance tests)
        self.check_level_tests()

        # Step 4: Manage safety orders if position goes against us
        self.manage_safety_orders(close)

        # Step 5: Manage exits based on take profit
        if self.position and self.position.size > 0:
            self.check_exit_conditions()

    def calculate_pivot(self):
        # This is a placeholder logic for pivot point calculation
        # Replace this with actual S/R logic from PineScript
        high = np.array(self.data.high.get(size=self.p.pivot_length))  # Convert to NumPy array
        low = np.array(self.data.low.get(size=self.p.pivot_length))    # Convert to NumPy array
        close = np.array(self.data.close.get(size=self.p.pivot_length))  # Convert to NumPy array

        # Calculate ATR for dynamic calculation of fo and md
        atr20 = talib.ATR(high, low, close, timeperiod=20)

        # Calculate fo and md based on ATR
        fo = ((atr20[-1] / close[-1]) * 100) / 2  # Dynamic fo using ATR
        md = fo * 30  # Dynamic max distance

        pivot = (max(high) + min(low) + close[-1]) / 3  # Simple pivot formula
        return pivot

    def check_level_tests(self):
        # Logic to check for support/resistance tests
        for level in self.sr_levels:
            if self.data.close[0] > level:  # Above support
                self.buy()  # Long position
            elif self.data.close[0] < level:  # Below resistance
                self.sell()  # Short position

    def manage_safety_orders(self, close):
        # If there's an open position, manage safety orders
        if not self.position and self.p.max_safe_orders > 0:
            self.entry_price = close
            self.safety_orders_level = self.entry_price
            for i in range(1, self.p.max_safe_orders + 1):
                so_price = self.safety_order_price(i)
                self.buy(size=self.position.size * self.p.safe_order_scale)  # Adjust this as needed
                self.safety_orders.append(so_price)

    def safety_order_price(self, index):
        # Calculate the price for safety orders based on price deviation
        return self.entry_price * (1 - self.p.price_deviation * index)

    def check_exit_conditions(self):
        # Step 1: Check take profit
        take_profit_price = self.entry_price * (1 + self.p.take_profit)
        if self.position.size > 0 and self.data.close[0] >= take_profit_price:
            self.close()  # Exit position on take profit

    def check_take_profit(self):
        # Step 1: Check take profit
        take_profit_price = self.entry_price * (1 + self.p.take_profit)
        if self.position.size > 0 and self.data.close[0] >= take_profit_price:
            self.close()  # Exit position on take profit