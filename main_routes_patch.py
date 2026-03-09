# ── PATCH: replace the two frontend routes in main.py ────────────────────────
# Find these two functions and replace them with the block below.
#
# FIND:
#   @app.get("/")
#   async def serve_frontend():
#       ...
#
#   @app.get("/frontend/ui_elections.html")
#   async def serve_analytics():
#       ...
#
# REPLACE WITH:

@app.get("/")
async def serve_frontend():
    """Main entry point — serves the unified analytics dashboard."""
    token = os.getenv("MAPBOX_TOKEN", "")
    html  = (BASE_DIR / "frontend" / "ui_elections.html").read_text()
    html  = html.replace("</head>", f'\n  <script>window.MAPBOX_TOKEN = "{token}";</script>\n</head>')
    return HTMLResponse(content=html)

@app.get("/frontend/ui_elections.html")
async def serve_analytics():
    """Backward-compatible redirect — same as /"""
    token = os.getenv("MAPBOX_TOKEN", "")
    html  = (BASE_DIR / "frontend" / "ui_elections.html").read_text()
    html  = html.replace("</head>", f'\n  <script>window.MAPBOX_TOKEN = "{token}";</script>\n</head>')
    return HTMLResponse(content=html)

@app.get("/explorer")
async def serve_explorer():
    """Legacy Georgia Explorer map — kept for reference."""
    token = os.getenv("MAPBOX_TOKEN", "")
    html  = (BASE_DIR / "index.html").read_text()
    html  = html.replace("</head>", f'\n  <script>window.MAPBOX_TOKEN = "{token}";</script>\n</head>')
    return HTMLResponse(content=html)