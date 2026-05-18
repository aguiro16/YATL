import numpy as np
import pandas as pd


def detect_descending_channel(highs: list, lows: list, lookback: int = 30) -> dict:
    if len(highs) < lookback or len(lows) < lookback:
        return {"is_channel": False}

    h = np.array(highs[-lookback:])
    l = np.array(lows[-lookback:])
    x = np.arange(lookback)

    high_slope, high_intercept = np.polyfit(x, h, 1)
    low_slope, low_intercept = np.polyfit(x, l, 1)

    is_descending = high_slope < 0 and low_slope < 0

    h_pred = high_slope * x + high_intercept
    ss_res = np.sum((h - h_pred) ** 2)
    ss_tot = np.sum((h - np.mean(h)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

    return {
        "is_channel": is_descending and r2 > 0.55,
        "upper_slope": high_slope,
        "lower_slope": low_slope,
        "high_intercept": high_intercept,
        "low_intercept": low_intercept,
        "channel_strength": r2,
    }


def find_key_levels(highs: list, lows: list, tolerance: float = 0.012) -> list:
    all_levels = []
    highs_arr = np.array(highs)
    lows_arr = np.array(lows)

    for i in range(2, len(highs_arr) - 2):
        if (highs_arr[i] >= highs_arr[i-1] and
                highs_arr[i] >= highs_arr[i+1] and
                highs_arr[i] >= highs_arr[i-2] and
                highs_arr[i] >= highs_arr[i+2]):
            all_levels.append(float(highs_arr[i]))

    for i in range(2, len(lows_arr) - 2):
        if (lows_arr[i] <= lows_arr[i-1] and
                lows_arr[i] <= lows_arr[i+1] and
                lows_arr[i] <= lows_arr[i-2] and
                lows_arr[i] <= lows_arr[i+2]):
            all_levels.append(float(lows_arr[i]))

    all_levels = sorted(set(all_levels))
    merged = []
    for level in all_levels:
        if not merged:
            merged.append(level)
        else:
            if abs(level - merged[-1]) / merged[-1] > tolerance:
                merged.append(level)
            else:
                merged[-1] = round((merged[-1] + level) / 2, 8)

    return merged


def get_buy_zone(current_price: float, key_levels: list) -> tuple:
    supports = [l for l in key_levels if l <= current_price]
    if not supports:
        return None, None
    nearest_support = max(supports)
    buy_low  = round(nearest_support, 8)
    buy_high = round(current_price * 1.003, 8)
    return buy_low, buy_high


def get_stop_loss(buy_low: float, key_levels: list) -> float:
    supports_below = [l for l in key_levels if l < buy_low * 0.995]
    if supports_below:
        return round(max(supports_below) * 0.995, 8)
    else:
        return round(buy_low * 0.97, 8)


def get_targets(buy_high: float, key_levels: list, n: int = 5) -> dict:
    resistances = sorted([l for l in key_levels if l > buy_high])
    targets = {}
    for i in range(min(n, len(resistances))):
        targets[f"T{i+1}"] = round(resistances[i], 8)

    last_val = targets[f"T{len(targets)}"] if targets else buy_high
    idx = len(targets) + 1
    while len(targets) < n:
        last_val = round(last_val * 1.10, 8)
        targets[f"T{idx}"] = last_val
        idx += 1

    return targets


def analyze_pair(df_4h: pd.DataFrame, df_1d: pd.DataFrame, symbol: str) -> dict | None:
    if df_4h is None or df_1d is None:
        return None
    if len(df_4h) < 35 or len(df_1d) < 30:
        return None

    highs_4h  = df_4h["high"].tolist()
    lows_4h   = df_4h["low"].tolist()
    closes_4h = df_4h["close"].tolist()
    highs_1d  = df_1d["high"].tolist()
    lows_1d   = df_1d["low"].tolist()

    current_price = closes_4h[-1]

    channel = detect_descending_channel(highs_4h, lows_4h, lookback=30)
    if not channel["is_channel"]:
        return None

    lookback = 30
    x_now = lookback - 1
    channel_bottom = channel["lower_slope"] * x_now + channel["low_intercept"]
    distance_to_bottom = abs(current_price - channel_bottom) / channel_bottom
    if distance_to_bottom > 0.05:
        return None

    key_levels = find_key_levels(highs_1d, lows_1d, tolerance=0.012)
    if len(key_levels) < 3:
        return None

    buy_low, buy_high = get_buy_zone(current_price, key_levels)
    if buy_low is None:
        return None

    stop    = get_stop_loss(buy_low, key_levels)
    targets = get_targets(buy_high, key_levels, n=5)
    if len(targets) < 3:
        return None

    entry_mid = round((buy_low + buy_high) / 2, 8)
    risk      = entry_mid - stop
    reward_t1 = targets.get("T1", entry_mid) - entry_mid
    rr        = round(reward_t1 / risk, 2) if risk > 0 else 0

    if rr < 1.2:
        return None

    return {
        "symbol":           symbol,
        "current_price":    current_price,
        "buy_zone":         (buy_low, buy_high),
        "stop":             stop,
        "targets":          targets,
        "rr":               rr,
        "channel_strength": round(channel["channel_strength"] * 100, 1),
    }
