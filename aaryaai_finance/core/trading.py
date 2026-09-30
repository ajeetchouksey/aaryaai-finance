"""Learn-by-doing trading: backtests and a paper-trading (fake money) account.

Ideas borrowed from backtesting.py / vectorbt / backtrader, re-implemented
small so every line is readable. No real orders are ever placed.

Plain-English metrics:
- CAGR: the steady yearly growth rate that would give the same end result.
- Max drawdown: the worst fall from a peak — "how much would I have seen
  disappear at the worst moment". This is what makes people panic-sell.
- Volatility: how bumpy the ride is (yearly standard deviation).
- Sharpe: return per unit of bumpiness. Above 1 is good, above 2 is rare.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd


# ---------- prices ----------
def fetch_prices(ticker: str, start: str, end: str | None = None) -> pd.Series:
    """Daily close prices. Uses yfinance (needs internet on your PC).
    Tickers: 'IWDA.AS' (MSCI World ETF, Amsterdam), 'VWCE.DE' (FTSE All-World,
    Xetra), 'RELIANCE.NS' (NSE India), '^NSEI' (Nifty 50), 'SAP.DE'."""
    import yfinance as yf  # optional dependency
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"No price data for {ticker}")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna().rename(ticker)


def prices_from_csv(text: str) -> pd.Series:
    """CSV with Date and Close (or Adj Close) columns."""
    from io import StringIO
    df = pd.read_csv(StringIO(text))
    cols = {c.lower().strip(): c for c in df.columns}
    dcol = cols.get("date") or df.columns[0]
    ccol = cols.get("adj close") or cols.get("close") or df.columns[-1]
    s = pd.Series(pd.to_numeric(df[ccol], errors="coerce").values,
                  index=pd.to_datetime(df[dcol]), name="csv").dropna().sort_index()
    return s


def synthetic_prices(years: int = 10, seed: int = 4, drift: float = 0.07, vol: float = 0.18) -> pd.Series:
    """Random-walk demo data so you can play without internet. NOT a real market."""
    rng = np.random.default_rng(seed)
    n = years * 252
    rets = rng.normal(drift / 252, vol / math.sqrt(252), n)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rets)), index=idx, name="DEMO")


# ---------- strategies: return a position series in [0,1] ----------
def strat_buy_hold(p: pd.Series, **_) -> pd.Series:
    return pd.Series(1.0, index=p.index)


def strat_sma_cross(p: pd.Series, fast: int = 50, slow: int = 200, **_) -> pd.Series:
    """Be invested when the short average is above the long average (trend following)."""
    f, s = p.rolling(fast).mean(), p.rolling(slow).mean()
    return (f > s).astype(float).shift(1).fillna(0)  # act the day AFTER the signal


def strat_momentum(p: pd.Series, lookback: int = 252, **_) -> pd.Series:
    """Invested only if the price is higher than a year ago."""
    return (p > p.shift(lookback)).astype(float).shift(1).fillna(0)


def strat_rsi(p: pd.Series, period: int = 14, low: int = 30, high: int = 70, **_) -> pd.Series:
    """Buy when 'oversold' (RSI<low), sell when 'overbought' (RSI>high)."""
    d = p.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    pos = pd.Series(np.nan, index=p.index)
    pos[rsi < low] = 1.0
    pos[rsi > high] = 0.0
    return pos.ffill().fillna(0).shift(1).fillna(0)


STRATEGIES = {
    "buy_hold": (strat_buy_hold, "Buy & hold — buy once, never sell."),
    "sma_cross": (strat_sma_cross, "Trend following — hold only while the 50-day average is above the 200-day average."),
    "momentum": (strat_momentum, "12-month momentum — hold only if the price is above where it was a year ago."),
    "rsi": (strat_rsi, "Mean reversion (RSI) — buy dips when 'oversold', sell when 'overbought'."),
}


def _metrics(equity: pd.Series) -> dict:
    rets = equity.pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    vol = rets.std() * math.sqrt(252)
    sharpe = (rets.mean() * 252) / vol if vol > 0 else 0
    dd = (equity / equity.cummax() - 1).min()
    return {"cagr": round(float(cagr), 4), "volatility": round(float(vol), 4),
            "sharpe": round(float(sharpe), 2), "max_drawdown": round(float(dd), 4),
            "final": round(float(equity.iloc[-1]), 2), "years": round(years, 1)}


def backtest(prices: pd.Series, strategy: str = "sma_cross", capital: float = 10000,
             cost_pct: float = 0.001, params: dict | None = None) -> dict:
    fn, desc = STRATEGIES[strategy]
    pos = fn(prices, **(params or {}))
    rets = prices.pct_change().fillna(0)
    trades = pos.diff().abs().fillna(pos.iloc[0])
    strat_rets = pos * rets - trades * cost_pct  # every buy/sell costs cost_pct
    eq = capital * (1 + strat_rets).cumprod()
    bh = capital * (1 + rets).cumprod()
    m, mb = _metrics(eq), _metrics(bh)
    n_trades = int((trades > 0).sum())
    time_in = float(pos.mean())
    # plain-English verdict
    beat = m["final"] > mb["final"]
    verdict = (
        f"{desc} Starting with {capital:,.0f}, this ended at {m['final']:,.0f} "
        f"({m['cagr']:.1%} a year) vs {mb['final']:,.0f} ({mb['cagr']:.1%}) for simply buying and holding. "
        f"Worst fall along the way: {m['max_drawdown']:.0%} (buy & hold: {mb['max_drawdown']:.0%}). "
        f"It made {n_trades} trades and was invested {time_in:.0%} of the time. "
    )
    if strategy != "buy_hold":
        if beat:
            verdict += ("It beat buy-and-hold here — but past results often don't repeat, and most countries tax "
                        "every profitable sale, which this test ignores.")
        elif m["max_drawdown"] > mb["max_drawdown"]:
            verdict += ("It earned less but had smaller falls — a trade-off some people accept "
                        "for a calmer ride.")
        else:
            verdict += "It lost to simply buying and holding — the most common outcome for trading rules."
    step = max(len(eq) // 400, 1)
    series = [{"d": str(i.date()), "s": round(float(a), 2), "b": round(float(b), 2)}
              for i, a, b in zip(eq.index[::step], eq.values[::step], bh.values[::step])]
    return {"strategy": strategy, "description": desc, "metrics": m, "buy_hold": mb,
            "trades": n_trades, "time_in_market": round(time_in, 3), "verdict": verdict,
            "series": series}


def sip_backtest(prices: pd.Series, monthly: float = 500) -> dict:
    """Invest a fixed amount on the first trading day of every month (a 'Sparplan'/SIP)."""
    firsts = prices.groupby([prices.index.year, prices.index.month]).head(1)
    units = (monthly / firsts).cumsum()
    invested = pd.Series(np.arange(1, len(firsts) + 1) * monthly, index=firsts.index)
    value = units * firsts
    gain = float(value.iloc[-1] - invested.iloc[-1])
    return {
        "months": len(firsts), "invested": round(float(invested.iloc[-1]), 2),
        "value": round(float(value.iloc[-1]), 2), "gain": round(gain, 2),
        "explanation": (
            f"Putting {monthly:,.0f} in every month for {len(firsts)} months: you paid in "
            f"{invested.iloc[-1]:,.0f} and it's now worth {value.iloc[-1]:,.0f}. Buying monthly "
            f"means you automatically buy more units when prices are low ('cost averaging')."),
        "series": [{"d": str(i.date()), "invested": round(float(a), 2), "value": round(float(b), 2)}
                   for i, a, b in zip(firsts.index, invested.values, value.values)],
    }


# ---------- paper trading ----------
def paper_positions(trades: list[dict], starting_cash: float) -> dict:
    """trades: {ticker, side: buy|sell, qty, price, fee}. Average-cost accounting."""
    cash, pos = starting_cash, {}
    realized = 0.0
    for t in sorted(trades, key=lambda x: x["ts"]):
        q, px, fee = t["qty"], t["price"], t.get("fee", 0) or 0
        p = pos.setdefault(t["ticker"], {"qty": 0.0, "cost": 0.0})
        if t["side"] == "buy":
            cash -= q * px + fee
            p["cost"] += q * px + fee
            p["qty"] += q
        else:
            avg = p["cost"] / p["qty"] if p["qty"] else 0
            realized += q * (px - avg) - fee
            p["cost"] -= avg * q
            p["qty"] -= q
            cash += q * px - fee
    open_pos = {k: {"qty": round(v["qty"], 6), "avg_cost": round(v["cost"] / v["qty"], 4)}
                for k, v in pos.items() if v["qty"] > 1e-9}
    return {"cash": round(cash, 2), "positions": open_pos, "realized_pnl": round(realized, 2)}
