"""QAura Demo App — Order Processing.

Handles product listing, ordering, and price calculation.
Contains intentional logic bugs for QAura to detect.
"""

from models import get_db


def get_products() -> list[dict]:
    """Get all products."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products")
    products = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return products


def get_product(product_id: int) -> dict | None:
    """Get a single product by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    conn.close()
    return dict(product) if product else None


def calculate_order_total(price: float, quantity: int, discount_pct: float = 0) -> float:
    """Calculate the total price for an order.

    BUG: Discount is added instead of subtracted.
    BUG: No validation that discount_pct is between 0-100.
    BUG: Negative quantities are allowed.
    """
    # BUG: should be (1 - discount_pct/100) but uses (1 + discount_pct/100)
    total = price * quantity * (1 + discount_pct / 100)
    return round(total, 2)


def place_order(user_id: int, product_id: int, quantity: int) -> dict:
    """Place an order for a product.

    BUG: Does not check stock availability.
    BUG: Does not decrement stock after order.
    """
    product = get_product(product_id)
    if product is None:
        return {"error": "Product not found"}

    # BUG: Missing stock check — can order out-of-stock items
    # Should be: if product["stock"] < quantity: return error

    total = calculate_order_total(product["price"], quantity)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO orders (user_id, product_id, quantity, total_price) "
        "VALUES (?, ?, ?, ?)",
        (user_id, product_id, quantity, total),
    )

    # BUG: Stock is never decremented
    # Should be: cursor.execute("UPDATE products SET stock = stock - ? WHERE id = ?", ...)

    conn.commit()
    order_id = cursor.lastrowid
    conn.close()

    return {
        "order_id": order_id,
        "product": product["name"],
        "quantity": quantity,
        "total_price": total,
        "status": "pending",
    }


def get_user_orders(user_id: int) -> list[dict]:
    """Get all orders for a user.

    BUG: No authorization check — any user_id can be queried.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT o.*, p.name as product_name FROM orders o "
        "JOIN products p ON o.product_id = p.id "
        "WHERE o.user_id = ?",
        (user_id,),
    )
    orders = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return orders
