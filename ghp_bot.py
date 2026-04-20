"""
SMC Signals Bot — إشارات فقط بدون تداول حقيقي
Multi-timeframe: 4H → 1H → 15M
"""

import os
import time
import json
import requests
import numpy as np
from datetime import datetime, timezone

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BINANCE_BASE     = "https://data-api.binance.vision"
TRADES_FILE      = "smc_signals.json"

CFG = {
    "min_confluence": 8,
    "min_volume_usd": 5_000_000,
    "min_gain_pct":   1.0,
    "max_gain_pct":   40.0,
    "btc_filter_pct": -2.0,
    "min_rr":         2.0,
    "ote_low":        0.618,
    "ote_high":       0.786,
    "sl_buffer":      0.005,
    "vol_mult":       1.5,
    "fvg_min_pct":    0.3,
    "ob_lookback":    10,
    "scan_interval":       60,
    "check_after_hours":   4,
    "signal_cooldown_hrs": 6,
    "daily_report_hour":   20,
    "top_n": 60,
    "tf_4h":  "4h",
    "tf_1h":  "1h",
    "tf_15m": "15m",
    "candle_limit": 60,
}

SYMBOLS_FIXED = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT",
    "SEIUSDT", "FETUSDT", "RENDERUSDT", "JUPUSDT", "PYTHUSDT",
    "STXUSDT", "ORDIUSDT", "ENAUSDT", "HBARUSDT", "NEARUSDT",
    "ALGOUSDT", "FILUSDT", "SANDUSDT", "AXSUSDT", "GALAUSDT",
    "CHZUSDT", "APEUSDT", "GMTUSDT", "DYDXUSDT", "MASKUSDT",
    "IOTAUSDT", "ZILUSDT", "KSMUSDT", "SKLUSDT", "CRVUSDT",
    "UNIUSDT", "ATOMUSDT", "LTCUSDT", "MATICUSDT", "TIAUSDT",
    "WLDUSDT", "CELOUSDT", "FLOWUSDT", "MANAUSDT", "ENAUSDT",
]

