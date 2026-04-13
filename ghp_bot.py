import os, time, requests, json
from datetime import datetime, timezone

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "400815773")
BINANCE_BASE     = "https://data-api.binance.vision"
TRADES_FILE      = "smc_trades.json"

CFG = {
    "top_n":60, "min_volume_usd":5000000,
    "min_gain_pct":1.0, "max_gain_pct":40.0,
    "scan_interval":60, "fast_interval":15,
    "tf_high":"4h", "tf_mid":"1h", "tf_entry":"15m",
    "structure_lookback":30, "ob_lookback":10,
    "fvg_min_pct":0.3, "vol_mult":1.5, "min_rr":2.0,
    "ote_low":0.618, "ote_high":0.786,
    "sl_buffer":0.005,
    "check_after_hours":4,
    "daily_report_hour":20,
    "btc_filter_pct":-2.0,
    "signal_cooldown_hours":6,
}

def load_trades():
    try:
        if os.path.exists(TRADES_FILE):
            with open(TRADES_FILE,"r") as f:
                return json.load(f)
    except: pass
    return {"trades":[],"stats":{"total":0,"wins":0,"losses":0,"pending":0}}

def save_trades(data):
    try:
        with open(TRADES_FILE,"w") as f:
            json.dump(data,f,indent=2)
    except Exception as e: print(f"خطأ حفظ: {e}")

def log_signal(sym, sig_type, entry, tp1, tp2, sl, rr, details):
    data=load_trades()
    trade={
        "id":len(data["trades"])+1,
        "sym":sym, "type":sig_type,
        "entry":entry, "tp1":tp1, "tp2":tp2, "sl":sl,
        "rr":rr, "details":details,
        "time":datetime.now(timezone.utc).isoformat(),
        "timestamp":time.time(),
        "result":"PENDING", "exit_price":0, "pct":0,
        "day":datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    data["trades"].append(trade)
    data["stats"]["total"]+=1
    data["stats"]["pending"]+=1
    save_trades(data)
    return trade["id"]

def check_trade_result(trade):
    try:
        sym=trade["sym"]; entry=trade["entry"]
        tp1=trade["tp1"]; tp2=trade["tp2"]; sl=trade["sl"]

        # تحديد نوع الصفقة: SHORT إذا كان SL أعلى من الدخول
        is_short = sl > entry

        klines=requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":sym,"interval":"15m","limit":20},timeout=10).json()
        if not klines or not isinstance(klines,list): return None
        t1=t2=hit_sl=False
        for k in klines:
            h=float(k[2]); l=float(k[3])
            if is_short:
                # SHORT: TP أقل من الدخول، SL أعلى
                if not t1 and l<=tp1: t1=True
                if t1 and not t2 and l<=tp2: t2=True
                if h>=sl and not t1: hit_sl=True; break
            else:
                # LONG: TP أعلى من الدخول، SL أقل
                if not t1 and h>=tp1: t1=True
                if t1 and not t2 and h>=tp2: t2=True
                if l<=sl and not t1: hit_sl=True; break

        if is_short:
            if t2:       result="TP2"; ep=tp2; pct=(entry/tp2-1)*100
            elif t1:     result="TP1"; ep=tp1; pct=(entry/tp1-1)*100
            elif hit_sl: result="SL";  ep=sl;  pct=(entry/sl-1)*100
            else:        ep=float(klines[-1][4]); pct=(entry/ep-1)*100; result="OPEN"
        else:
            if t2:       result="TP2"; ep=tp2; pct=(tp2/entry-1)*100
            elif t1:     result="TP1"; ep=tp1; pct=(tp1/entry-1)*100
            elif hit_sl: result="SL";  ep=sl;  pct=(sl/entry-1)*100
            else:        ep=float(klines[-1][4]); pct=(ep/entry-1)*100; result="OPEN"

        return {"result":result,"exit_price":ep,"pct":pct}
    except Exception as e:
        print(f"خطأ check {trade['sym']}: {e}"); return None

def update_pending_trades():
    data=load_trades(); now=time.time(); updated=[]
    for i,trade in enumerate(data["trades"]):
        if trade["result"]!="PENDING": continue
        if (now-trade["timestamp"])/3600>=CFG["check_after_hours"]:
            res=check_trade_result(trade)
            if res and res["result"]!="OPEN":
                data["trades"][i]["result"]=res["result"]
                data["trades"][i]["exit_price"]=res["exit_price"]
                data["trades"][i]["pct"]=res["pct"]
                data["stats"]["pending"]=max(0,data["stats"]["pending"]-1)
                if res["result"] in ["TP1","TP2"]: data["stats"]["wins"]+=1
                elif res["result"]=="SL": data["stats"]["losses"]+=1
                updated.append((trade,res))
    save_trades(data); return updated

def calc_rsi(closes, p=14):
    if len(closes)<p+1: return 50
    g=l=0
    for i in range(len(closes)-p,len(closes)):
        d=closes[i]-closes[i-1]
        if d>0: g+=d
        else: l-=d
    return 100-100/(1+(g/(l or 0.001)))

def calc_atr(H,L,C,p=14):
    if len(C)<p+1: return None
    return sum(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1]))
               for i in range(len(C)-p,len(C)))/p

