# QAura Demo Store — Requirements for Testing

## Application Overview
A simple e-commerce web application (FastAPI + SQLite) with:
- User registration and login (email/password)
- Product catalog browsing
- Order placement (authenticated users)
- User dashboard showing order history

## Source Files Under Test
- demo_app/server.py      — FastAPI routes and middleware
- demo_app/auth.py         — Authentication: register, login, session management
- demo_app/orders.py       — Product listing, order calculation, order placement
- demo_app/models.py       — SQLite database schema and seed data
- demo_app/templates/      — HTML frontend (login, dashboard, product listing)

## Functional Requirements
1. Users can register with email, password, and name
2. Users can log in and receive a session token
3. Authenticated users can browse products
4. Authenticated users can place orders
5. Users can view their own order history on the dashboard
6. Users can log out, invalidating their session

## Known Risk Areas (for QAura to discover)
- Authentication module may have SQL injection vectors
- Password storage practices
- Session expiry validation
- Order calculation logic (discounts)
- Stock management during ordering
- Authorization on user-specific endpoints
- Input validation on all forms (XSS, injection)

## API Endpoints
- POST /api/auth/register  — Register new user
- POST /api/auth/login     — Login, receive token
- DELETE /api/auth/logout   — Logout, invalidate session
- GET  /api/products        — List all products
- GET  /api/products/{id}   — Get single product
- POST /api/orders          — Place an order (auth required)
- GET  /api/orders           — Get current user's orders (auth required)
- GET  /api/users/{id}/orders — Get orders by user ID (NO AUTH — vulnerability)

## Frontend Pages
- / (Home)              — Product listing with order buttons
- /login                — Login and registration forms
- /dashboard            — User dashboard with order history