def load_data():
    try:
        if os.path.exists(TRADES_FILE):
            with open(TRADES_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Load error: {e}")
    return {
        "signals": [],
        "stats": {
            "total": 0, "wins": 0, "losses": 0,
            "pending": 0, "win_pct": 0.0
        }
    }

def save_data(data):
    try:
        with open(TRADES_FILE, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Save error: {e}")

def log_signal(sym, direction, entry, tp1, tp2, sl, rr,
               confluence, conf_details, rsi, atr,
               signal_source, ob, ote, in_ote):
    data = load_data()
    sig_id = data["stats"]["total"] + 1
    signal = {
        "id":           sig_id,
        "sym":          sym,
        "direction":    direction,
        "entry":        entry,
        "tp1":          tp1,
        "tp2":          tp2,
        "sl":           sl,
        "rr":           rr,
        "confluence":   confluence,
        "conf_details": conf_details,
        "rsi":          rsi,
        "atr":          atr,
        "source":       signal_source,
        "ob_top":       ob["top"],
        "ob_bottom":    ob["bottom"],
        "ote_low":      ote["low"],
        "ote_high":     ote["high"],
        "in_ote":       in_ote,
        "time":         datetime.now(timezone.utc).isoformat(),
        "timestamp":    time.time(),
        "day":          datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "result":       "PENDING",
        "exit_price":   0.0,
        "pnl_pct":      0.0,
    }
    data["signals"].append(signal)
    data["stats"]["total"]   += 1
    data["stats"]["pending"] += 1
    save_data(data)
    return sig_id

def check_signal_result(signal):
    try:
        sym    = signal["sym"]
        entry  = signal["entry"]
        tp1    = signal["tp1"]
        tp2    = signal["tp2"]
        sl     = signal["sl"]
        direct = signal["direction"]
        klines = requests.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": sym, "interval": "15m", "limit": 30},
            timeout=10
        ).json()
        if not klines or not isinstance(klines, list):
            return None
        hit_tp1 = hit_tp2 = hit_sl = False
        for k in klines:
            h = float(k[2])
            l = float(k[3])
            if direct == "LONG":
                if not hit_tp1 and h >= tp1: hit_tp1 = True
                if hit_tp1 and not hit_tp2 and h >= tp2: hit_tp2 = True
                if l <= sl and not hit_tp1: hit_sl = True; break
            else:
                if not hit_tp1 and l <= tp1: hit_tp1 = True
                if hit_tp1 and not hit_tp2 and l <= tp2: hit_tp2 = True
                if h >= sl and not hit_tp1: hit_sl = True; break
        if hit_tp2:
            result = "TP2"; ep = tp2; pnl = abs(tp2 / entry - 1) * 100
        elif hit_tp1:
            result = "TP1"; ep = tp1; pnl = abs(tp1 / entry - 1) * 100
        elif hit_sl:
            result = "SL"; ep = sl; pnl = -abs(sl / entry - 1) * 100
        else:
            ep = float(klines[-1][4])
            pnl = (ep / entry - 1) * 100 if direct == "LONG" else (entry / ep - 1) * 100
            result = "OPEN"
        return {"result": result, "exit_price": ep, "pnl_pct": pnl}
    except Exception as e:
        print(f"Check error {signal['sym']}: {e}")
        return None

def update_pending_signals():
    data = load_data()
    now = time.time()
    updated = []
    for i, sig in enumerate(data["signals"]):
        if sig["result"] != "PENDING":
            continue
        elapsed_hours = (now - sig["timestamp"]) / 3600
        if elapsed_hours < CFG["check_after_hours"]:
            continue
        res = check_signal_result(sig)
        if res and res["result"] != "OPEN":
            data["signals"][i]["result"]     = res["result"]
            data["signals"][i]["exit_price"] = res["exit_price"]
            data["signals"][i]["pnl_pct"]    = res["pnl_pct"]
            data["stats"]["pending"] = max(0, data["stats"]["pending"] - 1)
            if res["result"] in ["TP1", "TP2"]:
                data["stats"]["wins"] += 1
            elif res["result"] == "SL":
                data["stats"]["losses"] += 1
            total_decided = data["stats"]["wins"] + data["stats"]["losses"]
            data["stats"]["win_pct"] = (
                data["stats"]["wins"] / total_decided * 100
                if total_decided > 0 else 0.0
            )
            updated.append((sig, res))
    save_data(data)
    return updated

def send_tg(msg):
    if not TELEGRAM_TOKEN:
        print("No TG token")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"TG error: {e}")