def sma(data,p):
    return None if len(data)<p else sum(data[-p:])/p

def find_market_structure(klines):
    if len(klines)<10: return "NEUTRAL"
    H=[float(k[2]) for k in klines]
    L=[float(k[3]) for k in klines]
    n=len(klines)
    highs=[]; lows=[]
    for i in range(2,min(n-2,CFG["structure_lookback"])):
        idx=n-1-i
        if idx<1: continue
        if H[idx]>H[idx-1] and H[idx]>H[idx+1]: highs.append((idx,H[idx]))
        if L[idx]<L[idx-1] and L[idx]<L[idx+1]: lows.append((idx,L[idx]))
    if len(highs)<2 or len(lows)<2: return "NEUTRAL"
    highs.sort(key=lambda x:x[0]); lows.sort(key=lambda x:x[0])
    h1=highs[-2][1]; h2=highs[-1][1]
    l1=lows[-2][1];  l2=lows[-1][1]
    if h2>h1 and l2>l1: return "BULLISH"
    if h2<h1 and l2<l1: return "BEARISH"
    return "NEUTRAL"

def find_bos(klines):
    if len(klines)<15: return None
    H=[float(k[2]) for k in klines]
    L=[float(k[3]) for k in klines]
    C=[float(k[4]) for k in klines]
    V=[float(k[5]) for k in klines]
    n=len(klines)
    avg_v=sma(V,20) or V[-1]
    lookback=min(15,n-3)
    recent_high=max(H[-lookback-1:-1])
    recent_low =min(L[-lookback-1:-1])
    curr_close=C[-1]; curr_vol=V[-1]
    vol_confirm=curr_vol>avg_v*CFG["vol_mult"]
    if C[-1]>recent_high and C[-2]<=recent_high and vol_confirm:
        return {"type":"BULLISH","level":recent_high,"vol_ratio":curr_vol/avg_v}
    if C[-1]<recent_low and C[-2]>=recent_low and vol_confirm:
        return {"type":"BEARISH","level":recent_low,"vol_ratio":curr_vol/avg_v}
    return None

def find_choch(klines):
    if len(klines)<20: return None
    H=[float(k[2]) for k in klines]
    L=[float(k[3]) for k in klines]
    C=[float(k[4]) for k in klines]
    n=len(klines)
    lows=[]
    for i in range(2,min(20,n-2)):
        idx=n-1-i
        if L[idx]<L[idx-1] and L[idx]<L[idx+1]: lows.append(L[idx])
    highs=[]
    for i in range(2,min(20,n-2)):
        idx=n-1-i
        if H[idx]>H[idx-1] and H[idx]>H[idx+1]: highs.append(H[idx])
    if not lows or not highs: return None
    last_low=lows[0]; last_high=highs[0]
    if C[-1]>last_high and C[-2]<=last_high:
        return {"type":"BULLISH_CHOCH","level":last_high}
    if C[-1]<last_low and C[-2]>=last_low:
        return {"type":"BEARISH_CHOCH","level":last_low}
    return None

