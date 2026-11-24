"""Daily XAUUSD levels from the GLD options chain (open interest, Greeks, volatility)."""
import json, math, os, sys, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import yfinance as yf

RATE = 0.04
MAX_DAYS = 30
MIN_GAP = 0.0015
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "levels.json")


def retry(fn, tries=3, wait=5):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"attempt {i + 1} failed: {e}", file=sys.stderr)
            time.sleep(wait)
    raise last


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def xau_spot():
    for url in ("https://fapi.binance.com/fapi/v1/ticker/price?symbol=XAUUSDT",
                "https://data-api.binance.vision/api/v3/ticker/price?symbol=PAXGUSDT"):
        try:
            return float(http_json(url)["price"]), url.split("symbol=")[1]
        except Exception as e:
            print(f"spot source failed: {e}", file=sys.stderr)
    return float(yf.Ticker("GC=F").history(period="5d")["Close"].iloc[-1]), "GC=F"


def load_chain():
    t = yf.Ticker("GLD")
    gld = float(t.history(period="5d")["Close"].iloc[-1])
    today = datetime.now(timezone.utc).date()
    opts = []
    for exp in t.options:
        days = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        if days < 0 or days > MAX_DAYS:
            continue
        T = max(days, 0.5) / 365
        ch = t.option_chain(exp)
        for kind, df in (("C", ch.calls), ("P", ch.puts)):
            for r in df.itertuples():
                oi, iv, bid, ask = r.openInterest, r.impliedVolatility, r.bid, r.ask
                if oi > 0 and iv > 0.01 and bid > 0 and ask > 0:  # NaN fails these checks
                    opts.append(dict(k=float(r.strike), kind=kind, oi=float(oi), iv=float(iv), T=T, days=days))
    if not opts:
        raise RuntimeError("no usable options rows")
    return gld, opts


def npdf(x): return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
def ncdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def greeks(S, K, T, iv, kind):
    sq = iv * math.sqrt(T)
    d1 = (math.log(S / K) + (RATE + 0.5 * iv * iv) * T) / sq
    delta = ncdf(d1) if kind == "C" else ncdf(d1) - 1
    gamma = npdf(d1) / (S * sq)
    vega = S * npdf(d1) * math.sqrt(T) / 100
    return delta, gamma, vega


