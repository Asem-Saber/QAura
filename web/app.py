import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="QAura Dashboard")

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


@app.get("/")
async def index():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {
        "active_page": "dashboard",
    })


@app.get("/agents")
async def agents_page(request: Request):
    return templates.TemplateResponse(request, "agents.html", {
        "active_page": "agents",
    })


@app.get("/reports")
async def reports_page(request: Request):
    return templates.TemplateResponse(request, "reports.html", {
        "active_page": "reports",
    })
