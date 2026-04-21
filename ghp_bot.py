import os, time, requests, json
from datetime import datetime, timezone

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "400815773")
BINANCE_BASE     = "https://data-api.binance.vision"
TRADES_FILE      = "trades_log.json"

CFG = {
    "atr_len":14, "vol_len":20, "vol_mult":1.5,
    "rsi_len":14, "rsi_ob":75, "ema_fast":9,
    "ema_slow":21, "ema_trend":50,
    "tp1_mult":1.5, "tp2_mult":3.0, "tp3_mult":5.0, "sl_mult":1.2,
    "min_rr":2.0, "top_n":60,
    "main_interval":60, "fast_interval":15,
    "tf_main":"1h", "tf_fast":"15m",
    "min_gain_pct":2.0, "max_gain_pct":50.0,
    "min_volume_usd":3000000, "btc_filter_pct":-2.0,
    "roc_bars":3, "roc_min_pct":3.0, "momentum_roc_min":8.0, "momentum_rsi_min":55,
    "reentry_min_gain":15.0,
    "trend_lookback":20, "breakout_vol_mult":1.3, "sl_mult_bear":1.8,
    "check_after_hours":4,
    "daily_report_hour":20,
    "daily_report_minute":0,
    "weekly_report_day":4,
    "weekly_report_hour":20,
}

def load_trades():
    try:
        if os.path.exists(TRADES_FILE):
            with open(TRADES_FILE,"r") as f:
                return json.load(f)
    except: pass
    return {"trades":[], "stats":{"total":0,"wins":0,"losses":0,"pending":0,"total_pct":0}}

