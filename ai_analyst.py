import aiohttp
import logging
import os

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


def build_analysis_prompt(signals: list) -> str:
    losing  = [s for s in signals if s["result"] == "LOSS"]
    winning = [s for s in signals if s["result"] == "WIN"]

    total    = len(signals)
    wins     = len(winning)
    losses   = len(losing)
    winrate  = round(wins / total * 100, 1) if total > 0 else 0
    avg_profit = round(sum(s["profit_pct"] for s in winning) / wins, 2) if wins > 0 else 0
    avg_loss   = round(sum(s["profit_pct"] for s in losing) / losses, 2) if losses > 0 else 0
    losing_symbols = [s["symbol"] for s in losing]

    return f"""
أنت محلل تداول خبير. لديك نتائج بوت إشارات على Binance Futures خلال الأسبوع الماضي:

📊 الإحصائيات:
- إجمالي الإشارات: {total}
- إشارات رابحة: {wins} ({winrate}%)
- إشارات خاسرة: {losses}
- متوسط الربح: {avg_profit}%
- متوسط الخسارة: {avg_loss}%
- الأزواج الخاسرة: {', '.join(losing_symbols) if losing_symbols else 'لا يوجد'}

الاستراتيجية المستخدمة:
- كشف القناة الهابطة على 4H (R² > 55%)
- مناطق الدعم والمقاومة التاريخية على 1D
- 5 أهداف من المستويات التاريخية فوق الدخول
- Stop = الدعم التالي تحت Buy Zone
- شرط RR ≥ 1.2

المطلوب:
1. تحليل سبب الخسائر بناءً على البيانات
2. اقتراح 3 تحسينات محددة وقابلة للتطبيق على الكود
3. هل يجب رفع حد RR أو تغيير شروط الدخول؟
4. خلاصة سريعة

اكتب بالعربية وكن محدداً وعملياً.
""".strip()


async def analyze_with_ai(signals: list) -> str:
    if not ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY غير موجود."
    if not signals:
        return "📭 لا توجد إشارات مغلقة هذا الأسبوع."

    prompt = build_analysis_prompt(signals)
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                return data["content"][0]["text"]
    except Exception as e:
        logging.error(f"AI analysis error: {e}")
        return f"❌ خطأ في التحليل: {e}"
