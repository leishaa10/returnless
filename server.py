import http.server
import socketserver
import json
import urllib.parse
import os
import sys
import mimetypes
import secrets
import hmac
from database import (
    init_db, get_products, get_product_by_id, insert_product,
    update_product_status, get_analytics, get_profile, update_profile, get_payments,
    get_profile_by_email, list_demo_accounts, create_profile, DEFAULT_MERCHANT_ID,
    get_admin_overview
)
import payments
from payments import PaymentError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml"))
import predictor as ml

PORT = int(os.environ.get("PORT", 8000))

# ReturnLess platform admin (separate from the merchant companies). Override
# with RETURNLESS_ADMIN_EMAIL / RETURNLESS_ADMIN_PASSWORD. The session token
# is generated fresh at server start and required on every /api/admin/* call.
ADMIN_EMAIL = os.environ.get("RETURNLESS_ADMIN_EMAIL", "admin@returnless.com")
ADMIN_PASSWORD = os.environ.get("RETURNLESS_ADMIN_PASSWORD", "admin123")
ADMIN_TOKEN = "adm_" + secrets.token_urlsafe(24)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Ensure proper mime types
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("application/json", ".json")

class ReturnLessRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PATCH, PUT")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Merchant-Id, X-Admin-Token")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json_response(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        content_len = int(self.headers.get("Content-Length", 0))
        self.raw_body = self.rfile.read(content_len) if content_len else b""
        if not self.raw_body:
            return {}
        try:
            data = json.loads(self.raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def get_merchant_id(self):
        """
        Which logged-in company this request belongs to. The frontend sends
        this as the X-Merchant-Id header (set right after login/register -
        see static/js/app.js) so every company's products/profile/payments
        stay isolated from every other company's. Falls back to the default
        demo company (Apex) if the header is missing or invalid, so direct
        API calls / curl testing still work without a login step.
        """
        raw = self.headers.get("X-Merchant-Id", "")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return DEFAULT_MERCHANT_ID

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # ---------------- Product-level return risk API ----------------
        # Every one of these is scoped to the logged-in company
        # (get_merchant_id()) - a merchant only ever sees its own catalog.
        if path == "/api/admin/overview":
            if not hmac.compare_digest(self.headers.get("X-Admin-Token", ""), ADMIN_TOKEN):
                self.send_json_response({"success": False, "error": "Admin sign-in required"}, status=401)
                return
            self.send_json_response({"success": True, **get_admin_overview()})
            return

        elif path == "/api/products":
            merchant_id = self.get_merchant_id()
            risk = query.get("risk", [None])[0]
            category = query.get("category", [None])[0]
            search = query.get("search", [None])[0]
            products = get_products(merchant_id, risk_filter=risk, category_filter=category, search=search)
            self.send_json_response({"success": True, "products": products})
            return

        elif path.startswith("/api/products/"):
            merchant_id = self.get_merchant_id()
            product_id = path.replace("/api/products/", "").strip()
            product = get_product_by_id(merchant_id, product_id)
            if product:
                self.send_json_response({"success": True, "product": product})
            else:
                self.send_json_response({"success": False, "error": "Product not found"}, status=404)
            return

        elif path == "/api/analytics":
            merchant_id = self.get_merchant_id()
            analytics = get_analytics(merchant_id)
            self.send_json_response({"success": True, "analytics": analytics})
            return

        elif path == "/api/model-info":
            # Dataset + trained-model documentation for the "AI Model &
            # Dataset" page (source, records, features, metrics, confusion
            # matrix - all read straight from ml/model/*.json).
            if ml.is_ready():
                self.send_json_response({"success": True, **ml.get_model_info()})
            else:
                self.send_json_response({"success": False, "error": "Model artifacts not found. Run: python ml/train_model.py"}, status=503)
            return

        elif path == "/api/meta":
            # Category/market options the frontend form uses - sourced
            # from the trained model's feature config, so the form never
            # offers a category the model doesn't actually know.
            if ml.is_ready():
                self.send_json_response({
                    "success": True,
                    "categories": ml.get_categories(),
                    "countries": ml.get_countries(),
                })
            else:
                self.send_json_response({"success": False, "categories": [], "countries": []})
            return

        elif path == "/api/profile":
            merchant_id = self.get_merchant_id()
            profile = get_profile(merchant_id)
            self.send_json_response({"success": True, "profile": profile})
            return

        elif path == "/api/auth/demo-accounts":
            # Powers the "Quick login" list on the login page - one button
            # per real, separately-seeded demo company.
            self.send_json_response({"success": True, "accounts": list_demo_accounts()})
            return

        elif path == "/api/payment/config":
            self.send_json_response({"success": True, **payments.public_config()})
            return

        elif path == "/api/payment/history":
            merchant_id = self.get_merchant_id()
            self.send_json_response({"success": True, "payments": get_payments(merchant_id)})
            return

        # Static File Handling
        if path == "/" or path == "":
            self.serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html")
            return

        rel_path = path.lstrip("/")
        if rel_path.startswith("static/"):
            rel_path = rel_path[7:]

        file_path = os.path.join(STATIC_DIR, rel_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            mime_type, _ = mimetypes.guess_type(file_path)
            self.serve_file(file_path, mime_type or "application/octet-stream")
        else:
            # Single-page application fallback: serve index.html for unknown web paths
            self.serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self.read_json_body()

        # ---------------- ML prediction endpoint ----------------
        # This is the ONE genuine prediction pipeline in the app: it loads
        # the trained scikit-learn model (ml/model/model.joblib) and scores
        # the submitted PRODUCT features. No customer data is accepted.
        if path == "/predict-return" or path == "/api/predict-return":
            try:
                if not ml.is_ready():
                    self.send_json_response({
                        "success": False,
                        "error": "Model not trained yet. Run: python ml/train_model.py"
                    }, status=503)
                    return
                result = ml.predict_product(body)
                self.send_json_response({"success": True, **result})
            except Exception as e:
                self.send_json_response({"success": False, "error": str(e)}, status=400)
            return

        elif path == "/api/products":
            # Analyze + save a product under the logged-in company: runs the
            # real model, then persists the result (see
            # database.insert_product -> ml.predict_product).
            merchant_id = self.get_merchant_id()
            try:
                product = insert_product(merchant_id, body)
                self.send_json_response({"success": True, "product": product}, status=201)
            except Exception as e:
                self.send_json_response({"success": False, "error": str(e)}, status=400)
            return

        elif path.startswith("/api/products/") and path.endswith("/action"):
            merchant_id = self.get_merchant_id()
            product_id = path.replace("/api/products/", "").replace("/action", "").strip()
            status = body.get("status", "Needs Review")
            notes = body.get("notes", "")
            updated = update_product_status(merchant_id, product_id, status, notes)
            if updated:
                self.send_json_response({"success": True, "product": updated})
            else:
                self.send_json_response({"success": False, "error": "Product not found"}, status=404)
            return

        elif path == "/api/auth/login":
            # Looks up a REAL, separately-seeded company by email - each
            # company only ever sees its own products/profile/payments.
            # Demo mode: any password is accepted once the email matches a
            # known company (see database.DEMO_COMPANIES / /register below).
            email = str(body.get("email", "")).strip()
            profile = get_profile_by_email(email) if email else None
            if not profile:
                self.send_json_response({
                    "success": False,
                    "error": f"No merchant account found for '{email}'. Check the email or register a new business."
                }, status=404)
                return
            # The login form's Company dropdown sends company_id; the email
            # must belong to that company.
            company_id = body.get("company_id")
            if company_id not in (None, "") and str(company_id) != str(profile["id"]):
                self.send_json_response({
                    "success": False,
                    "error": f"'{email}' is not an account of the selected company."
                }, status=403)
                return
            self.send_json_response({
                "success": True,
                "token": "tok_demo_session_active",
                "merchant": {
                    "merchant_id": profile["id"],
                    "email": profile.get("business_email"),
                    "business_name": profile.get("business_name"),
                    "plan": profile.get("plan")
                }
            })
            return

        elif path == "/api/auth/admin-login":
            email = str(body.get("email", "")).strip().lower()
            password = str(body.get("password", ""))
            ok = hmac.compare_digest(email, ADMIN_EMAIL.lower()) & hmac.compare_digest(password, ADMIN_PASSWORD)
            if not ok:
                self.send_json_response({"success": False, "error": "Invalid admin credentials."}, status=401)
                return
            self.send_json_response({
                "success": True,
                "token": ADMIN_TOKEN,
                "admin": {"role": "admin", "email": ADMIN_EMAIL, "business_name": "ReturnLess Admin", "admin_token": ADMIN_TOKEN}
            })
            return

        elif path == "/api/auth/register":
            # Registers a BRAND NEW company as its own isolated merchant -
            # separate login, separate (initially empty) product catalog.
            name = body.get("business_name", "New Retail Brand")
            email = body.get("business_email", "").strip()
            cat = body.get("business_category", "E-Commerce Retail")
            if not email:
                self.send_json_response({"success": False, "error": "Business email is required"}, status=400)
                return
            profile, created = create_profile(name, email, cat, plan="Starter SME")
            if not created:
                self.send_json_response({
                    "success": False,
                    "error": f"An account already exists for '{email}'. Try signing in instead."
                }, status=409)
                return
            self.send_json_response({
                "success": True,
                "token": "tok_registered_session_active",
                "merchant": {
                    "merchant_id": profile["id"],
                    "email": profile.get("business_email"),
                    "business_name": profile.get("business_name"),
                    "plan": profile.get("plan")
                }
            })
            return

        elif path == "/api/profile":
            merchant_id = self.get_merchant_id()
            updated_prof = update_profile(merchant_id, body)
            self.send_json_response({"success": True, "profile": updated_prof})
            return

        elif path.startswith("/api/payment/"):
            self.handle_payment_post(path, body)
            return

        elif path == "/api/reset":
            init_db(force_reseed=True)
            self.send_json_response({"success": True, "message": "Demo data successfully re-seeded from the trained model's real product catalog."})
            return

        self.send_json_response({"success": False, "error": "Endpoint not found"}, status=404)

    def handle_payment_post(self, path, body):
        """Razorpay payment endpoints (see payments.py)."""
        try:
            if path == "/api/payment/create-order":
                merchant_id = self.get_merchant_id()
                order = payments.create_order(merchant_id, body.get("plan"), body.get("cycle", "monthly"))
                self.send_json_response({"success": True, **order}, status=201)

            elif path == "/api/payment/mock-authorize":
                result = payments.mock_authorize(body.get("razorpay_order_id"), body.get("outcome", "success"))
                self.send_json_response({"success": True, **result})

            elif path == "/api/payment/verify":
                payment, profile = payments.verify_payment(
                    body.get("razorpay_order_id"),
                    body.get("razorpay_payment_id"),
                    body.get("razorpay_signature"),
                )
                self.send_json_response({"success": True, "payment": payment, "profile": profile})

            elif path == "/api/payment/failed":
                payment = payments.report_failure(body.get("razorpay_order_id"), body.get("reason", ""))
                self.send_json_response({"success": True, "payment": payment})

            elif path == "/api/payment/webhook":
                signature = self.headers.get("X-Razorpay-Signature", "")
                result = payments.handle_webhook(getattr(self, "raw_body", b""), signature)
                self.send_json_response({"success": True, **result})

            else:
                self.send_json_response({"success": False, "error": "Endpoint not found"}, status=404)
        except PaymentError as e:
            self.send_json_response({"success": False, "error": e.message}, status=e.status)

    def serve_file(self, filepath, content_type):
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

def start_server():
    init_db()
    handler = ReturnLessRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"==================================================")
        print(f"  RETURNLESS B2B PLATFORM - SERVER ONLINE")
        print(f"  URL: http://localhost:{PORT}")
        print(f"  Payments: {payments.MODE.upper()} mode ({payments.CURRENCY})")
        print(f"  AI model ready: {ml.is_ready()}")
        print(f"==================================================")
        httpd.serve_forever()

if __name__ == "__main__":
    start_server()
