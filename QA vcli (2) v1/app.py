import yfinance as yf
import time


def GetStockData(ticker):
    stock = yf.Ticker(ticker)

    try:
        currentPrice = stock.fast_info["last_price"]
        print(f"Current price of {ticker}: {currentPrice}")
        return currentPrice

    except:
        print(f"No data available for {ticker}")
        return None


#if __name__ == "__main__":

    #tickerSymbol = input("Enter the stock ticker symbol: ").upper()

    #while True:
    #    price = GetStockData(tickerSymbol)

    #    if price:
    #        print("Live Trading Price:", price)
    #    else:
    #        print("No live data available.")

    #    time.sleep(0.25)