"""ขั้นที่ 3: baseline โมเดลพยากรณ์ราคา + ทดสอบว่าตัวแปรแต่ละกลุ่มช่วยจริงไหม

    python 3_baseline.py

วิธีทดสอบ: train ด้วยฤดูก่อนหน้าทั้งหมด -> test กับฤดูถัดไป (ไม่เอาอนาคตมาสอนโมเดล)
เทียบ 4 โมเดล
    naive     ราคาอีก h สัปดาห์ = ราคาสัปดาห์นี้             (ขั้นต่ำที่ต้องชนะให้ได้)
    seasonal  naive + การเปลี่ยนแปลงเฉลี่ยของสัปดาห์นั้นในฤดูก่อน ๆ
    ridge     linear regression + ตัวแปรทั้งหมด
    gbm       gradient boosting + ตัวแปรทั้งหมด

ช่วงราคา 80% มาจาก error จริงของโมเดลในฤดูก่อน ๆ (ไม่ใช้ error ของฤดูที่กำลังทดสอบ)

ทำทุกชนิดใน config.TARGETS (หมอนทอง, ชะนี) ผลรวมอยู่ในไฟล์เดียว มีคอลัมน์ product_id บอกชนิด
ผลลัพธ์ใน outputs/
    metrics.csv          MAE (บาท/กก.), MAPE, ชนะ naive กี่ %, ช่วงราคาครอบคลุมราคาจริงกี่ %
    ablation.csv         ถ้าตัดตัวแปรกลุ่มนี้ออก error เปลี่ยนเท่าไหร่ (บวก = กลุ่มนี้ช่วยจริง)
    latest_forecast.csv  พยากรณ์ล่าสุดจากสัปดาห์สุดท้ายที่มีข้อมูล (ใช้โมเดลที่แม่นสุดของแต่ละ horizon)
    backtest_h1_<รหัส>.png  กราฟราคาจริง vs พยากรณ์ 1 สัปดาห์
"""
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import config as C

warnings.filterwarnings("ignore", category=UserWarning)

GROUPS = {
    "price": ["price_mid", "price_min", "price_max", "price_range", "mid_lag1", "mid_lag2",
              "mid_ma4", "chg_1w", "imputed"],
    "season": ["week_of_season", "woy_sin", "woy_cos", "month"],
    "retail": ["retail_mid", "retail_spread"],
    "weather": ["rain_7d", "rain_30d", "rain_90d", "tmax_7d", "tmin_7d", "rh_7d"],
    "fx": ["cny_thb", "cny_thb_chg_4w"],
    "festival": ["days_to_festival", "pre_festival", "target_days_to_festival_h{h}",
                 "target_pre_festival_h{h}"],
}
GROUP_TH = {"season": "ฤดูกาล/วันที่", "retail": "ราคาขายปลีก", "weather": "สภาพอากาศ",
            "fx": "ค่าเงินหยวน", "festival": "เทศกาลจีน"}


def features(df, h, drop=()):
    cols = []
    for g, cs in GROUPS.items():
        if g in drop:
            continue
        cols += [c.format(h=h) for c in cs]
    return [c for c in cols if c in df.columns and df[c].notna().any()]


MODELS = ("naive", "seasonal", "ridge", "gbm")


def gbm():
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=300,
                                         min_samples_leaf=5, l2_regularization=1.0, random_state=0)


def ridge():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=10))


def folds(d):
    """train = ฤดูก่อนหน้าทั้งหมด, test = ฤดูถัดไป"""
    seasons = sorted(d["season_id"].unique())
    if len(seasons) >= 2:
        for s in seasons[1:]:
            yield f"season {int(s)}", d[d["season_id"] < s], d[d["season_id"] == s]
    else:
        print("   ⚠ มีฤดูเดียว — แบ่ง 70% แรก train / 30% หลัง test (ผลเชื่อถือได้น้อย)")
        cut = int(len(d) * 0.7)
        yield "single-season", d.iloc[:cut], d.iloc[cut:]


