import sqlite3
import json
import os
import sys
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "returnless.db")
SEED_PRODUCTS_PATH = os.path.join(os.path.dirname(__file__), "ml", "model", "seed_products.json")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "ml"))
import predictor as ml  # noqa: E402  (loads the trained model lazily)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------
# Multi-tenant demo companies. Each is a fully separate merchant:
# own login, own business_profile row, own products, own payments.
# The real seed catalog (16 real, model-scored products from the
# training dataset - see ml/model/seed_products.json) is split
# across these 4 by category, so every company's starting history
# is still 100% real data, just partitioned by theme.
# ---------------------------------------------------------------
DEMO_COMPANIES = [
    {
        "id": 1,
        "business_name": "Apex Retailers Global",
        "business_email": "operations@apexretail.com",
        "business_category": "Multi-Category Gift & Home Retail",
        "plan": "Growth Tier",
        "currency": "$",
    },
    {
        "id": 2,
        "business_name": "Hearth & Home Decor Co.",
        "business_email": "hello@hearthhomedecor.co.uk",
        "business_category": "Home Decor & Bathware Specialist",
        "plan": "Starter SME",
        "currency": "$",
    },
    {
        "id": 3,
        "business_name": "Sterling & Sage Jewellery",
        "business_email": "contact@sterlingsagejewellery.com",
        "business_category": "Jewellery & Lighting Accessories",
        "plan": "Enterprise Tier",
        "currency": "$",
    },
    {
        "id": 4,
        "business_name": "TableCraft Kitchen Supplies",
        "business_email": "support@tablecraftsupplies.com",
        "business_category": "Kitchen, Dining & Stationery Retail",
        "plan": "Growth Tier",
        "currency": "$",
    },
]

# Every real seed-product category is assigned to exactly one demo
# company, so nothing is duplicated and nothing is dropped.
CATEGORY_TO_MERCHANT = {
    "General Gifts & Other": 1,
    "Christmas & Seasonal": 1,
    "Garden & Outdoor": 1,
    "Home Decor": 2,
    "Bathroom": 2,
    "Jewellery & Accessories": 3,
    "Lighting & Candles": 3,
    "Kitchen & Dining": 4,
    "Stationery & Cards": 4,
}
DEFAULT_MERCHANT_ID = 1


def init_db(force_reseed=False):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS business_profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_name TEXT,
        business_email TEXT UNIQUE,
        business_category TEXT,
        plan TEXT,
        currency TEXT,
        shopify_connected INTEGER DEFAULT 1,
        woocommerce_connected INTEGER DEFAULT 0,
        email_alerts INTEGER DEFAULT 1,
        high_risk_threshold INTEGER DEFAULT 70
    )
    """)

    # PRODUCT-LEVEL return risk catalog. This is a B2B platform: every row is
    # a PRODUCT a given merchant (company) stocks, never an individual
    # customer. merchant_id ties each product to exactly one logged-in
    # company, so companies never see each other's catalogs. Every
    # prediction/risk value here is written by the trained ML model
    # (see ml/train_model.py + ml/predictor.py) - never hand-typed.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant_id INTEGER NOT NULL DEFAULT 1,
        product_id TEXT,
        product_name TEXT,
        category TEXT,
        price REAL,
        market TEXT,
        total_orders INTEGER,
        total_returns INTEGER,
        historical_return_rate REAL,
        predicted_return_probability REAL,
        risk_level TEXT,
        key_factors_json TEXT,
        status TEXT DEFAULT 'Needs Review',
        decision_notes TEXT DEFAULT '',
        created_at TEXT,
        last_analyzed_at TEXT,
        UNIQUE(merchant_id, product_id)
    )
    """)

    # Subscription payments (Razorpay orders), now scoped per merchant too -
    # each company's billing/plan activation is independent of the others.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant_id INTEGER NOT NULL DEFAULT 1,
        rz_order_id TEXT UNIQUE,
        rz_payment_id TEXT,
        plan TEXT,
        cycle TEXT,
        amount INTEGER,
        currency TEXT,
        mode TEXT,
        method TEXT,
        status TEXT DEFAULT 'created',
        failure_reason TEXT DEFAULT '',
        created_at TEXT,
        paid_at TEXT
    )
    """)
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM business_profile")
    if cursor.fetchone()[0] == 0:
        for c in DEMO_COMPANIES:
            cursor.execute("""
            INSERT INTO business_profile (id, business_name, business_email, business_category, plan, currency)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (c["id"], c["business_name"], c["business_email"], c["business_category"], c["plan"], c["currency"]))
        conn.commit()

    cursor.execute("SELECT COUNT(*) FROM products")
    product_count = cursor.fetchone()[0]
    if product_count == 0 or force_reseed:
        if force_reseed:
            cursor.execute("DELETE FROM products")
            cursor.execute("DELETE FROM payments")
            for c in DEMO_COMPANIES:
                cursor.execute("UPDATE business_profile SET plan = ? WHERE id = ?", (c["plan"], c["id"]))
            conn.commit()
        seed_products(conn)

    conn.close()


