"""ขั้นที่ 2: ทำความสะอาด + รวมทุกแหล่งเป็นตารางรายสัปดาห์ + รายงานว่าข้อมูลพอไหม

    python 2_build_features.py

ผลลัพธ์ (แยกตามชนิด เช่น W14021 = หมอนทอง, W14020 = ชะนี):
    data/processed/weekly_features_<รหัส>.csv   ตารางรายสัปดาห์ (1 แถว = 1 สัปดาห์ สิ้นสุดวันอาทิตย์)
    outputs/data_report_<รหัส>.md               จำนวนฤดู / สัปดาห์ต่อฤดู / สรุปว่าพอพยากรณ์ไหม
    outputs/weekly_price_<รหัส>.png             กราฟราคารายสัปดาห์ทุกปี (ดูหน้าตาของฤดู)
"""
import numpy as np
import pandas as pd

import config as C

WEEK = "W-SUN"  # สัปดาห์จันทร์-อาทิตย์ ใช้วันอาทิตย์เป็นป้ายชื่อสัปดาห์


# ------------------------------------------------------------------ prices
def load_prices(pid):
    path = C.RAW / f"moc_{pid}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=False, errors="coerce")
    # กันกรณีไฟล์เป็นปี พ.ศ.
    be = df["date"].dt.year > 2400
    df.loc[be, "date"] = df.loc[be, "date"] - pd.DateOffset(years=543)
    for c in ("price_min", "price_max"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df.loc[df[c] <= 0, c] = np.nan          # ราคา 0 = ไม่มีของขาย ไม่ใช่ราคาจริง
    swap = df["price_min"] > df["price_max"]
    df.loc[swap, ["price_min", "price_max"]] = df.loc[swap, ["price_max", "price_min"]].values
    df = df.dropna(subset=["date"]).dropna(subset=["price_min", "price_max"], how="all")
    df["price_mid"] = df[["price_min", "price_max"]].mean(axis=1)
    df = df.drop_duplicates("date").set_index("date").sort_index()
    w = df.resample(WEEK).agg(price_min=("price_min", "mean"), price_max=("price_max", "mean"),
                              price_mid=("price_mid", "mean"), n_days=("price_mid", "count"))
    w.loc[w["n_days"] == 0, ["price_min", "price_max", "price_mid"]] = np.nan
    return w


def assign_seasons(mid):
    """แบ่งฤดูจากช่วงที่มีราคา: ว่างติดกันเกิน SEASON_GAP_WEEKS สัปดาห์ = ขึ้นฤดูใหม่"""
    season = pd.Series(np.nan, index=mid.index)
    obs = mid.dropna().index
    if obs.empty:
        return season
    sid, start, prev = 0, obs[0], obs[0]
    runs = []
    for t in obs[1:]:
        gap = (t - prev).days // 7 - 1
        if gap > C.SEASON_GAP_WEEKS:
            runs.append((start, prev))
            start = t
        prev = t
    runs.append((start, prev))
    for sid, (s, e) in enumerate(runs, 1):
        season.loc[s:e] = sid
    return season


# ------------------------------------------------------------------ weather / fx / festival
def weekly_weather(week_ends):
    path = C.RAW / "weather_daily.csv"
    if not path.exists():
        print("⚠ ไม่มีไฟล์อากาศ — ข้าม")
        return pd.DataFrame(index=week_ends)
    d = pd.read_csv(path, parse_dates=["date"])
    d = d.groupby("date")[C.WEATHER_VARS].mean().asfreq("D")   # เฉลี่ยทุกจังหวัด
    out = pd.DataFrame(index=d.index)
    rain = d["precipitation_sum"]
    out["rain_7d"] = rain.rolling(7, min_periods=5).sum()
    out["rain_30d"] = rain.rolling(30, min_periods=25).sum()
    out["rain_90d"] = rain.rolling(90, min_periods=75).sum()
    out["tmax_7d"] = d["temperature_2m_max"].rolling(7, min_periods=5).mean()
    out["tmin_7d"] = d["temperature_2m_min"].rolling(7, min_periods=5).mean()
    out["rh_7d"] = d["relative_humidity_2m_mean"].rolling(7, min_periods=5).mean()
    return out.reindex(week_ends, method="ffill", limit=7)


def weekly_fx(week_ends):
    path = C.RAW / "fx_cny_thb.csv"
    if not path.exists():
        print("⚠ ไม่มีไฟล์ค่าเงิน — ข้าม")
        return pd.DataFrame(index=week_ends)
    d = pd.read_csv(path, parse_dates=["date"]).set_index("date")["cny_thb"].asfreq("D").ffill(limit=10)
    out = pd.DataFrame({"cny_thb": d})
    out["cny_thb_chg_4w"] = d.pct_change(28, fill_method=None)
    return out.reindex(week_ends, method="ffill", limit=7)


def festival_starts(years):
    import holidays
    cn = holidays.China(years=years)
    starts = []
    for d, name in sorted(cn.items()):
        for key in C.FESTIVALS:
            if name.startswith(key) and "补假" not in name:
                d = pd.Timestamp(d)
                # เอาวันแรกของเทศกาลที่ติดกันหลายวัน
                if not starts or starts[-1][1] != key or (d - starts[-1][0]).days > 10:
                    starts.append((d, key))
    return starts


def weekly_festival(week_ends):
    years = range(week_ends.min().year, week_ends.max().year + 2)
    starts = sorted(d for d, _ in festival_starts(list(years)))
    s = pd.Series(starts)
    idx = np.searchsorted(s.values, week_ends.values)          # เทศกาลถัดไปที่ >= วันนั้น
    nxt = s.reindex(idx).values
    days = (pd.to_datetime(nxt) - week_ends).days
    out = pd.DataFrame(index=week_ends)
    out["days_to_festival"] = days
    out["pre_festival"] = ((days >= 0) & (days <= C.PRE_FESTIVAL_DAYS)).astype(int)
    return out


# ------------------------------------------------------------------ build
def build(pid, cfg):
    ws = load_prices(pid)
    if ws is None or ws["price_mid"].notna().sum() == 0:
        print(f"⚠ ไม่พบราคาขายส่ง {pid} — ข้าม (รัน 1_fetch_data.py ก่อน)")
        return None
    ws = ws.loc[ws["price_mid"].first_valid_index(): ws["price_mid"].last_valid_index()]
    ws = ws.asfreq(WEEK)

    df = pd.DataFrame(index=ws.index)
    df.index.name = "week_end"
    df["season_id"] = assign_seasons(ws["price_mid"])
    df["observed"] = ws["price_mid"].notna().astype(int)

    # เติมเฉพาะช่องว่างสั้น ภายในฤดู — ช่วงนอกฤดูปล่อยว่าง
    for c in ("price_min", "price_max", "price_mid"):
        filled = ws[c].ffill(limit=C.FILL_GAP_WEEKS)
        df[c] = filled.where(df["season_id"].notna())
    df["imputed"] = ((df["observed"] == 0) & df["price_mid"].notna()).astype(int)
    df["n_days"] = ws["n_days"].fillna(0).astype(int)

    # ---- ฟีเจอร์ราคา (รู้ได้ ณ สัปดาห์ t) ----
    g = df.groupby("season_id")["price_mid"]
    df["price_range"] = df["price_max"] - df["price_min"]
    df["mid_lag1"] = g.shift(1)
    df["mid_lag2"] = g.shift(2)
    df["mid_ma4"] = g.transform(lambda s: s.rolling(4, min_periods=2).mean())
    df["chg_1w"] = np.log(df["price_mid"] / df["mid_lag1"])
    df["week_of_season"] = df.groupby("season_id").cumcount() + 1
    df.loc[df["season_id"].isna(), "week_of_season"] = np.nan
    woy = df.index.isocalendar().week.astype(float).values
    df["woy_sin"] = np.sin(2 * np.pi * woy / 52.18)
    df["woy_cos"] = np.cos(2 * np.pi * woy / 52.18)
    df["month"] = df.index.month

    rt = load_prices(cfg["retail"])
    if rt is not None:
        rt = rt.reindex(df.index)
        df["retail_mid"] = rt["price_mid"].ffill(limit=C.FILL_GAP_WEEKS)
        df["retail_spread"] = df["retail_mid"] - df["price_mid"]
    else:
        print("⚠ ไม่มีราคาขายปลีก — ข้ามฟีเจอร์ส่วนต่างปลีก-ส่ง")

    df = df.join(weekly_weather(df.index)).join(weekly_fx(df.index)).join(weekly_festival(df.index))

    # ---- เป้าหมาย: ราคากลางอีก h สัปดาห์ (เฉพาะที่ยังอยู่ในฤดูเดียวกันและเป็นค่าจริง ไม่ใช่ค่าที่เติม) ----
    for h in cfg["horizons"]:
        fut = df["price_mid"].shift(-h)
        ok = (df["season_id"].shift(-h) == df["season_id"]) & (df["observed"].shift(-h) == 1)
        df[f"target_h{h}"] = fut.where(ok)
        # วันเทศกาลรู้ล่วงหน้า จึงใช้ค่าของ "สัปดาห์เป้าหมาย" ได้โดยไม่รั่ว
        df[f"target_days_to_festival_h{h}"] = df["days_to_festival"].shift(-h)
        df[f"target_pre_festival_h{h}"] = df["pre_festival"].shift(-h)
    return df


def report(df, pid, cfg):
    s = df[df["season_id"].notna()]
    rows = []
    for sid, g in s.groupby("season_id"):
        rows.append({
            "ฤดู": int(sid), "เริ่ม": g.index.min().date(), "จบ": g.index.max().date(),
            "จำนวนสัปดาห์": len(g), "สัปดาห์ที่มีราคาจริง": int(g["observed"].sum()),
            "ราคากลางต่ำสุด": round(g["price_mid"].min(), 1),
            "ราคากลางสูงสุด": round(g["price_mid"].max(), 1),
        })
    t = pd.DataFrame(rows)
    n = len(t)
    full = int((t["สัปดาห์ที่มีราคาจริง"] >= 8).sum()) if n else 0
    if full >= 3:
        verdict = f"✅ พอ — มี {full} ฤดูที่ข้อมูลครบพอ ทดสอบแบบ train ฤดูก่อน → test ฤดูถัดไปได้"
    elif full >= 1:
        verdict = (f"⚠️ พอทำได้แต่จำกัด — มีแค่ {full} ฤดูที่ข้อมูลครบพอ "
                   "ควรพยากรณ์สั้น (1–2 สัปดาห์) และเขียนข้อจำกัดในรายงาน")
    else:
        verdict = "❌ ไม่พอ — ไม่มีฤดูไหนที่มีราคาจริงถึง 8 สัปดาห์"

    md = [f"# รายงานความพร้อมของข้อมูล: {cfg['name']} ขายส่ง ({pid})\n",
          f"- ราคาขายส่ง `{pid}` ตั้งแต่ {df.index.min().date()} ถึง {df.index.max().date()}",
          f"- พบ {n} ฤดู | สัปดาห์ที่เติมค่า (ช่องว่างสั้น): {int(df['imputed'].sum())}",
          f"- **สรุป: {verdict}**\n",
          t.to_markdown(index=False) if n else "(ไม่มีข้อมูล)", "",
          "## ความครบของตัวแปร (สัดส่วนที่ไม่ว่าง ในสัปดาห์ในฤดู)\n"]
    cov = s.drop(columns=[c for c in s.columns if c.startswith("target")]).notna().mean().round(2)
    md.append(cov.to_frame("ครบ").to_markdown())
    C.OUTPUTS.mkdir(parents=True, exist_ok=True)
    (C.OUTPUTS / f"data_report_{pid}.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:4]))
    print(t.to_string(index=False) if n else "")


def plot_weekly(df, pid, cfg):
    """กราฟราคารายสัปดาห์ 1 เส้นต่อปี วางซ้อนตามสัปดาห์ของปี -> เห็นว่าฤดูอยู่ช่วงไหน"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    axes[0].plot(df.index, df["price_mid"], lw=1)
    axes[0].set_title(f"{pid} weekly mid price (all years)")
    axes[0].set_ylabel("THB/kg")
    years = sorted(df.index.year.unique())
    cmap = plt.get_cmap("viridis", len(years))
    for i, y in enumerate(years):
        g = df[df.index.year == y]
        axes[1].plot(g.index.isocalendar().week, g["price_mid"], color=cmap(i), lw=1.2,
                     label=str(y))
    axes[1].set_title(f"{pid} by week of year (one line per year)")
    axes[1].set_xlabel("week of year (Apr ~ wk 14, Sep ~ wk 36)")
    axes[1].set_ylabel("THB/kg")
    axes[1].legend(ncol=6, fontsize=7)
    fig.tight_layout()
    fig.savefig(C.OUTPUTS / f"weekly_price_{pid}.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    C.PROCESSED.mkdir(parents=True, exist_ok=True)
    C.OUTPUTS.mkdir(parents=True, exist_ok=True)
    for pid, cfg in C.TARGETS.items():
        print(f"\n################ {cfg['name']} ขายส่ง ({pid}) ################")
        df = build(pid, cfg)
        if df is None:
            continue
        out = C.PROCESSED / f"weekly_features_{pid}.csv"
        df.to_csv(out, encoding="utf-8-sig")
        print(f"บันทึก {out.name} ({len(df)} สัปดาห์, {df.shape[1]} คอลัมน์)\n")
        report(df, pid, cfg)
        plot_weekly(df, pid, cfg)
