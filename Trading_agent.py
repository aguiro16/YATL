"""
AI Signals Bot — ملف واحد كامل
إشارات SMC + تتبع النتائج + تقرير يومي + تطوير ذاتي
"""
import ccxt
import pandas as pd
import json
import os
import time
import threading
import schedule
from datetime import datetime, date
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
import requests
import anthropic

BOT_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID       = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SIGNALS_FILE  = "signals_log.json"
STRATEGY_FILE = "strategy_config.json"

BOUNDS = {
    "min_confluence":        (4,     9,     int),
    "min_rr":                (1.5,   4.0,   float),
    "ob_lookback":           (10,    40,    int),
    "fvg_min_size":          (0.001, 0.006, float),
    "ote_low":               (0.5,   0.65,  float),
    "ote_high":              (0.75,  0.9,   float),
    "atr_sl_multiplier":     (1.0,   2.5,   float),
    "atr_tp1_multiplier":    (2.0,   6.0,   float),
    "atr_tp2_multiplier":    (3.5,   9.0,   float),
    "scan_interval_seconds": (300,   1800,  int),
}

exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "future"},
})


def load_config() -> dict:
    try:
        with open(STRATEGY_FILE) as f:
            return json.load(f)
    except Exception:
        return {
            "version": "1.0",
            "min_confluence": 6,
            "min_rr": 2.0,
            "ob_lookback": 20,
            "fvg_min_size": 0.002,
            "ote_low": 0.618,
            "ote_high": 0.786,
            "atr_sl_multiplier": 1.5,
            "atr_tp1_multiplier": 3.0,
            "atr_tp2_multiplier": 5.0,
            "scan_interval_seconds": 900,
            "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
        }


