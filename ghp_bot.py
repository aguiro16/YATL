import os, time, requests, json
from datetime import datetime, timezone

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "400815773")
BINANCE_BASE     = "https://data-api.binance.vision"
TRADES_FILE      = "vwap_trades.json"

CFG = {
    "top_n":50,
    "min_volume_usd":5000000,
    "min_gain_pct":1.0,
    "max_gain_pct":30.0,
    "scan_interval":60,
    "fast_interval":15,
    "timeframe":"1h",
    "vwap_period":20,
    "band_mult_1":1.0,
    "band_mult_2":2.0,
    "rsi_ob":70,
    "rsi_os":30,
    "vol_mult":1.5,
    "min_rr":1.5,
    "sl_pct":0.025,
    "check_after_hours":4,
    "daily_report_hour":20,
    "btc_filter_pct":-2.0,
    "signal_cooldown_hours":4,
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

def log_signal(sym, sig_type, entry, tp1, tp2, sl, rsi, vwap, b1u, b2u, b1d, b2d):
    data=load_trades()
    trade={
        "id":len(data["trades"])+1,
        "sym":sym, "type":sig_type,
        "entry":entry, "tp1":tp1, "tp2":tp2, "sl":sl,
        "rsi":rsi, "vwap":vwap,
        "upper1":b1u, "upper2":b2u,
        "lower1":b1d, "lower2":b2d,
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
        klines=requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":sym,"interval":"15m","limit":20},timeout=10).json()
        if not klines or not isinstance(klines,list): return None
        t1=t2=hit_sl=False
        for k in klines:
            h=float(k[2]); l=float(k[3])
            if not t1 and h>=tp1: t1=True
            if t1 and not t2 and h>=tp2: t2=True
            if l<=sl and not t1: hit_sl=True; break
        if t2:       result="TP2"; ep=tp2; pct=(tp2/entry-1)*100
        elif t1:     result="TP1"; ep=tp1; pct=(tp1/entry-1)*100
        elif hit_sl: result="SL";  ep=sl;  pct=(sl/entry-1)*100
        else:
            ep=float(klines[-1][4]); pct=(ep/entry-1)*100; result="OPEN"
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

def calc_vwap_bands(klines, period=20):
    if len(klines)<period+2: return None
    recent=klines[-period:]
    tp_v=[(float(k[2])+float(k[3])+float(k[4]))/3 for k in recent]
    vol_v=[float(k[5]) for k in recent]
    cum_vol=sum(vol_v)
    if cum_vol==0: return None
    vwap=sum(tp*v for tp,v in zip(tp_v,vol_v))/cum_vol
    variance=sum(v*(tp-vwap)**2 for tp,v in zip(tp_v,vol_v))/cum_vol
    std=variance**0.5
    if std==0: return None
    return {
        "vwap":vwap,
        "upper1":vwap+CFG["band_mult_1"]*std,
        "upper2":vwap+CFG["band_mult_2"]*std,
        "lower1":vwap-CFG["band_mult_1"]*std,
        "lower2":vwap-CFG["band_mult_2"]*std,
        "std":std,
    }

def calc_rsi(closes, period=14):
    if len(closes)<period+1: return None
    g=l=0
    for i in range(len(closes)-period,len(closes)):
        d=closes[i]-closes[i-1]
        if d>0: g+=d
        else: l-=d
    return 100-100/(1+(g/(l or 0.0001)))

def calc_atr(H,L,C,period=14):
    if len(C)<period+1: return None
    return sum(max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1]))
               for i in range(len(C)-period,len(C)))/period