def seed_products(conn):
    """
    Seeds each demo company's starting catalog from
    ml/model/seed_products.json - the real products from the training
    dataset, each already scored by the trained model (see
    ml/train_model.py::build_seed_catalog). Every number here
    (total_orders, total_returns, historical_return_rate,
    predicted_return_probability, risk_level, key_factors) came out of the
    real data + the real model; nothing below is hand-typed. Products are
    split across companies by category (see CATEGORY_TO_MERCHANT) so each
    company's demo history is thematically its own.
    """
    cursor = conn.cursor()
    now = datetime.now()

    try:
        with open(SEED_PRODUCTS_PATH) as f:
            seed_items = json.load(f)
    except FileNotFoundError:
        seed_items = []

    status_cycle = ["Needs Review", "Needs Review", "Listing Improved", "Monitoring", "Needs Review"]

    for i, item in enumerate(seed_items):
        merchant_id = CATEGORY_TO_MERCHANT.get(item["category"], DEFAULT_MERCHANT_ID)
        created_at = now.strftime("%Y-%m-%d %H:%M:%S")
        status = status_cycle[i % len(status_cycle)] if item["risk_level"] != "LOW" else "Monitoring"
        cursor.execute("""
        INSERT OR IGNORE INTO products (
            merchant_id, product_id, product_name, category, price, market, total_orders, total_returns,
            historical_return_rate, predicted_return_probability, risk_level, key_factors_json,
            status, decision_notes, created_at, last_analyzed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            merchant_id, item["product_id"], item["product_name"], item["category"], item["price"],
            "United Kingdom", item["total_orders"], item["total_returns"],
            item["historical_return_rate"], item["predicted_return_probability"], item["risk_level"],
            json.dumps(item["key_factors"]), status, "", created_at, created_at
        ))
    conn.commit()


def get_products(merchant_id, risk_filter=None, category_filter=None, search=None):
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM products WHERE merchant_id = ?"
    params = [merchant_id]

    if risk_filter and risk_filter.upper() != "ALL":
        query += " AND risk_level = ?"
        params.append(risk_filter.upper())

    if category_filter and category_filter.upper() != "ALL":
        query += " AND category = ?"
        params.append(category_filter)

    if search:
        search_term = f"%{search.strip()}%"
        query += " AND (product_id LIKE ? OR product_name LIKE ? OR category LIKE ?)"
        params.extend([search_term, search_term, search_term])

    query += " ORDER BY predicted_return_probability DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        r["key_factors"] = json.loads(r["key_factors_json"]) if r.get("key_factors_json") else []
    return rows


def get_product_by_id(merchant_id, product_id):
    conn = get_connection()
    cursor = conn.cursor()
    clean_id = str(product_id).strip()
    cursor.execute(
        "SELECT * FROM products WHERE merchant_id = ? AND (product_id = ? OR id = ?)",
        (merchant_id, clean_id, clean_id.lstrip("#") or "0")
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["key_factors"] = json.loads(d["key_factors_json"]) if d.get("key_factors_json") else []
    return d


def insert_product(merchant_id, product_data):
    """
    Runs the real trained ML model on the submitted product info and saves
    the result under the logged-in company (merchant_id). This is the ONLY
    place a new product's prediction is computed - the app never lets a
    hand-typed number reach the database.
    """
    prediction = ml.predict_product(product_data)

    conn = get_connection()
    cursor = conn.cursor()

    product_id = str(product_data.get("product_id") or "").strip()
    if not product_id:
        cursor.execute("SELECT COUNT(*) FROM products WHERE merchant_id = ?", (merchant_id,))
        n = cursor.fetchone()[0]
        product_id = f"P-{1000 + n + 1}"

    total_orders = max(0, int(product_data.get("total_orders", 0) or 0))
    total_returns = max(0, int(product_data.get("total_returns", 0) or 0))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO products (
        merchant_id, product_id, product_name, category, price, market, total_orders, total_returns,
        historical_return_rate, predicted_return_probability, risk_level, key_factors_json,
        status, decision_notes, created_at, last_analyzed_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(merchant_id, product_id) DO UPDATE SET
        product_name=excluded.product_name, category=excluded.category, price=excluded.price,
        market=excluded.market, total_orders=excluded.total_orders, total_returns=excluded.total_returns,
        historical_return_rate=excluded.historical_return_rate,
        predicted_return_probability=excluded.predicted_return_probability,
        risk_level=excluded.risk_level, key_factors_json=excluded.key_factors_json,
        last_analyzed_at=excluded.last_analyzed_at
    """, (
        merchant_id, product_id, product_data.get("product_name", "Untitled Product"), prediction["category"],
        float(product_data.get("price", 0) or 0), prediction["market"], total_orders, total_returns,
        prediction["historical_return_rate"], prediction["predicted_return_probability"], prediction["risk_level"],
        json.dumps(prediction["key_factors"]), "Needs Review", "", now_str, now_str
    ))
    conn.commit()
    conn.close()
    return get_product_by_id(merchant_id, product_id)


