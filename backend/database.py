import os
import psycopg2
import psycopg2.extras

from dotenv import load_dotenv
load_dotenv(".env.local")

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn

def create_tables():
    conn = get_connection()
    cur = conn.cursor()

    # =====================
    # ARTISTS
    # =====================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS artists(
            id SERIAL PRIMARY KEY,
            spotify_id TEXT UNIQUE,
            name TEXT NOT NULL,
            hometown TEXT,
            listeners INTEGER,
            summary TEXT,
            image_url TEXT,
            latitude REAL,
            longitude REAL
        )
    """)

    # =====================
    # ARTIST LINKS
    # =====================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS artist_links(
            id SERIAL PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES artists(spotify_id),
            FOREIGN KEY (target_id) REFERENCES artists(spotify_id),
            UNIQUE (source_id, target_id, relationship)
        )
    """)

    # =====================
    # TRACKS
    # =====================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tracks(
            id SERIAL PRIMARY KEY,
            spotify_id TEXT UNIQUE,
            name TEXT NOT NULL,
            artist_id TEXT NOT NULL,
            album_name TEXT,
            image_url TEXT,
            release_date TEXT,
            FOREIGN KEY (artist_id) REFERENCES artists(spotify_id)
        )
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    create_tables()
    print("Database created")