def save_trades(data):
    try:
        with open(TRADES_FILE,"w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"خطأ حفظ: {e}")

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
        sym=trade["sym"]; entry=trade["entry"]
        tp1=trade["tp1"]; tp2=trade["tp2"]; tp3=trade["tp3"]; sl=trade["sl"]
        klines=requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":sym,"interval":"15m","limit":20},timeout=10).json()
        if not klines or not isinstance(klines,list): return None
        t1=t2=t3=hit_sl=False
        exit_price=float(klines[-1][4])
        for k in klines:
            h=float(k[2]); l=float(k[3])
            if not t1 and h>=tp1: t1=True
            if t1 and not t2 and h>=tp2: t2=True
            if t2 and not t3 and h>=tp3: t3=True
            if l<=sl and not t2: hit_sl=True; break
        if t3: result="TP3"; exit_price=tp3; pct=(tp3/entry-1)*100
        elif t2: result="TP2"; exit_price=tp2; pct=(tp2/entry-1)*100
        elif t1 and hit_sl: result="TP1+SL"; exit_price=(tp1+sl)/2; pct=((tp1/entry-1)*100*0.5+(sl/entry-1)*100*0.5)
        elif t1: result="TP1"; exit_price=tp1; pct=(tp1/entry-1)*100
        elif hit_sl: result="SL"; exit_price=sl; pct=(sl/entry-1)*100
        else: result="OPEN"; exit_price=float(klines[-1][4]); pct=(exit_price/entry-1)*100
        return {"result":result,"exit_price":exit_price,"pct":pct,"t1":t1,"t2":t2,"t3":t3}
    except Exception as e:
        print(f"خطأ check_trade {trade['sym']}: {e}"); return None

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
                data["trades"][i]["checked"]=True
                data["stats"]["pending"]=max(0,data["stats"]["pending"]-1)
                data["stats"]["total_pct"]+=res["pct"]
                if res["result"] in ["TP1","TP2","TP3","TP1+SL"]: data["stats"]["wins"]+=1
                elif res["result"]=="SL": data["stats"]["losses"]+=1
                updated.append((trade,res))
    save_trades(data); return updated

def gen_daily_report():
    data=load_trades()
    today=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_trades=[t for t in data["trades"] if t.get("day")==today and t["result"]!="PENDING"]
    if not day_trades:
        return f"📊 <b>تقرير يومي — {today}</b>\n⏳ لا توجد صفقات محسومة اليوم بعد"
    wins=[t for t in day_trades if t["result"] in ["TP1","TP2","TP3","TP1+SL"]]
    losses=[t for t in day_trades if t["result"]=="SL"]
    total_pct=sum(t["pct"] for t in day_trades)
    wr=len(wins)/len(day_trades)*100 if day_trades else 0
    types={}
    for t in day_trades:
        tp=t["type"]
        if tp not in types: types[tp]={"w":0,"l":0,"total":0}
        types[tp]["total"]+=1
        if t["result"] in ["TP1","TP2","TP3","TP1+SL"]: types[tp]["w"]+=1
        else: types[tp]["l"]+=1
    type_lines=""
    for tp,v in types.items():
        emoji="🚀" if "STRONG" in tp else "💥" if "BREAKOUT" in tp else "⚡" if "EARLY" in tp else "🔥" if "MOMENTUM" in tp else "🔄"
        wr_t=v["w"]/v["total"]*100 if v["total"] else 0
        type_lines+=f"\n{emoji} {tp}: {v['w']}/{v['total']} ({wr_t:.0f}%)"
    pnl_color="🟢" if total_pct>0 else "🔴"
    msg=f"""📊 <b>تقرير يومي — {today}</b>
━━━━━━━━━━━━━━━
📈 إجمالي الإشارات: {len(day_trades)}
✅ رابحة: {len(wins)} | ❌ خاسرة: {len(losses)}
🎯 نسبة النجاح: {wr:.1f}%
{pnl_color} إجمالي الربح/الخسارة: {total_pct:+.2f}%
━━━━━━━━━━━━━━━
<b>تفصيل حسب النوع:</b>{type_lines}
━━━━━━━━━━━━━━━"""
    if wins:
        best=max(wins,key=lambda x:x["pct"])
        msg+=f"\n🏆 أفضل صفقة: #{best['id']} {best['sym']} {best['pct']:+.2f}%"
    if losses:
        worst=min(losses,key=lambda x:x["pct"])
        msg+=f"\n💔 أسوأ صفقة: #{worst['id']} {worst['sym']} {worst['pct']:+.2f}%"
    return msg

def gen_weekly_report():
    data=load_trades()
    all_trades=[t for t in data["trades"] if t["result"]!="PENDING"]
    if not all_trades:
        return "📊 <b>التقرير الأسبوعي</b>\n⏳ لا توجد صفقات محسومة بعد"
    wins=[t for t in all_trades if t["result"] in ["TP1","TP2","TP3","TP1+SL"]]
    losses=[t for t in all_trades if t["result"]=="SL"]
    total_pct=sum(t["pct"] for t in all_trades)
    wr=len(wins)/len(all_trades)*100 if all_trades else 0
    types={}
    for t in all_trades:
        tp=t["type"]
        if tp not in types: types[tp]={"w":0,"l":0,"total":0,"pct":0}
        types[tp]["total"]+=1; types[tp]["pct"]+=t["pct"]
        if t["result"] in ["TP1","TP2","TP3","TP1+SL"]: types[tp]["w"]+=1
        else: types[tp]["l"]+=1
    tp3_c=len([t for t in all_trades if t["result"]=="TP3"])
    tp2_c=len([t for t in all_trades if t["result"]=="TP2"])
    tp1_c=len([t for t in all_trades if t["result"] in ["TP1","TP1+SL"]])
    type_lines=""
    for tp,v in sorted(types.items(),key=lambda x:-x[1]["w"]):
        emoji="🚀" if "STRONG" in tp else "💥" if "BREAKOUT" in tp else "⚡" if "EARLY" in tp else "🔥" if "MOMENTUM" in tp else "🔄"
        wr_t=v["w"]/v["total"]*100 if v["total"] else 0
        type_lines+=f"\n{emoji} {tp}: {v['w']}/{v['total']} ({wr_t:.0f}%) | {v['pct']:+.1f}%"
    pnl_color="🟢" if total_pct>0 else "🔴"
    msg=f"""📊 <b>التقرير الأسبوعي — GHP Pro v4</b>
━━━━━━━━━━━━━━━━━━━━
📈 إجمالي الإشارات: {len(all_trades)}
✅ رابحة: {len(wins)} | ❌ خاسرة: {len(losses)} | ⏳ معلق: {data['stats']['pending']}
🎯 <b>نسبة النجاح: {wr:.1f}%</b>
{pnl_color} <b>إجمالي: {total_pct:+.2f}%</b>
━━━━━━━━━━━━━━━━━━━━
🎯 TP3:{tp3_c} | TP2:{tp2_c} | TP1:{tp1_c} | SL:{len(losses)}
━━━━━━━━━━━━━━━━━━━━
<b>أداء كل نوع إشارة:</b>{type_lines}
━━━━━━━━━━━━━━━━━━━━"""
    if wins:
        best=max(wins,key=lambda x:x["pct"])
        avg_win=sum(t["pct"] for t in wins)/len(wins)
        msg+=f"\n🏆 أفضل صفقة: #{best['id']} {best['sym']} {best['pct']:+.2f}%"
        msg+=f"\n📈 متوسط الربح: +{avg_win:.2f}%"
    if losses:
        avg_loss=sum(t["pct"] for t in losses)/len(losses)
        msg+=f"\n📉 متوسط الخسارة: {avg_loss:.2f}%"
    return msg

def gen_signal_check_report(trade, res):
    emoji={"TP3":"🎯","TP2":"✅","TP1":"👍","TP1+SL":"⚠️","SL":"❌"}.get(res["result"],"⏳")
    color="🟢" if res["pct"]>0 else "🔴"
    return f"""{emoji} <b>نتيجة إشارة #{trade['id']} — {trade['sym']}</b>
نوع: {trade['type']}
دخول: ${trade['entry']:.4f}
خروج: ${res['exit_price']:.4f}
{color} النتيجة: {res['result']} | {res['pct']:+.2f}%
⏱ بعد {CFG['check_after_hours']} ساعات"""

def ema_h(data, p):
    if len(data)<p: return []
    k=2/(p+1); r=[None]*(p-1)
    e=sum(data[:p])/p; r.append(e)
    for i in range(p,len(data)): e=data[i]*k+e*(1-k); r.append(e)
    return r

def ema(data,p): h=ema_h(data,p); return h[-1] if h else None
def sma(data,p): return None if len(data)<p else sum(data[-p:])/p

def rsi(closes, p=14):
    if len(closes)<p+1: return None
    g=l=0
    for i in range(len(closes)-p, len(closes)):
        d=closes[i]-closes[i-1]
        if d>0: g+=d
        else: l-=d
    return 100-100/(1+(g/(l or 0.0001)))

def atr(H,L,C,p):
    if len(C)<p+1: return None
    return sum(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])) for i in range(len(C)-p,len(C)))/p

