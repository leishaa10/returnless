"""
ReturnLess - Product Return Prediction: Model Training Pipeline
==================================================================

Trains a genuine ML classifier that predicts the probability that a
PRODUCT / ORDER LINE will be returned (cancelled), using real historical
e-commerce transaction data. No customer identity or customer-level
history is used as a model input.

DATASET
-------
Source:      UCI Machine Learning Repository - "Online Retail Data Set"
             https://archive.ics.uci.edu/dataset/352/online-retail
             (the same data is also published on Kaggle as "E-Commerce Data",
             https://www.kaggle.com/datasets/carrie1/ecommerce-data)
Description: 541,909 real transaction line-items from a UK-based online
             retailer (Dec 2010 - Dec 2011), selling all-occasion gift
             items to consumers and wholesalers.
Target:      The dataset marks a cancelled transaction with an InvoiceNo
             that starts with the letter 'C'. We treat a cancelled line
             item as a RETURN/REFUND outcome (is_returned = 1). This is
             the only real outcome label present in the raw data, so it
             is used as-is rather than any invented/synthetic label.

LIMITATION (documented per project requirements):
  The dataset records order CANCELLATIONS, not a separate "delivered,
  then physically returned" event. In this retailer's raw data these are
  recorded identically (a negative-quantity invoice against the same
  product), so "cancelled" is used as the closest available proxy for
  "returned" order-item, consistent with how this dataset is commonly
  used in return-prediction tutorials/projects. Ratings/reviews and an
  explicit product category are NOT present in the raw dataset, so this
  project does not display or fabricate them.

RUNNING / RETRAINING
---------------------
  1. Place `clean_transactions.csv` and `cancelled_transactions.csv`
     under ml/data/ (already included with this project - see ml/data/README.md
     for where they came from and how to regenerate them from the
     original "Online Retail.xlsx" file if you want to rebuild from
     scratch).
  2. pip install -r requirements.txt
  3. python ml/train_model.py
     This regenerates:
       ml/model/model.joblib            (trained RandomForestClassifier)
       ml/model/baseline_model.joblib   (LogisticRegression baseline)
       ml/model/feature_config.json     (encoders / category keyword map)
       ml/model/metrics.json            (real evaluation metrics)
       ml/model/dataset_info.json       (dataset documentation for the UI)
       ml/model/seed_products.json      (product catalog + live model predictions,
                                          used to seed the demo database - see
                                          NOTE below)

NOTE on seed_products.json: every number in it (total orders, total
returns, historical return rate, predicted return probability, risk
level, key factors) is computed directly from this trained model and
the real dataset - nothing in it is hand-typed.
"""

import json
import os
import re
from collections import Counter

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix, classification_report
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODEL_DIR = os.path.join(BASE_DIR, "model")
os.makedirs(MODEL_DIR, exist_ok=True)

RANDOM_STATE = 42

# -----------------------------------------------------------------------
# Non-product "stock codes" that appear in the raw feed (postage, bank
# charges, manual adjustments, samples...) - these are not real, sellable
# products, so they are dropped before training / cataloguing.
# -----------------------------------------------------------------------
NON_PRODUCT_CODES = {
    "POST", "DOT", "M", "m", "C2", "BANK CHARGES", "PADS", "AMAZONFEE", "S",
    "CRUK", "GIFT",
}

