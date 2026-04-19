import os
import time
import requests
import json
from datetime import datetime, timezone

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "400815773")
BINANCE_BASE     = "https://data-api.binance.vision"
TRADES_FILE      = "trades_log.json"

CFG = {
    "atr_len": 14,
    "vol_len": 20,
    "vol_mult": 1.5,
    "rsi_len": 14,
    "rsi_ob": 75,
    "ema_fast": 9,
    "ema_slow": 21,
    "ema_trend": 50,
    "tp1_mult": 1.5,
    "tp2_mult": 3.0,
    "tp3_mult": 5.0,
    "sl_mult": 1.2,
    "min_rr": 2.0,
    "top_n": 60,
    "main_interval": 60,
    "fast_interval": 15,
    "tf_main": "1h",
    "tf_fast": "15m",
    "min_gain_pct": 2.0,
    "max_gain_pct": 50.0,
    "min_volume_usd": 3000000,
    "btc_filter_pct": -2.0,
    "roc_bars": 3,
    "roc_min_pct": 3.0,
    "momentum_roc_min": 8.0,
    "momentum_rsi_min": 55,
    "reentry_min_gain": 20.0,
    "trend_lookback": 20,
    "breakout_vol_mult": 1.3,
    "sl_mult_bear": 1.8,
    "check_after_hours": 4,
    "daily_report_hour": 19,
    "daily_report_minute": 0,
    "weekly_report_day": 4,
    "weekly_report_hour": 19,
    "max_same_symbol_per_day": 1,
    "rsi_max_reentry": 78,
    "rsi_max_signal": 83,
    "rsi_extreme_block": 90,
    "max_signals_per_day": 15,
    "block_reentry_after_sl": True,
}


def load_trades():
    try:
        if os.path.exists(TRADES_FILE):
            with open(TRADES_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "trades": [],
        "stats": {"total": 0, "wins": 0, "losses": 0, "pending": 0, "total_pct": 0}
    }


def save_trades(data):
    try:
        with open(TRADES_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("save error: " + str(e))


def already_traded_today(sym):
    data = load_trades()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count = sum(1 for t in data["trades"] if t["sym"] == sym and t.get("day") == today)
    return count >= CFG["max_same_symbol_per_day"]


def had_sl_today(sym):
    if not CFG["block_reentry_after_sl"]:
        return False
    data = load_trades()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for t in data["trades"]:
        if t["sym"] == sym and t.get("day") == today and t["result"] == "SL":
            return True
    return False


def daily_signals_count():
    data = load_trades()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for t in data["trades"] if t.get("day") == today)


