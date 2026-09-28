"""
ReturnLess - Product Return Prediction: Inference Module
===========================================================
Loads the artifacts produced by ml/train_model.py and exposes a single
`predict_product(...)` function used by the backend's POST /predict-return
endpoint. There is exactly ONE prediction pipeline in this application -
this module - and every return-probability number the app shows comes
from here.

No customer identity or customer-level history is used as input.
"""
import json
import os
from datetime import datetime

import joblib
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "model")

_model = None
_feature_config = None
_dataset_info = None
_metrics = None


def _load():
    global _model, _feature_config, _dataset_info, _metrics
    if _model is None:
        _model = joblib.load(os.path.join(MODEL_DIR, "model.joblib"))
        with open(os.path.join(MODEL_DIR, "feature_config.json")) as f:
            _feature_config = json.load(f)
        with open(os.path.join(MODEL_DIR, "dataset_info.json")) as f:
            _dataset_info = json.load(f)
        with open(os.path.join(MODEL_DIR, "metrics.json")) as f:
            _metrics = json.load(f)
    return _model, _feature_config, _dataset_info, _metrics


def is_ready():
    try:
        _load()
        return True
    except FileNotFoundError:
        return False


def categorize(description: str) -> str:
    """Same keyword heuristic used at training time (see train_model.py)."""
    _, cfg, _, _ = _load()
    desc = str(description or "").lower()
    for category, keywords in cfg["category_keywords"]:
        if any(kw in desc for kw in keywords):
            return category
    return cfg["default_category"]


def get_categories():
    _, cfg, _, _ = _load()
    return cfg["categories"]


def get_countries():
    _, cfg, _, _ = _load()
    return cfg["countries"]


def get_model_info():
    _, cfg, dataset_info, metrics = _load()
    return {
        "dataset_info": dataset_info,
        "metrics": metrics,
        "top_feature_importances": cfg["feature_importances"][:10],
    }


def risk_level_for(p):
    # Same calibrated cut points used at training time (see
    # train_model.py::risk_level_for) - the 33rd / 66th percentile of
    # predicted probability across the full product catalog, since
    # class_weight="balanced" shifts absolute probabilities upward given
    # the dataset's low (~1.6%) base return rate.
    if p >= 0.48:
        return "HIGH"
    if p >= 0.35:
        return "MEDIUM"
    return "LOW"


