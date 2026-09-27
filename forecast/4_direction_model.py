"""ขั้นที่ 4: ทำนาย "โอกาสที่ราคาจะลดลง" แทนการทำนายตัวเลขราคา

    python 4_direction_model.py

คำถาม: ภายใน WINDOW สัปดาห์ข้างหน้า ราคาขายส่งจะลดลงอย่างน้อย DROP_BAHT บาท/กก. ไหม
       -> ตอบเป็น % เช่น "โอกาสราคาลง 65%" ใช้ช่วยตัดสินใจว่าตัดขายตอนนี้หรือรอ

เทียบ 4 วิธี (ทดสอบแบบ train ฤดูก่อน -> test ฤดูถัดไป เหมือนขั้นที่ 3)
    base_rate   ใช้ % ที่ราคาเคยลงในอดีตทั้งหมด (ค่าคงที่)         <- ขั้นต่ำที่ต้องชนะ
    seasonal    % ที่ราคาเคยลง ในช่วงเดียวกันของฤดู (ต้น/กลาง/ปลาย)
    logistic    logistic regression + ตัวแปรทั้งหมด
    gbm         gradient boosting + ตัวแปรทั้งหมด

และเทียบ 2 แบบของข้อมูลที่ใช้สอน: ทุกปี vs เฉพาะปี RECENT_FROM ขึ้นไป
(ทดสอบกับฤดูชุดเดียวกัน คือฤดูที่เริ่มตั้งแต่ TEST_FROM จะได้เทียบกันได้ตรง ๆ)

วัดผล
    Brier       ความคลาดเคลื่อนของ % (ยิ่งต่ำยิ่งดี)
    skill_%     ดีกว่า base_rate กี่ %  (บวก = มีประโยชน์จริง)
    AUC         แยกสัปดาห์ที่ราคาลง/ไม่ลงได้ดีแค่ไหน (0.5 = เดาสุ่ม, 1 = สมบูรณ์)

ผลลัพธ์ใน outputs/
    direction_metrics.csv    ตารางเทียบทุกวิธี
    direction_forecast.csv   % โอกาสราคาลง ของสัปดาห์ล่าสุด (ให้ทีมเว็บใช้)
"""
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import config as C

warnings.filterwarnings("ignore")

DROP_BAHT = 5        # ลดลงอย่างน้อยกี่บาท/กก. ถึงนับว่า "ราคาลง"
WINDOW = 2           # ภายในกี่สัปดาห์ (ต้องมีใน horizons ของ config)
RECENT_FROM = 2017   # แบบ "ข้อมูลช่วงหลัง" ใช้ฤดูที่เริ่มตั้งแต่ปีนี้
TEST_FROM = 2019     # ทดสอบกับฤดูที่เริ่มตั้งแต่ปีนี้ (ทั้งสองแบบใช้ชุดเดียวกัน)

FEATURES = [
    # ราคา
    "price_mid", "price_range", "mid_lag1", "mid_lag2", "mid_ma4", "chg_1w",
    # ตำแหน่งในฤดู
    "week_of_season", "woy_sin", "woy_cos",
    # ปลีก / อากาศ / ค่าเงิน / เทศกาล
    "retail_spread", "rain_7d", "rain_30d", "rain_90d", "tmax_7d", "rh_7d",
    "cny_thb", "cny_thb_chg_4w", "days_to_festival", f"target_days_to_festival_h{WINDOW}",
]
MODELS = ("base_rate", "seasonal", "logistic", "gbm")