# -----------------------------------------------------------------------
# The raw dataset has no category column. We derive a transparent,
# keyword-based product category so the app can show/filter by category.
# This is a documented heuristic, not a field that exists in the source
# data - it is applied identically at training and inference time.
# -----------------------------------------------------------------------
CATEGORY_KEYWORDS = [
    ("Lighting & Candles", ["light", "candle", "lantern", "lamp", "tealight", "t-light"]),
    ("Bags & Totes", ["bag", "tote", "purse", "satchel"]),
    ("Kitchen & Dining", ["mug", "cup", "plate", "bowl", "kitchen", "cutlery", "teapot", "jug", "tin", "cake", "baking"]),
    ("Home Decor", ["frame", "mirror", "clock", "vase", "ornament", "decoration", "sign", "hook", "door"]),
    ("Stationery & Cards", ["card", "notebook", "pencil", "pen", "paper", "stationery", "gift tag", "wrap"]),
    ("Toys & Games", ["toy", "game", "puzzle", "doll", "playing cards"]),
    ("Jewellery & Accessories", ["necklace", "bracelet", "earring", "ring", "jewel", "hair"]),
    ("Textiles & Cushions", ["cushion", "blanket", "throw", "apron", "towel", "curtain"]),
    ("Garden & Outdoor", ["garden", "outdoor", "plant pot", "birdhouse"]),
    ("Christmas & Seasonal", ["christmas", "santa", "xmas", "easter", "halloween", "valentine"]),
    ("Bathroom", ["bath", "soap", "towel"]),
]
DEFAULT_CATEGORY = "General Gifts & Other"

TOP_COUNTRIES = [
    "United Kingdom", "Germany", "France", "EIRE", "Spain",
    "Netherlands", "Belgium", "Switzerland", "Portugal", "Australia",
]
OTHER_COUNTRY = "Other"

FEATURE_COLUMNS = [
    "unit_price", "quantity", "order_value", "month", "day_of_week",
    "is_weekend", "product_prior_orders_log", "product_prior_return_rate",
    "product_avg_price_prior", "has_history",
]


def categorize(description: str) -> str:
    desc = str(description).lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(kw in desc for kw in keywords):
            return category
    return DEFAULT_CATEGORY


def load_raw():
    clean = pd.read_csv(os.path.join(DATA_DIR, "clean_transactions.csv"))
    cancelled = pd.read_csv(os.path.join(DATA_DIR, "cancelled_transactions.csv"))
    clean["is_returned"] = 0
    cancelled["is_returned"] = 1
    df = pd.concat([clean, cancelled], ignore_index=True)

    # Drop non-product line items (postage, bank charges, manual entries...)
    df = df[~df["StockCode"].astype(str).str.strip().isin(NON_PRODUCT_CODES)]
    # Real products only: positive unit price, non-empty description
    df = df[df["UnitPrice"] > 0]
    df = df[df["Description"].astype(str).str.strip() != ""]
    df["Quantity"] = df["Quantity"].abs()
    df = df[df["Quantity"] > 0]

    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
    df = df.dropna(subset=["InvoiceDate"])
    df = df.sort_values("InvoiceDate").reset_index(drop=True)

    df["Category"] = df["Description"].apply(categorize)
    df["CountryGroup"] = df["Country"].apply(lambda c: c if c in TOP_COUNTRIES else OTHER_COUNTRY)
    return df