def save_config(cfg: dict):
    with open(STRATEGY_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def send_message(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[Telegram] SKIP: {text[:60]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"[Telegram] Error: {e}")


def send_signal(sig: dict):
    emoji  = "🟢" if sig["direction"] == "LONG" else "🔴"
    dir_ar = "شراء" if sig["direction"] == "LONG" else "بيع"
    send_message(
        f"{emoji} <b>{dir_ar} | {sig['symbol']}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 <b>دخول:</b>       {sig['entry']}\n"
        f"🛑 <b>وقف خسارة:</b> {sig['sl']}\n"
        f"✅ <b>هدف 1:</b>      {sig['tp1']}\n"
        f"🎯 <b>هدف 2:</b>      {sig['tp2']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📊 R:R = <b>{sig['rr']}x</b>  |  Score: <b>{sig['score']}/10</b>\n"
        f"⏰ {sig['time'][:16]} UTC\n"
        f"#{sig['symbol'].replace('/', '')} #SMC"
    )


def send_daily_report(report: dict):
    icon = "📈" if report["pnl_pct"] >= 0 else "📉"
    sign = "+" if report["pnl_pct"] >= 0 else ""
    send_message(
        f"{icon} <b>التقرير اليومي — {report['date']}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📤 إشارات أُرسلت: {report['total']}\n"
        f"✅ TP مُحقَّق:    {report['wins']}\n"
        f"❌ SL مُحقَّق:    {report['losses']}\n"
        f"⏳ مفتوحة:       {report['open']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📊 Win Rate:     {report['win_rate']:.1f}%\n"
        f"💵 PnL افتراضي:  {sign}{report['pnl_pct']:.2f}%\n"
        f"🔝 أفضل إشارة:  {report['best']}\n"
        f"⚠️ أسوأ إشارة:  {report['worst']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🤖 الاستراتيجية: v{report['version']}"
    )


def send_optimizer_update(version: str, reasoning: str, changes: list):
    changes_text = "\n".join(changes) if changes else "• لا تغييرات جوهرية"
    send_message(
        f"🧠 <b>تحديث الاستراتيجية → v{version}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔍 <b>التحليل:</b>\n{reasoning}\n\n"
        f"⚙️ <b>التغييرات:</b>\n{changes_text}"
    )


def load_signals() -> list:
    try:
        with open(SIGNALS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_signals(data: list):
    with open(SIGNALS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def log_signal(sig: dict):
    data = load_signals()
    data.append(sig)
    save_signals(data)


def fetch_df(symbol: str, timeframe: str) -> pd.DataFrame:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])
    df["ema20"] = EMAIndicator(df["close"], window=20).ema_indicator()
    df["ema50"] = EMAIndicator(df["close"], window=50).ema_indicator()
    df["atr"]   = AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()
    return df


def detect_structure(df: pd.DataFrame):
    highs = df["high"].rolling(5).max()
    lows  = df["low"].rolling(5).min()
    return (
        df["close"].iloc[-1] > highs.iloc[-2],
        df["close"].iloc[-1] < lows.iloc[-2]
    )


def find_order_blocks(df: pd.DataFrame, lookback: int) -> list:
    obs = []
    for i in range(-lookback, -2):
        c, nc = df.iloc[i], df.iloc[i + 1]
        if c["close"] < c["open"] and nc["close"] > nc["open"]:
            obs.append({"type": "bullish", "high": c["high"], "low": c["low"]})
        elif c["close"] > c["open"] and nc["close"] < nc["open"]:
            obs.append({"type": "bearish", "high": c["high"], "low": c["low"]})
    return obs


def find_fvg(df: pd.DataFrame, min_size: float) -> list:
    fvgs = []
    for i in range(2, len(df) - 1):
        c1, c2, c3 = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]
        if (c3["low"] - c1["high"]) / c2["close"] > min_size:
            fvgs.append({"type": "bullish"})
        if (c1["low"] - c3["high"]) / c2["close"] > min_size:
            fvgs.append({"type": "bearish"})
    return fvgs


def in_ote(price: float, swing_h: float, swing_l: float, cfg: dict) -> bool:
    rng = swing_h - swing_l
    if rng == 0:
        return False
    return (swing_h - rng * cfg["ote_high"]) <= price <= (swing_h - rng * cfg["ote_low"])


def calc_levels(price: float, direction: str, atr: float, cfg: dict):
    s, t1, t2 = cfg["atr_sl_multiplier"], cfg["atr_tp1_multiplier"], cfg["atr_tp2_multiplier"]
    if direction == "LONG":
        sl, tp1, tp2 = price - atr * s, price + atr * t1, price + atr * t2
    else:
        sl, tp1, tp2 = price + atr * s, price - atr * t1, price - atr * t2
    rr = round(abs(tp1 - price) / max(abs(price - sl), 1e-9), 2)
    return sl, tp1, tp2, rr


def fmt(val: float, symbol: str) -> str:
    if "BTC" in symbol: return f"{val:,.1f}"
    if val >= 100:       return f"{val:.2f}"
    return f"{val:.4f}"


def analyze(symbol: str, cfg: dict) -> list:
    try:
        df4h = fetch_df(symbol, "4h")
        df1h = fetch_df(symbol, "1h")
        df15 = fetch_df(symbol, "15m")

        price  = df15["close"].iloc[-1]
        atr    = df15["atr"].iloc[-1]
        bull4h, bear4h = detect_structure(df4h)
        bull1h, bear1h = detect_structure(df1h)

        if   bull4h and not bear4h: direction = "LONG"
        elif bear4h and not bull4h: direction = "SHORT"
        else: return []

        obs     = find_order_blocks(df1h, cfg["ob_lookback"])
        fvgs    = find_fvg(df15, cfg["fvg_min_size"])
        swing_h = df4h["high"].rolling(20).max().iloc[-1]
        swing_l = df4h["low"].rolling(20).min().iloc[-1]

        score = 0
        if (direction == "LONG" and bull4h) or (direction == "SHORT" and bear4h): score += 2
        if (direction == "LONG" and bull1h) or (direction == "SHORT" and bear1h): score += 2
        if direction == "LONG"  and df4h["ema20"].iloc[-1] > df4h["ema50"].iloc[-1]: score += 1
        if direction == "SHORT" and df4h["ema20"].iloc[-1] < df4h["ema50"].iloc[-1]: score += 1
        for ob in obs:
            if ob["type"] == direction.lower() and ob["low"] <= price <= ob["high"]:
                score += 2; break
        if any(f["type"] == direction.lower() for f in fvgs): score += 1
        if in_ote(price, swing_h, swing_l, cfg): score += 1

        if score < cfg["min_confluence"]: return []

        sl, tp1, tp2, rr = calc_levels(price, direction, atr, cfg)
        if rr < cfg["min_rr"]: return []

        return [{
            "symbol":     symbol,
            "direction":  direction,
            "entry":      fmt(price, symbol),
            "sl":         fmt(sl, symbol),
            "tp1":        fmt(tp1, symbol),
            "tp2":        fmt(tp2, symbol),
            "entry_raw":  round(price, 6),
            "sl_raw":     round(sl, 6),
            "tp1_raw":    round(tp1, 6),
            "rr":         rr,
            "score":      score,
            "version":    cfg.get("version", "1.0"),
            "time":       datetime.utcnow().isoformat(),
            "date":       datetime.utcnow().strftime("%Y-%m-%d"),
            "result":     None,
            "result_pct": None,
        }]
    except Exception as e:
        print(f"[Bot] Error {symbol}: {e}")
        return []


def run_bot():
    print("[Bot] Started")
    while True:
        cfg = load_config()
        for sym in cfg.get("symbols", []):
            for sig in analyze(sym, cfg):
                send_signal(sig)
                log_signal(sig)
                print(f"[Bot] ✅ {sig['direction']} {sig['symbol']} score={sig['score']} rr={sig['rr']}")
            time.sleep(1)
        time.sleep(cfg.get("scan_interval_seconds", 900))


def hours_since(iso_time: str) -> float:
    try:
        return (datetime.utcnow() - datetime.fromisoformat(iso_time)).total_seconds() / 3600
    except Exception:
        return 0


def run_tracker():
    print("[Tracker] Started")
    while True:
        signals = load_signals()
        changed = False
        for sig in signals:
            if sig.get("result") is not None:
                continue
            try:
                price = exchange.fetch_ticker(sig["symbol"])["last"]
            except Exception:
                continue

            d     = sig["direction"]
            entry = sig["entry_raw"]
            sl    = sig["sl_raw"]
            tp1   = sig["tp1_raw"]

            if   d == "LONG"  and price >= tp1:
                sig["result"] = "win";  sig["result_pct"] = round((tp1 - entry) / entry * 100, 2)
            elif d == "SHORT" and price <= tp1:
                sig["result"] = "win";  sig["result_pct"] = round((entry - tp1) / entry * 100, 2)
            elif d == "LONG"  and price <= sl:
                sig["result"] = "loss"; sig["result_pct"] = round((sl - entry) / entry * 100, 2)
            elif d == "SHORT" and price >= sl:
                sig["result"] = "loss"; sig["result_pct"] = round((entry - sl) / entry * 100, 2)
            elif hours_since(sig["time"]) > 48:
                sig["result"] = "expired"; sig["result_pct"] = 0

            if sig.get("result"):
                sig["closed_at"] = datetime.utcnow().isoformat()
                icon = "✅" if sig["result"] == "win" else "❌"
                print(f"[Tracker] {icon} {sig['result'].upper()} {sig['symbol']} {sig['result_pct']}%")
                changed = True

        if changed:
            save_signals(signals)
        time.sleep(300)


def generate_daily_report():
    signals = load_signals()
    today   = str(date.today())
    daily   = [s for s in signals if s.get("date") == today]

    if not daily:
        send_message(f"📋 لا توجد إشارات اليوم ({today})")
        return

    closed  = [s for s in daily if s.get("result") in ("win", "loss")]
    wins    = [s for s in closed if s["result"] == "win"]
    losses  = [s for s in closed if s["result"] == "loss"]
    results = [s["result_pct"] for s in closed if s.get("result_pct") is not None]
    pnl     = round(sum(results), 2)
    rate    = round(len(wins) / len(closed) * 100, 1) if closed else 0.0

    report = {
        "date":     today,
        "total":    len(daily),
        "wins":     len(wins),
        "losses":   len(losses),
        "open":     len([s for s in daily if s.get("result") is None]),
        "win_rate": rate,
        "pnl_pct":  pnl,
        "best":     f"+{max(results):.2f}%" if wins   else "N/A",
        "worst":    f"{min(results):.2f}%"  if losses else "N/A",
        "version":  daily[-1].get("version", "1.0"),
        "signals":  daily,
    }

    send_daily_report(report)
    print(f"[Report] PnL={pnl}% WR={rate}%")

    if closed and (pnl < 0 or rate < 45):
        send_message("⚠️ نتائج دون المستوى — جاري تطوير الاستراتيجية...")
        optimize_strategy(report)


def bump_version(v: str) -> str:
    try:
        p = v.split("."); p[-1] = str(int(p[-1]) + 1); return ".".join(p)
    except Exception:
        return "1.1"


def clamp(cfg: dict) -> dict:
    for key, (lo, hi, cast) in BOUNDS.items():
        if key in cfg:
            try: cfg[key] = cast(max(lo, min(hi, cast(cfg[key]))))
            except Exception: pass
    return cfg


def optimize_strategy(report: dict):
    if not ANTHROPIC_KEY:
        print("[Optimizer] No ANTHROPIC_API_KEY — skipping")
        return

    current = load_config()
    prompt  = f"""أنت محلل تداول خبير في Smart Money Concepts.
مهمتك تحسين إعدادات استراتيجية إشارات التداول.

=== نتائج اليوم ===
PnL: {report['pnl_pct']:.2f}%
Win Rate: {report['win_rate']:.1f}%
رابحة: {report['wins']} | خاسرة: {report['losses']}
أفضل: {report['best']} | أسوأ: {report['worst']}

=== تفاصيل الإشارات ===
{json.dumps(report.get('signals', []), indent=2, ensure_ascii=False)}

=== الإعدادات الحالية ===
{json.dumps(current, indent=2, ensure_ascii=False)}

=== الحدود المسموحة ===
{json.dumps({k: {"min": v[0], "max": v[1]} for k, v in BOUNDS.items()}, indent=2)}

التعليمات:
1. حلل سبب الخسائر بدقة
2. اقترح إعدادات محسّنة ضمن الحدود
3. أضف حقل "reasoning" بالعربية (3-4 جمل)
4. لا تغيّر symbols أو version

أجب بـ JSON فقط بدون أي نص خارج JSON.
"""

    try:
        client  = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        resp    = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw     = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        new_cfg = json.loads(raw)
    except Exception as e:
        print(f"[Optimizer] Error: {e}")
        return

    reasoning          = new_cfg.pop("reasoning", "تحديث تلقائي")
    new_cfg            = clamp(new_cfg)
    new_cfg["symbols"] = current.get("symbols", [])
    new_cfg["version"] = bump_version(current.get("version", "1.0"))

    changes = [
        f"• {k}: {current.get(k)} → {v}"
        for k, v in new_cfg.items()
        if k not in ("symbols", "version") and current.get(k) != v
    ]

    save_config(new_cfg)
    send_optimizer_update(new_cfg["version"], reasoning, changes)
    print(f"[Optimizer] → v{new_cfg['version']} ({len(changes)} changes)")


def main():
    if not os.path.exists(STRATEGY_FILE):
        save_config(load_config())

    send_message(
        "🚀 <b>AI Signals Bot — انطلق!</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        "📊 مسح كل 15 دقيقة\n"
        "📱 إشارات SMC للتيليقرام\n"
        "📈 تقرير يومي 11 مساءً بتوقيت السعودية\n"
        "🧠 تطوير ذاتي عند النتائج السلبية"
    )

    threading.Thread(target=run_bot,     daemon=True).start()
    threading.Thread(target=run_tracker, daemon=True).start()

    schedule.every().day.at("20:00").do(generate_daily_report)
    print("[Main] Running — daily report at 20:00 UTC (11 PM KSA)")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
