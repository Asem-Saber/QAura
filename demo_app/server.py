"""QAura Demo App — FastAPI Server.

A simple e-commerce API with intentional vulnerabilities and bugs
designed for QAura to detect, test, and heal.

Run: uvicorn server:app --reload --port 3000
"""

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os

from models import init_db, seed_db, get_db
from auth import register_user, login_user, validate_session, logout_user
from orders import get_products, get_product, place_order, get_user_orders, calculate_order_total

app = FastAPI(title="QAura Demo App", version="1.0.0")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


@app.on_event("startup")
def startup():
    init_db()
    seed_db()


# --- Request Models --- #

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class OrderRequest(BaseModel):
    product_id: int
    quantity: int


# --- Auth Dependency --- #

def get_current_user(request: Request) -> dict:
    """Extract and validate the session token from Authorization header.

    VULNERABILITY: Does not validate token format before database lookup.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header[7:]
    user = validate_session(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user


# --- Page Routes --- #

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


# --- API Routes --- #

@app.post("/api/auth/register")
def api_register(body: RegisterRequest):
    """Register a new user."""
    result = register_user(body.email, body.password, body.name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/auth/login")
def api_login(body: LoginRequest):
    """Login and receive a session token."""
    result = login_user(body.email, body.password)
    if "error" in result:
        raise HTTPException(status_code=401, detail=result["error"])
    return result


@app.delete("/api/auth/logout")
def api_logout(user: dict = Depends(get_current_user), request: Request = None):
    """Logout and invalidate session."""
    token = request.headers.get("Authorization", "")[7:]
    logout_user(token)
    return {"message": "Logged out"}


@app.get("/api/products")
def api_products():
    """List all products."""
    return get_products()


@app.get("/api/products/{product_id}")
def api_product(product_id: int):
    """Get a single product."""
    product = get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.post("/api/orders")
def api_place_order(body: OrderRequest, user: dict = Depends(get_current_user)):
    """Place an order (requires authentication)."""
    result = place_order(user["id"], body.product_id, body.quantity)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/orders")
def api_get_orders(user: dict = Depends(get_current_user)):
    """Get current user's orders."""
    return get_user_orders(user["id"])


@app.get("/api/users/{user_id}/orders")
def api_get_user_orders(user_id: int):
    """Get orders for any user.

    VULNERABILITY: No authorization check — any user can view other users' orders.
    """
    return get_user_orders(user_id)


# --- Health Check --- #

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
