import os
import time
import hmac
import hashlib
import requests
from datetime import datetime

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "400815773")
BINANCE_API_KEY  = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET   = os.environ.get("BINANCE_SECRET", "")
BINANCE_BASE     = "https://data-api.binance.vision"



CFG = {
    "atr_len":14,"vol_len":20,"vol_mult":1.5,
    "rsi_len":14,"rsi_ob":75,"ema_fast":9,
    "ema_slow":21,"ema_trend":50,"tp1_mult":1.5,
    "tp2_mult":3.0,"tp3_mult":5.0,"sl_mult":1.2,
    "min_strength":3,"min_rr":2.0,"top_n":50,
    "scan_interval":60,"timeframe":"1h","auto_trade":False,
    "trade_amount":20,
}

def ema(data, period):
    if len(data) < period: return None
    k = 2/(period+1)
    e = sum(data[:period])/period
    for v in data[period:]: e = v*k + e*(1-k)
    return e

def ema_history(data, period):
    if len(data) < period: return []
    k = 2/(period+1)
    result = [None]*(period-1)
    e = sum(data[:period])/period
    result.append(e)
    for v in data[period:]:
        e = v*k + e*(1-k)
        result.append(e)
    return result

def sma(data, period):
    if len(data) < period: return None
    return sum(data[-period:])/period

def rsi(closes, period=14):
    if len(closes) < period+1: return None
    gains = losses = 0
    for i in range(len(closes)-period, len(closes)):
        d = closes[i]-closes[i-1]
        if d > 0: gains += d
        else: losses -= d
    return 100 - 100/(1+(gains/(losses or 0.0001)))

def atr(highs, lows, closes, period):
    if len(closes) < period+1: return None
    trs = []
    for i in range(len(closes)-period, len(closes)):
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    return sum(trs)/period

def macd(closes):
    if len(closes) < 35: return None, None
    fh = ema_history(closes,12)
    sh = ema_history(closes,26)
    ma = [f-s for f,s in zip(fh,sh) if f is not None and s is not None]
    if len(ma) < 9: return None, None
    return ma[-1], ema(ma,9)

def run_ghp(klines):
    if not klines or len(klines) < 60: return None
    try:
        H=[float(k[2]) for k in klines]
        L=[float(k[3]) for k in klines]
        C=[float(k[4]) for k in klines]
        V=[float(k[5]) for k in klines]
        O=[float(k[1]) for k in klines]
    except: return None
    n=len(C)
    atr_v=atr(H,L,C,CFG["atr_len"])
    rsi_v=rsi(C,CFG["rsi_len"])
    ef=ema(C,CFG["ema_fast"])
    es=ema(C,CFG["ema_slow"])
    et=ema(C,CFG["ema_trend"])
    va=sma(V,CFG["vol_len"])
    mv,ms=macd(C)
    fh=ema_history(C,CFG["ema_fast"])
    sh=ema_history(C,CFG["ema_slow"])
    pf=fh[-2] if len(fh)>=2 else None
    ps=sh[-2] if len(sh)>=2 else None
    cross=bool(pf and ps and pf<=ps and ef and es and ef>es)
    cl=C[-1]; op=O[-1]; pc=C[-2]; po=O[-2]; vol=V[-1]
    hv=bool(va and vol>va*CFG["vol_mult"])
    rh=bool(rsi_v and 50<rsi_v<CFG["rsi_ob"])
    at=bool(et and cl>et)
    mb=bool(mv and ms and mv>ms)
    be=bool(cl>op and pc<po and cl>po and op<pc)
    body=abs(cl-op)
    bodies=[abs(C[i]-O[i]) for i in range(max(0,n-11),n-1)]
    ab=sum(bodies)/len(bodies) if bodies else 1
    sc=bool(body>ab*1.3 and cl>op)
    h20=max(H[-21:-1]) if len(H)>=21 else H[-1]
    br=bool(H[-1]>=h20 and cl>op)
    score=0
    if cross: score+=2
    if hv: score+=2
    if rh: score+=1
    if at: score+=1
    if mb: score+=1
    if be: score+=1
    if sc: score+=1
    if br: score+=1
    st=5 if score>=8 else 4 if score>=6 else 3 if score>=4 else 2 if score>=3 else 1
    buy=bool(cross and rh and hv and at and mb and (be or sc) and st>=CFG["min_strength"])
    if not atr_v: return None
    tp1=cl+atr_v*CFG["tp1_mult"]
    tp2=cl+atr_v*CFG["tp2_mult"]
    tp3=cl+atr_v*CFG["tp3_mult"]
    sl=cl-atr_v*CFG["sl_mult"]
    t1p=(tp1/cl-1)*100; t2p=(tp2/cl-1)*100
    t3p=(tp3/cl-1)*100; slp=(1-sl/cl)*100
    rr=t2p/slp if slp>0 else 0
    vr=vol/va if va else 0
    return {"buy":buy,"strength":st,"score":score,"close":cl,
            "tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
            "tp1p":t1p,"tp2p":t2p,"tp3p":t3p,"slp":slp,"rr":rr,
            "rsi":rsi_v,"vr":vr}

