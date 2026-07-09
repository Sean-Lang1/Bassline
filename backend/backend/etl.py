import time
import config
import requests
from database import get_connection
import json
import os
import sys
import warnings
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore')


# =====================
# SPOTIFY AUTH
# =====================
def get_spotify_token():
    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "client_credentials",
            "client_id": config.SPOTIFY_CLIENT_ID,
            "client_secret": config.SPOTIFY_CLIENT_SECRET
        }
    )
    return response.json()["access_token"]


SPOTIFY_TOKEN = get_spotify_token()
SPOTIFY_HEADERS = {
    "Authorization": f"Bearer {SPOTIFY_TOKEN}"
}

CACHE_DIR = "./api_cache"

def cache_read(cache_name):
    path = f"{CACHE_DIR}/{cache_name}.json"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return None
    return None

def cache_write(cache_name, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(f"{CACHE_DIR}/{cache_name}.json", "w") as f:
        json.dump(data, f)


# =====================
# SAFE CACHE KEY 
# =====================
def cache_key(name):
    return name.replace(" ", "_").replace("/", "_").replace(",", "_")

# =====================
#  RETRY HELPER
# =====================
def request_with_retry(method, url, max_attempts=3, backoff_seconds=2, **kwargs):
    
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = method(url, timeout=10, **kwargs)

            if response.status_code == 429 or response.status_code >= 500:
                print(f"[retry] {url} returned {response.status_code} "
                      f"(attempt {attempt}/{max_attempts})")
                last_error = f"HTTP {response.status_code}"
            else:
                return response

        except requests.exceptions.RequestException as e:
            print(f"[retry] {url} failed: {e} (attempt {attempt}/{max_attempts})")
            last_error = str(e)

        if attempt < max_attempts:
            time.sleep(backoff_seconds)

    print(f"[error] giving up on {url} after {max_attempts} attempts: {last_error}")
    return None

# =====================
# FILTER
# =====================
def is_valid_artist(name, source_artist):
    if not name:
        return False

    n = name.lower().strip()

    bad_keywords = [
        "various artists",
        "compilation",
        "tribute",
        "usa for",
        "u.s.a for",
        "artists against",
        "unknown",
        "unknown artist",
        "artist: unknown",
        "n/a"
    ]

    if any(k in n for k in bad_keywords):
        return False

    if source_artist.lower() in n:
        return False

    return True

# =====================
# LAST.FM
# =====================
def get_lastfm_similar(artist_name):
    cached = cache_read(f"lastfm_similar_{cache_key(artist_name)}")
    if cached:
        return cached

    r = request_with_retry(
        requests.get,
        "https://ws.audioscrobbler.com/2.0/",
        params={
            "method": "artist.getSimilar",
            "artist": artist_name,
            "api_key": config.LASTFM_API_KEY,
            "format": "json",
            "limit": 10
        }
    )

    if r is None:
        return []

    artists = r.json().get("similarartists", {}).get("artist", [])

    result = [{"name": a["name"]} for a in artists]

    cache_write(f"lastfm_similar_{cache_key(artist_name)}", result)
    return result


def get_lastfm_artist_info(artist_name):
    cached = cache_read(f"lastfm_info_{cache_key(artist_name)}")
    if cached:
        return cached

    r = request_with_retry(
        requests.get,
        "https://ws.audioscrobbler.com/2.0/",
        params={
            "method": "artist.getInfo",
            "artist": artist_name,
            "api_key": config.LASTFM_API_KEY,
            "format": "json"
        }
    )

    if r is None:
        return {"listeners": 0, "summary": "", "hometown": ""}

    data = r.json().get("artist", {})
    listeners = int(data.get("stats", {}).get("listeners", 0))

    summary = data.get("bio", {}).get("summary", "")
    if summary:
        summary = summary.split("<a")[0].strip()

    hometown = ""

    bio = data.get("bio", {}).get("content", "") or data.get("bio", {}).get("summary", "")

    if bio:
        lower_bio = bio.lower()
        bx = lower_bio.find("born in")

        if bx != -1:
            after = bio[bx + len("born in"):]

            parts = after.split(",")

            if len(parts) >= 2:
                hometown = parts[0].strip() + ", " + parts[1].strip()
            else:
                hometown = parts[0].strip()

    result = {
        "listeners": listeners,
        "summary": summary,
        "hometown": hometown
    }

    cache_write(f"lastfm_info_{cache_key(artist_name)}", result)
    return result

# =====================
# TOP TRACKS
# =====================
def get_lastfm_top_tracks(artist_name):
    r = request_with_retry(
        requests.get,
        "https://ws.audioscrobbler.com/2.0/",
        params={
            "method": "artist.getTopTracks",
            "artist": artist_name,
            "api_key": config.LASTFM_API_KEY,
            "format": "json",
            "limit": 5
        }
    )

    if r is None:
        return []

    data = r.json().get("toptracks", {}).get("track", [])

    results = []

    for t in data:
        track_name = t["name"]

        sp_r = request_with_retry(
            requests.get,
            "https://api.spotify.com/v1/search",
            headers=SPOTIFY_HEADERS,
            params={
                "q": f"track:{track_name} artist:{artist_name}",
                "type": "track",
                "limit": 1
            }
        )

        items = sp_r.json().get("tracks", {}).get("items", []) if sp_r is not None else []

        if items:
            s = items[0]
            album = s.get("album", {})
            images = album.get("images", [])

            results.append({
                "name": track_name,
                "spotify_id": s["id"],
                "album_name": album.get("name"),
                "release_date": album.get("release_date"),
                "album_image": images[0]["url"] if images else None,
                "artists": [a["name"] for a in s.get("artists", [])]
            })
        else:
            results.append({
                "name": track_name,
                "spotify_id": None,
                "album_name": None,
                "release_date": None,
                "album_image": None,
                "artists": []
            })

    return results

# =====================
# SPOTIFY SEARCH
# =====================
def search_spotify_artist(artist_name):
    cached = cache_read(f"spotify_search_{cache_key(artist_name)}")
    if cached:
        return cached

    r = request_with_retry(
        requests.get,
        "https://api.spotify.com/v1/search",
        headers=SPOTIFY_HEADERS,
        params={
            "q": f"artist:{artist_name}",
            "type": "artist",
            "limit": 1
        }
    )

    if r is None:
        return None

    items = r.json().get("artists", {}).get("items", [])
    if not items:
        return None

    artist = items[0]

    images = artist.get("images", [])
    image_url = images[0]["url"] if images else None

    result = {
        "id": artist["id"],
        "name": artist["name"],
        "image": image_url,
        "images": images
    }

    cache_write(f"spotify_search_{cache_key(artist_name)}", result)
    return result


# =====================
# GEOCODING (for hometown)
# =====================
_last_geocode_call = 0

def _geocode_throttle():
    global _last_geocode_call
    elapsed = time.time() - _last_geocode_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_geocode_call = time.time()


def geocode_hometown(hometown):
    if not hometown:
        return None, None

    cached = cache_read(f"geocode_{cache_key(hometown)}")
    if cached:
        return cached.get("lat"), cached.get("lon")

    _geocode_throttle()

    r = request_with_retry(
        requests.get,
        "https://nominatim.openstreetmap.org/search",
        params={
            "q": hometown,
            "format": "json",
            "limit": 1
        },
        headers={"User-Agent": "bassline-app/1.0"}
    )

    if r is None:
        print(f"[error] geocoding failed for '{hometown}', skipping")
        return None, None

    try:
        results = r.json()
    except Exception as e:
        print(f"[error] geocoding returned bad JSON for '{hometown}': {e}")
        return None, None

    if not results:
        cache_write(f"geocode_{cache_key(hometown)}", {"lat": None, "lon": None})
        return None, None

    lat = float(results[0]["lat"])
    lon = float(results[0]["lon"])

    cache_write(f"geocode_{cache_key(hometown)}", {"lat": lat, "lon": lon})
    return lat, lon

_last_musicbrainz_call = 0

def _musicbrainz_throttle():
    global _last_musicbrainz_call
    elapsed = time.time() - _last_musicbrainz_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_musicbrainz_call = time.time()


def check_musicbrainz_collaboration(a1, a2):
    _musicbrainz_throttle()

    r = request_with_retry(
        requests.get,
        "https://musicbrainz.org/ws/2/recording/",
        params={
            "query": f'artist:"{a1}"',
            "fmt": "json",
            "limit": 50
        },
        headers={"User-Agent": "bassline-app/1.0"}
    )

    if r is None:
        print(f"[error] MusicBrainz collab check failed for {a1} / {a2}, skipping")
        return False

    try:
        data = r.json()
    except Exception as e:
        print(f"[error] MusicBrainz returned bad JSON for {a1}: {e}")
        return False

    for rec in data.get("recordings", []):
        for c in rec.get("artist-credit", []):
            name = c.get("artist", {}).get("name", "")
            if name.lower() == a2.lower():
                return True

    return False


# =====================
# BUILD RELATIONS
# =====================
def build_artist_relations(artist_name, limit_related=10):
    conn = get_connection()
    cur = conn.cursor()

    print(f"\nBuilding relations for {artist_name}...")

    base = search_spotify_artist(artist_name)
    if not base:
        return []

    base_id = base["id"]

    cur.execute("SELECT spotify_id FROM artists WHERE spotify_id = ?", (base_id,))
    if not cur.fetchone():
        import_artist(artist_name)

    similar = get_lastfm_similar(artist_name)

    collab_bucket = []
    similar_bucket = []
    seen = set()

    for rel in similar:
        name = rel["name"]

        if not is_valid_artist(name, artist_name):
            continue

        if name.lower() in seen:
            continue
        seen.add(name.lower())

        spotify = search_spotify_artist(name)
        if not spotify:
            continue

        if spotify["id"] == base_id:
            continue

        info = get_lastfm_artist_info(name)
        listeners = info["listeners"]

        is_collab = check_musicbrainz_collaboration(artist_name, name)

        candidate = {
            "name": name,
            "spotify_id": spotify["id"],
            "listeners": listeners,
            "summary": info["summary"],
            "image": spotify.get("image"),
            "collab": is_collab
        }

        if is_collab:
            collab_bucket.append(candidate)
        else:
            similar_bucket.append(candidate)

    collab_bucket.sort(key=lambda x: x["listeners"], reverse=True)
    similar_bucket.sort(key=lambda x: x["listeners"], reverse=True)

    final = []

    for c in collab_bucket:
        final.append(c)

    i = 0
    while len(final) < limit_related and i < len(similar_bucket):
        final.append(similar_bucket[i])
        i += 1

    final.sort(key=lambda x: x["listeners"], reverse=True)

    links = []

    for c in final:
        import_artist(c["name"])
        print(c["name"], "[", c["listeners"], "]")

        links.append({
            "source": base_id,
            "target": c["spotify_id"],
            "rel_type": "collaboration" if c["collab"] else "similar",
            "listeners": c["listeners"]
        })

    for e in links:
        cur.execute("""
            INSERT OR IGNORE INTO artist_links
            (source_id, target_id, relationship)
            VALUES (?, ?, ?)
        """, (e["source"], e["target"], e["rel_type"]))

    conn.commit()
    conn.close()

    print(f"\nInserted {len(links)} links")
    return links

# =====================
# IMPORT ARTIST
# =====================
def import_artist(artist_name):
    conn = get_connection()
    cur = conn.cursor()

    spotify = search_spotify_artist(artist_name)
    if not spotify:
        return

    info = get_lastfm_artist_info(artist_name)

    hometown = info.get("hometown", "")
    lat, lon = geocode_hometown(hometown)

    cur.execute("""
        INSERT OR IGNORE INTO artists
        (spotify_id, name, hometown, listeners, summary, image_url, latitude, longitude)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        spotify["id"],
        spotify["name"],
        hometown,
        info["listeners"],
        info["summary"],
        spotify.get("image"),
        lat,
        lon
    ))

    top_tracks = get_lastfm_top_tracks(artist_name)
    for t in top_tracks:
        if not t.get("spotify_id"):
            continue

        cur.execute("""
            INSERT OR IGNORE INTO tracks
            (spotify_id, name, artist_id, album_name, image_url, release_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            t["spotify_id"],
            t["name"],
            spotify["id"],
            t.get("album_name"),
            t.get("album_image"),
            t.get("release_date"),
            )
        )
    print(f"\nSuccessfully imported {len(top_tracks)} top tracks for {artist_name}...")

    conn.commit()
    conn.close()


# =====================
# TEST
# =====================
if __name__ == "__main__":
  import_artist("Michael Jackson")