def update_product_status(merchant_id, product_id, status, notes=""):
    conn = get_connection()
    cursor = conn.cursor()
    clean_id = str(product_id).strip()
    cursor.execute("""
    UPDATE products
    SET status = ?, decision_notes = ?
    WHERE merchant_id = ? AND (product_id = ? OR id = ?)
    """, (status, notes, merchant_id, clean_id, clean_id.lstrip("#") or "0"))
    conn.commit()
    conn.close()
    return get_product_by_id(merchant_id, clean_id)


def get_analytics(merchant_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*), AVG(predicted_return_probability), AVG(historical_return_rate) FROM products WHERE merchant_id = ?",
        (merchant_id,)
    )
    total_count, avg_pred, avg_hist = cursor.fetchone()
    total_count = total_count or 0
    avg_pred = round((avg_pred or 0) * 100, 1)
    avg_hist = round((avg_hist or 0) * 100, 1)

    cursor.execute("SELECT COUNT(*) FROM products WHERE merchant_id = ? AND risk_level = 'HIGH'", (merchant_id,))
    high_count = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(*) FROM products WHERE merchant_id = ? AND risk_level = 'MEDIUM'", (merchant_id,))
    med_count = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(*) FROM products WHERE merchant_id = ? AND risk_level = 'LOW'", (merchant_id,))
    low_count = cursor.fetchone()[0] or 0

    # Estimated return-related cost exposure: expected units returned
    # (total_orders * AI predicted probability) times a typical per-return
    # cost (28% of item price lost to restocking/handling + a small flat
    # reverse-logistics fee). This is a business estimate for the dashboard,
    # not a model output.
    cursor.execute("""
    SELECT SUM(total_orders * predicted_return_probability * (price * 0.28 + 1.50))
    FROM products WHERE merchant_id = ?
    """, (merchant_id,))
    cost_exposure = cursor.fetchone()[0] or 0.0

    cursor.execute("""
    SELECT category, COUNT(*) as count,
           AVG(predicted_return_probability) as avg_predicted,
           AVG(historical_return_rate) as avg_historical,
           SUM(CASE WHEN risk_level = 'HIGH' THEN 1 ELSE 0 END) as high_risk_count
    FROM products
    WHERE merchant_id = ?
    GROUP BY category
    ORDER BY avg_predicted DESC
    """, (merchant_id,))
    categories = [dict(r) for r in cursor.fetchall()]
    for c in categories:
        c["avg_predicted"] = round((c["avg_predicted"] or 0) * 100, 1)
        c["avg_historical"] = round((c["avg_historical"] or 0) * 100, 1)

    cursor.execute("""
    SELECT product_id, product_name, category, predicted_return_probability, risk_level
    FROM products WHERE merchant_id = ? ORDER BY predicted_return_probability DESC LIMIT 8
    """, (merchant_id,))
    top_risk_products = [dict(r) for r in cursor.fetchall()]
    for p in top_risk_products:
        p["predicted_return_probability"] = round(p["predicted_return_probability"] * 100, 1)

    distribution = {"High Risk": high_count, "Medium Risk": med_count, "Low Risk": low_count}

    conn.close()

    return {
        "total_products": total_count,
        "avg_predicted_probability": avg_pred,
        "avg_historical_rate": avg_hist,
        "high_risk_count": high_count,
        "medium_risk_count": med_count,
        "low_risk_count": low_count,
        "estimated_cost_exposure": round(cost_exposure, 2),
        "risk_distribution": distribution,
        "category_breakdown": categories,
        "top_risk_products": top_risk_products,
    }


