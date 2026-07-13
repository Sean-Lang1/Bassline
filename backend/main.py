from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from database import get_connection
from etl import build_artist_relations, build_artist_profile
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

favicon_path = "favicon.ico"


@app.get("/")
def root():
    return {"message": "Bassline API is groovinnnn'."}


@app.get("/artists/{name}")
def get_artist(name: str):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "SELECT * FROM artists WHERE name = %s",
            (name,)
        )
        artist = cur.fetchone()
    finally:
        conn.close()

    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    return dict(artist)


@app.get("/profile/{name}")
def get_profile(name: str):
    data = build_artist_profile(name)

    if not data:
        raise HTTPException(status_code=404, detail="Artist not found")

    return data


@app.get("/relations/{name}")
def get_relations(name: str):
    data = build_artist_relations(name)

    if not data:
        raise HTTPException(status_code=404, detail="Artist not found")

    return data


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    if not os.path.exists(favicon_path):
        raise HTTPException(status_code=404)
    return FileResponse(favicon_path, media_type="image/x-icon")