def get_klines(sym, tf, limit=60):
    try:
        return requests.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": sym, "interval": tf, "limit": limit},
            timeout=15
        ).json()
    except:
        return []

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0: gains += d
        else: losses -= d
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0.0
    tr_sum = 0.0
    for i in range(len(closes) - period, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_sum += tr
    return tr_sum / period

def find_market_structure(klines):
    if len(klines) < 10:
        return "NEUTRAL"
    H = [float(k[2]) for k in klines]
    L = [float(k[3]) for k in klines]
    n = len(klines)
    highs, lows = [], []
    for i in range(2, min(n - 2, 30)):
        idx = n - 1 - i
        if idx < 1: continue
        if H[idx] > H[idx-1] and H[idx] > H[idx+1]:
            highs.append((idx, H[idx]))
        if L[idx] < L[idx-1] and L[idx] < L[idx+1]:
            lows.append((idx, L[idx]))
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"
    highs.sort(key=lambda x: x[0])
    lows.sort(key=lambda x: x[0])
    h1, h2 = highs[-2][1], highs[-1][1]
    l1, l2 = lows[-2][1],  lows[-1][1]
    if h2 > h1 and l2 > l1: return "BULLISH"
    if h2 < h1 and l2 < l1: return "BEARISH"
    return "NEUTRAL"

def find_bos(klines, bias):
    if len(klines) < 15: return None
    H = [float(k[2]) for k in klines]
    L = [float(k[3]) for k in klines]
    C = [float(k[4]) for k in klines]
    V = [float(k[5]) for k in klines]
    n = len(klines)
    avg_v = sum(V[-20:]) / 20 if len(V) >= 20 else V[-1]
    lookback = min(15, n - 3)
    recent_high = max(H[-lookback-1:-1])
    recent_low  = min(L[-lookback-1:-1])
    vol_confirm = V[-1] > avg_v * CFG["vol_mult"]
    if bias == "BULLISH" and C[-1] > recent_high and C[-2] <= recent_high and vol_confirm:
        return {"type": "BOS", "direction": "LONG", "level": recent_high}
    if bias == "BEARISH" and C[-1] < recent_low and C[-2] >= recent_low and vol_confirm:
        return {"type": "BOS", "direction": "SHORT", "level": recent_low}
    return None

def find_choch(klines, bias):
    if len(klines) < 20: return None
    H = [float(k[2]) for k in klines]
    L = [float(k[3]) for k in klines]
    C = [float(k[4]) for k in klines]
    n = len(klines)
    highs, lows = [], []
    for i in range(2, min(20, n - 2)):
        idx = n - 1 - i
        if H[idx] > H[idx-1] and H[idx] > H[idx+1]: highs.append(H[idx])
        if L[idx] < L[idx-1] and L[idx] < L[idx+1]: lows.append(L[idx])
    if not highs or not lows: return None
    last_high = highs[0]
    last_low  = lows[0]
    if bias == "BEARISH" and C[-1] > last_high and C[-2] <= last_high:
        return {"type": "CHoCH", "direction": "LONG", "level": last_high}
    if bias == "BULLISH" and C[-1] < last_low and C[-2] >= last_low:
        return {"type": "CHoCH", "direction": "SHORT", "level": last_low}
    return None

def find_order_block(klines, direction):
    if len(klines) < 5: return None
    O = [float(k[1]) for k in klines]
    H = [float(k[2]) for k in klines]
    L = [float(k[3]) for k in klines]
    C = [float(k[4]) for k in klines]
    n = len(klines)
    lookback = min(CFG["ob_lookback"], n - 3)
    if direction == "LONG":
        for i in range(2, lookback + 1):
            idx = n - 1 - i
            if idx < 1: break
            if C[idx] < O[idx]:
                if C[idx+1] > O[idx+1] and (C[idx+1] - O[idx+1]) > abs(C[idx] - O[idx]) * 0.8:
                    return {"top": O[idx], "bottom": C[idx], "mid": (O[idx] + C[idx]) / 2}
    else:
        for i in range(2, lookback + 1):
            idx = n - 1 - i
            if idx < 1: break
            if C[idx] > O[idx]:
                if C[idx+1] < O[idx+1] and abs(C[idx+1] - O[idx+1]) > abs(C[idx] - O[idx]) * 0.8:
                    return {"top": C[idx], "bottom": O[idx], "mid": (O[idx] + C[idx]) / 2}
    return None

def find_fvg(klines, direction, curr_price):
    if len(klines) < 5: return None
    H = [float(k[2]) for k in klines]
    L = [float(k[3]) for k in klines]
    n = len(klines)
    lookback = min(15, n - 3)
    fvgs = []
    for i in range(1, lookback + 1):
        idx = n - 1 - i
        if idx < 1 or idx + 1 >= n: continue
        if direction == "LONG":
            gap_top = L[idx+1]; gap_bot = H[idx-1]
            if gap_top > gap_bot:
                gs = (gap_top - gap_bot) / gap_bot * 100
                if gs >= CFG["fvg_min_pct"]:
                    fvgs.append({
                        "top": gap_top, "bottom": gap_bot,
                        "mid": (gap_top + gap_bot) / 2,
                        "in_fvg": gap_bot <= curr_price <= gap_top * 1.02,
                    })
        else:
            gap_top = L[idx-1]; gap_bot = H[idx+1]
            if gap_top > gap_bot:
                gs = (gap_top - gap_bot) / gap_bot * 100
                if gs >= CFG["fvg_min_pct"]:
                    fvgs.append({
                        "top": gap_top, "bottom": gap_bot,
                        "mid": (gap_top + gap_bot) / 2,
                        "in_fvg": gap_bot <= curr_price <= gap_top * 1.02,
                    })
    if fvgs:
        return min(fvgs, key=lambda x: abs(x["mid"] - curr_price))
    return None

def find_liquidity_sweep(klines):
    if len(klines) < 10: return None
    H = [float(k[2]) for k in klines]
    L = [float(k[3]) for k in klines]
    C = [float(k[4]) for k in klines]
    O = [float(k[1]) for k in klines]
    n = len(klines)
    lookback = min(20, n - 3)
    prev_high = max(H[-lookback-1:-2])
    prev_low  = min(L[-lookback-1:-2])
    ph = H[-2]; pl = L[-2]; pc = C[-2]
    cl = C[-1]; op = O[-1]
    bull_sweep = (pl < prev_low  and pc > prev_low  and cl > op and cl > pc)
    bear_sweep = (ph > prev_high and pc < prev_high and cl < op and cl < pc)
    if bull_sweep: return {"type": "BULLISH", "swept_level": prev_low}
    if bear_sweep: return {"type": "BEARISH", "swept_level": prev_high}
    return None

def calc_ote(swing_low, swing_high):
    rng = swing_high - swing_low
    return {
        "low":  swing_high - rng * CFG["ote_high"],
        "high": swing_high - rng * CFG["ote_low"],
        "mid":  swing_high - rng * 0.702,
    }

def get_pairs():
    try:
        r = requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", timeout=15).json()
        if not isinstance(r, list): return SYMBOLS_FIXED
        f = [
            t for t in r
            if isinstance(t, dict)
            and isinstance(t.get("symbol", ""), str)
            and t.get("symbol", "").endswith("USDT")
            and not any(x in t.get("symbol", "") for x in ["DOWN", "UP", "BEAR", "BULL"])
            and CFG["min_gain_pct"] <= abs(float(t.get("priceChangePercent", 0))) <= CFG["max_gain_pct"]
            and float(t.get("quoteVolume", 0)) > CFG["min_volume_usd"]
        ]
        s = sorted(f, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        dynamic = [t["symbol"] for t in s[:CFG["top_n"]]]
        combined = list(dict.fromkeys(SYMBOLS_FIXED + dynamic))
        return combined[:CFG["top_n"]]
    except:
        return SYMBOLS_FIXED

def check_btc():
    try:
        k = requests.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "1h", "limit": 5},
            timeout=10
        ).json()
        if not k or len(k) < 2: return True, 0
        C = [float(x[4]) for x in k]
        chg = (C[-1] - C[-4]) / C[-4] * 100
        return chg >= CFG["btc_filter_pct"], chg
    except:
        return True, 0

