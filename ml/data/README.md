# ml/data - training data

`cancelled_transactions.csv` (824 KB, 9,289 rows) is committed as-is - it's
small and is the "returns" half of the real signal used for training.

`clean_transactions.csv` (531,283 completed-order rows, ~46 MB) is **not**
committed to keep this repository small. The trained model
(`ml/model/model.joblib`) already ships pre-built, so you do **not** need
this file to run the app - only to re-run `python ml/train_model.py` from
scratch.

## Regenerating clean_transactions.csv

The original source is the UCI "Online Retail" dataset:
https://archive.ics.uci.edu/dataset/352/online-retail
(also on Kaggle as `carrie1/ecommerce-data`).

1. Download `Online Retail.xlsx` from the link above (or the Kaggle CSV).
2. Split it into the two files this project expects:

```python
import pandas as pd

df = pd.read_excel("Online Retail.xlsx")  # or pd.read_csv(...) for the Kaggle CSV
cancelled = df[df["InvoiceNo"].astype(str).str.startswith("C")]
clean = df[~df["InvoiceNo"].astype(str).str.startswith("C")]

clean.to_csv("ml/data/clean_transactions.csv", index=False)
cancelled.to_csv("ml/data/cancelled_transactions.csv", index=False)
```

3. Run `python ml/train_model.py` to retrain and regenerate everything under
   `ml/model/`.
