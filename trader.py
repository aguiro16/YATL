import logging
import os
from binance.client import Client
from binance.enums import *

BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TRADE_AMOUNT_USDT  = float(os.getenv("TRADE_AMOUNT_USDT", "100"))
LEVERAGE           = 1


def get_client() -> Client:
    return Client(BINANCE_API_KEY, BINANCE_API_SECRET)


def set_leverage(client: Client, symbol: str):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)
    except Exception as e:
        logging.warning(f"Leverage set error {symbol}: {e}")


def get_quantity(client: Client, symbol: str, usdt_amount: float) -> float:
    try:
        price     = float(client.futures_symbol_ticker(symbol=symbol)["price"])
        info      = client.futures_exchange_info()
        step_size = 0.001

        for s in info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])
                        break

        qty       = usdt_amount / price
        precision = len(str(step_size).rstrip("0").split(".")[-1])
        qty       = round(qty - (qty % step_size), precision)
        return qty
    except Exception as e:
        logging.error(f"Error calculating quantity {symbol}: {e}")
        return 0.0


def open_long(client: Client, symbol: str, stop: float, t1: float) -> bool:
    try:
        set_leverage(client, symbol)
        qty = get_quantity(client, symbol, TRADE_AMOUNT_USDT)
        if qty <= 0:
            return False

        # أمر الشراء
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY,
            type="MARKET",
            quantity=qty,
            positionSide="LONG"
        )
        logging.info(f"✅ LONG opened: {symbol} qty={qty}")

        # Stop Loss
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type="STOP_MARKET",
            stopPrice=round(stop, 8),
            closePosition=True,
            positionSide="LONG"
        )

        # Take Profit عند T1
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(t1, 8),
            closePosition=True,
            positionSide="LONG"
        )

        logging.info(f"📌 SL={stop} | TP={t1} set for {symbol}")
        return True

    except Exception as e:
        logging.error(f"Error opening LONG {symbol}: {e}")
        return False


def open_short(client: Client, symbol: str, stop: float, t1: float) -> bool:
    try:
        set_leverage(client, symbol)
        qty = get_quantity(client, symbol, TRADE_AMOUNT_USDT)
        if qty <= 0:
            return False

        # أمر البيع
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type="MARKET",
            quantity=qty,
            positionSide="SHORT"
        )
        logging.info(f"✅ SHORT opened: {symbol} qty={qty}")

        # Stop Loss
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY,
            type="STOP_MARKET",
            stopPrice=round(stop, 8),
            closePosition=True,
            positionSide="SHORT"
        )

        # Take Profit عند T1
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(t1, 8),
            closePosition=True,
            positionSide="SHORT"
        )

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

    client = get_client()

    if direction == "LONG":
        return open_long(client, symbol, stop, t1)
    else:
        return open_short(client, symbol, stop, t1)