def macd(closes):
    if len(closes)<35: return None,None
    fh=ema_h(closes,12); sh=ema_h(closes,26)
    ma=[f-s for f,s in zip(fh,sh) if f and s]
    return (ma[-1],ema(ma,9)) if len(ma)>=9 else (None,None)

def roc(closes, bars=3):
    if len(closes)<bars+1: return 0
    return (closes[-1]-closes[-bars-1])/closes[-bars-1]*100

def detect_trendline_break(H, L, C, V, lookback=20):
    if len(H)<lookback+2: return False,0,0
    local_highs=[]
    for i in range(2,lookback):
        idx=len(H)-i
        if idx<1: continue
        if H[idx]>H[idx-1] and H[idx]>H[idx+1]:
            local_highs.append((idx,H[idx]))
    if len(local_highs)<2: return False,0,0
    h1_idx,h1_val=local_highs[0]; h2_idx,h2_val=local_highs[1]
    if h1_val>=h2_val: return False,0,0
    if h1_idx<=h2_idx: return False,0,0
    slope=(h1_val-h2_val)/(h1_idx-h2_idx)
    trend_level=h1_val+slope*(len(H)-1-h1_idx)
    curr_close=C[-1]; prev_close=C[-2]; curr_vol=V[-1]; avg_vol=sma(V,20)
    broke_trend=curr_close>trend_level and prev_close<=trend_level
    vol_confirm=avg_vol and curr_vol>avg_vol*CFG["breakout_vol_mult"]
    return broke_trend and vol_confirm,trend_level,slope