def find_order_block(klines, direction="BULLISH"):
    if len(klines)<5: return None
    O=[float(k[1]) for k in klines]
    H=[float(k[2]) for k in klines]
    L=[float(k[3]) for k in klines]
    C=[float(k[4]) for k in klines]
    n=len(klines)
    lookback=min(CFG["ob_lookback"],n-3)
    if direction=="BULLISH":
        for i in range(2,lookback+1):
            idx=n-1-i
            if idx<1: break
            if C[idx]<O[idx]:
                if C[idx+1]>O[idx+1] and (C[idx+1]-O[idx+1])>abs(C[idx]-O[idx])*0.8:
                    return {"top":O[idx],"bottom":C[idx],"mid":(O[idx]+C[idx])/2,"idx":idx}
    else:
        for i in range(2,lookback+1):
            idx=n-1-i
            if idx<1: break
            if C[idx]>O[idx]:
                if C[idx+1]<O[idx+1] and abs(C[idx+1]-O[idx+1])>abs(C[idx]-O[idx])*0.8:
                    return {"top":C[idx],"bottom":O[idx],"mid":(O[idx]+C[idx])/2,"idx":idx}
    return None

def find_fvg(klines, direction="BULLISH"):
    if len(klines)<5: return None
    H=[float(k[2]) for k in klines]
    L=[float(k[3]) for k in klines]
    C=[float(k[4]) for k in klines]
    n=len(klines); curr_price=C[-1]
    lookback=min(15,n-3); fvgs=[]
    for i in range(2,lookback+1):
        idx=n-1-i
        if idx<1 or idx+1>=n: continue
        if direction=="BULLISH":
            gap_top=L[idx+1]; gap_bot=H[idx-1]
            if gap_top>gap_bot:
                gs=(gap_top-gap_bot)/gap_bot*100
                if gs>=CFG["fvg_min_pct"]:
                    fvgs.append({"top":gap_top,"bot":gap_bot,"mid":(gap_top+gap_bot)/2,
                                 "size":gs,"in_fvg":gap_bot<=curr_price<=gap_top*1.02,
                                 "near_fvg":curr_price>gap_top and curr_price<gap_top*1.05,"idx":idx})
        else:
            gap_top=L[idx-1]; gap_bot=H[idx+1]
            if gap_top>gap_bot:
                gs=(gap_top-gap_bot)/gap_bot*100
                if gs>=CFG["fvg_min_pct"]:
                    fvgs.append({"top":gap_top,"bot":gap_bot,"mid":(gap_top+gap_bot)/2,
                                 "size":gs,"in_fvg":gap_bot<=curr_price<=gap_top*1.02,
                                 "near_fvg":False,"idx":idx})
    if fvgs: return min(fvgs,key=lambda x:abs(x["mid"]-curr_price))
    return None

def find_liquidity_sweep(klines):
    if len(klines)<10: return None
    H=[float(k[2]) for k in klines]
    L=[float(k[3]) for k in klines]
    C=[float(k[4]) for k in klines]
    O=[float(k[1]) for k in klines]
    n=len(klines)
    lookback=min(20,n-3)
    prev_high=max(H[-lookback-1:-2])
    prev_low =min(L[-lookback-1:-2])
    cl=C[-1]; op=O[-1]
    ph=float(klines[-2][2]); pl=float(klines[-2][3])
    pc=float(klines[-2][4]); po=float(klines[-2][1])
    bull_sweep=(pl<prev_low and pc>prev_low and cl>op and cl>pc)
    bear_sweep=(ph>prev_high and pc<prev_high and cl<op and cl<pc)
    if bull_sweep: return {"type":"BULLISH","swept_level":prev_low}
    if bear_sweep: return {"type":"BEARISH","swept_level":prev_high}
    return None

def calc_ote(swing_low, swing_high):
    rng=swing_high-swing_low
    return {
        "low": swing_high-rng*CFG["ote_high"],
        "high":swing_high-rng*CFG["ote_low"],
        "mid": swing_high-rng*0.702,
    }

