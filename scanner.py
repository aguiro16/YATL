import asyncio
import aiohttp
import logging
from fetcher import get_top_futures_pairs, get_klines
from strategy import analyze_pair
from telegram_sender import send_telegram, send_startup_message, format_signal
from database import save_signal

sent_signals: set = set()

SCAN_INTERVAL_SECONDS = 4 * 60 * 60
MAX_PAIRS_PER_SCAN = 80
DELAY_BETWEEN_PAIRS = 0.3


async def scan_once(session: aiohttp.ClientSession):
    global sent_signals

    logging.info("🔍 Starting scan...")
    pairs = await get_top_futures_pairs(session, limit=MAX_PAIRS_PER_SCAN)
    signals_found = 0

    for symbol in pairs:
        try:
            df_4h = await get_klines(session, symbol, "4h", limit=100)
            await asyncio.sleep(DELAY_BETWEEN_PAIRS)
            df_1d = await get_klines(session, symbol, "1d", limit=100)
            await asyncio.sleep(DELAY_BETWEEN_PAIRS)

            result = analyze_pair(df_4h, df_1d, symbol)

            if result and symbol not in sent_signals:
                message = format_signal(result)
                success = await send_telegram(session, message)
                if success:
                    save_signal(result)
                    sent_signals.add(symbol)
                    signals_found += 1
                    logging.info(f"📡 Signal sent: {symbol}")
                    await asyncio.sleep(2)

        except Exception as e:
            logging.warning(f"Error processing {symbol}: {e}")
            continue

    logging.info(f"✅ Scan done. Signals found: {signals_found}")
    sent_signals.clear()


async def run_scanner():
    async with aiohttp.ClientSession() as session:
        await send_startup_message(session)

        while True:
            try:
                await scan_once(session)
            except Exception as e:
                logging.error(f"Scanner error: {e}")

            logging.info("⏳ Sleeping 4 hours...")
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)
