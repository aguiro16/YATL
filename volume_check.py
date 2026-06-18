"""
سكريبت قراءة فقط (Read-Only) لفحص الفوليوم وقت دخول الصفقات الرابحة.
لا يتصل بأي API خاص بحسابك، ولا يفتح/يغلق أي صفقة.
يستخدم Binance Futures Public Klines endpoint فقط.
"""

import requests
import time
from datetime import datetime, timezone

# الصفقات المطلوب فحصها: (الرمز, sent_at ISO, manual_close)
TRADES = [
    ("ALLOUSDT", "2026-06-03T00:05:33.882611", True),
    ("LABUSDT",  "2026-06-06T08:05:02.887291", True),   # أول صفقة LAB
    ("LABUSDT",  "2026-06-11T15:30:20.896713", True),   # ثاني صفقة LAB
    ("OPGUSDT",  "2026-06-01T09:18:55.590640", False),
    ("MUUSDT",   "2026-06-06T08:04:53.586680", False),
    ("TAOUSDT",  "2026-06-05T08:07:51.483995", False),
    ("ONDOUSDT", "2026-06-03T16:13:34.079813", False),
]

BASE_URL = "https://fapi.binance.com/fapi/v1/klines"


def get_klines(symbol: str, interval: str, start_ms: int, limit: int = 50):
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "limit": limit,
    }
    r = requests.get(BASE_URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def analyze_trade(symbol: str, sent_at_iso: str, manual: bool):
    sent_dt = datetime.fromisoformat(sent_at_iso).replace(tzinfo=timezone.utc)
    sent_ms = int(sent_dt.timestamp() * 1000)

    lookback_ms = sent_ms - (30 * 4 * 60 * 60 * 1000)

    try:
        klines = get_klines(symbol, "4h", lookback_ms, limit=35)
    except Exception as e:
        print(f"  ⚠️ خطأ بجلب البيانات لـ {symbol}: {e}")
        return None

    if not klines or len(klines) < 5:
        print(f"  ⚠️ بيانات غير كافية لـ {symbol}")
        return None

    volumes = [float(k[7]) for k in klines]

    entry_candle = None
    for k in klines:
        if k[0] <= sent_ms:
            entry_candle = k
        else:
            break

    if entry_candle is None:
        entry_candle = klines[-1]

    entry_volume = float(entry_candle[7])

    other_volumes = [v for v in volumes if v != entry_volume]
    avg_volume = sum(other_volumes) / len(other_volumes) if other_volumes else 0

    ratio = (entry_volume / avg_volume) if avg_volume > 0 else 0

    return {
        "symbol": symbol,
        "manual": manual,
        "entry_volume_usdt": entry_volume,
        "avg_volume_usdt": avg_volume,
        "volume_ratio": ratio,
        "sent_at": sent_at_iso,
    }


def main():
    results = []
    print("جاري فحص الفوليوم لكل صفقة...\n")
    for symbol, sent_at, manual in TRADES:
        print(f"🔍 {symbol} ({'يدوي' if manual else 'آلي'}) — {sent_at}")
        res = analyze_trade(symbol, sent_at, manual)
        if res:
            results.append(res)
            print(f"   فوليوم الدخول: {res['entry_volume_usdt']:,.0f} USDT")
            print(f"   متوسط الفوليوم: {res['avg_volume_usdt']:,.0f} USDT")
            print(f"   النسبة: {res['volume_ratio']:.2f}x\n")
        time.sleep(0.3)

    print("=" * 60)
    print("📊 ملخص نهائي (مرتب من الأعلى نسبة فوليوم):")
    print("=" * 60)
    results.sort(key=lambda x: x["volume_ratio"], reverse=True)
    for r in results:
        tag = "👤 يدوي" if r["manual"] else "🤖 آلي"
        print(f"{r['symbol']:12} {tag:10} نسبة الفوليوم: {r['volume_ratio']:.2f}x")


if __name__ == "__main__":
    main()
