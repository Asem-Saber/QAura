# test_orders.py
"""Unit tests for demo_app/orders.py — Order Calculation Logic."""

import pytest
from unittest.mock import patch, MagicMock
from demo_app.orders import calculate_order_total, place_order

# --- Fixtures ---
@pytest.fixture
def mock_db_conn():
    """Mock SQLite database connection."""
    with patch("demo_app.orders.get_db") as mock_get_db:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn
        yield mock_conn, mock_cursor

@pytest.fixture
def mock_product():
    """Mock product data."""
    return {"id": 1, "name": "Test Product", "price": 10.0, "stock": 100}

# --- Tests for calculate_order_total ---
@pytest.mark.parametrize(
    "price, quantity, discount_pct, expected",
    [
        (10.0, 2, 0, 20.0),      # No discount
        (10.0, 2, 10, 22.0),     # 10% discount (BUG: should be 18.0)
        (10.0, 1, 100, 20.0),    # 100% discount (BUG: should be 0.0)
        (10.0, 0, 0, 0.0),       # Zero quantity
        (0.0, 5, 0, 0.0),        # Zero price
        (10.0, -1, 0, -10.0),    # Negative quantity (BUG: should raise ValueError)
        (10.0, 2, -10, 18.0),    # Negative discount (BUG: should raise ValueError)
        (10.0, 2, 110, 22.0),    # Discount > 100% (BUG: should raise ValueError)
    ],
)
def test_calculate_order_total(price, quantity, discount_pct, expected):
    """Test order total calculation with various inputs."""
    result = calculate_order_total(price, quantity, discount_pct)
    assert result == expected, f"Expected {expected}, got {result}"

# --- Tests for place_order ---
def test_place_order_success(mock_db_conn, mock_product):
    """Test successful order placement."""
    mock_conn, mock_cursor = mock_db_conn
    mock_cursor.lastrowid = 1

    with patch("demo_app.orders.get_product", return_value=mock_product):
        result = place_order(1, 1, 2)

    assert result["order_id"] == 1
    assert result["product"] == "Test Product"
    assert result["quantity"] == 2
    assert result["total_price"] == 20.0  # 10.0 * 2 * (1 + 0/100)
    assert result["status"] == "pending"

    # Verify DB interactions
    mock_cursor.execute.assert_called_once_with(
        "INSERT INTO orders (user_id, product_id, quantity, total_price) VALUES (?, ?, ?, ?)",
        (1, 1, 2, 20.0),
    )
    mock_conn.commit.assert_called_once()

def test_place_order_product_not_found(mock_db_conn):
    """Test order placement with invalid product."""
    with patch("demo_app.orders.get_product", return_value=None):
        result = place_order(1, 999, 1)

    assert result == {"error": "Product not found"}
    mock_db_conn[0].cursor.return_value.execute.assert_not_called()

def test_place_order_negative_quantity(mock_db_conn, mock_product):
    """Test order placement with negative quantity (BUG: should fail)."""
    with patch("demo_app.orders.get_product", return_value=mock_product):
        result = place_order(1, 1, -1)

    assert result["quantity"] == -1  # BUG: Negative quantity allowed
    assert result["total_price"] == -10.0  # BUG: Negative total

def test_place_order_no_stock_check(mock_db_conn, mock_product):
    """Test order placement does not check stock (BUG: should fail)."""
    mock_product["stock"] = 0  # Out of stock
    with patch("demo_app.orders.get_product", return_value=mock_product):
        result = place_order(1, 1, 2)

    assert result["quantity"] == 2  # BUG: No stock check
    assert result["total_price"] == 20.0  # BUG: Order allowed despite no stock