def log_signal(sym, signal_type, entry, tp1, tp2, tp3, sl, rr, gain_pct):
    data = load_trades()
    trade = {
        "id": len(data["trades"]) + 1,
        "sym": sym, "type": signal_type, "entry": entry,
        "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl, "rr": rr,
        "gain_24h": gain_pct,
        "time": datetime.now(timezone.utc).isoformat(),
        "timestamp": time.time(),
        "result": "PENDING", "exit_price": 0, "pct": 0, "checked": False,
        "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    data["trades"].append(trade)
    data["stats"]["total"] += 1
    data["stats"]["pending"] += 1
    save_trades(data)
    return trade["id"]


def check_trade_result(trade):
    try:
        sym = trade["sym"]
        entry = trade["entry"]
        tp1 = trade["tp1"]
        tp2 = trade["tp2"]
        tp3 = trade["tp3"]
        sl = trade["sl"]
        klines = requests.get(
            BINANCE_BASE + "/api/v3/klines",
            params={"symbol": sym, "interval": "15m", "limit": 20},
            timeout=10
        ).json()
        if not klines or not isinstance(klines, list):
            return None
        t1 = False
        t2 = False
        t3 = False
        hit_sl = False
        exit_price = float(klines[-1][4])
        for k in klines:
            h = float(k[2])
            lo = float(k[3])
            if not t1 and h >= tp1:
                t1 = True
            if t1 and not t2 and h >= tp2:
                t2 = True
            if t2 and not t3 and h >= tp3:
                t3 = True
            if lo <= sl and not t2:
                hit_sl = True
                break
        if t3:
            result = "TP3"
            exit_price = tp3
            pct = (tp3 / entry - 1) * 100
        elif t2:
            result = "TP2"
            exit_price = tp2
            pct = (tp2 / entry - 1) * 100
        elif t1 and hit_sl:
            result = "TP1+SL"
            exit_price = (tp1 + sl) / 2
            pct = ((tp1 / entry - 1) * 100 * 0.5 + (sl / entry - 1) * 100 * 0.5)
        elif t1:
            result = "TP1"
            exit_price = tp1
            pct = (tp1 / entry - 1) * 100
        elif hit_sl:
            result = "SL"
            exit_price = sl
            pct = (sl / entry - 1) * 100
        else:
            result = "OPEN"
            exit_price = float(klines[-1][4])
            pct = (exit_price / entry - 1) * 100
        return {"result": result, "exit_price": exit_price, "pct": pct, "t1": t1, "t2": t2, "t3": t3}
    except Exception as e:
        print("check_trade error " + trade["sym"] + ": " + str(e))
        return None


def update_pending_trades():
    data = load_trades()
    now = time.time()
    updated = []
    for i, trade in enumerate(data["trades"]):
        if trade["result"] != "PENDING":
            continue
        if (now - trade["timestamp"]) / 3600 >= CFG["check_after_hours"]:
            res = check_trade_result(trade)
            if res and res["result"] != "OPEN":
                data["trades"][i]["result"] = res["result"]
                data["trades"][i]["exit_price"] = res["exit_price"]
                data["trades"][i]["pct"] = res["pct"]
                data["trades"][i]["checked"] = True
                data["stats"]["pending"] = max(0, data["stats"]["pending"] - 1)
                data["stats"]["total_pct"] += res["pct"]
                if res["result"] in ["TP1", "TP2", "TP3", "TP1+SL"]:
                    data["stats"]["wins"] += 1
                elif res["result"] == "SL":
                    data["stats"]["losses"] += 1
                updated.append((trade, res))
    save_trades(data)
    return updated


def gen_daily_report():
    data = load_trades()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_trades = [t for t in data["trades"] if t.get("day") == today and t["result"] != "PENDING"]
    if not day_trades:
        return "\U0001f4ca <b>\u062a\u0642\u0631\u064a\u0631 \u064a\u0648\u0645\u064a \u2014 " + today + "</b>\n\u23f3 \u0644\u0627 \u062a\u0648\u062c\u062f \u0635\u0641\u0642\u0627\u062a \u0645\u062d\u0633\u0648\u0645\u0629 \u0627\u0644\u064a\u0648\u0645"
    wins = [t for t in day_trades if t["result"] in ["TP1", "TP2", "TP3", "TP1+SL"]]
    losses = [t for t in day_trades if t["result"] == "SL"]
    total_pct = sum(t["pct"] for t in day_trades)
    wr = len(wins) / len(day_trades) * 100 if day_trades else 0
    types = {}
    for t in day_trades:
        tp = t["type"]
        if tp not in types:
            types[tp] = {"w": 0, "l": 0, "total": 0}
        types[tp]["total"] += 1
        if t["result"] in ["TP1", "TP2", "TP3", "TP1+SL"]:
            types[tp]["w"] += 1
        else:
            types[tp]["l"] += 1
    type_lines = ""
    for tp, v in types.items():
        wr_t = v["w"] / v["total"] * 100 if v["total"] else 0
        type_lines += "\n" + tp + ": " + str(v["w"]) + "/" + str(v["total"]) + " (" + str(round(wr_t)) + "%)"
    sign = "+" if total_pct > 0 else ""
    pnl_ico = "\U0001f7e2" if total_pct > 0 else "\U0001f534"
    msg = (
        "\U0001f4ca <b>\u062a\u0642\u0631\u064a\u0631 \u064a\u0648\u0645\u064a \u2014 " + today + "</b>\n"
        "\u2015\u2015\u2015\u2015\u2015\u2015\u2015\n"
        "\U0001f4c8 \u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0625\u0634\u0627\u0631\u0627\u062a: " + str(len(day_trades)) + "\n"
        "\u2705 \u0631\u0627\u0628\u062d\u0629: " + str(len(wins)) + " | \u274c \u062e\u0627\u0633\u0631\u0629: " + str(len(losses)) + "\n"
        "\U0001f3af \u0646\u0633\u0628\u0629 \u0627\u0644\u0646\u062c\u0627\u062d: " + str(round(wr, 1)) + "%\n"
        + pnl_ico + " \u0625\u062c\u0645\u0627\u0644\u064a: " + sign + str(round(total_pct, 2)) + "%\n"
        "\u2015\u2015\u2015\u2015\u2015\u2015\u2015\n"
        "<b>\u062a\u0641\u0635\u064a\u0644 \u062d\u0633\u0628 \u0627\u0644\u0646\u0648\u0639:</b>" + type_lines + "\n"
        "\u2015\u2015\u2015\u2015\u2015\u2015\u2015"
    )
    if wins:
        best = max(wins, key=lambda x: x["pct"])
        msg += "\n\U0001f3c6 \u0623\u0641\u0636\u0644 \u0635\u0641\u0642\u0629: #" + str(best["id"]) + " " + best["sym"] + " +" + str(round(best["pct"], 2)) + "%"
    if losses:
        worst = min(losses, key=lambda x: x["pct"])
        msg += "\n\U0001f494 \u0623\u0633\u0648\u0623 \u0635\u0641\u0642\u0629: #" + str(worst["id"]) + " " + worst["sym"] + " " + str(round(worst["pct"], 2)) + "%"
    return msg


def gen_weekly_report():
    data = load_trades()
    all_trades = [t for t in data["trades"] if t["result"] != "PENDING"]
    if not all_trades:
        return "\U0001f4ca <b>\u0627\u0644\u062a\u0642\u0631\u064a\u0631 \u0627\u0644\u0623\u0633\u0628\u0648\u0639\u064a</b>\n\u23f3 \u0644\u0627 \u062a\u0648\u062c\u062f \u0635\u0641\u0642\u0627\u062a \u0628\u0639\u062f"
    wins = [t for t in all_trades if t["result"] in ["TP1", "TP2", "TP3", "TP1+SL"]]
    losses = [t for t in all_trades if t["result"] == "SL"]
    total_pct = sum(t["pct"] for t in all_trades)
    wr = len(wins) / len(all_trades) * 100 if all_trades else 0
    types = {}
    for t in all_trades:
        tp = t["type"]
        if tp not in types:
            types[tp] = {"w": 0, "l": 0, "total": 0, "pct": 0}
        types[tp]["total"] += 1
        types[tp]["pct"] += t["pct"]
        if t["result"] in ["TP1", "TP2", "TP3", "TP1+SL"]:
            types[tp]["w"] += 1
        else:
            types[tp]["l"] += 1
    tp3_c = len([t for t in all_trades if t["result"] == "TP3"])
    tp2_c = len([t for t in all_trades if t["result"] == "TP2"])
    tp1_c = len([t for t in all_trades if t["result"] in ["TP1", "TP1+SL"]])
    type_lines = ""
    for tp, v in sorted(types.items(), key=lambda x: -x[1]["w"]):
        wr_t = v["w"] / v["total"] * 100 if v["total"] else 0
        type_lines += "\n" + tp + ": " + str(v["w"]) + "/" + str(v["total"]) + " (" + str(round(wr_t)) + "%) | " + str(round(v["pct"], 1)) + "%"
    sign = "+" if total_pct > 0 else ""
    pnl_ico = "\U0001f7e2" if total_pct > 0 else "\U0001f534"
    msg = (
        "\U0001f4ca <b>\u0627\u0644\u062a\u0642\u0631\u064a\u0631 \u0627\u0644\u0623\u0633\u0628\u0648\u0639\u064a \u2014 GHP Pro v5</b>\n"
        "\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\n"
        "\U0001f4c8 \u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0625\u0634\u0627\u0631\u0627\u062a: " + str(len(all_trades)) + "\n"
        "\u2705 \u0631\u0627\u0628\u062d\u0629: " + str(len(wins)) + " | \u274c \u062e\u0627\u0633\u0631\u0629: " + str(len(losses)) + " | \u23f3 \u0645\u0639\u0644\u0642: " + str(data["stats"]["pending"]) + "\n"
        "\U0001f3af <b>\u0646\u0633\u0628\u0629 \u0627\u0644\u0646\u062c\u0627\u062d: " + str(round(wr, 1)) + "%</b>\n"
        + pnl_ico + " <b>\u0625\u062c\u0645\u0627\u0644\u064a: " + sign + str(round(total_pct, 2)) + "%</b>\n"
        "\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\n"
        "\U0001f3af TP3:" + str(tp3_c) + " | TP2:" + str(tp2_c) + " | TP1:" + str(tp1_c) + " | SL:" + str(len(losses)) + "\n"
        "\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\n"
        "<b>\u0623\u062f\u0627\u0621 \u0643\u0644 \u0646\u0648\u0639 \u0625\u0634\u0627\u0631\u0629:</b>" + type_lines + "\n"
        "\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015\u2015"
    )
    if wins:
        best = max(wins, key=lambda x: x["pct"])
        avg_win = sum(t["pct"] for t in wins) / len(wins)
        msg += "\n\U0001f3c6 \u0623\u0641\u0636\u0644 \u0635\u0641\u0642\u0629: #" + str(best["id"]) + " " + best["sym"] + " +" + str(round(best["pct"], 2)) + "%"
        msg += "\n\U0001f4c8 \u0645\u062a\u0648\u0633\u0637 \u0627\u0644\u0631\u0628\u062d: +" + str(round(avg_win, 2)) + "%"
    if losses:
        avg_loss = sum(t["pct"] for t in losses) / len(losses)
        msg += "\n\U0001f4c9 \u0645\u062a\u0648\u0633\u0637 \u0627\u0644\u062e\u0633\u0627\u0631\u0629: " + str(round(avg_loss, 2)) + "%"
    return msg


def gen_signal_check_report(trade, res):
    labels = {"TP3": "\U0001f3af TP3", "TP2": "\u2705 TP2", "TP1": "\U0001f44d TP1", "TP1+SL": "\u26a0\ufe0f TP1+SL", "SL": "\u274c SL"}
    label = labels.get(res["result"], "?")
    sign = "+" if res["pct"] > 0 else ""
    return (
        label + " <b>\u0646\u062a\u064a\u062c\u0629 \u0625\u0634\u0627\u0631\u0629 #" + str(trade["id"]) + " \u2014 " + trade["sym"] + "</b>\n"
        "\u0646\u0648\u0639: " + trade["type"] + "\n"
        "\u062f\u062e\u0648\u0644: $" + str(round(trade["entry"], 6)) + "\n"
        "\u062e\u0631\u0648\u062c: $" + str(round(res["exit_price"], 6)) + "\n"
        "\u0627\u0644\u0646\u062a\u064a\u062c\u0629: " + res["result"] + " | " + sign + str(round(res["pct"], 2)) + "%\n"
        "\u0628\u0639\u062f " + str(CFG["check_after_hours"]) + " \u0633\u0627\u0639\u0627\u062a"
    )


def ema_h(data, p):
    if len(data) < p:
        return []
    k = 2.0 / (p + 1)
    result = [None] * (p - 1)
    e = sum(data[:p]) / p
    result.append(e)
    for i in range(p, len(data)):
        e = data[i] * k + e * (1 - k)
        result.append(e)
    return result


def ema(data, p):
    h = ema_h(data, p)
    return h[-1] if h else None


def sma(data, p):
    if len(data) < p:
        return None
    return sum(data[-p:]) / p


def rsi(closes, p=14):
    if len(closes) < p + 1:
        return None
    g = 0.0
    lo = 0.0
    for i in range(len(closes) - p, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0:
            g += d
        else:
            lo -= d
    denom = lo if lo != 0 else 0.0001
    return 100.0 - 100.0 / (1.0 + g / denom)


def atr(H, L, C, p):
    if len(C) < p + 1:
        return None
    total = 0.0
    for i in range(len(C) - p, len(C)):
        tr = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
        total += tr
    return total / p


def macd(closes):
    if len(closes) < 35:
        return None, None
    fh = ema_h(closes, 12)
    sh = ema_h(closes, 26)
    ma = [f - s for f, s in zip(fh, sh) if f is not None and s is not None]
    if len(ma) >= 9:
        return ma[-1], ema(ma, 9)
    return None, None


def roc(closes, bars=3):
    if len(closes) < bars + 1:
        return 0.0
    return (closes[-1] - closes[-bars - 1]) / closes[-bars - 1] * 100.0


def detect_trendline_break(H, L, C, V, lookback=20):
    if len(H) < lookback + 2:
        return False, 0, 0
    local_highs = []
    for i in range(2, lookback):
        idx = len(H) - i
        if idx < 1:
            continue
        if H[idx] > H[idx - 1] and H[idx] > H[idx + 1]:
            local_highs.append((idx, H[idx]))
    if len(local_highs) < 2:
        return False, 0, 0
    h1_idx, h1_val = local_highs[0]
    h2_idx, h2_val = local_highs[1]
    if h1_val >= h2_val:
        return False, 0, 0
    if h1_idx <= h2_idx:
        return False, 0, 0
    slope = (h1_val - h2_val) / (h1_idx - h2_idx)
    trend_level = h1_val + slope * (len(H) - 1 - h1_idx)
    curr_close = C[-1]
    prev_close = C[-2]
    curr_vol = V[-1]
    avg_vol = sma(V, 20)
    broke_trend = curr_close > trend_level and prev_close <= trend_level
    vol_confirm = avg_vol is not None and curr_vol > avg_vol * CFG["breakout_vol_mult"]
    return broke_trend and vol_confirm, trend_level, slope


def run_ghp(klines_1h, klines_15m=None):
    if not klines_1h or len(klines_1h) < 60:
        return None
    try:
        H1 = [float(k[2]) for k in klines_1h]
        L1 = [float(k[3]) for k in klines_1h]
        C1 = [float(k[4]) for k in klines_1h]
        V1 = [float(k[5]) for k in klines_1h]
        O1 = [float(k[1]) for k in klines_1h]
    except Exception:
        return None
    n = len(C1)
    av1 = atr(H1, L1, C1, 14)
    rv1 = rsi(C1, 14)
    ef1 = ema(C1, 9)
    es1 = ema(C1, 21)
    et1 = ema(C1, 50)
    va1 = sma(V1, 20)
    mv1, ms1 = macd(C1)
    fh1 = ema_h(C1, 9)
    sh1 = ema_h(C1, 21)
    pf1 = fh1[-2] if len(fh1) >= 2 else None
    ps1 = sh1[-2] if len(sh1) >= 2 else None
    cross_1h = bool(pf1 is not None and ps1 is not None and pf1 <= ps1 and ef1 is not None and es1 is not None and ef1 > es1)
    cl1 = C1[-1]
    op1 = O1[-1]
    pc1 = C1[-2]
    po1 = O1[-2]
    vol1 = V1[-1]
    hv1 = bool(va1 is not None and vol1 > va1 * CFG["vol_mult"])
    rh1 = bool(rv1 is not None and 50 < rv1 < CFG["rsi_ob"])
    at1 = bool(et1 is not None and cl1 > et1)
    mb1 = bool(mv1 is not None and ms1 is not None and mv1 > ms1)
    be1 = cl1 > op1 and pc1 < po1 and cl1 > po1 and op1 < pc1
    body1 = abs(cl1 - op1)
    bodies1 = [abs(C1[i] - O1[i]) for i in range(max(0, n - 11), n - 1)]
    ab1 = sum(bodies1) / len(bodies1) if bodies1 else 1.0
    sc1 = body1 > ab1 * 1.3 and cl1 > op1
    h20_1 = max(H1[-21:-1]) if n >= 21 else H1[-1]
    br1 = H1[-1] >= h20_1 and cl1 > op1
    roc_1h = roc(C1, CFG["roc_bars"])
    momentum_1h = roc_1h >= CFG["roc_min_pct"]
    tb_1h, _, _ = detect_trendline_break(H1, L1, C1, V1, CFG["trend_lookback"])
    score = 0
    if cross_1h: score += 2
    if hv1: score += 2
    if rh1: score += 1
    if at1: score += 1
    if mb1: score += 1
    if be1: score += 1
    if sc1: score += 1
    if br1: score += 1
    if momentum_1h: score += 1
    if tb_1h: score += 2
    if score >= 10: st = 5
    elif score >= 8: st = 4
    elif score >= 6: st = 3
    elif score >= 4: st = 2
    else: st = 1
    cross_15m = False
    tb_15m = False
    roc_15m = 0.0
    momentum_15m = False
    if klines_15m and len(klines_15m) >= 30:
        try:
            H15 = [float(k[2]) for k in klines_15m]
            L15 = [float(k[3]) for k in klines_15m]
            C15 = [float(k[4]) for k in klines_15m]
            V15 = [float(k[5]) for k in klines_15m]
            ef15 = ema(C15, 9)
            es15 = ema(C15, 21)
            fh15 = ema_h(C15, 9)
            sh15 = ema_h(C15, 21)
            pf15 = fh15[-2] if len(fh15) >= 2 else None
            ps15 = sh15[-2] if len(sh15) >= 2 else None
            cross_15m = bool(pf15 is not None and ps15 is not None and pf15 <= ps15 and ef15 is not None and es15 is not None and ef15 > es15)
            tb_15m, _, _ = detect_trendline_break(H15, L15, C15, V15, min(20, len(H15) - 2))
            roc_15m = roc(C15, 3)
            momentum_15m = roc_15m >= CFG["roc_min_pct"]
        except Exception:
            pass
    strong_buy = cross_1h and rh1 and hv1 and at1 and mb1 and (be1 or sc1) and st >= 4 and score >= 8
    breakout_buy = tb_1h and hv1 and mb1 and rv1 is not None and rv1 > 40 and not strong_buy
    early_15m = (cross_15m or tb_15m) and momentum_15m and at1 and mb1
    early_buy = early_15m and rv1 is not None and rv1 > 40 and hv1 and not strong_buy and not breakout_buy
    momentum_buy = momentum_1h and roc_1h >= CFG["momentum_roc_min"] and hv1 and mb1 and rv1 is not None and rv1 > CFG["momentum_rsi_min"] and at1 and not strong_buy and not breakout_buy and not early_buy
    early_cond = sum([rh1, hv1, at1, mb1, bool(be1 or sc1)])
    reentry = early_cond >= 3 and momentum_1h and not strong_buy and not breakout_buy and not early_buy and not momentum_buy
    if av1 is None:
        return None
    tp1 = cl1 + av1 * CFG["tp1_mult"]
    tp2 = cl1 + av1 * CFG["tp2_mult"]
    tp3 = cl1 + av1 * CFG["tp3_mult"]
    sl = cl1 - av1 * CFG["sl_mult"]
    t2p = (tp2 / cl1 - 1) * 100
    slp = (1 - sl / cl1) * 100
    rr = t2p / (slp if slp != 0 else 1)
    vr = vol1 / va1 if va1 else 0
    rsi_warning = bool(rv1 is not None and rv1 > CFG["rsi_max_signal"])
    rsi_extreme = bool(rv1 is not None and rv1 > CFG["rsi_extreme_block"])
    return {
        "strong_buy": strong_buy, "breakout_buy": breakout_buy,
        "early_buy": early_buy, "momentum_buy": momentum_buy, "reentry": reentry,
        "any_buy": strong_buy or breakout_buy or early_buy or momentum_buy,
        "st": st, "score": score, "cl": cl1,
        "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "t1p": (tp1 / cl1 - 1) * 100, "t2p": t2p, "t3p": (tp3 / cl1 - 1) * 100,
        "slp": slp, "rr": rr, "rsi": rv1, "vr": vr,
        "roc_1h": roc_1h, "roc_15m": roc_15m,
        "tb_1h": tb_1h, "tb_15m": tb_15m,
        "cross_1h": cross_1h, "cross_15m": cross_15m,
        "hv": hv1, "rh": rh1, "at": at1, "mb": mb1, "momentum": momentum_1h,
        "rsi_warning": rsi_warning, "rsi_extreme": rsi_extreme,
    }


def get_market_state():
    try:
        k = requests.get(BINANCE_BASE + "/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "1h", "limit": 55}, timeout=10).json()
        if not k or len(k) < 50:
            return "NEUTRAL", 0, 0
        C = [float(x[4]) for x in k]
        chg_4h = (C[-1] - C[-4]) / C[-4] * 100
        chg_24h = (C[-1] - C[-24]) / C[-24] * 100
        k2 = 2.0 / 51
        e = sum(C[:50]) / 50
        for i in range(50, len(C)):
            e = C[i] * k2 + e * (1 - k2)
        btc_above_ema50 = C[-1] > e
        tickers = requests.get(BINANCE_BASE + "/api/v3/ticker/24hr", timeout=10).json()
        gainer_ratio = 0.5
        if isinstance(tickers, list):
            usdt = [t for t in tickers if isinstance(t, dict) and t.get("symbol", "").endswith("USDT")]
            gainers = len([t for t in usdt if float(t.get("priceChangePercent", 0)) > 0])
            gainer_ratio = gainers / len(usdt) if usdt else 0.5
        bull_score = 0
        if chg_4h > 0.5: bull_score += 2
        if chg_4h > -0.5: bull_score += 1
        if chg_24h > 1: bull_score += 2
        if chg_24h > -2: bull_score += 1
        if btc_above_ema50: bull_score += 2
        if gainer_ratio > 0.55: bull_score += 2
        if bull_score >= 7: state = "BULL"
        elif bull_score >= 4: state = "NEUTRAL"
        else: state = "BEAR"
        print("Market: " + state + " 4h:" + str(round(chg_4h, 2)) + "%")
        return state, chg_4h, chg_24h
    except Exception as e:
        print("market error: " + str(e))
        return "NEUTRAL", 0, 0


def check_btc():
    try:
        k = requests.get(BINANCE_BASE + "/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "1h", "limit": 5}, timeout=10).json()
        if not k or len(k) < 2:
            return True, 0
        C = [float(x[4]) for x in k]
        chg = (C[-1] - C[-4]) / C[-4] * 100
        return chg >= CFG["btc_filter_pct"], chg
    except Exception:
        return True, 0


def get_tickers():
    try:
        r = requests.get(BINANCE_BASE + "/api/v3/ticker/24hr", timeout=15).json()
        return r if isinstance(r, list) else []
    except Exception:
        return []


def filter_gainers(tickers, min_pct, max_pct, top_n):
    filtered = []
    for t in tickers:
        if not isinstance(t, dict):
            continue
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        if any(x in sym for x in ["DOWN", "UP", "BEAR", "BULL"]):
            continue
        pct = float(t.get("priceChangePercent", 0))
        vol = float(t.get("quoteVolume", 0))
        if min_pct <= pct <= max_pct and vol > CFG["min_volume_usd"]:
            filtered.append(t)
    filtered.sort(key=lambda x: float(x.get("priceChangePercent", 0)), reverse=True)
    return filtered[:top_n]


def get_klines(sym, tf, limit=120):
    try:
        return requests.get(BINANCE_BASE + "/api/v3/klines", params={"symbol": sym, "interval": tf, "limit": limit}, timeout=15).json()
    except Exception:
        return []


def send_tg(msg):
    if not TELEGRAM_TOKEN:
        return
    try:
        requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print("TG error: " + str(e))


STAR5 = "\u2605\u2605\u2605\u2605\u2605"
STAR4 = "\u2605\u2605\u2605\u2605\u2606"
STAR3 = "\u2605\u2605\u2605\u2606\u2606"
STAR2 = "\u2605\u2605\u2606\u2606\u2606"
STAR1 = "\u2605\u2606\u2606\u2606\u2606"
STARS_MAP = {5: STAR5, 4: STAR4, 3: STAR3, 2: STAR2, 1: STAR1}

ICO_MONEY  = "\U0001f4b0"
ICO_TARGET = "\U0001f3af"
ICO_STOP   = "\U0001f6d1"
ICO_CHART  = "\U0001f4ca"
ICO_UP     = "\U0001f4c8"
ICO_BOLT   = "\u26a1"
ICO_CLOCK  = "\U0001f550"
ICO_WARN   = "\u26a0\ufe0f"
ICO_CHECK  = "\u2705"
ICO_ROCKET = "\U0001f680"
ICO_BOOM   = "\U0001f4a5"
ICO_FIRE   = "\U0001f525"
ICO_CYCLE  = "\U0001f504"
ICO_RED    = "\U0001f534"
ICO_GREEN  = "\U0001f7e2"
ICO_ARROW  = "\u27a1\ufe0f"

TXT_ENTRY  = "\u062f\u062e\u0648\u0644"
TXT_STR    = "\u0642\u0648\u0629"
TXT_PTS    = "\u0646\u0642\u0627\u0637"
TXT_VOL    = "\u062d\u062c\u0645"
TXT_MOM    = "\u0632\u062e\u0645"
TXT_EARLY  = "\u062f\u062e\u0648\u0644 \u0645\u0628\u0643\u0631"
TXT_WAVE   = "\u0645\u0648\u062c\u0629 \u062c\u062f\u064a\u062f\u0629"
TXT_TODAY  = "\u0627\u0644\u064a\u0648\u0645"
TXT_BREAK  = "\u0643\u0633\u0631 \u0627\u0644\u062a\u0631\u0646\u062f \u0627\u0644\u0647\u0627\u0628\u0637 + \u0625\u063a\u0644\u0627\u0642 \u0641\u0648\u0642\u0647"
TXT_ALSO   = "\u0643\u0633\u0631 15m \u0623\u064a\u0636\u0627!"
TXT_CONF   = "\u062a\u0623\u0643\u064a\u062f 1h"
TXT_CROSS  = "EMA Cross 15m"
TXT_TBRK   = "\u0643\u0633\u0631 \u062a\u0631\u0646\u062f 15m"
TXT_FULL   = "EMA Cross + GHP \u0643\u0627\u0645\u0644"
TXT_DISC   = "\u062a\u062d\u0644\u064a\u0644 \u0641\u0642\u0637 \u2014 \u0644\u064a\u0633\u062a \u0646\u0635\u064a\u062d\u0629 \u0645\u0627\u0644\u064a\u0629"
TXT_24H    = "\u0627\u0631\u062a\u0641\u0627\u0639 24h"
TXT_RSIH   = "RSI \u0645\u0631\u062a\u0641\u0639"


def _base(r, gain):
    g = "\n" + ICO_CHART + " " + TXT_24H + ": +" + str(round(gain, 1)) + "%" if gain > 0 else ""
    rsi_warn = "\n" + ICO_WARN + " " + TXT_RSIH + ": " + str(round(r["rsi"], 1)) if r.get("rsi_warning") and r["rsi"] else ""
    rr_ok = ICO_CHECK if r["rr"] >= CFG["min_rr"] else ICO_WARN
    rsi_val = str(round(r["rsi"], 1)) if r["rsi"] else "N/A"
    return (
        ICO_MONEY + " " + TXT_ENTRY + ": $" + str(round(r["cl"], 6)) + g + rsi_warn + "\n"
        + ICO_TARGET + " TP1: $" + str(round(r["tp1"], 6)) + " (+" + str(round(r["t1p"], 2)) + "%)\n"
        + ICO_TARGET + " TP2: $" + str(round(r["tp2"], 6)) + " (+" + str(round(r["t2p"], 2)) + "%)\n"
        + ICO_TARGET + " TP3: $" + str(round(r["tp3"], 6)) + " (+" + str(round(r["t3p"], 2)) + "%)\n"
        + ICO_STOP + " SL:  $" + str(round(r["sl"], 6)) + "  (-" + str(round(r["slp"], 2)) + "%)\n"
        + ICO_CHART + " R:R: 1:" + str(round(r["rr"], 2)) + " " + rr_ok + "\n"
        + ICO_UP + " RSI: " + rsi_val + " | " + TXT_VOL + ": " + str(round(r["vr"], 1)) + "x\n"
        + ICO_BOLT + " " + TXT_MOM + " 1h: " + str(round(r["roc_1h"], 2)) + "% | 15m: " + str(round(r["roc_15m"], 2)) + "%\n"
        + ICO_CLOCK + " " + datetime.now(timezone.utc).strftime("%H:%M:%S") + " UTC\n"
        + ICO_WARN + " <i>" + TXT_DISC + "</i>"
    )


def send_signal(sym, signal_type, r, gain):
    trade_id = log_signal(sym, signal_type, r["cl"], r["tp1"], r["tp2"], r["tp3"], r["sl"], r["rr"], gain)
    st_label = STARS_MAP.get(r["st"], STAR1)
    if signal_type == "STRONG":
        msg = (
            ICO_ROCKET + " <b>STRONG BUY #" + str(trade_id) + " \u2014 " + sym + "</b>\n"
            + st_label + " " + TXT_STR + ": " + str(r["st"]) + "/5 | " + TXT_PTS + ": " + str(r["score"]) + "/12\n"
            + ICO_CHECK + " 1h: " + TXT_FULL + "\n"
            + _base(r, gain)
        )
    elif signal_type == "BREAKOUT":
        tb15 = ICO_CHECK + " " + TXT_ALSO if r["tb_15m"] else ""
        msg = (
            ICO_BOOM + " <b>BREAKOUT BUY #" + str(trade_id) + " \u2014 " + sym + "</b>\n"
            + st_label + " " + TXT_STR + ": " + str(r["st"]) + "/5\n"
            + ICO_RED + ICO_ARROW + ICO_GREEN + " " + TXT_BREAK + " " + tb15 + "\n"
            + _base(r, gain)
        )
    elif signal_type == "EARLY":
        src = TXT_CROSS if r["cross_15m"] else TXT_TBRK
        msg = (
            ICO_BOLT + " <b>EARLY BUY #" + str(trade_id) + " \u2014 " + sym + "</b>\n"
            + st_label + " " + TXT_STR + ": " + str(r["st"]) + "/5 | " + TXT_EARLY + "\n"
            + ICO_CHART + " " + src + " + " + TXT_CONF + "\n"
            + _base(r, gain)
        )
    elif signal_type == "MOMENTUM":
        msg = (
            ICO_FIRE + " <b>MOMENTUM BUY #" + str(trade_id) + " \u2014 " + sym + "</b>\n"
            + st_label + " " + TXT_STR + ": " + str(r["st"]) + "/5\n"
            + ICO_BOLT + " " + TXT_MOM + ": " + str(round(r["roc_1h"], 2)) + "%\n"
            + _base(r, gain)
        )
    else:
        msg = (
            ICO_CYCLE + " <b>RE-ENTRY #" + str(trade_id) + " \u2014 " + sym + "</b>\n"
            + ICO_CHART + " +" + str(round(gain, 1)) + "% " + TXT_TODAY + " | " + TXT_WAVE + "\n"
            + st_label + " " + TXT_STR + ": " + str(r["st"]) + "/5\n"
            + _base(r, gain)
        )
    send_tg(msg)


def run_scan(fast=False):
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
    label = "\u26a1 \u0645\u0633\u062d \u0633\u0631\u064a\u0639 15\u062f" if fast else "\U0001f50d \u0645\u0633\u062d \u0631\u0626\u064a\u0633\u064a 1\u0633"
    print("[" + now_str + "] scan...")
    today_count = daily_signals_count()
    if today_count >= CFG["max_signals_per_day"]:
        print("Daily limit: " + str(today_count))
        return
    if not fast:
        market_state, btc_4h, btc_24h = get_market_state()
    else:
        btc_ok, btc_4h = check_btc()
        market_state = "BEAR" if not btc_ok else "NEUTRAL"
        btc_24h = 0
    state_emoji = {"BULL": "\U0001f7e2", "NEUTRAL": "\U0001f7e1", "BEAR": "\U0001f534"}.get(market_state, "\U0001f7e1")
    btc_s = state_emoji + " " + market_state + " | BTC " + str(round(btc_4h, 2)) + "%"
    if market_state == "BEAR" and btc_4h < CFG["btc_filter_pct"]:
        if not fast:
            send_tg("\U0001f534 <b>\u0633\u0648\u0642 \u0647\u0627\u0628\u0637 \u2014 \u0625\u064a\u0642\u0627\u0641 \u0627\u0644\u0625\u0634\u0627\u0631\u0627\u062a</b>\nBTC " + str(round(btc_4h, 2)) + "% 4h\n\U0001f550 " + now_str)
        return
    tickers = get_tickers()
    if not tickers:
        return
    normal = filter_gainers(tickers, CFG["min_gain_pct"], 25.0, CFG["top_n"])
    reentry_c = filter_gainers(tickers, CFG["reentry_min_gain"], CFG["max_gain_pct"], 20)
    results = []
    strong = []
    breakout = []
    early = []
    momentum = []
    reentry = []
    for t in normal:
        sym = t["symbol"]
        gain = float(t.get("priceChangePercent", 0))
        if already_traded_today(sym):
            continue
        try:
            r = run_ghp(get_klines(sym, CFG["tf_main"], 120), get_klines(sym, CFG["tf_fast"], 60))
            if r:
                if r.get("rsi_extreme"):
                    time.sleep(0.15)
                    continue
                r["sym"] = sym
                r["gain"] = gain
                results.append(r)
                if r["strong_buy"] and r["rr"] >= CFG["min_rr"]:
                    strong.append(r)
                elif r["breakout_buy"] and r["rr"] >= 1.5 and market_state != "BEAR":
                    breakout.append(r)
                elif r["early_buy"] and r["rr"] >= 1.5 and market_state == "BULL":
                    early.append(r)
                elif r["momentum_buy"] and r["rr"] >= 1.5 and market_state == "BULL":
                    momentum.append(r)
            time.sleep(0.15)
        except Exception as e:
            print("err " + sym + ": " + str(e))
    reentry_syms = {t["symbol"] for t in normal}
    for t in reentry_c:
        sym = t["symbol"]
        gain = float(t.get("priceChangePercent", 0))
        if sym in reentry_syms:
            continue
        if already_traded_today(sym):
            continue
        if had_sl_today(sym):
            continue
        try:
            r = run_ghp(get_klines(sym, CFG["tf_main"], 120), get_klines(sym, CFG["tf_fast"], 60))
            if r and r["rr"] >= 1.5 and r["momentum"] and r["hv"] and r["mb"]:
                if r["rsi"] is not None and r["rsi"] > CFG["rsi_max_reentry"]:
                    time.sleep(0.15)
                    continue
                if r.get("rsi_extreme"):
                    time.sleep(0.15)
                    continue
                r["sym"] = sym
                r["gain"] = gain
                reentry.append(r)
            time.sleep(0.15)
        except Exception as e:
            print("err " + sym + ": " + str(e))
    strong.sort(key=lambda x: (x["st"], x["rr"]), reverse=True)
    breakout.sort(key=lambda x: (x.get("tb_15m", False), x["rr"]), reverse=True)
    early.sort(key=lambda x: x["rr"], reverse=True)
    momentum.sort(key=lambda x: x["roc_1h"], reverse=True)
    reentry.sort(key=lambda x: x["rr"], reverse=True)
    send_tg(
        label + " \u2014 GHP Pro v5\n"
        + btc_s + "\n"
        + "\U0001f4ca \u0645\u062d\u0644\u0644: " + str(len(results))
        + " | \U0001f680 " + str(len(strong))
        + " | \U0001f4a5 " + str(len(breakout))
        + " | \u26a1 " + str(len(early))
        + " | \U0001f525 " + str(len(momentum))
        + " | \U0001f504 " + str(len(reentry)) + "\n"
        + "\U0001f4cb \u0625\u0634\u0627\u0631\u0627\u062a \u0627\u0644\u064a\u0648\u0645: " + str(today_count) + "/" + str(CFG["max_signals_per_day"]) + "\n"
        + "\U0001f550 " + now_str + " UTC"
    )
    for r in strong[:3]:   send_signal(r["sym"], "STRONG",   r, r["gain"]); time.sleep(0.5)
    for r in breakout[:3]: send_signal(r["sym"], "BREAKOUT", r, r["gain"]); time.sleep(0.5)
    for r in early[:2]:    send_signal(r["sym"], "EARLY",    r, r["gain"]); time.sleep(0.5)
    for r in momentum[:2]: send_signal(r["sym"], "MOMENTUM", r, r["gain"]); time.sleep(0.5)
    for r in reentry[:3]:  send_signal(r["sym"], "REENTRY",  r, r["gain"]); time.sleep(0.5)
    print("done: " + str(len(strong)) + "S " + str(len(breakout)) + "B " + str(len(early)) + "E " + str(len(momentum)) + "M " + str(len(reentry)) + "R")


last_daily_report = -1
last_weekly_report = -1


def check_reports():
    global last_daily_report, last_weekly_report
    now = datetime.now(timezone.utc)
    if now.hour == CFG["daily_report_hour"] and 0 <= now.minute < 60:
        if last_daily_report != now.day:
            send_tg(gen_daily_report())
            last_daily_report = now.day
            print("sent daily report")
    if now.weekday() == CFG["weekly_report_day"] and now.hour == CFG["weekly_report_hour"] and now.minute < 60:
        week = now.isocalendar()[1]
        if last_weekly_report != week:
            send_tg(gen_weekly_report())
            last_weekly_report = week
            print("sent weekly report")
    updated = update_pending_trades()
    for trade, res in updated:
        send_tg(gen_signal_check_report(trade, res))
        print("#" + str(trade["id"]) + " " + trade["sym"] + ": " + res["result"] + " " + str(round(res["pct"], 2)) + "%")


if __name__ == "__main__":
    print("GHP Pro v5 starting...")
    data = load_trades()
    send_tg(
        "\u26a1 <b>GHP Pro v5 \u0628\u062f\u0623!</b>\n\n"
        "<b>\U0001f6e1 \u0627\u0644\u0625\u0635\u0644\u0627\u062d\u0627\u062a:</b>\n"
        "1) \u062d\u0638\u0631 \u062a\u0643\u0631\u0627\u0631 \u0646\u0641\u0633 \u0627\u0644\u0639\u0645\u0644\u0629 \u064a\u0648\u0645\u064a\u0627\n"
        "2) \u062d\u0638\u0631 RSI \u0641\u0648\u0642 78 \u0641\u064a REENTRY\n"
        "3) \u0631\u0641\u0639 \u062d\u062f REENTRY \u0625\u0644\u0649 +20%\n"
        "4) \u062d\u062f \u0623\u0642\u0635\u0649 " + str(CFG["max_signals_per_day"]) + " \u0625\u0634\u0627\u0631\u0629 \u064a\u0648\u0645\u064a\u0627\n"
        "5) \u0645\u0646\u0639 REENTRY \u0628\u0639\u062f SL \u0646\u0641\u0633 \u0627\u0644\u0639\u0645\u0644\u0629\n"
        "6) STRONG \u064a\u062d\u062a\u0627\u062c score 8+\n"
        "7) \u062a\u0642\u0631\u064a\u0631 \u064a\u0648\u0645\u064a 22:00 \u0628\u062a\u0648\u0642\u064a\u062a \u0627\u0644\u0633\u0639\u0648\u062f\u064a\u0629\n\n"
        "\U0001f4e6 \u0635\u0641\u0642\u0627\u062a: " + str(data["stats"]["total"]) + "\n"
        "\u2705 \u0631\u0627\u0628\u062d\u0629: " + str(data["stats"]["wins"]) + " | \u274c \u062e\u0627\u0633\u0631\u0629: " + str(data["stats"]["losses"])
    )
    while True:
        try:
            run_scan(fast=False)
            check_reports()
            for _ in range(3):
                time.sleep(CFG["fast_interval"] * 60)
                run_scan(fast=True)
                check_reports()
            time.sleep(CFG["fast_interval"] * 60)
        except KeyboardInterrupt:
            send_tg("\u23f9 GHP Pro v5 \u062a\u0648\u0642\u0641")
            break
        except Exception as e:
            print("ERROR: " + str(e))
            time.sleep(60)