def run_ghp(klines_1h, klines_15m=None):
    if not klines_1h or len(klines_1h)<60: return None
    try:
        H1=[float(k[2]) for k in klines_1h]; L1=[float(k[3]) for k in klines_1h]
        C1=[float(k[4]) for k in klines_1h]; V1=[float(k[5]) for k in klines_1h]
        O1=[float(k[1]) for k in klines_1h]
    except: return None
    n=len(C1)
    av1=atr(H1,L1,C1,14); rv1=rsi(C1,14)
    ef1=ema(C1,9); es1=ema(C1,21); et1=ema(C1,50); va1=sma(V1,20)
    mv1,ms1=macd(C1)
    fh1=ema_h(C1,9); sh1=ema_h(C1,21)
    pf1=fh1[-2] if len(fh1)>=2 else None; ps1=sh1[-2] if len(sh1)>=2 else None
    cross_1h=bool(pf1 and ps1 and pf1<=ps1 and ef1 and es1 and ef1>es1)
    cl1=C1[-1]; op1=O1[-1]; pc1=C1[-2]; po1=O1[-2]; vol1=V1[-1]
    hv1=bool(va1 and vol1>va1*CFG["vol_mult"])
    rh1=bool(rv1 and 50<rv1<CFG["rsi_ob"])
    at1=bool(et1 and cl1>et1)
    mb1=bool(mv1 and ms1 and mv1>ms1)
    be1=cl1>op1 and pc1<po1 and cl1>po1 and op1<pc1
    body1=abs(cl1-op1)
    bodies1=[abs(C1[i]-O1[i]) for i in range(max(0,n-11),n-1)]
    ab1=sum(bodies1)/len(bodies1) if bodies1 else 1
    sc1=body1>ab1*1.3 and cl1>op1
    h20_1=max(H1[-21:-1]) if n>=21 else H1[-1]
    br1=H1[-1]>=h20_1 and cl1>op1
    roc_1h=roc(C1,CFG["roc_bars"]); momentum_1h=roc_1h>=CFG["roc_min_pct"]
    tb_1h,_,_=detect_trendline_break(H1,L1,C1,V1,CFG["trend_lookback"])
    score=0
    if cross_1h: score+=2
    if hv1: score+=2
    if rh1: score+=1
    if at1: score+=1
    if mb1: score+=1
    if be1: score+=1
    if sc1: score+=1
    if br1: score+=1
    if momentum_1h: score+=1
    if tb_1h: score+=2
    st=5 if score>=10 else 4 if score>=8 else 3 if score>=6 else 2 if score>=4 else 1
    cross_15m=False; tb_15m=False; roc_15m=0; momentum_15m=False
    if klines_15m and len(klines_15m)>=30:
        try:
            H15=[float(k[2]) for k in klines_15m]; L15=[float(k[3]) for k in klines_15m]
            C15=[float(k[4]) for k in klines_15m]; V15=[float(k[5]) for k in klines_15m]
            ef15=ema(C15,9); es15=ema(C15,21)
            fh15=ema_h(C15,9); sh15=ema_h(C15,21)
            pf15=fh15[-2] if len(fh15)>=2 else None; ps15=sh15[-2] if len(sh15)>=2 else None
            cross_15m=bool(pf15 and ps15 and pf15<=ps15 and ef15 and es15 and ef15>es15)
            tb_15m,_,_=detect_trendline_break(H15,L15,C15,V15,min(20,len(H15)-2))
            roc_15m=roc(C15,3); momentum_15m=roc_15m>=CFG["roc_min_pct"]
        except: pass
    strong_buy=cross_1h and rh1 and hv1 and at1 and mb1 and (be1 or sc1) and st>=3
    breakout_buy=tb_1h and hv1 and mb1 and (rv1 and rv1>40) and not strong_buy
    early_15m=(cross_15m or tb_15m) and momentum_15m and at1 and mb1
    early_buy=early_15m and (rv1 and rv1>40) and hv1 and not strong_buy and not breakout_buy
    momentum_buy=momentum_1h and roc_1h>=CFG["momentum_roc_min"] and hv1 and mb1 and (rv1 and rv1>CFG["momentum_rsi_min"]) and at1
    momentum_buy=momentum_buy and not strong_buy and not breakout_buy and not early_buy
    early_cond=sum([rh1,hv1,at1,mb1,(be1 or sc1)])
    reentry=early_cond>=3 and momentum_1h and not strong_buy and not breakout_buy and not early_buy and not momentum_buy
    if not av1: return None
    tp1=cl1+av1*CFG["tp1_mult"]; tp2=cl1+av1*CFG["tp2_mult"]
    tp3=cl1+av1*CFG["tp3_mult"]; sl=cl1-av1*CFG["sl_mult"]
    t2p=(tp2/cl1-1)*100; slp=(1-sl/cl1)*100; rr=t2p/(slp or 1)
    vr=vol1/va1 if va1 else 0
    return {
        "strong_buy":strong_buy,"breakout_buy":breakout_buy,
        "early_buy":early_buy,"momentum_buy":momentum_buy,"reentry":reentry,
        "any_buy":strong_buy or breakout_buy or early_buy or momentum_buy,
        "st":st,"score":score,"cl":cl1,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
        "t1p":(tp1/cl1-1)*100,"t2p":t2p,"t3p":(tp3/cl1-1)*100,
        "slp":slp,"rr":rr,"rsi":rv1,"vr":vr,"roc_1h":roc_1h,"roc_15m":roc_15m,
        "tb_1h":tb_1h,"tb_15m":tb_15m,"cross_1h":cross_1h,"cross_15m":cross_15m,
        "hv":hv1,"rh":rh1,"at":at1,"mb":mb1,"momentum":momentum_1h,
    }

