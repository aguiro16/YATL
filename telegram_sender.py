import aiohttp
import logging
import os

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "400815773")


def format_signal(signal: dict) -> str:
    symbol      = signal["symbol"].replace("USDT", "")
    buy_low, buy_high = signal["buy_zone"]
    targets     = signal["targets"]
    stop        = signal["stop"]
    rr          = signal["rr"]
    strength    = signal["channel_strength"]
    number      = signal.get("signal_number", "?")
    direction   = signal.get("direction", "LONG")
    signal_type = signal.get("signal_type", "BOTTOM")

    if direction == "LONG" and signal_type == "BREAKOUT":
        icon        = "🚀 🟢 LONG BREAKOUT"
        entry_label = "🔱 Buy"
        stop_label  = "🔴 STOP: اغلاق 4H أقل من"
    elif direction == "LONG":
        icon        = "✅ 🟢 LONG"
        entry_label = "🔱 Buy"
        stop_label  = "🔴 STOP: اغلاق 4H أقل من"
    else:
        icon        = "⚡ 🔴 SHORT"
        entry_label = "🔻 Sell"
        stop_label  = "🔴 STOP: اغلاق 4H أعلى من"

    msg = (
        f"#{number:03d} {icon} {symbol}/USDT\n\n"
        f"{entry_label}: {buy_low} - {buy_high}\n\n"
        f"Target 🎯:\n"
        f"T1: {targets.get('T1', '-')}\n"
        f"T2: {targets.get('T2', '-')}\n"
        f"T3: {targets.get('T3', '-')}\n"
        f"T4: {targets.get('T4', '-')}\n"
        f"T5: {targets.get('T5', '-')}\n\n"
        f"{stop_label} {stop}\n\n"
        f"📊 RR: {rr} | قوة القناة: {strength}%"
    )
    return msg


async def send_telegram(session: aiohttp.ClientSession, message: str) -> bool:
    if not TELEGRAM_TOKEN:
        logging.error("TELEGRAM_TOKEN not set!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text":    message,
        "parse_mode": "HTML"
    }
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                logging.info("✅ Signal sent to Telegram")
                return True
            else:
                logging.error(f"Telegram error: {resp.status}")
                return False
    except Exception as e:
        logging.error(f"Telegram send error: {e}")
        return False


async def send_startup_message(session: aiohttp.ClientSession):
    msg = "🤖 <b>F35 Signal Bot</b> started!\n📡 Scanning Long / Breakout / Short..."
    await send_telegram(session, msg)
