import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI

app = FastAPI(title="Lyka Realty AI Agent + CRM", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="frontend/dist"), name="static")

# Serve React app on root path
@app.get("/{full_path:path}")
async def serve_react(full_path: str):
    file_path = os.path.join("frontend/dist", full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join("frontend/dist", "index.html"))