def make_label(df):
    """1 = ภายใน WINDOW สัปดาห์ มีสัปดาห์ที่ราคาต่ำกว่าตอนนี้ >= DROP_BAHT"""
    fut = [f"target_h{h}" for h in range(1, WINDOW + 1) if f"target_h{h}" in df]
    if f"target_h{WINDOW}" not in df:
        raise SystemExit(f"ไม่มี target_h{WINDOW} — เพิ่ม {WINDOW} ใน horizons ของ config แล้วรันขั้นที่ 2 ใหม่")
    d = df[df["price_mid"].notna() & df[f"target_h{WINDOW}"].notna()].copy()
    d["future_min"] = d[fut].min(axis=1)
    d["y"] = (d["future_min"] <= d["price_mid"] - DROP_BAHT).astype(int)
    d["season_start"] = d.groupby("season_id")["week_of_season"].transform(
        lambda s: s.index.min().year)
    d["phase"] = pd.cut(d["week_of_season"], [0, 6, 14, 999], labels=["ต้น", "กลาง", "ปลาย"])
    return d


def logistic():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(C=0.3, max_iter=2000))


def gbm():
    return HistGradientBoostingClassifier(max_depth=2, learning_rate=0.05, max_iter=200,
                                          min_samples_leaf=10, l2_regularization=1.0, random_state=0)


def predict_all(tr, te, cols):
    p = pd.DataFrame(index=te.index)
    p["y"], p["season_id"] = te["y"], te["season_id"]
    p["base_rate"] = tr["y"].mean()
    # seasonal: % ราคาลงแยกตามช่วงของฤดู (ถ่วงเข้าหาค่าเฉลี่ยรวม กันกลุ่มเล็กเหวี่ยง)
    g = tr.groupby("phase", observed=False)["y"].agg(["sum", "count"])
    k = 10
    rate = (g["sum"] + k * tr["y"].mean()) / (g["count"] + k)
    p["seasonal"] = te["phase"].map(rate).astype(float).fillna(tr["y"].mean()).values
    if tr["y"].nunique() < 2:
        p["logistic"] = p["gbm"] = p["base_rate"]
    else:
        p["logistic"] = logistic().fit(tr[cols], tr["y"]).predict_proba(te[cols])[:, 1]
        p["gbm"] = gbm().fit(tr[cols], tr["y"]).predict_proba(te[cols])[:, 1]
    return p


def backtest(d, train_from=None):
    cols = [c for c in FEATURES if c in d and d[c].notna().any()]
    preds = []
    for s in sorted(d.loc[d["season_start"] >= TEST_FROM, "season_id"].unique()):
        tr = d[d["season_id"] < s]
        if train_from:
            tr = tr[tr["season_start"] >= train_from]
        te = d[d["season_id"] == s]
        if len(tr) < 20 or te.empty:
            continue
        preds.append(predict_all(tr, te, [c for c in cols if tr[c].notna().any()]))
    return pd.concat(preds) if preds else None


def score(P, label):
    rows = []
    ref = brier_score_loss(P["y"], P["base_rate"])
    for m in MODELS:
        b = brier_score_loss(P["y"], P[m])
        auc = roc_auc_score(P["y"], P[m]) if P["y"].nunique() == 2 and P[m].nunique() > 1 else np.nan
        rows.append({"train_data": label, "model": m, "Brier": round(b, 4),
                     "skill_vs_base_%": round((1 - b / ref) * 100, 1),
                     "AUC": round(auc, 3) if not np.isnan(auc) else np.nan,
                     "accuracy_at_50%": round(((P[m] >= 0.5) == P["y"]).mean() * 100, 1),
                     "test_weeks": len(P), "actual_drop_rate_%": round(P["y"].mean() * 100, 1)})
    return rows


def latest(df, d, best_model, train_from):
    last = df[df["observed"] == 1].index.max()
    row = df.loc[[last]].copy()
    row["phase"] = pd.cut(row["week_of_season"], [0, 6, 14, 999], labels=["ต้น", "กลาง", "ปลาย"])
    tr = d if not train_from else d[d["season_start"] >= train_from]
    cols = [c for c in FEATURES if c in tr and tr[c].notna().any()]
    row = row.reindex(columns=list(row.columns) + [c for c in cols if c not in row.columns])
    row["y"] = np.nan
    row["season_id"] = df.loc[last, "season_id"]
    prob = float(predict_all(tr, row, cols)[best_model].iloc[0])
    return last, prob