def analyze_symbol(sym):
    try:
        k4h  = get_klines(sym, CFG["tf_4h"],  CFG["candle_limit"])
        k1h  = get_klines(sym, CFG["tf_1h"],  CFG["candle_limit"])
        k15m = get_klines(sym, CFG["tf_15m"], CFG["candle_limit"])
        if not k4h or not k1h or not k15m: return None
        if len(k4h) < 30 or len(k1h) < 30 or len(k15m) < 20: return None
        bias = find_market_structure(k4h)
        if bias == "NEUTRAL": return None
        bos   = find_bos(k1h, bias)
        choch = find_choch(k1h, bias)
        direction     = "LONG" if bias == "BULLISH" else "SHORT"
        confirmed     = False
        signal_source = ""
        if bos and bos["direction"] == direction:
            confirmed = True; signal_source = "BOS"
        elif choch and choch["direction"] == direction:
            confirmed = True; signal_source = "CHoCH"
        if not confirmed: return None
        C15 = [float(k[4]) for k in k15m]
        H15 = [float(k[2]) for k in k15m]
        L15 = [float(k[3]) for k in k15m]
        curr_price = C15[-1]
        rsi = calc_rsi(C15, 14)
        atr = calc_atr(H15, L15, C15, 14)
        if direction == "LONG"  and (rsi > 75 or rsi < 30): return None
        if direction == "SHORT" and (rsi < 25 or rsi > 70): return None
        ob = find_order_block(k15m, direction)
        if not ob: return None
        fvg = find_fvg(k15m, direction, curr_price)
        liq = find_liquidity_sweep(k15m)
        swing_low  = min(L15[-20:])
        swing_high = max(H15[-20:])
        ote      = calc_ote(swing_low, swing_high)
        in_ote   = ote["low"] <= curr_price <= ote["high"]
        near_ote = (curr_price < ote["high"] * 1.03 if direction == "LONG"
                    else curr_price > ote["low"] * 0.97)
        confluence   = 0
        conf_details = []
        if bias != "NEUTRAL":
            confluence += 2; conf_details.append(f"4H {bias}")
        if bos:
            confluence += 2; conf_details.append("BOS 1H")
        if choch:
            confluence += 2; conf_details.append("CHoCH 1H")
        if ob:
            confluence += 2; conf_details.append("Order Block")
        if fvg and fvg.get("in_fvg"):
            confluence += 2; conf_details.append("FVG")
        elif fvg:
            confluence += 1; conf_details.append("FVG")
        if liq and liq["type"] == ("BULLISH" if direction == "LONG" else "BEARISH"):
            confluence += 2; conf_details.append("Liq Sweep")
        if in_ote:
            confluence += 2; conf_details.append("OTE")
        elif near_ote:
            confluence += 1; conf_details.append("Near OTE")
        if confluence < CFG["min_confluence"]: return None
        if direction == "LONG":
            sl  = ob["bottom"] * (1 - CFG["sl_buffer"])
            if sl >= curr_price: sl = curr_price * 0.98
            risk = curr_price - sl
            tp1  = curr_price + risk * 2.0
            tp2  = curr_price + risk * 4.0
        else:
            sl  = ob["top"] * (1 + CFG["sl_buffer"])
            if sl <= curr_price: sl = curr_price * 1.02
            risk = sl - curr_price
            tp1  = curr_price - risk * 2.0
            tp2  = curr_price - risk * 4.0
        rr = abs(tp1 - curr_price) / abs(sl - curr_price) if abs(sl - curr_price) > 0 else 0
        if rr < CFG["min_rr"]: return None
        if direction == "LONG"  and tp1 <= curr_price: return None
        if direction == "SHORT" and tp1 >= curr_price: return None
        return {
            "sym": sym, "direction": direction, "source": signal_source,
            "bias": bias, "entry": curr_price,
            "tp1": tp1, "tp2": tp2, "sl": sl, "rr": rr,
            "confluence": confluence, "conf_details": conf_details,
            "rsi": rsi, "atr": atr,
            "ob": ob, "fvg": fvg, "liq": liq,
            "ote": ote, "in_ote": in_ote,
        }
    except Exception as e:
        print(f"Error {sym}: {e}")
        return None