def get_top_pairs():
    try:
        r=requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr",timeout=15).json()
        if not isinstance(r, list): return []
        f=[t for t in r if isinstance(t,dict)
           and isinstance(t.get("symbol",""),str)
           and t.get("symbol","").endswith("USDT")
           and not any(x in t.get("symbol","") for x in ["DOWN","UP","BEAR","BULL"])
           and float(t.get("priceChangePercent",0)) > 2
           and float(t.get("priceChangePercent",0)) < 15
           and float(t.get("quoteVolume",0)) > 1000000]
        sorted_pairs = sorted(f,key=lambda x:float(x.get("priceChangePercent",0)),reverse=True)
        result = [t["symbol"] for t in sorted_pairs[:CFG["top_n"]]]
        gainers_info = ", ".join([f"{t['symbol']}(+{float(t['priceChangePercent']):.1f}%)" for t in sorted_pairs[:10]])
        print(f"أفضل الرابحون: {gainers_info}")
        return result
    except Exception as e:
        print(f"خطأ get_top_pairs: {e}")
        return []


def get_klines(sym):
    try:
        return requests.get(f"{BINANCE_BASE}/api/v3/klines",params={"symbol":sym,"interval":CFG["timeframe"],"limit":120},timeout=15).json()
    except:
        return []

def send_tg(msg):
    if not TELEGRAM_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"},timeout=10)
    except: pass

STARS={5:"★★★★★",4:"★★★★☆",3:"★★★☆☆",2:"★★☆☆☆",1:"★☆☆☆☆"}

def fmt(sym,r):
    return f"""🚀 <b>BUY — {sym}</b>
{STARS[r['strength']]} قوة: {r['strength']}/5 | نقاط: {r['score']}/10
💰 دخول: ${r['close']:.4f}
🎯 TP1: ${r['tp1']:.4f} (+{r['tp1p']:.2f}%)
🎯 TP2: ${r['tp2']:.4f} (+{r['tp2p']:.2f}%)
🎯 TP3: ${r['tp3']:.4f} (+{r['tp3p']:.2f}%)
🛑 SL:  ${r['sl']:.4f}  (-{r['slp']:.2f}%)
📊 R:R: 1:{r['rr']:.2f} {'✅' if r['rr']>=CFG['min_rr'] else '⚠️'}
📈 RSI: {r['rsi']:.1f} | حجم: {r['vr']:.1f}x
🕐 {datetime.now().strftime('%H:%M:%S')}
⚠️ <i>تحليل فقط — ليست نصيحة مالية</i>"""

def run_scan():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] مسح السوق...")
    pairs=get_top_pairs()
    if not pairs:
        send_tg("❌ فشل جلب الأزواج"); return
    results=[]; buys=[]
    for sym in pairs:
        try:
            klines=get_klines(sym)
            if not isinstance(klines,list): continue
            r=run_ghp(klines)
            if r:
                r["sym"]=sym; results.append(r)
                if r["buy"] and r["rr"]>=CFG["min_rr"]: buys.append(r)
            time.sleep(0.15)
        except Exception as e:
            print(f"خطأ {sym}: {e}")
    buys.sort(key=lambda x:(x["strength"],x["rr"]),reverse=True)
    strong=[b for b in buys if b["strength"]>=4]
    send_tg(f"""🔍 <b>مسح GHP مكتمل</b>
📊 أزواج: {len(results)} | ✅ BUY: {len(buys)} | ⚡ قوية: {len(strong)}
🕐 {datetime.now().strftime('%H:%M:%S')}""")
    for r in buys[:5]:
        send_tg(fmt(r["sym"],r))
        time.sleep(0.5)
    if not buys: print("لا توجد إشارات")

if __name__=="__main__":
    print("GHP Bot يعمل!")
    send_tg(f"""⚡ <b>GHP Bot بدأ!</b>
📊 {CFG['top_n']} عملة | ⏱ {CFG['timeframe']} | 🔄 كل {CFG['scan_interval']} دقيقة""")
    while True:
        try:
            run_scan()
            time.sleep(CFG["scan_interval"]*60)
        except KeyboardInterrupt:
            send_tg("⏹ GHP Bot توقف"); break
        except Exception as e:
            print(f"خطأ: {e}"); time.sleep(60)