def get_market_state():
    try:
        k=requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":"BTCUSDT","interval":"1h","limit":55},timeout=10).json()
        if not k or len(k)<50: return "NEUTRAL",0,0
        C=[float(x[4]) for x in k]
        chg_4h=(C[-1]-C[-4])/C[-4]*100
        chg_24h=(C[-1]-C[-24])/C[-24]*100
        k2=2/(50+1); e=sum(C[:50])/50
        for i in range(50,len(C)): e=C[i]*k2+e*(1-k2)
        btc_above_ema50=C[-1]>e
        tickers=requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr",timeout=10).json()
        if isinstance(tickers,list):
            usdt=[t for t in tickers if isinstance(t,dict) and t.get("symbol","").endswith("USDT")]
            gainers=len([t for t in usdt if float(t.get("priceChangePercent",0))>0])
            gainer_ratio=gainers/len(usdt) if usdt else 0.5
        else:
            gainer_ratio=0.5
        bull_score=0
        if chg_4h>0.5:        bull_score+=2
        if chg_4h>-0.5:       bull_score+=1
        if chg_24h>1:         bull_score+=2
        if chg_24h>-2:        bull_score+=1
        if btc_above_ema50:   bull_score+=2
        if gainer_ratio>0.55: bull_score+=2
        state="BULL" if bull_score>=7 else "NEUTRAL" if bull_score>=4 else "BEAR"
        print(f"السوق: {state} | 4h:{chg_4h:.2f}% 24h:{chg_24h:.2f}% | Gainers:{gainer_ratio:.0%} | Score:{bull_score}")
        return state,chg_4h,chg_24h
    except Exception as e:
        print(f"خطأ market_state: {e}"); return "NEUTRAL",0,0