def format_signal(r, sig_id):
    dir_emoji  = "📈" if r["direction"] == "LONG" else "📉"
    rr_emoji   = "✅" if r["rr"] >= 3.0 else "🔸"
    ote_emoji  = "✅" if r["in_ote"] else "🔸"
    conf_str   = " | ".join(r["conf_details"])
    t1p = abs(r["tp1"] / r["entry"] - 1) * 100
    t2p = abs(r["tp2"] / r["entry"] - 1) * 100
    slp = abs(r["sl"]  / r["entry"] - 1) * 100
    fvg_line = ""
    if r.get("fvg") and r["fvg"].get("in_fvg"):
        fvg_line = f"\n🔷 FVG: ${r['fvg']['bottom']:.4f} — ${r['fvg']['top']:.4f}"
    liq_line = ""
    if r.get("liq"):
        liq_line = f"\n💧 Liq Sweep: ${r['liq']['swept_level']:.4f}"
    return (
        f"{dir_emoji} <b>SMC #{sig_id} — {r['sym']}</b>\n"
        f"📐 {r['source']} | {r['bias']} على 4H\n"
        f"⭐ تقاطع: {r['confluence']}/14 نقطة\n"
        f"📌 {conf_str}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💵 دخول:  ${r['entry']:.4f}\n"
        f"🎯 TP1:   ${r['tp1']:.4f}  (+{t1p:.2f}%)\n"
        f"🎯 TP2:   ${r['tp2']:.4f}  (+{t2p:.2f}%)\n"
        f"🛑 SL:    ${r['sl']:.4f}  (-{slp:.2f}%)\n"
        f"📊 R:R:   1:{r['rr']:.2f} {rr_emoji} | 🔧 1x\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📦 OB: ${r['ob']['bottom']:.4f} — ${r['ob']['top']:.4f}\n"
        f"🎯 OTE: ${r['ote']['low']:.4f} — ${r['ote']['high']:.4f} {ote_emoji}"
        f"{fvg_line}{liq_line}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔢 RSI: {r['rsi']:.1f} | ATR: ${r['atr']:.4f}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC\n"
        f"⚠️ <i>تحليل فقط — ليست نصيحة مالية</i>"
    )

