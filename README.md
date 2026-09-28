# ReturnLess - B2B AI-Powered Product Return Risk Platform

> **What changed:** ReturnLess used to score individual *customers/orders* with a
> hand-written formula (customer return history, COD vs. prepaid, shipping
> distance...) including a hardcoded "82% return probability" for a
> presentation order (`#1025`). That has all been removed. ReturnLess now
> predicts **PRODUCT-level return risk** for a seller/merchant, using a
> **real trained machine-learning model** on a **real public dataset**.
> There is exactly one prediction pipeline in this app (`ml/predictor.py`),
> and every probability the UI shows comes from it - nothing is hand-typed.

---

## 1. What this app does

ReturnLess is a **B2B** platform: the user is a **seller/merchant**, not an
individual shopper. For each product in their catalog, ReturnLess shows:

* **Historical Return Rate** - Total Returns / Total Orders, straight from the data.
* **AI Predicted Return Probability** - the trained model's own output for
  that product, given its price, category, market, and order history.
* **Risk Level** - LOW / MEDIUM / HIGH, calibrated against the full product catalog.
* **Key Factors** - a short, human-readable explanation of what pushed the
  prediction up or down, derived from the model's feature importances.

The UI is careful to show these as two **different numbers**, never mixing
"historical" with "AI predicted" - see the Product Return Analysis page.

The dashboard, Product Return History, Analytics, and a dedicated
**AI Model & Dataset** page round out the B2B experience: total products
analyzed, high-risk products, category-wise return trends, and an estimated
return cost exposure.

---

## 2. The dataset

| | |
|---|---|
| **Name** | Online Retail Data Set (UCI Machine Learning Repository) |
| **Also published as** | Kaggle: "E-Commerce Data" (`carrie1/ecommerce-data`) |
| **Source** | https://archive.ics.uci.edu/dataset/352/online-retail |
| **Size** | 541,909 raw transaction line-items; 536,570 used after cleaning |
| **Period** | 2010-12-01 to 2011-12-09 |
| **What it is** | Real transactions from a UK-based online gift retailer, selling to consumers and wholesalers worldwide |

**Target variable:** the dataset marks a **cancelled order** with an
`InvoiceNo` that starts with `C`. This is used as `is_returned = 1` - the
closest real outcome label available. There is no separate "delivered, then
physically returned" flag in the source data, so a cancellation is used as
the return proxy, exactly as this dataset is commonly used in return/churn
prediction tutorials. This limitation is documented in-app on the **AI Model
& Dataset** page, not hidden.

**What the dataset does *not* have**, and so this app never shows or invents:
a star rating/review score, or an explicit product category (a transparent,
keyword-based category heuristic is used instead - see
`ml/train_model.py::CATEGORY_KEYWORDS`).

The two source files used for training live in `ml/data/`:
`clean_transactions.csv` (531,283 completed transactions) and
`cancelled_transactions.csv` (9,289 cancelled transactions).

---

## 3. The ML pipeline (`ml/train_model.py`)

```
Raw UCI transactions
  -> drop non-product rows (postage, bank charges, manual entries...)
  -> derive a product category from the description (keyword heuristic)
  -> engineer LEAKAGE-SAFE features (see below)
  -> chronological 80/20 train/test split
  -> train RandomForestClassifier (class_weight="balanced")
     + a LogisticRegression baseline for comparison
  -> evaluate on the held-out, most-recent 20% of transactions
  -> save model.joblib, feature_config.json, metrics.json, dataset_info.json
  -> score a spread of REAL products from the catalog -> seed_products.json
```

**Leakage prevention:** a product's `product_prior_orders`,
`product_prior_return_rate` and `product_avg_price_prior` are computed with
an expanding window over only the transactions that happened **strictly
before** the current one (see `build_leakage_safe_features`). The
train/test split is **chronological**, not random - the model is evaluated
on genuinely later, unseen orders, not a random shuffle of the same period.

**Features used (33):** unit price, quantity, order value, month/day-of-week/
weekend flag, the product's own prior order count & prior return rate & prior
average price, a "has history" flag (cold-start indicator), one-hot product
category (12 categories), one-hot market/country group (10 top countries +
"Other"). No customer ID, name, or any customer-level field is used anywhere.

**Why Random Forest:** it beat the Logistic Regression baseline on ROC-AUC
and F1 on the held-out set, needs no feature scaling for the mixed
numeric/one-hot inputs, handles the ~1.6% class imbalance via
`class_weight="balanced"`, and exposes `feature_importances_` for
explainability without an extra SHAP dependency.

