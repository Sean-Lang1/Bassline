from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from database import get_connection
from etl import build_artist_relations
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
            "SELECT * FROM artists WHERE name ILIKE %s",
            (name,)
        )
        artist = cur.fetchone()
    finally:
        conn.close()

    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")

    return dict(artist)


@app.get("/relations/{name}")
def get_relations(name: str):

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute(
            "SELECT * FROM artists WHERE name ILIKE %s",
            (name,)
        )

        artist = cur.fetchone()

        if not artist:

            data = build_artist_relations(name)

            if not data:
                raise HTTPException(
                    status_code=404,
                    detail="Artist not found"
                )

            cur.execute(
                "SELECT * FROM artists WHERE spotify_id = %s",
                (data["artist"]["id"],)
            )

            artist = cur.fetchone()

        cur.execute(
            """
            SELECT
                a.*,
                l.relationship AS rel_type
            FROM artist_links l
            JOIN artists a
                ON a.spotify_id = l.target_id
            WHERE l.source_id = %s
            ORDER BY
            CASE l.relationship
                WHEN 'member of band' THEN 1
                WHEN 'discovered' THEN 2
                WHEN 'discovered by' THEN 2
                WHEN 'sibling' THEN 3
                WHEN 'married' THEN 3
                WHEN 'collaboration' THEN 4
                ELSE 5
            END,
            a.listeners DESC
            """,
            (artist["spotify_id"],)
        )

        related = cur.fetchall()

    finally:

        conn.close()

    return {
        "artist": dict(artist),
        "related": [dict(r) for r in related]
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    if not os.path.exists(favicon_path):
        raise HTTPException(status_code=404)
    return FileResponse(favicon_path, media_type="image/x-icon")