def check_btc():
    try:
        k=requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":"BTCUSDT","interval":"1h","limit":5},timeout=10).json()
        if not k or len(k)<2: return True,0
        C=[float(x[4]) for x in k]; chg=(C[-1]-C[-4])/C[-4]*100
        return chg>=CFG["btc_filter_pct"],chg
    except: return True,0

def get_tickers():
    try:
        r=requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr",timeout=15).json()
        return r if isinstance(r,list) else []
    except: return []

def filter_gainers(tickers,min_pct,max_pct,top_n):
    f=[t for t in tickers if isinstance(t,dict) and isinstance(t.get("symbol",""),str)
       and t.get("symbol","").endswith("USDT")
       and not any(x in t.get("symbol","") for x in ["DOWN","UP","BEAR","BULL"])
       and min_pct<=float(t.get("priceChangePercent",0))<=max_pct
       and float(t.get("quoteVolume",0))>CFG["min_volume_usd"]]
    return sorted(f,key=lambda x:float(x.get("priceChangePercent",0)),reverse=True)[:top_n]

def get_klines(sym,tf,limit=120):
    try:
        return requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":sym,"interval":tf,"limit":limit},timeout=15).json()
    except: return []

STARS={5:"★★★★★",4:"★★★★☆",3:"★★★☆☆",2:"★★☆☆☆",1:"★☆☆☆☆"}

def send_tg(msg):
    if not TELEGRAM_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"},timeout=10)
    except Exception as e: print(f"TG: {e}")

def _base(r, gain):
    g=f"\n📊 ارتفاع 24h: +{gain:.1f}%" if gain>0 else ""
    return f"""💰 دخول: ${r['cl']:.4f}{g}
🎯 TP1: ${r['tp1']:.4f} (+{r['t1p']:.2f}%)
🎯 TP2: ${r['tp2']:.4f} (+{r['t2p']:.2f}%)
🎯 TP3: ${r['tp3']:.4f} (+{r['t3p']:.2f}%)
🛑 SL:  ${r['sl']:.4f}  (-{r['slp']:.2f}%)
📊 R:R: 1:{r['rr']:.2f} {'✅' if r['rr']>=CFG['min_rr'] else '⚠️'}
📈 RSI: {r['rsi']:.1f} | حجم: {r['vr']:.1f}x
⚡ زخم 1h: {r['roc_1h']:+.2f}% | 15m: {r['roc_15m']:+.2f}%
🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC
⚠️ <i>تحليل فقط — ليست نصيحة مالية</i>"""