### Evaluation (on the held-out, most-recent 20% of transactions)

| Metric | Random Forest | Logistic Regression (baseline) |
|---|---|---|
| Accuracy | 81.7% | 71.8% |
| Precision | 4.0% | 2.7% |
| Recall | 59.5% | 62.3% |
| F1-score | 7.4% | 5.2% |
| ROC-AUC | 0.789 | 0.725 |

Confusion matrix (Random Forest): TN 86,834 / FP 19,153 / FN 537 / TP 790.

**Read this honestly:** returns are only ~1.6% of all transactions, so
precision is low by construction - a classifier that "cries wolf" on ~19%
of non-returns to catch 60% of real returns is a real, disclosed trade-off,
not an accuracy claim. **ROC-AUC (0.79)** - how well the model ranks
returned vs. non-returned items relative to each other - is the more
informative number here, and it is well above the 0.50 random-guess
baseline. This is all shown, with the same caveat, on the in-app
**AI Model & Dataset** page.

**Risk-level calibration:** because `class_weight="balanced"` shifts
absolute predicted probabilities upward (given the low base rate), fixed
cutoffs like 40%/70% would have marked almost every product "HIGH risk".
Instead, LOW/MEDIUM/HIGH cut points (35% / 48%) are the 33rd/66th
percentile of predicted probability across the ~3,900-product catalog -
see `risk_level_for()` in both `train_model.py` and `predictor.py`.

### Retraining

```bash
pip install -r requirements.txt
python ml/train_model.py
```

This regenerates everything under `ml/model/`. Documentation of where the
two CSVs came from is at the top of `ml/train_model.py`'s module docstring.

---

## 4. How a prediction is served (`ml/predictor.py` + `POST /predict-return`)

`ml/predictor.py` is the **only** place in this app that computes a
return-probability number. It loads `ml/model/model.joblib` +
`feature_config.json` once, then:

1. Takes product-level input only: `product_name`, `category`, `price`,
   `quantity`, `total_orders`, `total_returns`, `market`. No customer field
   is accepted.
2. Builds the same feature vector used at training time (including the
   cold-start fallback for a brand-new product with 0 prior orders).
3. Calls `model.predict_proba(...)` - a real scikit-learn inference call.
4. Derives `risk_level` from the calibrated cutoffs, and `key_factors` from
   the model's global feature importances compared against this product's
   own values.

```
POST /predict-return
Content-Type: application/json

{ "product_name": "Running Shoes", "category": "Kitchen & Dining",
  "price": 25.0, "total_orders": 500, "total_returns": 85 }
```
```json
{
  "success": true,
  "prediction": 0.5885,
  "predicted_return_probability": 0.5885,
  "risk_level": "HIGH",
  "historical_return_rate": 0.17,
  "category": "Kitchen & Dining",
  "market": "United Kingdom",
  "key_factors": [
    "This product's historical return rate is above the dataset-wide average",
    "Unit price (GBP 25.00) is on the higher side for this category",
    "High order volume gives the model a reliable history to learn from",
    "Market/region 'United Kingdom' historical return pattern"
  ],
  "inputs_used": { "...": "..." }
}
```

This same endpoint powers both the **live preview** on the "Analyze Product"
page (debounced as you type) and the saved prediction shown throughout the
app. `GET /api/model-info` exposes the dataset/pipeline documentation and
metrics for the in-app AI Model & Dataset page; `GET /api/meta` exposes the
model's own category/market lists so the intake form never offers a category
the model doesn't know.

---

## 5. Full page list

1. **Landing / Login / Register** - unchanged B2B marketing + auth shell.
2. **Dashboard (`#dashboard`)** - Total Products Analyzed, High-Risk Products,
   Avg. AI Predicted Probability, Estimated Return Cost Exposure; a
   highest-risk-products table; risk distribution donut.
3. **Analyze Product (`#add-order`)** - product intake form (identity, price,
   market, order history) with a live `/predict-return` preview showing
   Historical Rate *and* AI Predicted Probability side by side, plus 3
   presets built from real dataset products (incl. a cold-start example).
4. **Product Return Analysis (`#order-details`)** - the two headline numbers,
   risk badge, AI-generated recommendation, estimated cost exposure, key
   factors, and seller actions (Mark Listing Improved / Flag for Monitoring /
   Discontinue Product).
5. **Product Return History (`#order-history`)** - full catalog table with
   search + risk/category filters.
