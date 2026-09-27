import importlib
import pandas as pd
import config as C

m4 = importlib.import_module("4_direction_model")
df = pd.read_csv(C.PROCESSED / "weekly_features_W14021.csv", index_col="week_end", parse_dates=True)
d = m4.make_label(df)

WEATHER = ["rain_7d", "rain_30d", "rain_90d", "tmax_7d", "rh_7d"]
FX = ["cny_thb", "cny_thb_chg_4w"]
full = list(m4.FEATURES)

rows = []
for name, drop in [("ใช้ทุกตัวแปร", []), ("ไม่มีอากาศ", WEATHER),
                   ("ไม่มีค่าเงิน", FX), ("ไม่มีทั้งคู่", WEATHER + FX)]:
    m4.FEATURES = [c for c in full if c not in drop]
    P = m4.backtest(d)
    r = [x for x in m4.score(P, name) if x["model"] == "logistic"][0]
    rows.append({"แบบ": name, "Brier": r["Brier"], "skill_vs_base_%": r["skill_vs_base_%"], "AUC": r["AUC"]})

print(pd.DataFrame(rows).to_string(index=False))