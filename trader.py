import logging
import os
import time
import hmac
import hashlib
import requests

BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TRADE_AMOUNT_USDT  = float(os.getenv("TRADE_AMOUNT_USDT", "100"))
BASE_URL           = "https://fapi.binance.com"


def sign(params: dict) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    sig   = hmac.new(
        BINANCE_API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()
    params["signature"] = sig
    return params


def headers() -> dict:
    return {"X-MBX-APIKEY": BINANCE_API_KEY}


def get_price(symbol: str) -> float:
    r = requests.get(f"{BASE_URL}/fapi/v1/ticker/price", params={"symbol": symbol})
    return float(r.json()["price"])


def get_step_size(symbol: str) -> float:
    r = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo")
    for s in r.json()["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    return float(f["stepSize"])
    return 0.001


def get_quantity(symbol: str, usdt_amount: float) -> float:
    try:
        price     = get_price(symbol)
        step_size = get_step_size(symbol)
        qty       = usdt_amount / price
        precision = len(str(step_size).rstrip("0").split(".")[-1])
        qty       = round(qty - (qty % step_size), precision)
        return qty
    except Exception as e:
        logging.error(f"Error calculating quantity {symbol}: {e}")
        return 0.0


def place_order(params: dict) -> dict:
    params["timestamp"] = int(time.time() * 1000)
    params = sign(params)
    r = requests.post(
        f"{BASE_URL}/fapi/v1/order",
        headers=headers(),
        params=params
    )
    return r.json()


def set_leverage(symbol: str, leverage: int = 1):
    params = {
        "symbol":    symbol,
        "leverage":  leverage,
        "timestamp": int(time.time() * 1000)
    }
    params = sign(params)
    requests.post(
        f"{BASE_URL}/fapi/v1/leverage",
        headers=headers(),
        params=params
    )


def open_long(symbol: str, stop: float, t1: float) -> bool:
    try:
        set_leverage(symbol, 1)
        qty = get_quantity(symbol, TRADE_AMOUNT_USDT)
        if qty <= 0:
            return False

        # أمر الشراء
        res = place_order({
            "symbol":       symbol,
            "side":         "BUY",
            "type":         "MARKET",
            "quantity":     qty,
            "positionSide": "LONG"
        })
        if "orderId" not in res:
            logging.error(f"LONG order failed: {res}")
            return False
        logging.info(f"✅ LONG opened: {symbol} qty={qty}")

        # Stop Loss
        place_order({
            "symbol":        symbol,
            "side":          "SELL",
            "type":          "STOP_MARKET",
            "stopPrice":     round(stop, 8),
            "closePosition": "true",
            "positionSide":  "LONG"
        })

        # Take Profit
        place_order({
            "symbol":        symbol,
            "side":          "SELL",
            "type":          "TAKE_PROFIT_MARKET",
            "stopPrice":     round(t1, 8),
            "closePosition": "true",
            "positionSide":  "LONG"
        })

        logging.info(f"📌 SL={stop} | TP={t1} set for {symbol}")
        return True

    except Exception as e:
        logging.error(f"Error opening LONG {symbol}: {e}")
        return False


def open_short(symbol: str, stop: float, t1: float) -> bool:
    try:
        set_leverage(symbol, 1)
        qty = get_quantity(symbol, TRADE_AMOUNT_USDT)
        if qty <= 0:
            return False

        # أمر البيع
        res = place_order({
            "symbol":       symbol,
            "side":         "SELL",
            "type":         "MARKET",
            "quantity":     qty,
            "positionSide": "SHORT"
        })
        if "orderId" not in res:
            logging.error(f"SHORT order failed: {res}")
            return False
        logging.info(f"✅ SHORT opened: {symbol} qty={qty}")

        # Stop Loss
        place_order({
            "symbol":        symbol,
            "side":          "BUY",
            "type":          "STOP_MARKET",
            "stopPrice":     round(stop, 8),
            "closePosition": "true",
            "positionSide":  "SHORT"
        })

        # Take Profit
        place_order({
            "symbol":        symbol,
            "side":          "BUY",
            "type":          "TAKE_PROFIT_MARKET",
            "stopPrice":     round(t1, 8),
            "closePosition": "true",
            "positionSide":  "SHORT"
        })

        logging.info(f"📌 SL={stop} | TP={t1} set for {symbol}")
        return True

    except Exception as e:
        logging.error(f"Error opening SHORT {symbol}: {e}")
        return False


def execute_signal(signal: dict) -> bool:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logging.error("BINANCE_API_KEY or BINANCE_API_SECRET not set!")
        return False

    symbol    = signal["symbol"]
    direction = signal.get("direction", "LONG")
    stop      = signal["stop"]
    t1        = signal["targets"].get("T1")

    if not t1:
        logging.error(f"No T1 for {symbol}")
        return False

    if direction == "LONG":
        return open_long(symbol, stop, t1)
    else:
        return open_short(symbol, stop, t1)