def predict_product(payload: dict) -> dict:
    """
    Runs the real trained model on product-level inputs ONLY (price,
    category, market, and the product's own prior order/return history).
    No customer identity or customer behaviour is accepted or used.

    payload keys (all optional except price):
      product_name        str
      category             str   (matched with the same heuristic used in
                                   training if not one of the known category
                                   labels; free text is fine)
      price                float (required)
      quantity              int   (units per order, default 1)
      total_orders         int   (this product's total orders to date, default 0)
      total_returns        int   (this product's total returns to date, default 0)
      market               str   (country/region; default 'United Kingdom')
    """
    model, cfg, dataset_info, _ = _load()
    feature_cols = cfg["feature_columns"]

    price = float(payload.get("price", 0) or 0)
    quantity = max(1, int(payload.get("quantity", 1) or 1))
    total_orders = max(0, int(payload.get("total_orders", 0) or 0))
    total_returns = max(0, min(int(payload.get("total_returns", 0) or 0), total_orders if total_orders else int(payload.get("total_returns", 0) or 0)))

    category_input = str(payload.get("category", "") or "").strip()
    if category_input in cfg["categories"]:
        category = category_input
    elif category_input:
        category = categorize(category_input)
    else:
        category = categorize(payload.get("product_name", ""))

    market = payload.get("market") or "United Kingdom"
    market_group = market if market in cfg["countries"] else "Other"

    cold_start_rate = cfg["cold_start_return_rate"]
    has_history = 1 if total_orders > 0 else 0
    historical_return_rate = (total_returns / total_orders) if total_orders > 0 else 0.0
    model_prior_return_rate = historical_return_rate if total_orders > 0 else cold_start_rate

    now = datetime.now()
    feat = {c: 0 for c in feature_cols}
    feat["unit_price"] = price
    feat["quantity"] = quantity
    feat["order_value"] = price * quantity
    feat["month"] = now.month
    feat["day_of_week"] = now.weekday()
    feat["is_weekend"] = 1 if now.weekday() >= 5 else 0
    feat["product_prior_orders_log"] = float(__import__("math").log1p(total_orders))
    feat["product_prior_return_rate"] = model_prior_return_rate
    feat["product_avg_price_prior"] = price
    feat["has_history"] = has_history
    cat_col = f"Category__{category}"
    if cat_col in feat:
        feat[cat_col] = 1
    country_col = f"CountryGroup__{market_group}"
    if country_col in feat:
        feat[country_col] = 1

    X = pd.DataFrame([feat])[feature_cols]
    raw_proba = float(model.predict_proba(X)[0, 1])

    # --- Credibility-weighted blending (empirical Bayes shrinkage) -------
    # The RandomForest alone leans heavily on price/category/market and
    # under-weights a product's OWN track record, so a product with 150
    # real orders and a genuine 3% return rate could still get scored near
    # the category's typical rate (~50%+) - the model has no built-in
    # notion of "how much should I trust this product's own history vs.
    # the general pattern for this price+category+market?"
    #
    # This blends the model's raw output with the product's own observed
    # rate, weighted by how much order history it actually has. A product
    # with few/no orders is scored almost entirely by the model (price/
    # category/market pattern, same as before). A product with a lot of
    # real orders is scored mostly by its OWN real return rate, since that
    # is direct evidence and should dominate a general category pattern.
    # CREDIBILITY_K controls how fast trust shifts to the product's own
    # data; a product needs roughly this many orders before its own
    # history and the model's prior are weighted equally.
    CREDIBILITY_K = 15
    credibility = total_orders / (total_orders + CREDIBILITY_K) if total_orders > 0 else 0.0
    proba = (credibility * historical_return_rate) + ((1 - credibility) * raw_proba)

    risk = risk_level_for(proba)

    # Explainability: rank plausible drivers using the model's global
    # feature importances, compared against this product's own values vs.
    # the dataset-wide benchmarks documented in dataset_info.json.
    importances = cfg["feature_importances"]
    base_rate = cold_start_rate
    key_factors = []

    if total_orders >= CREDIBILITY_K:
        key_factors.append(
            f"This product has {total_orders} real orders, so its own "
            f"{historical_return_rate*100:.1f}% return rate carries more weight than the general "
            f"price/category pattern (~{raw_proba*100:.0f}%)"
        )

    for fname, _imp in importances:
        if len(key_factors) >= 4:
            break
        if fname == "product_prior_return_rate":
            cond = model_prior_return_rate > base_rate
            key_factors.append(
                "This product's historical return rate is above the dataset-wide average"
                if cond else
                "This product's historical return rate is at or below the dataset-wide average"
                if has_history else
                "No return history yet for this product (new listing) - prediction relies on price and category"
            )
        elif fname == "unit_price":
            key_factors.append(
                f"Unit price (£{price:.2f}) is on the higher side for this category"
                if price > 10 else f"Unit price (£{price:.2f}) is relatively low, which historically correlates with fewer returns"
            )
        elif fname == "product_prior_orders_log":
            key_factors.append(
                "High order volume gives the model a reliable history to learn from"
                if total_orders >= 100 else
                "Limited order history for this product" if has_history else
                "No prior orders recorded yet for this product"
            )
        elif fname.startswith("Category__"):
            key_factors.append(f"Category '{category}' historical return pattern")
        elif fname.startswith("CountryGroup__"):
            key_factors.append(f"Market/region '{market}' historical return pattern")

    return {
        "prediction": round(proba, 4),
        "predicted_return_probability": round(proba, 4),
        "model_raw_probability": round(raw_proba, 4),
        "risk_level": risk,
        "historical_return_rate": round(historical_return_rate, 4),
        "category": category,
        "market": market,
        "key_factors": key_factors[:4],
        "inputs_used": {
            "price": price, "quantity": quantity, "total_orders": total_orders,
            "total_returns": total_returns, "category": category, "market": market,
        },
    }