def main():
    gld, opts = retry(load_chain)
    xau, src = retry(xau_spot)
    ratio = xau / gld

    strikes = {}
    for o in opts:
        dl, g, v = greeks(gld, o["k"], o["T"], o["iv"], o["kind"])
        s = strikes.setdefault(o["k"], dict(call_oi=0, put_oi=0, call_gex=0, put_gex=0, call_delta=0,
                                            put_delta=0, call_vega=0, put_vega=0, ivs=[]))
        gex = g * o["oi"] * 100 * gld * gld * 0.01
        s["ivs"].append(o["iv"])
        if o["kind"] == "C":
            s["call_oi"] += o["oi"]; s["call_gex"] += gex
            s["call_delta"] += dl * o["oi"] * 100; s["call_vega"] += v * o["oi"] * 100
        else:
            s["put_oi"] += o["oi"]; s["put_gex"] -= gex
            s["put_delta"] += dl * o["oi"] * 100; s["put_vega"] += v * o["oi"] * 100

    # ATM implied volatility and expected daily move
    near = min(o["days"] for o in opts)
    pool = [o for o in opts if o["days"] == near]
    atm_k = min((o["k"] for o in pool), key=lambda k: abs(k - gld))
    atm_ivs = [o["iv"] for o in pool if o["k"] == atm_k]
    atm_iv = sum(atm_ivs) / len(atm_ivs)
    em = xau * atm_iv * math.sqrt(1 / 252)

    # Walls
    up = [k for k in strikes if k > gld] or list(strikes)
    dn = [k for k in strikes if k < gld] or list(strikes)
    ck = max(up, key=lambda k: strikes[k]["call_gex"])
    pk = max(dn, key=lambda k: abs(strikes[k]["put_gex"]))
    call_wall = dict(price=round(ck * ratio, 2), open_interest=int(strikes[ck]["call_oi"]), gex=round(strikes[ck]["call_gex"]))
    put_wall = dict(price=round(pk * ratio, 2), open_interest=int(strikes[pk]["put_oi"]), gex=round(strikes[pk]["put_gex"]))

    # Gamma flip: zero crossing of total GEX over a +/-5% spot grid
    def total(P):
        t = 0.0
        for o in opts:
            _, g, _ = greeks(P, o["k"], o["T"], o["iv"], o["kind"])
            x = g * o["oi"] * 100 * P * P * 0.01
            t += x if o["kind"] == "C" else -x
        return t
    grid = [gld * (0.95 + 0.0025 * i) for i in range(41)]
    vals = [total(p) for p in grid]
    cross = []
    for i in range(40):
        a, b = vals[i], vals[i + 1]
        if a == 0:
            cross.append(grid[i])
        elif a * b < 0:
            cross.append(grid[i] + (grid[i + 1] - grid[i]) * (-a / (b - a)))
    flip_g = min(cross, key=lambda p: abs(p - gld)) if cross else grid[min(range(41), key=lambda i: abs(vals[i]))]
    gamma_flip = round(flip_g * ratio, 2)
    anchors = [call_wall["price"], put_wall["price"], gamma_flip]

    def pick(side):
        sign = 1 if side == "R" else -1
        pre = "call" if side == "R" else "put"
        c = []
        for k, s in strikes.items():
            p = k * ratio
            if not (xau < p <= xau * 1.04 if side == "R" else xau * 0.96 <= p < xau):
                continue
            c.append(dict(price=p, oi=s[pre + "_oi"], gex=abs(s[pre + "_gex"]), dl=abs(s[pre + "_delta"]),
                          vg=s[pre + "_vega"], iv=sum(s["ivs"]) / len(s["ivs"])))
        for n in (1, 2):
            c.append(dict(price=xau + sign * n * em, oi=0, gex=0, dl=0, vg=0, iv=atm_iv))
        mx = lambda key: max(x[key] for x in c) or 1
        mo, mg, md, mv = mx("oi"), mx("gex"), mx("dl"), mx("vg")
        ms = max(abs(x["iv"] - atm_iv) / atm_iv for x in c) or 1
        for x in c:
            skew = abs(x["iv"] - atm_iv) / atm_iv / ms
            emc = max(0, 1 - min(abs(x["price"] - (xau + sign * n * em)) for n in (1, 2)) / em)
            prox = max(0, 1 - min(abs(x["price"] - a) for a in anchors) / (2 * em))
            x["score"] = 100 * (0.35 * x["oi"] / mo + 0.25 * x["gex"] / mg
                                + 0.15 * (0.5 * x["dl"] / md + 0.5 * x["vg"] / mv)
                                + 0.15 * (0.5 * skew + 0.5 * emc) + 0.10 * prox)
        chosen = []
        for x in sorted(c, key=lambda x: -x["score"]):
            if all(abs(x["price"] - y["price"]) / x["price"] >= MIN_GAP for y in chosen):
                chosen.append(x)
            if len(chosen) == 3:
                break
        chosen.sort(key=lambda x: abs(x["price"] - xau))
        return [dict(price=round(x["price"], 2), score=round(x["score"], 1),
                     open_interest=int(x["oi"]), gex=round(x["gex"])) for x in chosen]

    top = sorted(strikes.items(), key=lambda kv: -abs(kv[1]["call_gex"] + kv[1]["put_gex"]))[:10]
    now = datetime.now(timezone.utc)
    out = dict(
        sample=False,
        analyzed_at=now.astimezone(ZoneInfo("Africa/Nairobi")).isoformat(timespec="seconds"),
        analyzed_at_utc=now.isoformat(timespec="seconds"),
        spot_source=src, gld_ratio=round(ratio, 4), gld_spot=round(gld, 2),
        xauusd_spot_at_analysis=round(xau, 2), atm_iv=round(atm_iv, 4), expected_move_1sd=round(em, 2),
        call_wall=call_wall, put_wall=put_wall, gamma_flip=gamma_flip,
        resistances=pick("R"), supports=pick("S"),
        top_gex_strikes=[dict(price=round(k * ratio, 2), net_gex=round(s["call_gex"] + s["put_gex"]),
                              call_oi=int(s["call_oi"]), put_oi=int(s["put_oi"])) for k, s in top],
    )
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, indent=2)
    os.replace(tmp, OUT)  # only reached on success, so old levels survive a failed run
    print("levels written", out["analyzed_at"])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"analysis failed, keeping previous levels: {e}", file=sys.stderr)
        sys.exit(1)
