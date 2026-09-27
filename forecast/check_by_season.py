import importlib
import pandas as pd
from sklearn.metrics import brier_score_loss
import config as C

m4 = importlib.import_module("4_direction_model")
df = pd.read_csv(C.PROCESSED / "weekly_features_W14021.csv", index_col="week_end", parse_dates=True)
d = m4.make_label(df)
P = m4.backtest(d)   # ทุกปี

rows = []
for s, g in P.groupby("season_id"):
    b_base = brier_score_loss(g["y"], g["base_rate"])
    b_log = brier_score_loss(g["y"], g["logistic"])
    rows.append({"ฤดูปี": d.loc[d["season_id"] == s, "season_start"].iloc[0],
                 "สัปดาห์": len(g), "ราคาลงจริง_%": round(g["y"].mean() * 100),
                 "Brier_base": round(b_base, 3), "Brier_logistic": round(b_log, 3),
                 "logistic_ชนะ": "✅" if b_log < b_base else "❌"})

t = pd.DataFrame(rows)
print(t.to_string(index=False))
print(f"\nlogistic ชนะ {(t['logistic_ชนะ'] == '✅').sum()} จาก {len(t)} ฤดู")