def analyze_smc(sym, klines_4h, klines_1h, klines_15m):
    if not all([klines_4h,klines_1h,klines_15m]): return None
    if len(klines_4h)<30 or len(klines_1h)<30 or len(klines_15m)<20: return None
    trend_4h=find_market_structure(klines_4h)
    if trend_4h=="NEUTRAL": return None
    bos_1h=find_bos(klines_1h)
    choch_1h=find_choch(klines_1h)
    confirmed=False; signal_source=""
    if bos_1h and bos_1h["type"]==trend_4h:
        confirmed=True; signal_source="BOS"
    elif choch_1h:
        if choch_1h["type"]=="BULLISH_CHOCH" and trend_4h=="BULLISH":
            confirmed=True; signal_source="CHoCH"
        elif choch_1h["type"]=="BEARISH_CHOCH" and trend_4h=="BEARISH":
            confirmed=True; signal_source="CHoCH"
    if not confirmed: return None
    direction="BULLISH" if trend_4h=="BULLISH" else "BEARISH"
    ob=find_order_block(klines_15m,direction)
    fvg=find_fvg(klines_15m,direction)
    liq=find_liquidity_sweep(klines_15m)
    if not ob: return None
    C15=[float(k[4]) for k in klines_15m]
    H15=[float(k[2]) for k in klines_15m]
    L15=[float(k[3]) for k in klines_15m]
    rsi=calc_rsi(C15,14)
    atr=calc_atr(H15,L15,C15,14)
    curr_price=C15[-1]
    if not atr: return None
    if direction=="BULLISH" and (rsi>75 or rsi<30): return None
    if direction=="BEARISH" and (rsi<25 or rsi>70): return None
    swing_low=min(L15[-20:]); swing_high=max(H15[-20:])
    ote=calc_ote(swing_low,swing_high)
    in_ote=ote["low"]<=curr_price<=ote["high"]
    near_ote=(curr_price<ote["high"]*1.03 if direction=="BULLISH"
              else curr_price>ote["low"]*0.97)
    confluence=0; conf_details=[]
    if trend_4h!="NEUTRAL":   confluence+=2; conf_details.append(f"4H {trend_4h}")
    if bos_1h:                confluence+=2; conf_details.append("BOS 1H")
    if choch_1h:              confluence+=2; conf_details.append("CHoCH 1H")
    if ob:                    confluence+=2; conf_details.append("Order Block")
    if fvg and (fvg.get("in_fvg") or fvg.get("near_fvg")):
                              confluence+=2; conf_details.append("FVG")
    if liq and liq["type"]==direction:
                              confluence+=2; conf_details.append("Liq Sweep")
    if in_ote:                confluence+=2; conf_details.append("OTE ✅")
    elif near_ote:            confluence+=1; conf_details.append("Near OTE")
    if confluence<6: return None
    if direction=="BULLISH":
        entry=curr_price; sl=ob["bottom"]*(1-CFG["sl_buffer"])
        if sl>=entry: sl=entry*0.98
        tp1_level=bos_1h["level"] if bos_1h else entry+(entry-sl)*2
        tp1=max(tp1_level,entry+(entry-sl)*2.0)
        tp2=max(entry+(tp1-entry)*1.618,entry+(entry-sl)*4.0)
        rr=(tp1-entry)/(entry-sl) if entry>sl else 0
    else:
        entry=curr_price; sl=ob["top"]*(1+CFG["sl_buffer"])
        if sl<=entry: sl=entry*1.02
        tp1_level=bos_1h["level"] if bos_1h else entry-(sl-entry)*2
        tp1=min(tp1_level,entry-(sl-entry)*2.0)
        tp2=min(entry-(tp1-entry)*1.618,entry-(sl-entry)*4.0) if tp1<entry else entry-(sl-entry)*4
        rr=(entry-tp1)/(sl-entry) if sl>entry else 0
    if rr<CFG["min_rr"]: return None
    if direction=="BULLISH" and tp1<=entry: return None
    if direction=="BEARISH" and tp1>=entry: return None
    return {
        "signal":direction, "source":signal_source,
        "entry":entry, "tp1":tp1, "tp2":tp2, "sl":sl,
        "t1p":abs(tp1/entry-1)*100, "t2p":abs(tp2/entry-1)*100,
        "slp":abs(sl/entry-1)*100, "rr":rr,
        "rsi":rsi, "atr":atr,
        "confluence":confluence, "conf_details":conf_details,
        "ob":ob, "fvg":fvg, "liq":liq,
        "ote":ote, "in_ote":in_ote,
        "trend_4h":trend_4h, "bos":bos_1h, "choch":choch_1h,
    }

