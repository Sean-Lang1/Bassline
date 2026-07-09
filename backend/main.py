from fastapi import FastAPI
from fastapi.responses import FileResponse
from database import get_connection

app = FastAPI()

favicon_path = "favicon.ico"


@app.get("/")
def root():
    return {"message": "Bassline API is groovinnnn'."}


@app.get("/artists/{name}")
def get_artist(name: str):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM artists WHERE name = ?",
        (name,)
    )

    artist = cur.fetchone()

    conn.close()

    if not artist:
        return {"error": "Artist not found"}

    return dict(artist)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(favicon_path, media_type="image/x-icon")