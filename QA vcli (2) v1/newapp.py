import finnhub
import time
import os

API_KEY = os.environ.get("FINNHUB_API_KEY")
if not API_KEY:
    raise ValueError("FINNHUB_API_KEY environment variable is not set")

client = finnhub.Client(api_key=API_KEY)


def get_stock_data(ticker):
    try:
        quote = client.quote(ticker)

        current_price = quote["c"]  # Current price
        high = quote["h"]           # High of day
        low = quote["l"]            # Low of day
        open_price = quote["o"]     # Open
        previous_close = quote["pc"]

        return {
            "price": current_price,
            "high": high,
            "low": low,
            "open": open_price,
            "previous_close": previous_close,
        }

    except Exception as e:
        print("Error:", e)
        return None


if __name__ == "__main__":
    ticker = input("Ticker: ").upper()

    while True:
        data = get_stock_data(ticker)

        if data:
            print(
                f"{ticker} | "
                f"Price: {data['price']} | "
                f"High: {data['high']} | "
                f"Low: {data['low']}"
            )
        else:
            print("No data.")

        time.sleep(1)