def get_market_state():
    try:
        k=requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":"BTCUSDT","interval":"4h","limit":50},timeout=10).json()
        if not k or len(k)<30: return "NEUTRAL",0,0
        C=[float(x[4]) for x in k]
        chg_4h=(C[-1]-C[-2])/C[-2]*100
        chg_24h=(C[-1]-C[-6])/C[-6]*100
        trend=find_market_structure(k)
        return trend,chg_4h,chg_24h
    except: return "NEUTRAL",0,0

def check_btc():
    try:
        k=requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":"BTCUSDT","interval":"1h","limit":5},timeout=10).json()
        if not k or len(k)<2: return True,0
        C=[float(x[4]) for x in k]
        chg=(C[-1]-C[-4])/C[-4]*100
        return chg>=CFG["btc_filter_pct"],chg
    except: return True,0

def get_pairs():
    try:
        r=requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr",timeout=15).json()
        if not isinstance(r,list): return []
        f=[t for t in r
           if isinstance(t,dict)
           and isinstance(t.get("symbol",""),str)
           and t.get("symbol","").endswith("USDT")
           and not any(x in t.get("symbol","") for x in ["DOWN","UP","BEAR","BULL"])
           and CFG["min_gain_pct"]<=abs(float(t.get("priceChangePercent",0)))<=CFG["max_gain_pct"]
           and float(t.get("quoteVolume",0))>CFG["min_volume_usd"]]
        s=sorted(f,key=lambda x:float(x.get("quoteVolume",0)),reverse=True)
        return [t["symbol"] for t in s[:CFG["top_n"]]]
    except: return []

def get_klines(sym,tf,limit=60):
    try:
        return requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":sym,"interval":tf,"limit":limit},timeout=15).json()
    except: return []

def gen_daily_report():
    data=load_trades()
    today=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_trades=[t for t in data["trades"]
                if t.get("day")==today and t["result"]!="PENDING"]
    if not day_trades:
        return f"📐 <b>تقرير SMC اليومي — {today}</b>\n⏳ لا توجد صفقات محسومة اليوم"
    wins=[t for t in day_trades if t["result"] in ["TP1","TP2"]]
    losses=[t for t in day_trades if t["result"]=="SL"]
    total_pct=sum(t["pct"] for t in day_trades)
    wr=len(wins)/len(day_trades)*100
    types={}
    for t in day_trades:
        tp=t["type"]
        if tp not in types: types[tp]={"w":0,"l":0,"total":0}
        types[tp]["total"]+=1
        if t["result"] in ["TP1","TP2"]: types[tp]["w"]+=1
        else: types[tp]["l"]+=1
    type_lines=""
    for tp,v in types.items():
        emoji="📈" if "BULLISH" in tp else "📉"
        wr_t=v["w"]/v["total"]*100
        type_lines+=f"\n{emoji} {tp}: {v['w']}/{v['total']} ({wr_t:.0f}%)"
    pnl_color="🟢" if total_pct>0 else "🔴"
    tp2_c=len([t for t in wins if t["result"]=="TP2"])
    tp1_c=len([t for t in wins if t["result"]=="TP1"])
    msg=f"""📐 <b>تقرير SMC اليومي — {today}</b>
━━━━━━━━━━━━━━━
📈 الإشارات: {len(day_trades)} | ✅ {len(wins)} | ❌ {len(losses)}
🎯 نسبة النجاح: {wr:.1f}%
{pnl_color} إجمالي: {total_pct:+.2f}%
━━━━━━━━━━━━━━━
🎯 TP2: {tp2_c} | 👍 TP1: {tp1_c} | ❌ SL: {len(losses)}{type_lines}
━━━━━━━━━━━━━━━"""
    if wins:
        best=max(wins,key=lambda x:x["pct"])
        avg_w=sum(t["pct"] for t in wins)/len(wins)
        msg+=f"\n🏆 أفضل: #{best['id']} {best['sym']} {best['pct']:+.2f}%"
        msg+=f"\n📈 متوسط الربح: +{avg_w:.2f}%"
    if losses:
        avg_l=sum(t["pct"] for t in losses)/len(losses)
        msg+=f"\n📉 متوسط الخسارة: {avg_l:.2f}%"
    return msg

