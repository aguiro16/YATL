import asyncio
import aiohttp
import logging
from datetime import datetime, timezone
from database import get_signals_last_days, get_open_signals, close_signal
from ai_analyst import analyze_with_ai
from telegram_sender import send_telegram
from fetcher import get_klines


async def check_and_close_signals(session: aiohttp.ClientSession):
    open_signals = get_open_signals()
    if not open_signals:
        return

    for sig in open_signals:
        try:
            df = await get_klines(session, sig["symbol"], "4h", limit=5)
            if df is None:
                continue

            current_price = df["close"].iloc[-1]
            low_4h        = df["low"].iloc[-1]

            # ضرب Stop
            if low_4h < sig["stop"]:
                profit_pct = round(
                    (sig["stop"] - sig["entry_price"]) / sig["entry_price"] * 100, 2
                )
                close_signal(sig["id"], "LOSS", profit_pct, 0)
                logging.info(f"❌ STOP hit: {sig['symbol']}")

            # وصل T1
            elif current_price >= sig["t1"]:
                profit_pct = round(
                    (sig["t1"] - sig["entry_price"]) / sig["entry_price"] * 100, 2
                )
                close_signal(sig["id"], "WIN", profit_pct, 1)
                logging.info(f"✅ T1 hit: {sig['symbol']}")

        except Exception as e:
            logging.warning(f"Error checking {sig['symbol']}: {e}")


def build_daily_report(signals: list) -> str:
    if not signals:
        return "📋 التقرير اليومي\n\nلا توجد إشارات مغلقة اليوم."

    total        = len(signals)
    wins         = len([s for s in signals if s["result"] == "WIN"])
    losses       = len([s for s in signals if s["result"] == "LOSS"])
    winrate      = round(wins / total * 100, 1) if total > 0 else 0
    total_profit = round(sum(s["profit_pct"] for s in signals), 2)

    lines = [
        f"📋 التقرير اليومي — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"",
        f"✅ رابح: {wins} | ❌ خاسر: {losses} | نسبة الفوز: {winrate}%",
        f"💰 مجموع الربح/الخسارة: {total_profit:+.2f}%",
        f"",
        "التفاصيل:",
    ]
    for s in signals:
        icon = "✅" if s["result"] == "WIN" else "❌"
        lines.append(f"{icon} {s['symbol']} → {s['profit_pct']:+.2f}%")

    return "\n".join(lines)


def build_weekly_report(signals: list) -> str:
    if not signals:
        return "📊 التقرير الأسبوعي\n\nلا توجد إشارات مغلقة هذا الأسبوع."

    total        = len(signals)
    wins         = len([s for s in signals if s["result"] == "WIN"])
    losses       = len([s for s in signals if s["result"] == "LOSS"])
    winrate      = round(wins / total * 100, 1) if total > 0 else 0
    total_profit = round(sum(s["profit_pct"] for s in signals), 2)
    best         = max(signals, key=lambda x: x["profit_pct"])
    worst        = min(signals, key=lambda x: x["profit_pct"])

    lines = [
        f"📊 التقرير الأسبوعي",
        f"",
        f"إجمالي الإشارات: {total}",
        f"✅ رابح: {wins} ({winrate}%)",
        f"❌ خاسر: {losses}",
        f"💰 صافي الربح: {total_profit:+.2f}%",
        f"🏆 أفضل صفقة: {best['symbol']} ({best['profit_pct']:+.2f}%)",
        f"💀 أسوأ صفقة: {worst['symbol']} ({worst['profit_pct']:+.2f}%)",
    ]
    return "\n".join(lines)


async def run_reporter():
    """
    كل 30 دقيقة: يتحقق من الإشارات المفتوحة
    08:00 UTC يومياً (= 11:00 AM السعودية): تقرير يومي
    كل جمعة 08:00 UTC: تقرير أسبوعي + تحليل AI
    """
    sent_daily_today  = None
    sent_weekly_today = None

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                now = datetime.now(timezone.utc)

                await check_and_close_signals(session)

                # تقرير يومي
                if now.hour == 8 and sent_daily_today != now.date():
                    signals_today = get_signals_last_days(1)
                    report = build_daily_report(signals_today)
                    await send_telegram(session, report)
                    sent_daily_today = now.date()
                    logging.info("📋 Daily report sent")

                # تقرير أسبوعي كل جمعة
                if now.weekday() == 4 and now.hour == 8 and sent_weekly_today != now.date():
                    signals_week = get_signals_last_days(7)
                    weekly = build_weekly_report(signals_week)
                    await send_telegram(session, weekly)
                    await asyncio.sleep(3)

                    ai_report = await analyze_with_ai(signals_week)
                    await send_telegram(session, f"🤖 تحليل AI:\n\n{ai_report}")
                    sent_weekly_today = now.date()
                    logging.info("📊 Weekly report + AI sent")

            except Exception as e:
                logging.error(f"Reporter error: {e}")

            await asyncio.sleep(30 * 60)
