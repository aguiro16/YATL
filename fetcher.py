import aiohttp
import pandas as pd
import logging

BINANCE_FUTURES_BASE = "https://fapi.binance.com"


async def get_top_futures_pairs(session: aiohttp.ClientSession, limit: int = 80) -> list:
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/24hr"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            usdt_pairs = [
                d for d in data
                if d["symbol"].endswith("USDT") and float(d["quoteVolume"]) > 1_000_000
            ]
            sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x["quoteVolume"]), reverse=True)
            symbols = [p["symbol"] for p in sorted_pairs[:limit]]
            logging.info(f"✅ Found {len(symbols)} futures pairs")
            return symbols
    except Exception as e:
        logging.error(f"Error fetching pairs: {e}")
        return []


async def get_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
    limit: int = 100
) -> pd.DataFrame | None:
    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            df = pd.DataFrame(data, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            return df
    except Exception as e:
        logging.warning(f"Error fetching {symbol} {interval}: {e}")
        return None