def run_horizon(df, h):
    tcol = f"target_h{h}"
    d = df[df[tcol].notna() & df["price_mid"].notna()].copy()
    d["y"] = np.log(d[tcol] / d["price_mid"])      # พยากรณ์ % การเปลี่ยนแปลง แล้วแปลงกลับเป็นบาท
    X = features(d, h)
    preds = []
    for name, tr, te in folds(d):
        if len(tr) < 10 or te.empty:
            continue
        p = pd.DataFrame(index=te.index)
        p["fold"], p["season_id"] = name, te["season_id"]
        p["actual"], p["base"] = te[tcol], te["price_mid"]
        p["naive"] = 0.0
        by_wk = tr.groupby("week_of_season")["y"].mean()
        p["seasonal"] = te["week_of_season"].map(by_wk).fillna(0).values
        cols = [c for c in X if tr[c].notna().any()]
        p["ridge"] = ridge().fit(tr[cols], tr["y"]).predict(te[cols])
        p["gbm"] = gbm().fit(tr[cols], tr["y"]).predict(te[cols])
        # ablation: ตัดทีละกลุ่ม
        for g in GROUP_TH:
            cg = [c for c in features(tr, h, drop=(g,)) if tr[c].notna().any()]
            if set(cg) != set(cols):
                p[f"abl_{g}"] = gbm().fit(tr[cg], tr["y"]).predict(te[cg])
        preds.append(p)
    if not preds:
        return None
    P = pd.concat(preds)
    for c in [c for c in P.columns if c in MODELS or c.startswith("abl_")]:
        P[c] = P["base"] * np.exp(P[c])
    # ช่วงราคา: ใช้ error (log) ของโมเดลเดียวกันจากฤดูที่ทดสอบไปก่อนหน้าเท่านั้น
    order = list(dict.fromkeys(P["fold"]))
    for m in MODELS:
        r = np.log(P["actual"] / P[m])
        lo = pd.Series(np.nan, index=P.index)
        hi = lo.copy()
        for i, f in enumerate(order[1:], 1):
            prior = r[P["fold"].isin(order[:i])]
            if len(prior) >= 10:
                q0, q1 = prior.quantile(C.INTERVAL[0]), prior.quantile(C.INTERVAL[1])
                idx = P["fold"] == f
                lo[idx], hi[idx] = P.loc[idx, m] * np.exp(q0), P.loc[idx, m] * np.exp(q1)
        P[f"{m}_lo"], P[f"{m}_hi"] = lo, hi
    return P


def mae(P, c):
    return (P[c] - P["actual"]).abs().mean()


def summarize(P, h):
    rows = []
    naive = mae(P, "naive")
    for m in MODELS:
        e = mae(P, m)
        iv = P[P[f"{m}_lo"].notna()]
        cover = ((iv["actual"] >= iv[f"{m}_lo"]) & (iv["actual"] <= iv[f"{m}_hi"])).mean()
        rows.append({"horizon_weeks": h, "model": m, "MAE_baht": round(e, 2),
                     "MAPE_%": round(((P[m] - P["actual"]).abs() / P["actual"]).mean() * 100, 2),
                     "better_than_naive_%": round((1 - e / naive) * 100, 1), "n_test_weeks": len(P),
                     "interval_coverage_%": round(cover * 100, 1) if len(iv) else np.nan,
                     "interval_width_baht": round((iv[f"{m}_hi"] - iv[f"{m}_lo"]).mean(), 2)
                     if len(iv) else np.nan})
    abl = []
    full = mae(P, "gbm")
    for g, th in GROUP_TH.items():
        if f"abl_{g}" in P:
            e = mae(P, f"abl_{g}")
            abl.append({"horizon_weeks": h, "group": g, "กลุ่มตัวแปร": th,
                        "MAE_without_group": round(e, 2), "MAE_full": round(full, 2),
                        "change_if_removed": round(e - full, 2),
                        "verdict": "ช่วย" if e - full > 0.01 * full else
                        ("ทำให้แย่ลง" if e - full < -0.01 * full else "ไม่ต่าง")})
    return rows, abl


def latest_forecast(df, results):
    """พยากรณ์จากสัปดาห์ล่าสุดที่มีราคาจริง ด้วยโมเดลที่ MAE ต่ำสุดของแต่ละ horizon
    ช่วงราคา = error จริงทั้งหมดของโมเดลนั้นใน backtest"""
    out = []
    last = df[df["observed"] == 1].index.max()
    row = df.loc[[last]]
    base = row["price_mid"].iloc[0]
    for h, (P, best) in results.items():
        tcol = f"target_h{h}"
        d = df[df[tcol].notna() & df["price_mid"].notna()].copy()
        d["y"] = np.log(d[tcol] / d["price_mid"])
        cols = [c for c in features(d, h) if d[c].notna().any()]
        if best == "naive":
            y = 0.0
        elif best == "seasonal":
            y = d.groupby("week_of_season")["y"].mean().get(row["week_of_season"].iloc[0], 0.0)
        else:
            y = (gbm() if best == "gbm" else ridge()).fit(d[cols], d["y"]).predict(row[cols])[0]
        point = base * np.exp(y)
        r = np.log(P["actual"] / P[best])
        out.append({"from_week": last.date(), "horizon_weeks": h,
                    "target_week": (last + pd.Timedelta(weeks=h)).date(), "model": best,
                    "last_price": round(base, 1), "forecast": round(point, 1),
                    "low_80": round(point * np.exp(r.quantile(C.INTERVAL[0])), 1),
                    "high_80": round(point * np.exp(r.quantile(C.INTERVAL[1])), 1)})
    return pd.DataFrame(out), last