def gen_check_report(trade, res):
    emoji={"TP2":"🎯","TP1":"✅","SL":"❌"}.get(res["result"],"⏳")
    color="🟢" if res["pct"]>0 else "🔴"
    dir_emoji="📈" if "BULLISH" in trade["type"] else "📉"
    return f"""{emoji} <b>نتيجة #{trade['id']} — {trade['sym']}</b>
{dir_emoji} نوع: {trade['type']}
💰 دخول: ${trade['entry']:.4f}
🚪 خروج: ${res['exit_price']:.4f}
{color} <b>{res['result']} | {res['pct']:+.2f}%</b>
⏱ بعد {CFG['check_after_hours']} ساعات"""

def send_tg(msg):
    if not TELEGRAM_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"},timeout=10)
    except Exception as e: print(f"TG: {e}")

def send_signal(sym, r):
    sig_type=f"{'BULLISH' if r['signal']=='BULLISH' else 'BEARISH'}_SMC"
    trade_id=log_signal(sym,sig_type,r["entry"],r["tp1"],r["tp2"],r["sl"],
                        r["rr"],{"confluence":r["confluence"],"details":r["conf_details"]})
    dir_emoji="📈" if r["signal"]=="BULLISH" else "📉"
    dir_text="LONG" if r["signal"]=="BULLISH" else "SHORT"
    rr_emoji="✅" if r["rr"]>=3.0 else "🔸"
    ote_emoji="✅" if r.get("in_ote") else "🔸"
    conf_str=" | ".join(r["conf_details"])
    fvg_line=""
    if r.get("fvg") and (r["fvg"].get("in_fvg") or r["fvg"].get("near_fvg")):
        fvg_line=f"\n🔷 FVG: ${r['fvg']['bot']:.4f} — ${r['fvg']['top']:.4f}"
    liq_line=""
    if r.get("liq"):
        liq_line=f"\n💧 Liq Sweep: ${r['liq']['swept_level']:.4f}"
    msg=f"""{dir_emoji} <b>SMC {dir_text} #{trade_id} — {sym}</b>
📐 {r['source']} | {r['trend_4h']} على 4H
⭐ تقاطع: {r['confluence']}/14 نقطة
📌 {conf_str}
━━━━━━━━━━━━━━━
💰 دخول:  ${r['entry']:.4f}
🎯 TP1:   ${r['tp1']:.4f}  (+{r['t1p']:.2f}%)
🎯 TP2:   ${r['tp2']:.4f}  (+{r['t2p']:.2f}%)
🛑 SL:    ${r['sl']:.4f}  (-{r['slp']:.2f}%)
📊 R:R:   1:{r['rr']:.2f} {rr_emoji}
━━━━━━━━━━━━━━━
📦 Order Block: ${r['ob']['bottom']:.4f} — ${r['ob']['top']:.4f}
🎯 OTE Zone: ${r['ote']['low']:.4f} — ${r['ote']['high']:.4f} {ote_emoji}{fvg_line}{liq_line}
━━━━━━━━━━━━━━━
🔢 RSI: {r['rsi']:.1f} | ATR: ${r['atr']:.4f}
🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC
⚠️ <i>تحليل فقط — ليست نصيحة مالية</i>"""
    send_tg(msg)
    print(f"{dir_emoji} #{trade_id} {sym} | {dir_text} | RR:{r['rr']:.2f} | Conf:{r['confluence']}")

last_signals={}