def send_signal(sym, signal_type, r, gain):
    STARS_={5:"★★★★★",4:"★★★★☆",3:"★★★☆☆",2:"★★☆☆☆",1:"★☆☆☆☆"}
    trade_id=log_signal(sym,signal_type,r['cl'],r['tp1'],r['tp2'],r['tp3'],r['sl'],r['rr'],gain)
    if signal_type=="STRONG":
        msg=f"""🚀 <b>STRONG BUY #{trade_id} — {sym}</b>
{STARS_[r['st']]} قوة: {r['st']}/5 | نقاط: {r['score']}/12
✅ 1h: EMA Cross + GHP كامل
{_base(r,gain)}"""
    elif signal_type=="BREAKOUT":
        tb15="✅ كسر 15m أيضاً!" if r['tb_15m'] else ""
        msg=f"""💥 <b>BREAKOUT BUY #{trade_id} — {sym}</b>
{STARS_[r['st']]} قوة: {r['st']}/5
🔴➡️🟢 كسر الترند الهابط + إغلاق فوقه {tb15}
{_base(r,gain)}"""
    elif signal_type=="EARLY":
        src="EMA Cross 15m" if r['cross_15m'] else "كسر ترند 15m"
        msg=f"""⚡ <b>EARLY BUY #{trade_id} — {sym}</b>
{STARS_[r['st']]} قوة: {r['st']}/5 | دخول مبكر
📊 {src} + تأكيد 1h
{_base(r,gain)}"""
    elif signal_type=="MOMENTUM":
        msg=f"""🔥 <b>MOMENTUM BUY #{trade_id} — {sym}</b>
{STARS_[r['st']]} قوة: {r['st']}/5
⚡ زخم: {r['roc_1h']:+.2f}%
{_base(r,gain)}"""
    else:
        msg=f"""🔄 <b>RE-ENTRY #{trade_id} — {sym}</b>
📊 +{gain:.1f}% اليوم | موجة جديدة
{STARS_[r['st']]} قوة: {r['st']}/5
{_base(r,gain)}"""
    send_tg(msg)

def run_scan(fast=False):
    now=datetime.now(timezone.utc).strftime('%H:%M:%S')
    label="⚡ مسح سريع 15د" if fast else "🔍 مسح رئيسي 1س"
    print(f"[{now}] {label}...")
    if not fast:
        market_state,btc_4h,btc_24h=get_market_state()
    else:
        btc_ok,btc_4h=check_btc()
        market_state="BEAR" if not btc_ok else "NEUTRAL"
        btc_24h=0
    state_emoji={"BULL":"🟢","NEUTRAL":"🟡","BEAR":"🔴"}.get(market_state,"🟡")
    btc_s=f"{state_emoji} {market_state} | BTC {btc_4h:+.2f}%"
    if market_state=="BEAR" and btc_4h<CFG["btc_filter_pct"]:
        if not fast:
            send_tg(f"🔴 <b>سوق هابط — إيقاف الإشارات</b>\nBTC {btc_4h:.2f}% 4h\n🕐 {now}")
        return
    tickers=get_tickers()
    if not tickers: return
    normal=filter_gainers(tickers,CFG["min_gain_pct"],25.0,CFG["top_n"])
    reentry_c=filter_gainers(tickers,CFG["reentry_min_gain"],CFG["max_gain_pct"],20)
    results=[]; strong=[]; breakout=[]; early=[]; momentum=[]; reentry=[]
    for t in normal:
        sym=t["symbol"]; gain=float(t.get("priceChangePercent",0))
        try:
            r=run_ghp(get_klines(sym,CFG["tf_main"],120),get_klines(sym,CFG["tf_fast"],60))
            if r:
                r["sym"]=sym; r["gain"]=gain; results.append(r)
                if r["strong_buy"] and r["rr"]>=CFG["min_rr"]:
                    strong.append(r)
                elif r["breakout_buy"] and r["rr"]>=1.5 and market_state!="BEAR":
                    breakout.append(r)
                elif r["early_buy"] and r["rr"]>=1.5 and market_state=="BULL":
                    early.append(r)
                elif r["momentum_buy"] and r["rr"]>=1.5 and market_state=="BULL":
                    momentum.append(r)
            time.sleep(0.15)
        except Exception as e: print(f"خطأ {sym}: {e}")
    reentry_syms={t["symbol"] for t in normal}
    for t in reentry_c:
        sym=t["symbol"]
        if sym in reentry_syms: continue
        gain=float(t.get("priceChangePercent",0))
        try:
            r=run_ghp(get_klines(sym,CFG["tf_main"],120),get_klines(sym,CFG["tf_fast"],60))
            if r and r["rr"]>=1.5 and r["momentum"] and r["hv"] and r["mb"]:
                r["sym"]=sym; r["gain"]=gain; reentry.append(r)
            time.sleep(0.15)
        except Exception as e: print(f"خطأ {sym}: {e}")
    strong.sort(key=lambda x:(x["st"],x["rr"]),reverse=True)
    breakout.sort(key=lambda x:(x.get("tb_15m",False),x["rr"]),reverse=True)
    early.sort(key=lambda x:x["rr"],reverse=True)
    momentum.sort(key=lambda x:x["roc_1h"],reverse=True)
    reentry.sort(key=lambda x:x["rr"],reverse=True)
    send_tg(f"""{label} — GHP Pro v4
{btc_s}
📊 محلل: {len(results)} | 🚀 {len(strong)} | 💥 {len(breakout)} | ⚡ {len(early)} | 🔥 {len(momentum)} | 🔄 {len(reentry)}
🕐 {now} UTC""")
    for r in strong[:5]:   send_signal(r["sym"],"STRONG",r,r["gain"]); time.sleep(0.5)
    for r in breakout[:4]: send_signal(r["sym"],"BREAKOUT",r,r["gain"]); time.sleep(0.5)
    for r in early[:3]:    send_signal(r["sym"],"EARLY",r,r["gain"]); time.sleep(0.5)
    for r in momentum[:3]: send_signal(r["sym"],"MOMENTUM",r,r["gain"]); time.sleep(0.5)
    for r in reentry[:5]:  send_signal(r["sym"],"REENTRY",r,r["gain"]); time.sleep(0.5)
    print(f"✅ {len(strong)}S {len(breakout)}B {len(early)}E {len(momentum)}M {len(reentry)}R")

