import time
import config
import requests
from database import get_connection
from pairs import DISCOVERED_PAIRS
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
            "client_id": os.getenv("SPOTIFY_CLIENT_ID"),
            "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET")
        }
    )
    data = response.json()
    return data.get("access_token")

def get_spotify_headers():
    token = get_spotify_token()
    return {"Authorization": f"Bearer {token}"}


_memory_cache = {}

def cache_read(cache_name):
    return _memory_cache.get(cache_name)

def cache_write(cache_name, data):
    _memory_cache[cache_name] = data


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


def extract_joint_artist(name, source_artist):
    normalized = name.replace(" and ", " & ").replace(" And ", " & ")
    if " & " not in normalized:
        return None
    for part in normalized.split(" & "):
        if source_artist.lower() not in part.lower().strip():
            return part.strip()
    return None

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
            headers=get_spotify_headers(),
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
        headers=get_spotify_headers(),
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
_last_call_times = {}

def throttle(seconds):
    caller = sys._getframe(1).f_code.co_name
    last_call = _last_call_times.get(caller, 0)
    elapsed = time.time() - last_call
    if elapsed < seconds:
        time.sleep(seconds - elapsed)
    _last_call_times[caller] = time.time()


def geocode_hometown(hometown):
    if not hometown:
        return None, None

    cached = cache_read(f"geocode_{cache_key(hometown)}")
    if cached:
        return cached.get("lat"), cached.get("lon")

    throttle(1)

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


ALLOWED_REL_TYPES = ["sibling", "married", "member of band", "collaboration"]

def get_musicbrainz_relations(artist_name):
    throttle(1)

    search = request_with_retry(
        requests.get,
        "https://musicbrainz.org/ws/2/artist/",
        params={"query": artist_name, "fmt": "json", "limit": 1},
        headers={"User-Agent": "bassline-app/1.0"}
    )

    if search is None:
        return []

    try:
        artists = search.json().get("artists", [])
    except Exception as e:
        print(f"[error] MusicBrainz search returned bad JSON for {artist_name}: {e}")
        return []

    if not artists:
        return []

    mbid = artists[0]["id"]

    throttle(1)

    rels = request_with_retry(
        requests.get,
        f"https://musicbrainz.org/ws/2/artist/{mbid}",
        params={"inc": "artist-rels", "fmt": "json"},
        headers={"User-Agent": "bassline-app/1.0"}
    )

    if rels is None:
        return []

    try:
        data = rels.json()
    except Exception as e:
        print(f"[error] MusicBrainz relations returned bad JSON for {artist_name}: {e}")
        return []

    results = []
    for rel in data.get("relations", []):
        rel_type = rel.get("type")
        if rel_type not in ALLOWED_REL_TYPES:
            continue

        target = rel.get("artist", {})
        results.append({"name": target.get("name", ""), "rel_type": rel_type})

    return results


# =====================
# BUILD RELATIONS
# =====================
def build_artist_relations(artist_name, limit_related=10):
    conn = get_connection()
    cur = conn.cursor()

    print(f"\nBuilding relations for {artist_name}...")

    base = search_spotify_artist(artist_name)
    if not base:
        return None

    base_id = base["id"]

    cur.execute("SELECT spotify_id FROM artists WHERE spotify_id = %s", (base_id,))
    if not cur.fetchone():
        import_artist(artist_name)

    similar = get_lastfm_similar(artist_name)
    mb_relations = get_musicbrainz_relations(artist_name)

    rel_bucket = []
    similar_bucket = []
    seen = set()

    for rel in mb_relations:
        name = rel["name"]

        if not is_valid_artist(name, artist_name):
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())

        spotify = search_spotify_artist(name)
        if not spotify or spotify["id"] == base_id:
            continue

        info = get_lastfm_artist_info(name)

        rel_bucket.append({
            "name": name,
            "spotify_id": spotify["id"],
            "listeners": info["listeners"],
            "summary": info["summary"],
            "image": spotify.get("image"),
            "rel_type": rel["rel_type"]
        })

    discovered_bucket = []

    for mentor, discovered in DISCOVERED_PAIRS:
        name = None
        rel_type = None

        if mentor.lower() == artist_name.lower():
            name = discovered
            rel_type = "discovered"
        elif discovered.lower() == artist_name.lower():
            name = mentor
            rel_type = "discovered by"

        if not name:
            continue
        if not is_valid_artist(name, artist_name):
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())

        spotify = search_spotify_artist(name)
        if not spotify or spotify["id"] == base_id:
            continue

        info = get_lastfm_artist_info(name)

        discovered_bucket.append({
            "name": name,
            "spotify_id": spotify["id"],
            "listeners": info["listeners"],
            "summary": info["summary"],
            "image": spotify.get("image"),
            "rel_type": rel_type
        })

    for rel in similar:
        name = rel["name"]

        joint = extract_joint_artist(name, artist_name)
        if joint:
            name = joint

            if not is_valid_artist(name, artist_name):
                continue
            if name.lower() in seen:
                continue
            seen.add(name.lower())

            spotify = search_spotify_artist(name)
            if not spotify or spotify["id"] == base_id:
                continue

            info = get_lastfm_artist_info(name)

            rel_bucket.append({
                "name": name,
                "spotify_id": spotify["id"],
                "listeners": info["listeners"],
                "summary": info["summary"],
                "image": spotify.get("image"),
                "rel_type": "collaboration"
            })
            continue

        if not is_valid_artist(name, artist_name):
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())

        spotify = search_spotify_artist(name)
        if not spotify or spotify["id"] == base_id:
            continue

        info = get_lastfm_artist_info(name)

        similar_bucket.append({
            "name": name,
            "spotify_id": spotify["id"],
            "listeners": info["listeners"],
            "summary": info["summary"],
            "image": spotify.get("image"),
            "rel_type": "similar"
        })

    rel_bucket.sort(key=lambda x: x["listeners"], reverse=True)
    similar_bucket.sort(key=lambda x: x["listeners"], reverse=True)
    discovered_bucket.sort(key=lambda x: x["listeners"], reverse=True)

    final = rel_bucket[:3]

    i = 0
    while len(final) < limit_related and i < len(similar_bucket):
        final.append(similar_bucket[i])
        i += 1

    final = final + discovered_bucket[:2]

    final.sort(key=lambda x: x["listeners"], reverse=True)

    related = []
    links = []

    for c in final:
        import_artist(c["name"])
        print(c["name"], "[", c["listeners"], "]")

        related.append(c)

        links.append({
            "source": base_id,
            "target": c["spotify_id"],
            "rel_type": c["rel_type"],
            "listeners": c["listeners"]
        })

    for e in links:
        cur.execute("""
            INSERT INTO artist_links
            (source_id, target_id, relationship)
            VALUES (%s, %s, %s)
            ON CONFLICT (source_id, target_id, relationship) DO NOTHING
        """, (e["source"], e["target"], e["rel_type"]))

    conn.commit()
    conn.close()

    print(f"\nInserted {len(links)} links")

    return {
        "artist": base,
        "related": related,
        "links": links
    }

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
        INSERT INTO artists
        (spotify_id, name, hometown, listeners, summary, image_url, latitude, longitude)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (spotify_id) DO NOTHING
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
            INSERT INTO tracks
            (spotify_id, name, artist_id, album_name, image_url, release_date)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (spotify_id) DO NOTHING
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