def format_result(signal, res):
    result_emoji = {"TP2": "🎯", "TP1": "✅", "SL": "❌"}.get(res["result"], "⏳")
    color        = "🟢" if res["pnl_pct"] > 0 else "🔴"
    dir_emoji    = "📈" if signal["direction"] == "LONG" else "📉"
    return (
        f"{result_emoji} <b>نتيجة #{signal['id']} — {signal['sym']}</b>\n"
        f"{dir_emoji} {signal['direction']} | {signal['source']}\n"
        f"💵 دخول: ${signal['entry']:.4f}\n"
        f"🚪 خروج: ${res['exit_price']:.4f}\n"
        f"{color} <b>{res['result']} | {res['pnl_pct']:+.2f}%</b>\n"
        f"⭐ تقاطع: {signal['confluence']}/14\n"
        f"⏱ بعد {CFG['check_after_hours']} ساعات"
    )

def gen_daily_report():
    data  = load_data()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_sigs = [s for s in data["signals"]
                if s.get("day") == today and s["result"] != "PENDING"]
    stats = data["stats"]
    total_decided = stats["wins"] + stats["losses"]
    win_pct = stats["wins"] / total_decided * 100 if total_decided > 0 else 0
    if not day_sigs:
        return (
            f"📊 <b>تقرير SMC اليومي — {today}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⏳ لا توجد إشارات محسومة اليوم\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📈 الإجمالي الكلي:\n"
            f"📊 {stats['total']} إشارة | ✅ {stats['wins']} | ❌ {stats['losses']}\n"
            f"🎯 نسبة النجاح: {win_pct:.1f}%"
        )
    wins   = [s for s in day_sigs if s["result"] in ["TP1", "TP2"]]
    losses = [s for s in day_sigs if s["result"] == "SL"]
    tp2_c  = len([s for s in wins if s["result"] == "TP2"])
    tp1_c  = len([s for s in wins if s["result"] == "TP1"])
    day_wr = len(wins) / len(day_sigs) * 100
    total_pnl = sum(s["pnl_pct"] for s in day_sigs)
    pnl_emoji = "🟢" if total_pnl > 0 else "🔴"
    avg_conf = sum(s["confluence"] for s in day_sigs) / len(day_sigs)
    report = (
        f"📊 <b>تقرير SMC اليومي — {today}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 إشارات اليوم: {len(day_sigs)}\n"
        f"✅ ناجحة: {len(wins)} | ❌ فاشلة: {len(losses)}\n"
        f"🎯 نسبة اليوم: {day_wr:.1f}%\n"
        f"{pnl_emoji} إجمالي: {total_pnl:+.2f}%\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 TP2: {tp2_c} | 👍 TP1: {tp1_c} | ❌ SL: {len(losses)}\n"
        f"⭐ متوسط تقاطع: {avg_conf:.1f}/14\n"
        f"━━━━━━━━━━━━━━━\n"
    )
    if wins:
        best  = max(wins, key=lambda x: x["pnl_pct"])
        avg_w = sum(s["pnl_pct"] for s in wins) / len(wins)
        report += f"🏆 أفضل: #{best['id']} {best['sym']} {best['pnl_pct']:+.2f}%\n"
        report += f"📈 متوسط ربح: +{avg_w:.2f}%\n"
    if losses:
        avg_l = sum(s["pnl_pct"] for s in losses) / len(losses)
        report += f"📉 متوسط خسارة: {avg_l:.2f}%\n"
    report += (
        f"━━━━━━━━━━━━━━━\n"
        f"📈 الإجمالي الكلي:\n"
        f"📊 {stats['total']} إشارة | ✅ {stats['wins']} | ❌ {stats['losses']}\n"
        f"🎯 نسبة النجاح: {win_pct:.1f}%\n"
        f"⏳ معلقة: {stats['pending']}"
    )
    return report