def analyze_vwap(sym, klines):
    if not klines or len(klines)<25: return None
    bands=calc_vwap_bands(klines,CFG["vwap_period"])
    if not bands: return None
    C=[float(k[4]) for k in klines]
    O=[float(k[1]) for k in klines]
    H=[float(k[2]) for k in klines]
    L=[float(k[3]) for k in klines]
    V=[float(k[5]) for k in klines]
    cl=C[-1]; op=O[-1]
    pc=C[-2]; pl=L[-2]; ph=H[-2]; po=O[-2]
    vol=V[-1]
    avg_vol=sum(V[-20:])/20 if len(V)>=20 else vol
    rsi=calc_rsi(C)
    atr=calc_atr(H,L,C,14)
    if not rsi or not atr: return None
    vwap   =bands["vwap"]
    upper1 =bands["upper1"]
    upper2 =bands["upper2"]
    lower1 =bands["lower1"]
    lower2 =bands["lower2"]
    high_vol=vol>avg_vol*CFG["vol_mult"]
    bull_candle=cl>op
    sig=None
    if (pl<=lower1 and cl>lower1 and cl>pc and
        bull_candle and rsi>35 and rsi<60):
        sig="BOUNCE"
    elif (pc<vwap and cl>vwap and bull_candle and
          high_vol and rsi>45 and rsi<CFG["rsi_ob"]):
        sig="BREAKOUT"
    elif (ph>upper1 and cl>vwap and cl<upper1 and
          bull_candle and rsi>40 and rsi<65):
        sig="PULLBACK"
    if not sig: return None
    if sig=="BOUNCE":
        tp1=vwap; tp2=upper1
        sl=max(lower2, cl*(1-CFG["sl_pct"]))
    elif sig=="BREAKOUT":
        tp1=upper1; tp2=upper2
        sl=max(lower1, cl*(1-CFG["sl_pct"]))
    else:
        tp1=upper1; tp2=upper2
        sl=vwap*(1-CFG["sl_pct"])
    if sl>=cl: sl=cl*(1-CFG["sl_pct"])
    if tp1<=cl: return None
    rr=(tp1-cl)/(cl-sl) if cl>sl else 0
    if rr<CFG["min_rr"]: return None
    return {
        "signal":sig, "cl":cl,
        "tp1":tp1, "tp2":tp2, "sl":sl,
        "t1p":(tp1/cl-1)*100,
        "t2p":(tp2/cl-1)*100,
        "slp":(1-sl/cl)*100,
        "rr":rr, "rsi":rsi, "atr":atr,
        "vwap":vwap,
        "upper1":upper1, "upper2":upper2,
        "lower1":lower1, "lower2":lower2,
        "vol_ratio":vol/avg_vol,
        "high_vol":high_vol,
    }

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
           and CFG["min_gain_pct"]<=float(t.get("priceChangePercent",0))<=CFG["max_gain_pct"]
           and float(t.get("quoteVolume",0))>CFG["min_volume_usd"]]
        s=sorted(f,key=lambda x:float(x.get("quoteVolume",0)),reverse=True)
        return [t["symbol"] for t in s[:CFG["top_n"]]]
    except Exception as e:
        print(f"خطأ pairs: {e}"); return []