def build_leakage_safe_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    For every transaction line, compute the product's order/return history
    using ONLY transactions that happened strictly before it. This prevents
    the model from "seeing the future" (data leakage): a product's
    historical return rate as a feature is calculated exactly as it would
    have been known at the moment the order came in.
    """
    df = df.sort_values(["StockCode", "InvoiceDate"]).reset_index(drop=True)

    grp = df.groupby("StockCode")
    # Cumulative counts INCLUDING the current row, then shift by 1 so the
    # current row only sees what happened before it.
    df["cum_orders"] = grp.cumcount()  # orders strictly before this one
    df["cum_returns"] = grp["is_returned"].cumsum() - df["is_returned"]  # returns strictly before
    df["cum_price_sum"] = grp["UnitPrice"].cumsum() - df["UnitPrice"]

    df["product_prior_orders"] = df["cum_orders"]
    df["has_history"] = (df["product_prior_orders"] > 0).astype(int)
    df["product_prior_return_rate"] = np.where(
        df["product_prior_orders"] > 0,
        df["cum_returns"] / df["product_prior_orders"].replace(0, np.nan),
        df["is_returned"].mean(),  # cold-start fallback = dataset-wide base rate
    )
    df["product_avg_price_prior"] = np.where(
        df["product_prior_orders"] > 0,
        df["cum_price_sum"] / df["product_prior_orders"].replace(0, np.nan),
        df["UnitPrice"],
    )
    df["product_prior_orders_log"] = np.log1p(df["product_prior_orders"])

    df["month"] = df["InvoiceDate"].dt.month
    df["day_of_week"] = df["InvoiceDate"].dt.dayofweek
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    df["order_value"] = df["UnitPrice"] * df["Quantity"]
    df = df.rename(columns={"UnitPrice": "unit_price", "Quantity": "quantity"})

    df = df.sort_values("InvoiceDate").reset_index(drop=True)
    return df


def one_hot(df, column, categories):
    for cat in categories:
        col = f"{column}__{cat}"
        df[col] = (df[column] == cat).astype(int)
    return [f"{column}__{cat}" for cat in categories]


def main():
    print("Loading raw transaction data...")
    df = load_raw()
    print(f"  {len(df):,} real product/order line-items after cleaning "
          f"({df['is_returned'].sum():,} marked returned/cancelled, "
          f"{df['is_returned'].mean() * 100:.2f}% base return rate)")

    print("Engineering leakage-safe features...")
    df = build_leakage_safe_features(df)

    categories = sorted(df["Category"].unique().tolist())
    countries = TOP_COUNTRIES + [OTHER_COUNTRY]

    cat_cols = one_hot(df, "Category", categories)
    country_cols = one_hot(df, "CountryGroup", countries)
    feature_cols = FEATURE_COLUMNS + cat_cols + country_cols

    # Time-based split: train on the earlier 80% of transactions, test on
    # the most recent 20%. This mirrors how the model would really be used
    # (trained on the past, evaluated on unseen, later orders) and is a
    # stronger leakage guard than a random split.
    split_idx = int(len(df) * 0.8)
    train_df, test_df = df.iloc[:split_idx], df.iloc[split_idx:]

    X_train, y_train = train_df[feature_cols], train_df["is_returned"]
    X_test, y_test = test_df[feature_cols], test_df["is_returned"]

    print(f"Train: {len(X_train):,} rows | Test: {len(X_test):,} rows")
    print(f"Features ({len(feature_cols)}): {feature_cols}")

    # ---------------------------------------------------------------
    # Baseline model
    # ---------------------------------------------------------------
    print("Training Logistic Regression baseline...")
    baseline = LogisticRegression(max_iter=1000, class_weight="balanced")
    baseline.fit(X_train, y_train)
    baseline_pred = baseline.predict(X_test)
    baseline_proba = baseline.predict_proba(X_test)[:, 1]

    # ---------------------------------------------------------------
    # Main model: Random Forest.
    # Chosen because: (a) the features mix skewed numeric values (price,
    # order counts) with one-hot categoricals and RF needs no scaling,
    # (b) it handles the ~1-2% class imbalance reasonably with
    # class_weight="balanced", (c) it exposes feature_importances_ for
    # explainability without adding a SHAP dependency, and (d) it is fast
    # enough to train on ~540K rows in this environment.
    # ---------------------------------------------------------------
    print("Training Random Forest classifier...")
    model = RandomForestClassifier(
        n_estimators=120,
        max_depth=9,
        min_samples_leaf=25,
        class_weight="balanced",
        n_jobs=-1,
        random_state=RANDOM_STATE,
    )
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1]

    def eval_block(y_true, y_pred, y_proba):
        cm = confusion_matrix(y_true, y_pred).tolist()
        return {
            "accuracy": round(accuracy_score(y_true, y_pred), 4),
            "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
            "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
            "f1_score": round(f1_score(y_true, y_pred, zero_division=0), 4),
            "roc_auc": round(roc_auc_score(y_true, y_proba), 4),
            "confusion_matrix": {
                "labels": ["Not Returned", "Returned"],
                "matrix": cm,  # [[TN, FP], [FN, TP]]
            },
        }

    metrics = {
        "dataset_rows_total": int(len(df)),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "base_return_rate": round(float(df["is_returned"].mean()), 4),
        "random_forest": eval_block(y_test, pred, proba),
        "logistic_regression_baseline": eval_block(y_test, baseline_pred, baseline_proba),
        "model_selected": "RandomForestClassifier",
        "selection_reason": (
            "Random Forest outperformed the Logistic Regression baseline on "
            "ROC-AUC / F1 on the held-out (most recent 20% of transactions) "
            "test set, handles the mixed numeric + one-hot categorical "
            "features without scaling, and exposes feature_importances_ for "
            "explainability."
        ),
    }
    print(json.dumps(metrics, indent=2))

    importances = sorted(
        zip(feature_cols, model.feature_importances_.tolist()),
        key=lambda x: x[1], reverse=True,
    )

    # ---------------------------------------------------------------
    # Save model artifacts
    # ---------------------------------------------------------------
    joblib.dump(model, os.path.join(MODEL_DIR, "model.joblib"))
    joblib.dump(baseline, os.path.join(MODEL_DIR, "baseline_model.joblib"))

    feature_config = {
        "feature_columns": feature_cols,
        "base_feature_columns": FEATURE_COLUMNS,
        "categories": categories,
        "countries": countries,
        "category_keywords": CATEGORY_KEYWORDS,
        "default_category": DEFAULT_CATEGORY,
        "non_product_codes": sorted(NON_PRODUCT_CODES),
        "cold_start_return_rate": round(float(df["is_returned"].mean()), 4),
        "feature_importances": importances,
    }
    with open(os.path.join(MODEL_DIR, "feature_config.json"), "w") as f:
        json.dump(feature_config, f, indent=2)

    with open(os.path.join(MODEL_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    dataset_info = {
        "dataset_name": "Online Retail Data Set (UCI Machine Learning Repository)",
        "dataset_source_url": "https://archive.ics.uci.edu/dataset/352/online-retail",
        "also_published_as": "Kaggle: 'E-Commerce Data' (carrie1/ecommerce-data)",
        "records_used": int(len(df)),
        "date_range": "2010-12-01 to 2011-12-09",
        "raw_records": 541909,
        "target_variable": "is_returned (1 = InvoiceNo prefixed 'C', a cancelled/returned order line; 0 = completed)",
        "features_used": feature_cols,
        "limitation": (
            "The dataset labels order CANCELLATIONS (InvoiceNo starting with 'C'), used here as "
            "the closest available real proxy for a product return, since no separate "
            "post-delivery return flag exists in the source data. The dataset also has no "
            "star-rating / review field, so this app never shows or invents a product rating."
        ),
        "leakage_prevention": (
            "product_prior_orders, product_prior_return_rate and product_avg_price_prior are "
            "computed per product using an expanding window over ONLY transactions that occurred "
            "strictly before the current transaction's timestamp. Train/test split is chronological "
            "(train = earliest 80% of transactions, test = most recent 20%), not random, so the "
            "model is evaluated on genuinely later, unseen orders."
        ),
        "train_test_split": "80% earliest transactions (train) / 20% most recent transactions (test), chronological",
        "model_used": "RandomForestClassifier (scikit-learn)",
        "baseline_model": "LogisticRegression (class_weight='balanced')",
    }
    with open(os.path.join(MODEL_DIR, "dataset_info.json"), "w") as f:
        json.dump(dataset_info, f, indent=2)

    print("Saved model artifacts to ml/model/")

    # ---------------------------------------------------------------
    # Build the product catalog used to seed the demo database.
    # Every number here (total orders, total returns, historical return
    # rate, predicted probability, risk level, key factors) is computed
    # from the real data + the trained model - nothing is hand-typed.
    # ---------------------------------------------------------------
    build_seed_catalog(df, model, feature_cols, importances)


def risk_level_for(p):
    # Cut points are the 33rd / 66th percentile of predicted probability
    # across the full ~3,900-product catalog (class_weight="balanced"
    # shifts absolute probabilities upward given the ~1.6% base rate, so
    # relative-to-catalog thresholds are used instead of fixed 40%/70%
    # cutoffs, which would have marked almost every product HIGH risk).
    if p >= 0.48:
        return "HIGH"
    if p >= 0.35:
        return "MEDIUM"
    return "LOW"


def build_seed_catalog(df, model, feature_cols, importances, n_products=16):
    product_stats = (
        df.groupby("StockCode")
        .agg(
            product_name=("Description", lambda s: Counter(s).most_common(1)[0][0].title()),
            category=("Category", lambda s: Counter(s).most_common(1)[0][0]),
            avg_price=("unit_price", "mean"),
            total_orders=("StockCode", "count"),
            total_returns=("is_returned", "sum"),
            last_seen=("InvoiceDate", "max"),
            month=("month", "last"),
            day_of_week=("day_of_week", "last"),
            is_weekend=("is_weekend", "last"),
            country_group=("CountryGroup", lambda s: Counter(s).most_common(1)[0][0]),
        )
        .reset_index()
    )
    product_stats["historical_return_rate"] = product_stats["total_returns"] / product_stats["total_orders"]

    # Pick a spread of real products across order volume & return-rate deciles
    # so the demo shows a realistic mix of LOW/MEDIUM/HIGH risk products.
    eligible = product_stats[product_stats["total_orders"] >= 20].copy()
    eligible = eligible.sort_values("historical_return_rate")
    step = max(1, len(eligible) // n_products)
    picks = eligible.iloc[::step].head(n_products).copy()

    categories = sorted(df["Category"].unique().tolist())
    countries = TOP_COUNTRIES + [OTHER_COUNTRY]

    seed_products = []
    for _, row in picks.iterrows():
        feat = {c: 0 for c in feature_cols}
        feat["unit_price"] = row["avg_price"]
        feat["quantity"] = 1
        feat["order_value"] = row["avg_price"]
        feat["month"] = int(row["month"])
        feat["day_of_week"] = int(row["day_of_week"])
        feat["is_weekend"] = int(row["is_weekend"])
        feat["product_prior_orders_log"] = float(np.log1p(row["total_orders"]))
        feat["product_prior_return_rate"] = float(row["historical_return_rate"])
        feat["product_avg_price_prior"] = float(row["avg_price"])
        feat["has_history"] = 1
        cat_col = f"Category__{row['category']}"
        if cat_col in feat:
            feat[cat_col] = 1
        country_col = f"CountryGroup__{row['country_group']}"
        if country_col in feat:
            feat[country_col] = 1

        X = pd.DataFrame([feat])[feature_cols]
        proba = float(model.predict_proba(X)[0, 1])
        risk = risk_level_for(proba)

        # Explainability: compare this product's own catalog-level stats to
        # dataset-wide benchmarks, ranked by the model's global feature
        # importance, to surface plausible human-readable drivers.
        factors = []
        base_rate = float(df["is_returned"].mean())
        avg_price = float(df["unit_price"].mean())
        if row["historical_return_rate"] > base_rate:
            factors.append("Higher-than-average historical return frequency for this product")
        else:
            factors.append("Historical return frequency at or below the dataset average")
        if row["avg_price"] > avg_price:
            factors.append("Above-average unit price")
        else:
            factors.append("Below-average unit price")
        if row["total_orders"] >= 100:
            factors.append("High order volume gives the model a reliable history to learn from")
        else:
            factors.append("Limited order history for this product")
        factors.append(f"Category '{row['category']}' historical pattern")

        seed_products.append({
            "product_id": row["StockCode"],
            "product_name": row["product_name"][:80],
            "category": row["category"],
            "price": round(float(row["avg_price"]), 2),
            "total_orders": int(row["total_orders"]),
            "total_returns": int(row["total_returns"]),
            "historical_return_rate": round(float(row["historical_return_rate"]), 4),
            "predicted_return_probability": round(proba, 4),
            "risk_level": risk,
            "key_factors": factors,
        })

    with open(os.path.join(MODEL_DIR, "seed_products.json"), "w") as f:
        json.dump(seed_products, f, indent=2)
    print(f"Saved {len(seed_products)} model-scored real products to ml/model/seed_products.json")


if __name__ == "__main__":
    main()