last_signals = {}
last_daily_report = -1

def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{now_str}] Scanning...")
    btc_ok, btc_chg = check_btc()
    btc_emoji = "🟢" if btc_chg > 0 else "🔴"
    pairs   = get_pairs()
    signals = []
    for sym in pairs:
        try:
            last = last_signals.get(sym, 0)
            if time.time() - last < CFG["signal_cooldown_hrs"] * 3600:
                continue
            r = analyze_symbol(sym)
            if r:
                signals.append(r)
            time.sleep(0.3)
        except Exception as e:
            print(f"Error {sym}: {e}")
    signals.sort(key=lambda x: (x["confluence"], x["rr"]), reverse=True)
    bull_c = len([s for s in signals if s["direction"] == "LONG"])
    bear_c = len([s for s in signals if s["direction"] == "SHORT"])
    data  = load_data()
    stats = data["stats"]
    total_decided = stats["wins"] + stats["losses"]
    win_pct = stats["wins"] / total_decided * 100 if total_decided > 0 else 0
    send_tg(
        f"⚡ <b>SMC Bot — مسح</b>\n"
        f"{btc_emoji} BTC: {btc_chg:+.2f}%\n"
        f"📊 أزواج: {len(pairs)} | 📈 {bull_c} | 📉 {bear_c}\n"
        f"🎯 إجمالي: {stats['total']} | ✅ {stats['wins']} | نسبة: {win_pct:.1f}%\n"
        f"🕐 {now_str} UTC"
    )
    sent = 0
    for r in signals[:5]:
        sig_id = log_signal(
            r["sym"], r["direction"], r["entry"],
            r["tp1"], r["tp2"], r["sl"], r["rr"],
            r["confluence"], r["conf_details"],
            r["rsi"], r["atr"], r["source"],
            r["ob"], r["ote"], r["in_ote"]
        )
        send_tg(format_signal(r, sig_id))
        last_signals[r["sym"]] = time.time()
        sent += 1
        time.sleep(0.5)
    print(f"Sent {sent} signals")

def check_results_and_report():
    global last_daily_report
    updated = update_pending_signals()
    for signal, res in updated:
        send_tg(format_result(signal, res))
        print(f"Result #{signal['id']} {signal['sym']}: {res['result']} {res['pnl_pct']:+.2f}%")
    now = datetime.now(timezone.utc)
    if now.hour == CFG["daily_report_hour"] and 0 <= now.minute < 15:
        if last_daily_report != now.day:
            send_tg(gen_daily_report())
            last_daily_report = now.day
            print("Daily report sent.")

if __name__ == "__main__":
    print("SMC Signals Bot starting...")
    data  = load_data()
    stats = data["stats"]
    send_tg(
        f"📐 <b>SMC Signals Bot بدأ!</b>\n\n"
        f"⭐ تقاطع {CFG['min_confluence']}/14+ مطلوب\n"
        f"📐 R:R minimum: {CFG['min_rr']}\n"
        f"⏱ نتيجة كل إشارة بعد {CFG['check_after_hours']} ساعات\n"
        f"📅 تقرير يومي {CFG['daily_report_hour']}:00 UTC\n\n"
        f"📦 الإجمالي: {stats['total']} | ✅ {stats['wins']} | ❌ {stats['losses']}"
    )
    while True:
        try:
            run_scan()
            check_results_and_report()
            time.sleep(CFG["scan_interval"] * 60)
        except KeyboardInterrupt:
            send_tg("⏹ SMC Bot توقف")
            print("Bot stopped.")
            break
        except Exception as e:
            print(f"Main error: {e}")
            time.sleep(60)