def get_admin_overview():
    """
    Combined, cross-company analysis for the ReturnLess Admin Dashboard.
    Everything is computed live from the same products/business_profile
    tables the company dashboards use (each company's block is literally
    get_analytics(company_id)); overall metrics are aggregated in SQL over
    all products, so they are true catalog-wide figures, not averages of
    averages.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, business_name, business_category, plan FROM business_profile ORDER BY id")
    profiles = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT COUNT(*), AVG(predicted_return_probability), AVG(historical_return_rate),
           SUM(total_orders * predicted_return_probability * (price * 0.28 + 1.50))
    FROM products
    """)
    total, avg_pred, avg_hist, exposure = cursor.fetchone()
    cursor.execute("SELECT risk_level, COUNT(*) FROM products GROUP BY risk_level")
    by_risk = dict(cursor.fetchall())
    conn.close()

    companies = []
    for p in profiles:
        p["analytics"] = get_analytics(p["id"])
        companies.append(p)

    return {
        "overall": {
            "total_companies": len(companies),
            "total_products": total or 0,
            "avg_predicted_probability": round((avg_pred or 0) * 100, 1),
            "avg_historical_rate": round((avg_hist or 0) * 100, 1),
            "high_risk_count": by_risk.get("HIGH", 0),
            "medium_risk_count": by_risk.get("MEDIUM", 0),
            "low_risk_count": by_risk.get("LOW", 0),
            "estimated_cost_exposure": round(exposure or 0.0, 2),
            "risk_distribution": {
                "High Risk": by_risk.get("HIGH", 0),
                "Medium Risk": by_risk.get("MEDIUM", 0),
                "Low Risk": by_risk.get("LOW", 0),
            },
        },
        "companies": companies,
    }


