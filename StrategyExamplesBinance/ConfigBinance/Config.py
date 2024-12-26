# How to get Binance API Token:
# 1. Register your account at Binance https://www.binance.com/?ref=CPA_004RZBKQWK
# 2. Go to "API Management" https://www.binance.com/en/my/settings/api-management?ref=CPA_004RZBKQWK
# 3. Then push the button "Create API" and select "System generated"
# 4. In "API restrictions" enable "Enable Spot & Margin Trading"
# 5. Copy & Paste here "API Key" and "Secret Key"
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# P.S. If you use my referral link - Thanks a lot))
# If you liked this software => Put a star on github - https://github.com/alimohyudin/backtrader_binance_futures
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
    TESTNET = os.getenv("TESTNET") == '1'
