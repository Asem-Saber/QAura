"""QAura Demo App — Database Models.

Simple SQLite-backed user and session models.
Contains intentional issues for QAura to detect.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "demo.db")


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            total_price REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
    """)
    conn.commit()
    conn.close()


def seed_db():
    """Seed the database with sample data."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    # BUG: passwords stored in plain text (no hashing)
    users = [
        ("admin@demo.com", "admin123", "Admin User", "admin"),
        ("alice@demo.com", "password", "Alice Smith", "user"),
        ("bob@demo.com", "letmein", "Bob Jones", "user"),
    ]
    cursor.executemany(
        "INSERT INTO users (email, password, name, role) VALUES (?, ?, ?, ?)",
        users,
    )

    products = [
        ("Wireless Mouse", 29.99, 50, "Ergonomic wireless mouse"),
        ("Mechanical Keyboard", 79.99, 30, "RGB mechanical keyboard"),
        ("USB-C Hub", 49.99, 100, "7-port USB-C hub"),
        ("Monitor Stand", 39.99, 25, "Adjustable monitor stand"),
        ("Webcam HD", 59.99, 0, "1080p HD webcam"),  # Out of stock
    ]
    cursor.executemany(
        "INSERT INTO products (name, price, stock, description) VALUES (?, ?, ?, ?)",
        products,
    )

    conn.commit()
    conn.close()
