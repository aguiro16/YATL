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

    # تفاصيل الإشارات الخاسرة
    losing_details = ""
    for s in losing:
        try:
            sent_at  = __import__('datetime').datetime.fromisoformat(s["sent_at"])
            closed_at = __import__('datetime').datetime.fromisoformat(s["closed_at"])
            hours = int((closed_at - sent_at).total_seconds() // 3600)
        except Exception:
            hours = "؟"

        losing_details += (
            f"\n❌ {s['symbol']}\n"
            f"   - قوة القناة: {s.get('channel_strength', '؟')}%\n"
            f"   - RR: {s.get('rr', '؟')}\n"
            f"   - سعر الدخول: {s.get('entry_price', '؟')}\n"
            f"   - Stop عند: {s.get('stop', '؟')}\n"
            f"   - خسارة: {s.get('profit_pct', '؟')}%\n"
            f"   - مدة الصفقة: {hours} ساعة\n"
        )

    # تفاصيل الإشارات الرابحة
    winning_details = ""
    for s in winning:
        try:
            sent_at   = __import__('datetime').datetime.fromisoformat(s["sent_at"])
            closed_at = __import__('datetime').datetime.fromisoformat(s["closed_at"])
            hours = int((closed_at - sent_at).total_seconds() // 3600)
        except Exception:
            hours = "؟"

        winning_details += (
            f"\n✅ {s['symbol']}\n"
            f"   - قوة القناة: {s.get('channel_strength', '؟')}%\n"
            f"   - RR: {s.get('rr', '؟')}\n"
            f"   - سعر الدخول: {s.get('entry_price', '؟')}\n"
            f"   - T1 عند: {s.get('t1', '؟')}\n"
            f"   - ربح: {s.get('profit_pct', '؟')}%\n"
            f"   - مدة الصفقة: {hours} ساعة\n"
        )

    return f"""
أنت محلل تداول خبير ومتخصص في استراتيجيات SMC والقنوات السعرية.
لديك نتائج بوت إشارات على Binance Futures خلال الأسبوع الماضي.

━━━━━━━━━━━━━━━━━━━
📊 الإحصائيات العامة:
━━━━━━━━━━━━━━━━━━━
- إجمالي الإشارات: {total}
- إشارات رابحة: {wins} ({winrate}%)
- إشارات خاسرة: {losses}
- متوسط الربح: {avg_profit}%
- متوسط الخسارة: {avg_loss}%

━━━━━━━━━━━━━━━━━━━
❌ تفاصيل الإشارات الخاسرة:
━━━━━━━━━━━━━━━━━━━
{losing_details if losing_details else "لا يوجد"}

━━━━━━━━━━━━━━━━━━━
✅ تفاصيل الإشارات الرابحة:
━━━━━━━━━━━━━━━━━━━
{winning_details if winning_details else "لا يوجد"}

━━━━━━━━━━━━━━━━━━━
⚙️ معاملات الاستراتيجية الحالية:
━━━━━━━━━━━━━━━━━━━
- كشف القناة الهابطة على 4H
- الحد الأدنى لقوة القناة: 55%
- السعر يجب أن يكون قرب قاع القناة (±5%)
- مناطق الدعم والمقاومة من الإطار اليومي 1D
- 5 أهداف من المستويات التاريخية
- Stop = الدعم التالي تحت Buy Zone
- الحد الأدنى للـ RR: 1.2

━━━━━━━━━━━━━━━━━━━
المطلوب:
━━━━━━━━━━━━━━━━━━━
1. هل هناك نمط مشترك بين الإشارات الخاسرة؟
   (قوة قناة منخفضة؟ RR منخفض؟ مدة قصيرة؟)
2. هل هناك نمط مشترك بين الإشارات الرابحة؟
3. اقتراح 3 تعديلات محددة على معاملات الاستراتيجية مع القيم الجديدة المقترحة
4. خلاصة سريعة بجملتين

اكتب بالعربية وكن محدداً بالأرقام والقيم.
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
        "max_tokens": 1500,
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