def get_profile(merchant_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM business_profile WHERE id = ?", (merchant_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def get_profile_by_email(email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM business_profile WHERE LOWER(business_email) = LOWER(?)", (str(email).strip(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def list_demo_accounts():
    """Companies the login page can offer as one-click demo logins."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, business_name, business_email, business_category, plan FROM business_profile ORDER BY id")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def create_profile(business_name, business_email, business_category, plan="Starter SME", currency="$"):
    """Registers a brand-new company as its own isolated merchant (own empty
    product catalog, own login) - used by the 'Register your business' flow."""
    existing = get_profile_by_email(business_email)
    if existing:
        return existing, False

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO business_profile (business_name, business_email, business_category, plan, currency,
        shopify_connected, woocommerce_connected, email_alerts, high_risk_threshold)
    VALUES (?, ?, ?, ?, ?, 1, 0, 1, 70)
    """, (business_name, business_email, business_category, plan, currency))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return get_profile(new_id), True


def update_profile(merchant_id, data):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE business_profile
    SET business_name = ?, business_email = ?, business_category = ?, plan = ?,
        shopify_connected = ?, woocommerce_connected = ?, email_alerts = ?, high_risk_threshold = ?
    WHERE id = ?
    """, (
        data.get("business_name", "Untitled Company"),
        data.get("business_email", ""),
        data.get("business_category", ""),
        data.get("plan", "Starter SME"),
        int(data.get("shopify_connected", 1)),
        int(data.get("woocommerce_connected", 0)),
        int(data.get("email_alerts", 1)),
        int(data.get("high_risk_threshold", 70)),
        merchant_id
    ))
    conn.commit()
    conn.close()
    return get_profile(merchant_id)

# ---------------------------------------------------------------
# Payments (Razorpay) - now scoped per merchant.
# ---------------------------------------------------------------
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def create_payment(merchant_id, rz_order_id, plan, cycle, amount, currency, mode):
    conn = get_connection()
    conn.execute(
        """INSERT INTO payments (merchant_id, rz_order_id, plan, cycle, amount, currency, mode, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?)""",
        (merchant_id, rz_order_id, plan, cycle, amount, currency, mode, _now())
    )
    conn.commit()
    conn.close()
    return get_payment_by_order(rz_order_id)

def get_payment_by_order(rz_order_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM payments WHERE rz_order_id = ?", (rz_order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def mark_payment_paid(rz_order_id, rz_payment_id, method=None):
    """Idempotent: a payment that is already paid is left untouched."""
    conn = get_connection()
    conn.execute(
        """UPDATE payments
           SET status = 'paid', rz_payment_id = ?, method = COALESCE(?, method),
               failure_reason = '', paid_at = ?
           WHERE rz_order_id = ? AND status != 'paid'""",
        (rz_payment_id, method, _now(), rz_order_id)
    )
    conn.commit()
    conn.close()
    return get_payment_by_order(rz_order_id)

def mark_payment_failed(rz_order_id, reason=""):
    """A paid payment can never be turned back into a failed one."""
    conn = get_connection()
    conn.execute(
        "UPDATE payments SET status = 'failed', failure_reason = ? WHERE rz_order_id = ? AND status = 'created'",
        (reason or "Payment failed", rz_order_id)
    )
    conn.commit()
    conn.close()
    return get_payment_by_order(rz_order_id)

def get_payments(merchant_id, limit=20):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM payments WHERE merchant_id = ? ORDER BY id DESC LIMIT ?",
        (merchant_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_plan(merchant_id, plan):
    """Change only the plan (update_profile() would reset every other setting)."""
    conn = get_connection()
    conn.execute("UPDATE business_profile SET plan = ? WHERE id = ?", (plan, merchant_id))
    conn.commit()
    conn.close()
    return get_profile(merchant_id)


if __name__ == "__main__":
    init_db(force_reseed=True)
    print("Database initialized and seeded successfully.")
    for c in DEMO_COMPANIES:
        print(f"--- {c['business_name']} ({c['business_email']}) ---")
        print(get_analytics(c["id"]))