6. **Analytics & Reports (`#analytics`)** - historical rate by category,
   historical-vs-AI-predicted comparison by category, top 8 highest-risk
   products.
7. **AI Model & Dataset (`#model-info`)** - dataset source & limitations, ML
   pipeline description, leakage prevention, live evaluation metrics +
   confusion matrix, top feature importances. Everything on this page is
   read from `ml/model/*.json`.
8. **SaaS Plans (`#plans`)** and **Store Settings (`#settings`)** - unchanged.

---

## 6. How to run locally

### Requirements
* Python 3.9+
* `pip install -r requirements.txt` (pandas, scikit-learn, joblib - needed
  for the ML inference the old zero-dependency version didn't have)

### Quick launch
```cmd
run.bat
```
or
```bash
pip install -r requirements.txt
python server.py
```
Then open `http://localhost:8000`. The model is already trained and
committed under `ml/model/`; `python ml/train_model.py` retrains it from the
CSVs in `ml/data/`.

## 6b. Login flow & Admin Dashboard

* **Company sign-in:** the login form has a **Company** dropdown (populated from the
  `business_profile` table). Pick a company, enter that company's work email and
  password, and you land on that company's own dashboard. The email must belong to
  the selected company.
* **Admin (separate from companies):** click *"ReturnLess admin? Sign in here"* under
  the form. Defaults: `admin@returnless.com` / `admin123` (override with the
  `RETURNLESS_ADMIN_EMAIL` and `RETURNLESS_ADMIN_PASSWORD` environment variables).
* **Admin Dashboard (`#admin`):** overall metrics across all companies, risk
  distribution, a company comparison chart + table, and a per-company analysis tab
  for each company. All numbers come live from the existing `products` /
  `business_profile` tables via `GET /api/admin/overview` (requires the admin session
  token issued at admin login).

---

## 7. Payments (Razorpay) - unchanged

The **SaaS Plans** page takes payments through the Razorpay flow:
`create order (server) -> checkout -> verify signature (server) -> plan activated`,
shown under **Billing history**. This part of the app was not touched by the
AI rework.

* **Default: simulated checkout.** No keys needed, works offline.
* **Real Razorpay (test or live keys):**
```cmd
set RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
set RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
python server.py
```
Optional: `RAZORPAY_WEBHOOK_SECRET`, `RETURNLESS_CURRENCY=INR` (default `USD`),
`RAZORPAY_MODE=mock`.

---

## 8. Files changed / added for the AI rework

| File | What changed |
|---|---|
| `ml/train_model.py` | New. Full training pipeline (data prep, features, training, evaluation, seed catalog). |
| `ml/predictor.py` | New. The one real inference module used by the backend. |
| `ml/model/*` | New. Trained model + config + metrics + dataset docs + seed catalog (all regenerable). |
| `ml/data/*.csv` | New. The two UCI source files used for training. |
| `prediction_engine.py` | Removed. This was the old hand-written, customer-level scoring formula with a hardcoded order #1025 override. |
| `database.py` | Rewritten. `orders` (customer-level) becomes `products` (product-level) table; seeded from real model output, not hand-typed demo rows. |
| `server.py` | Rewritten. New `POST /predict-return`, `/api/products*`, `/api/model-info`, `/api/meta` endpoints. Payments endpoints unchanged. |
| `static/js/prediction.js` | Rewritten. The old in-browser fake scoring engine is gone; this now just wraps a `fetch('/predict-return')` call. |
| `static/js/app.js` | Rewritten. Product-level rendering everywhere; live preview now calls the real API instead of a local formula. |
| `static/js/charts.js` | Rewritten. The old "payment method risk" chart (fabricated) and "savings trend" chart (hardcoded fake time series) are replaced with real category comparisons and a real top-risk-products chart. |
| `static/index.html` | Rewritten intake form, analysis page, history table, analytics page; added the AI Model & Dataset page. |
| `requirements.txt` | New. pandas, scikit-learn, joblib. |

## 9. Limitations (stated plainly)

* "Returned" = cancelled order (`InvoiceNo` starts with `C`), the closest
  proxy available in this dataset - not a confirmed post-delivery physical
  return.
* No product rating/review field exists in the source data, so none is shown.
* Product category is a keyword heuristic, not a field from the source data.
* Precision is low (~4%) given the ~1.6% base return rate; ROC-AUC (0.79) is
  the more meaningful metric for this problem. See Section 3.
* The seed catalog uses 16 real products spanning the risk spectrum, not the
  full ~3,900-product catalog, to keep the demo fast and readable; sellers
  can add any product via the intake form.