def message(prob, price):
    target = price - DROP_BAHT
    if prob >= 0.6:
        advice = "มีแนวโน้มลง ถ้าผลพร้อมตัด การขายเร็วน่าจะได้ราคาดีกว่า"
    elif prob <= 0.3:
        advice = "โอกาสลงต่ำ ถ้ายังรอได้ไม่ต้องรีบ"
    else:
        advice = "ไม่ชัดเจน ราคาอาจทรงตัว"
    return (f"โอกาสที่ราคาจะลดลงถึง {target:.0f} บาท/กก. หรือต่ำกว่า "
            f"ภายใน {WINDOW} สัปดาห์: {prob * 100:.0f}% — {advice}")


if __name__ == "__main__":
    C.OUTPUTS.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    all_rows, fc_rows = [], []
    for pid, cfg in C.TARGETS.items():
        path = C.PROCESSED / f"weekly_features_{pid}.csv"
        if not path.exists():
            print(f"⚠ ไม่มี {path.name} — รัน 2_build_features.py ก่อน")
            continue
        print(f"\n################ {cfg['name']} ขายส่ง ({pid}) ################")
        df = pd.read_csv(path, index_col="week_end", parse_dates=True)
        d = make_label(df)
        print(f"ราคาลง >= {DROP_BAHT} บาทภายใน {WINDOW} สัปดาห์ เกิดขึ้น "
              f"{d['y'].mean() * 100:.0f}% ของสัปดาห์ทั้งหมด ({int(d['y'].sum())}/{len(d)})")

        rows, best = [], None
        for label, tf in (("ทุกปี", None), (f"{RECENT_FROM}+", RECENT_FROM)):
            P = backtest(d, tf)
            if P is None:
                print(f"   ⚠ {label}: ข้อมูลไม่พอทดสอบ")
                continue
            r = score(P, label)
            rows += r
            for x in r:
                if best is None or x["Brier"] < best[0]:
                    best = (x["Brier"], x["model"], tf, label)
        if not rows:
            continue
        M = pd.DataFrame(rows)
        print("\n=== ผลทดสอบ (Brier ยิ่งต่ำยิ่งดี, skill > 0 = ดีกว่าเดาจากสถิติอดีต) ===")
        print(M.to_string(index=False))
        all_rows += [dict(x, product_id=pid, product=cfg["name"]) for x in rows]

        _, model, tf, label = best
        last, prob = latest(df, d, model, tf)
        price = df.loc[last, "price_mid"]
        msg = message(prob, price)
        print(f"\n=== สัปดาห์ล่าสุด {last.date()} ราคา {price:.1f} บาท (ใช้ {model}, ข้อมูล {label}) ===")
        print(msg)
        if model == "base_rate":
            print("   (หมายเหตุ: วิธีที่ดีที่สุดคือค่าเฉลี่ยในอดีต แปลว่าตัวแปรยังไม่ช่วยทำนาย)")
        gap = (pd.Timestamp.today() - last).days
        if gap > 21:
            print(f"⚠ ราคาจริงล่าสุดเก่ากว่าวันนี้ {gap} วัน (น่าจะอยู่นอกฤดู) — ใช้เป็นตัวอย่างเท่านั้น")
        fc_rows.append({"product_id": pid, "product": cfg["name"], "from_week": last.date(),
                        "last_price": round(price, 1), "drop_baht": DROP_BAHT,
                        "window_weeks": WINDOW, "prob_drop": round(prob, 3), "model": model,
                        "train_data": label, "message": msg})

    if all_rows:
        pd.DataFrame(all_rows).to_csv(C.OUTPUTS / "direction_metrics.csv", index=False,
                                      encoding="utf-8-sig")
        pd.DataFrame(fc_rows).to_csv(C.OUTPUTS / "direction_forecast.csv", index=False,
                                     encoding="utf-8-sig")
        print("\nบันทึก outputs/direction_metrics.csv, direction_forecast.csv")