def plot(P, m, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    seasons = P["season_id"].unique()[-6:]          # แสดง 6 ฤดูล่าสุด
    ncol = min(3, len(seasons))
    nrow = -(-len(seasons) // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(5 * ncol, 3.6 * nrow), squeeze=False)
    for ax in axes.flat[len(seasons):]:
        ax.set_visible(False)
    for ax, s in zip(axes.flat, seasons):
        g = P[P["season_id"] == s]
        ax.fill_between(g.index, g[f"{m}_lo"], g[f"{m}_hi"], alpha=0.2, label=f"{m} 80% range")
        ax.plot(g.index, g["actual"], "k-o", ms=3, label="actual")
        ax.plot(g.index, g["naive"], "--", label="naive")
        ax.plot(g.index, g[m], "-", label=m)
        ax.set_title(f"Season {int(s)} - 1-week-ahead")
        ax.set_ylabel("THB/kg")
        ax.tick_params(axis="x", rotation=45)
    axes[0][0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def run_target(pid, cfg):
    path = C.PROCESSED / f"weekly_features_{pid}.csv"
    if not path.exists():
        print(f"⚠ ไม่มี {path.name} — รัน 2_build_features.py ก่อน")
        return None
    df = pd.read_csv(path, index_col="week_end", parse_dates=True)
    metrics, ablation, results = [], [], {}
    for h in cfg["horizons"]:
        print(f"→ {cfg['name']}: ทดสอบพยากรณ์ล่วงหน้า {h} สัปดาห์")
        P = run_horizon(df, h)
        if P is None:
            print("   ข้อมูลไม่พอสำหรับ horizon นี้")
            continue
        m, a = summarize(P, h)
        metrics += m
        ablation += a
        best = min(m, key=lambda r: r["MAE_baht"])["model"]
        results[h] = (P, best)
        if h == 1:
            plot(P, best, C.OUTPUTS / f"backtest_h1_{pid}.png")
    F, last = latest_forecast(df, results)
    tag = lambda d: d.assign(product_id=pid, product=cfg["name"])  # noqa: E731
    return tag(pd.DataFrame(metrics)), tag(pd.DataFrame(ablation)), tag(F), last


if __name__ == "__main__":
    C.OUTPUTS.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    Ms, As, Fs = [], [], []
    for pid, cfg in C.TARGETS.items():
        print(f"\n################ {cfg['name']} ขายส่ง ({pid}) ################")
        r = run_target(pid, cfg)
        if r is None:
            continue
        M, A, F, last = r
        Ms.append(M), As.append(A), Fs.append(F)
        print("\n=== ความแม่น (MAE ยิ่งต่ำยิ่งดี) ===")
        print(M.drop(columns=["product_id", "product"]).to_string(index=False))
        if not A.empty:
            print("\n=== ตัวแปรแต่ละกลุ่มช่วยจริงไหม (change_if_removed > 0 = ช่วย) ===")
            print(A[["horizon_weeks", "กลุ่มตัวแปร", "MAE_full", "MAE_without_group",
                     "change_if_removed", "verdict"]].to_string(index=False))
        print(f"\n=== พยากรณ์ล่าสุด (จากสัปดาห์ {last.date()}) ===")
        print(F.drop(columns=["product_id", "product"]).to_string(index=False))
        gap = (pd.Timestamp.today() - last).days
        if gap > 21:
            print(f"⚠ ราคาจริงล่าสุดเก่ากว่าวันนี้ {gap} วัน (น่าจะอยู่นอกฤดู) — "
                  "พยากรณ์นี้ใช้ได้เป็นตัวอย่าง ไม่ใช่ราคาของสัปดาห์หน้าจริง")
    if Ms:
        pd.concat(Ms).to_csv(C.OUTPUTS / "metrics.csv", index=False, encoding="utf-8-sig")
        pd.concat(As).to_csv(C.OUTPUTS / "ablation.csv", index=False, encoding="utf-8-sig")
        pd.concat(Fs).to_csv(C.OUTPUTS / "latest_forecast.csv", index=False, encoding="utf-8-sig")
        print("\nบันทึก outputs/metrics.csv, ablation.csv, latest_forecast.csv")