last_daily_report=-1
last_weekly_report=-1

def check_reports():
    global last_daily_report,last_weekly_report
    now=datetime.now(timezone.utc)
    if now.hour==CFG["daily_report_hour"] and 0<=now.minute<15:
        if last_daily_report!=now.day:
            send_tg(gen_daily_report())
            last_daily_report=now.day
            print("📊 أُرسل التقرير اليومي")
    if now.weekday()==CFG["weekly_report_day"] and now.hour==CFG["weekly_report_hour"] and now.minute<5:
        week=now.isocalendar()[1]
        if last_weekly_report!=week:
            send_tg(gen_weekly_report())
            last_weekly_report=week
            print("📊 أُرسل التقرير الأسبوعي")
    updated=update_pending_trades()
    for trade,res in updated:
        send_tg(gen_signal_check_report(trade,res))
        print(f"📊 #{trade['id']} {trade['sym']}: {res['result']} {res['pct']:+.2f}%")

if __name__=="__main__":
    print("⚡ GHP Pro v4 يعمل!")
    data=load_trades()
    send_tg(f"""⚡ <b>GHP Pro v4 بدأ!</b>

🆕 <b>تحديثات اليوم:</b>
🟢🟡🔴 مؤشر اتجاه السوق الكلي
🔥 MOMENTUM أشد شروطاً (ROC>8% RSI>55)
🛡 SL أوسع في السوق الهابط
📊 الإشارات تتكيف مع السوق تلقائياً
🔄 REENTRY رُفع إلى 5 إشارات

📋 <b>نظام التقارير:</b>
⏱ فوري — نتيجة كل إشارة بعد 4 ساعات
📅 يومي — 20:00 UTC (23:00 بتوقيت السعودية)
📊 أسبوعي — الجمعة 20:00 UTC

📦 صفقات محفوظة: {data['stats']['total']}
✅ رابحة: {data['stats']['wins']} | ❌ خاسرة: {data['stats']['losses']}""")
    while True:
        try:
            run_scan(fast=False); check_reports()
            for _ in range(3):
                time.sleep(CFG["fast_interval"]*60)
                run_scan(fast=True); check_reports()
            time.sleep(CFG["fast_interval"]*60)
        except KeyboardInterrupt:
            send_tg("⏹ GHP Pro v4 توقف"); break
        except Exception as e:
            print(f"❌ {e}"); time.sleep(60)