def get_klines(sym):
    try:
        return requests.get(f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol":sym,"interval":CFG["timeframe"],"limit":60},timeout=15).json()
    except: return []

def gen_daily_report():
    data=load_trades()
    today=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_trades=[t for t in data["trades"]
                if t.get("day")==today and t["result"]!="PENDING"]
    if not day_trades:
        return f"〰️ <b>تقرير VWAP اليومي — {today}</b>\n⏳ لا توجد صفقات محسومة اليوم"
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
        emoji="🔄" if tp=="BOUNCE" else "💥" if tp=="BREAKOUT" else "📉"
        wr_t=v["w"]/v["total"]*100
        type_lines+=f"\n{emoji} {tp}: {v['w']}/{v['total']} ({wr_t:.0f}%)"
    pnl_color="🟢" if total_pct>0 else "🔴"
    msg=f"""〰️ <b>تقرير VWAP اليومي — {today}</b>
━━━━━━━━━━━━━━━
📈 الإشارات: {len(day_trades)} | ✅ {len(wins)} | ❌ {len(losses)}
🎯 نسبة النجاح: {wr:.1f}%
{pnl_color} إجمالي: {total_pct:+.2f}%
━━━━━━━━━━━━━━━{type_lines}
━━━━━━━━━━━━━━━"""
    if wins:
        best=max(wins,key=lambda x:x["pct"])
        msg+=f"\n🏆 أفضل: #{best['id']} {best['sym']} {best['pct']:+.2f}%"
    if losses:
        worst=min(losses,key=lambda x:x["pct"])
        msg+=f"\n💔 أسوأ: #{worst['id']} {worst['sym']} {worst['pct']:+.2f}%"
    return msg

def gen_check_report(trade, res):
    emoji={"TP2":"🎯","TP1":"✅","SL":"❌"}.get(res["result"],"⏳")
    color="🟢" if res["pct"]>0 else "🔴"
    type_emoji={"BOUNCE":"🔄","BREAKOUT":"💥","PULLBACK":"📉"}.get(trade["type"],"〰️")
    return f"""{emoji} <b>نتيجة #{trade['id']} — {trade['sym']}</b>
{type_emoji} نوع: {trade['type']}
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
    trade_id=log_signal(
        sym, r["signal"], r["cl"],
        r["tp1"], r["tp2"], r["sl"],
        r["rsi"], r["vwap"],
        r["upper1"], r["upper2"],
        r["lower1"], r["lower2"],
    )
    emoji={"BOUNCE":"🔄","BREAKOUT":"💥","PULLBACK":"📉"}.get(r["signal"],"〰️")
    desc={
        "BOUNCE":  "ارتداد من Lower Band — صعود نحو VWAP",
        "BREAKOUT":"كسر VWAP للأعلى مع حجم قوي",
        "PULLBACK":"تراجع صحي إلى VWAP بعد صعود",
    }[r["signal"]]
    rr_emoji="✅" if r["rr"]>=2.0 else "🔸"
    vol_emoji="✅" if r["high_vol"] else "🔸"
    msg=f"""{emoji} <b>VWAP {r['signal']} #{trade_id} — {sym}</b>
📌 {desc}
━━━━━━━━━━━━━━━
💰 دخول:  ${r['cl']:.4f}
🎯 TP1:   ${r['tp1']:.4f}  (+{r['t1p']:.2f}%)
🎯 TP2:   ${r['tp2']:.4f}  (+{r['t2p']:.2f}%)
🛑 SL:    ${r['sl']:.4f}  (-{r['slp']:.2f}%)
📊 R:R:   1:{r['rr']:.2f} {rr_emoji}
━━━━━━━━━━━━━━━
〰️ VWAP:    ${r['vwap']:.4f}
📈 Upper 1: ${r['upper1']:.4f}
📈 Upper 2: ${r['upper2']:.4f}
📉 Lower 1: ${r['lower1']:.4f}
━━━━━━━━━━━━━━━
🔢 RSI: {r['rsi']:.1f} | حجم: {r['vol_ratio']:.1f}x {vol_emoji}
🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC
⚠️ <i>تحليل فقط — ليست نصيحة مالية</i>"""
    send_tg(msg)
    print(f"{emoji} #{trade_id} {sym} | {r['signal']} | RR:{r['rr']:.2f}")

last_signals={}

def run_scan(fast=False):
    now=datetime.now(timezone.utc).strftime('%H:%M:%S')
    label="⚡ مسح سريع 15د" if fast else "🔍 مسح رئيسي 1س"
    print(f"[{now}] {label}...")
    btc_ok,btc_chg=check_btc()
    if not btc_ok:
        if not fast:
            send_tg(f"⚠️ <b>BTC هابط {btc_chg:.2f}%</b>\nإيقاف VWAP مؤقتاً\n🕐 {now}")
        return
    btc_s=f"✅ BTC {btc_chg:+.2f}%"
    pairs=get_pairs()
    if not pairs:
        if not fast: send_tg(f"⏳ لا توجد أزواج\n{btc_s}\n🕐 {now}")
        return
    signals=[]
    for sym in pairs:
        try:
            last=last_signals.get(sym,0)
            if time.time()-last<CFG["signal_cooldown_hours"]*3600:
                continue
            klines=get_klines(sym)
            r=analyze_vwap(sym,klines)
            if r:
                r["sym"]=sym
                signals.append(r)
            time.sleep(0.12)
        except Exception as e:
            print(f"خطأ {sym}: {e}")
    signals.sort(key=lambda x:x["rr"],reverse=True)
    bounce  =[s for s in signals if s["signal"]=="BOUNCE"]
    breakout=[s for s in signals if s["signal"]=="BREAKOUT"]
    pullback=[s for s in signals if s["signal"]=="PULLBACK"]
    send_tg(f"""{label} — VWAP Bands
{btc_s}
📊 أزواج: {len(pairs)} | 🔄 {len(bounce)} | 💥 {len(breakout)} | 📉 {len(pullback)}
🕐 {now} UTC""")
    sent=0
    for r in signals[:5]:
        send_signal(r["sym"],r)
        last_signals[r["sym"]]=time.time()
        sent+=1
        time.sleep(0.5)
    print(f"✅ {sent} إشارة")

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
    print("〰️ VWAP Bands Bot يعمل!")
    data=load_trades()
    send_tg(f"""〰️ <b>VWAP Bands Bot بدأ!</b>

📊 <b>3 أنواع إشارات:</b>
🔄 BOUNCE  — ارتداد من Lower Band نحو VWAP
💥 BREAKOUT — كسر VWAP للأعلى مع حجم
📉 PULLBACK — تراجع صحي إلى VWAP

⚙️ <b>الإعدادات:</b>
〰️ VWAP Period: {CFG['vwap_period']} شمعة ساعية
📊 Bands: ±1σ و ±2σ
📈 حجم: {CFG['vol_mult']}x | R:R min: {CFG['min_rr']}

📋 <b>التقارير:</b>
⏱ نتيجة كل إشارة بعد {CFG['check_after_hours']} ساعات
📅 يومي 20:00 UTC (23:00 بتوقيت السعودية)

📦 صفقات: {data['stats']['total']} | ✅ {data['stats']['wins']} | ❌ {data['stats']['losses']}""")
    while True:
        try:
            run_scan(fast=False)
            check_reports()
            for _ in range(3):
                time.sleep(CFG["fast_interval"]*60)
                run_scan(fast=True)
                check_reports()
            time.sleep(CFG["fast_interval"]*60)
        except KeyboardInterrupt:
            send_tg("⏹ VWAP Bot توقف"); break
        except Exception as e:
            print(f"❌ {e}"); time.sleep(60)