def run_scan(fast=False):
    now=datetime.now(timezone.utc).strftime('%H:%M:%S')
    label="⚡ مسح سريع 15د" if fast else "🔍 مسح رئيسي 1س"
    print(f"[{now}] {label}...")
    if not fast:
        market_state,btc_4h,btc_24h=get_market_state()
    else:
        btc_ok,btc_4h=check_btc()
        market_state="BEARISH" if not btc_ok else "NEUTRAL"
        btc_24h=0
    state_emoji={"BULLISH":"🟢","BEARISH":"🔴","NEUTRAL":"🟡"}.get(market_state,"🟡")
    btc_s=f"{state_emoji} BTC {market_state} | {btc_4h:+.2f}%"
    pairs=get_pairs()
    if not pairs:
        if not fast: send_tg(f"⏳ لا توجد أزواج\n{btc_s}\n🕐 {now}")
        return
    signals=[]; bull_sigs=[]; bear_sigs=[]
    for sym in pairs:
        try:
            last=last_signals.get(sym,0)
            if time.time()-last<CFG["signal_cooldown_hours"]*3600: continue
            k4h=get_klines(sym,CFG["tf_high"],60)
            k1h=get_klines(sym,CFG["tf_mid"],60)
            k15m=get_klines(sym,CFG["tf_entry"],60)
            r=analyze_smc(sym,k4h,k1h,k15m)
            if r:
                r["sym"]=sym; signals.append(r)
                if r["signal"]=="BULLISH": bull_sigs.append(r)
                else: bear_sigs.append(r)
            time.sleep(0.2)
        except Exception as e: print(f"خطأ {sym}: {e}")
    signals.sort(key=lambda x:(x["confluence"],x["rr"]),reverse=True)
    send_tg(f"""{label} — SMC Bot
{btc_s}
📊 أزواج: {len(pairs)} | 📈 {len(bull_sigs)} | 📉 {len(bear_sigs)}
🕐 {now} UTC""")
    sent=0
    for r in signals[:5]:
        if market_state=="BEARISH" and r["signal"]=="BULLISH" and r["confluence"]<10:
            continue
        send_signal(r["sym"],r)
        last_signals[r["sym"]]=time.time()
        sent+=1; time.sleep(0.5)
    print(f"✅ {sent} إشارة | Bull:{len(bull_sigs)} Bear:{len(bear_sigs)}")

last_daily=-1

def check_reports():
    global last_daily
    now=datetime.now(timezone.utc)
    if now.hour==CFG["daily_report_hour"] and 0<=now.minute<15:
        if last_daily!=now.day:
            send_tg(gen_daily_report())
            last_daily=now.day
            print("📊 التقرير اليومي أُرسل")
    updated=update_pending_trades()
    for trade,res in updated:
        send_tg(gen_check_report(trade,res))
        print(f"📊 #{trade['id']} {trade['sym']}: {res['result']} {res['pct']:+.2f}%")

if __name__=="__main__":
    print("📐 SMC Bot يعمل!")
    data=load_trades()
    send_tg(f"""📐 <b>SMC Bot بدأ!</b>

🧠 <b>Smart Money Concepts — 3 فريمات:</b>
📊 4H — اتجاه السوق الكبير
📊 1H — BOS و CHoCH
📊 15m — Order Block + FVG + OTE

⚙️ <b>محركات الإشارة:</b>
✅ Market Structure
✅ Break of Structure (BOS)
✅ Change of Character (CHoCH)
✅ Order Blocks
✅ Fair Value Gaps (FVG)
✅ Liquidity Sweeps
✅ OTE (Fibonacci 61.8%-78.6%)

⭐ تقاطع 6+ نقاط مطلوب | R:R min: {CFG['min_rr']}

📋 <b>التقارير:</b>
⏱ نتيجة كل إشارة بعد {CFG['check_after_hours']} ساعات
📅 يومي 20:00 UTC (23:00 بتوقيت السعودية)

📦 صفقات: {data['stats']['total']} | ✅ {data['stats']['wins']} | ❌ {data['stats']['losses']}""")
    while True:
        try:
            run_scan(fast=False); check_reports()
            for _ in range(3):
                time.sleep(CFG["fast_interval"]*60)
                run_scan(fast=True); check_reports()
            time.sleep(CFG["fast_interval"]*60)
        except KeyboardInterrupt:
            send_tg("⏹ SMC Bot توقف"); break
        except Exception as e:
            print(f"❌ {e}"); time.sleep(60)
