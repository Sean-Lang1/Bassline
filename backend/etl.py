from database import get_connection
from pairs import DISCOVERED_PAIRS
import time
import config
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    data = response.json()
    expires_in = data.get("expires_in", 3600)
    return data["access_token"], time.time() + expires_in

SPOTIFY_TOKEN, SPOTIFY_TOKEN_EXPIRY = get_spotify_token()
SPOTIFY_HEADERS = {
    "Authorization": f"Bearer {SPOTIFY_TOKEN}"
}

def ensure_spotify_token():
    global SPOTIFY_TOKEN, SPOTIFY_TOKEN_EXPIRY, SPOTIFY_HEADERS

    if time.time() >= SPOTIFY_TOKEN_EXPIRY - 60:
        refresh_spotify_token()

def refresh_spotify_token():
    global SPOTIFY_TOKEN, SPOTIFY_TOKEN_EXPIRY, SPOTIFY_HEADERS
    SPOTIFY_TOKEN, SPOTIFY_TOKEN_EXPIRY = get_spotify_token()
    SPOTIFY_HEADERS = {"Authorization": f"Bearer {SPOTIFY_TOKEN}"}

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
# RETRY HELPER
# =====================
def request_with_retry(method, url, max_attempts=3, **kwargs):

    for attempt in range(max_attempts):
        try:
            response = method(url, timeout=10, **kwargs)

            if response.status_code == 429:
                wait = min(int(response.headers.get("Retry-After", 5)), 20)
                print(f"Rate limited. Waiting {wait}s...")
                time.sleep(wait)
                continue

            if response.status_code >= 500:
                print(f"Server error {response.status_code}. Retrying...")
                time.sleep(2)
                continue

            return response

        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            time.sleep(2)

    print(f"Failed request after {max_attempts} attempts: {url}")
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

    separators = [
        " & ",
        " and ",
        " feat. ",
        " ft. ",
        " featuring ",
        " with "
    ]

    lower = name.lower()
    for sep in separators:
        if sep in lower:
            parts = name.split(sep)

            for part in parts:
                if source_artist.lower() not in part.lower():
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

NOT_A_PLACE_WORDS = {
    "he", "she", "they", "it", "was", "is", "were", "raised", "taught",
    "grew", "became", "would", "his", "her", "their", "now", "later",
    "moved", "attended", "began", "started", "on"
}

def parse_hometown(bio):
    lower_bio = bio.lower()
    bx = lower_bio.find("born in")
    if bx == -1:
        return ""

    after = bio[bx + len("born in"):].strip()

    period_idx = after.find(".")
    if period_idx != -1:
        after = after[:period_idx]

    parts = [p.strip() for p in after.split(",")]
    first = parts[0]

    truncated = False
    if " and " in first.lower():
        first = first[:first.lower().index(" and ")].strip()
        truncated = True

    if " of " in first.lower():
        first = first.rsplit(" of ", 1)[-1].strip()

    hometown = first

    if len(parts) >= 2 and not truncated:
        second = parts[1]
        words = second.lower().split()
        looks_like_place = len(words) <= 3 and not any(w in NOT_A_PLACE_WORDS for w in words)
        if looks_like_place:
            hometown += ", " + second

    return hometown

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

    AMBIGUOUS_MARKERS = ["more than one artist", "at least two artists", "at least 2 artists"]
    if any(m in summary.lower() for m in AMBIGUOUS_MARKERS):
        summary = ""

    hometown = ""

    bio = data.get("bio", {}).get("content", "") or data.get("bio", {}).get("summary", "")

    if bio and not any(m in bio.lower() for m in AMBIGUOUS_MARKERS):
        hometown = parse_hometown(bio)

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
def get_artist_top_tracks(artist_name, artist_id=None):
    cache_id = artist_id or cache_key(artist_name)
    cached = cache_read(f"top_tracks_{cache_id}")
    if cached:
        return cached

    ensure_spotify_token()

    r = request_with_retry(
        requests.get,
        "https://api.spotify.com/v1/search",
        headers=SPOTIFY_HEADERS,
        params={
            "q": f'artist:"{artist_name}"',
            "type": "track",
            "limit": 10
        }
    )

    if r is not None and r.status_code == 401:
        refresh_spotify_token()
        r = request_with_retry(
            requests.get,
            "https://api.spotify.com/v1/search",
            headers=SPOTIFY_HEADERS,
            params={
                "q": f'artist:"{artist_name}"',
                "type": "track",
                "limit": 10
            }
        )

    if r is None:
        return []

    try:
        items = r.json().get("tracks", {}).get("items", [])
    except Exception as e:
        print(f"[error] Spotify track search returned bad JSON for {artist_name}: {e}")
        return []

    if artist_id:
        matching = [t for t in items if any(a.get("id") == artist_id for a in t.get("artists", []))]
        if matching:
            items = matching

    results = []
    seen_names = set()

    for t in items:
        name_key = t["name"].lower().strip()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        album = t.get("album", {})
        images = album.get("images", [])

        results.append({
            "name": t["name"],
            "spotify_id": t["id"],
            "album_name": album.get("name"),
            "release_date": album.get("release_date"),
            "album_image": images[0]["url"] if images else None,
            "artists": [a["name"] for a in t.get("artists", [])]
        })

        if len(results) == 5:
            break

    cache_write(f"top_tracks_{cache_id}", results)
    return results

# =====================
# SPOTIFY SEARCH
# =====================
def search_spotify_artist(artist_name):
    cached = cache_read(f"spotify_search_{cache_key(artist_name)}")
    if cached:
        return cached

    ensure_spotify_token()

    r = request_with_retry(
        requests.get,
        "https://api.spotify.com/v1/search",
        headers=SPOTIFY_HEADERS,
        params={
            "q": f"artist:{artist_name}",
            "type": "artist",
            "limit": 3
        }
    )

    if r is not None and r.status_code == 401:
        refresh_spotify_token()
        r = request_with_retry(
            requests.get,
            "https://api.spotify.com/v1/search",
            headers=SPOTIFY_HEADERS,
            params={
                "q": f"artist:{artist_name}",
                "type": "artist",
                "limit": 3
            }
        )

    if r is None:
        return None

    items = r.json().get("artists", {}).get("items", [])
    if not items:
        print(f"[spotify] no results for '{artist_name}' (status {r.status_code})")
        return None

    artist = None

    for item in items:
        if item["name"].lower() == artist_name.lower():
            artist = item
            break

    if artist is None:
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
def geocode_hometown(hometown):
    if not hometown:
        return None, None, ""

    cached = cache_read(f"geocode_{cache_key(hometown)}")
    if cached:
        return cached.get("lat"), cached.get("lon"), cached.get("display", hometown)

    time.sleep(1)

    r = request_with_retry(
        requests.get,
        "https://nominatim.openstreetmap.org/search",
        params={
            "q": hometown,
            "format": "json",
            "limit": 1,
            "addressdetails": 1
        },
        headers={"User-Agent": "bassline-app/1.0"}
    )

    if r is None:
        print(f"[error] geocoding failed for '{hometown}', skipping")
        return None, None, hometown

    try:
        results = r.json()
    except Exception as e:
        print(f"[error] geocoding returned bad JSON for '{hometown}': {e}")
        return None, None, hometown

    if not results:
        cache_write(f"geocode_{cache_key(hometown)}", {"lat": None, "lon": None, "display": hometown})
        return None, None, hometown

    lat = float(results[0]["lat"])
    lon = float(results[0]["lon"])

    address = results[0].get("address", {})
    city = address.get("city") or address.get("town") or address.get("village") or hometown.split(",")[0].strip()
    region = address.get("state") or address.get("country") or ""
    display = f"{city}, {region}" if region else city

    cache_write(f"geocode_{cache_key(hometown)}", {"lat": lat, "lon": lon, "display": display})
    return lat, lon, display


def get_musicbrainz_hometown(artist_name, known_mbid=None):
    cache_id = known_mbid or cache_key(artist_name)
    cached = cache_read(f"mb_hometown_{cache_id}")
    if cached is not None:
        return cached

    result = ""
    mbid = known_mbid

    if mbid is None:
        time.sleep(1)

        search = request_with_retry(
            requests.get,
            "https://musicbrainz.org/ws/2/artist/",
            params={"query": artist_name, "fmt": "json", "limit": 1},
            headers={"User-Agent": "bassline-app/1.0"}
        )

        if search is not None:
            try:
                artists = search.json().get("artists", [])
            except Exception as e:
                print(f"[error] MusicBrainz search returned bad JSON for {artist_name}: {e}")
                artists = []

            for a in artists:
                if a.get("name","").lower() == artist_name.lower():
                    mbid = a["id"]
                    break

            if not mbid and artists:
                mbid = artists[0]["id"]

    if mbid:
        time.sleep(1)

        detail = request_with_retry(
            requests.get,
            f"https://musicbrainz.org/ws/2/artist/{mbid}",
            params={"fmt": "json"},
            headers={"User-Agent": "bassline-app/1.0"}
        )

        if detail is not None:
            try:
                data = detail.json()
            except Exception as e:
                print(f"[error] MusicBrainz artist lookup returned bad JSON for {artist_name}: {e}")
                data = {}

            begin_area = data.get("begin-area") or {}
            area = data.get("area") or {}
            area_is_country = area.get("type") == "Country"

            if begin_area.get("name") and area.get("name") and area_is_country:
                result = begin_area["name"] + ", " + area["name"]
            elif begin_area.get("name"):
                result = begin_area["name"]
            elif area.get("name"):
                result = area["name"]

    cache_write(f"mb_hometown_{cache_id}", result)
    return result

ALLOWED_REL_TYPES = [
    "sibling",
    "married",
    "member of band",
    "collaboration",
    "child",
    "parent",
    "artist",
    "producer",
    "similar"
]

def get_musicbrainz_relations(artist_name):
    time.sleep(1)

    search = request_with_retry(
        requests.get,
        "https://musicbrainz.org/ws/2/artist/",
        params={
            "query": f'artist:"{artist_name}"',
            "fmt": "json",
            "limit": 5
        },
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

    mbid = None

    for a in artists:
        if a.get("name","").lower() == artist_name.lower():
            mbid = a["id"]
            break

    if not mbid:
        mbid = artists[0]["id"]

    time.sleep(1)

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

        if rel_type in ("spouse", "partner"):
            rel_type = "married"

        if rel_type not in ALLOWED_REL_TYPES:
            continue

        target = rel.get("artist", {})
        results.append({
            "name": target.get("name", ""),
            "rel_type": rel_type,
            "mbid": target.get("id")
        })

    return results

# =====================
# RELATIONSHIP PRIORITY
# =====================
REL_PRIORITY = {
    "married": 1,
    "sibling": 1,
    "member of band": 2,
    "collaboration": 2,
    "discovered": 3,
    "discovered by": 3,
    "similar": 5,
}

def rel_priority(rel_type):
    return REL_PRIORITY.get(rel_type, 99)

# =====================
# BUILD ARTIST PROFILE
# =====================
def build_artist_profile(artist_name):
    base = search_spotify_artist(artist_name)
    if not base:
        return None

    info = get_lastfm_artist_info(artist_name)

    hometown = info.get("hometown", "")
    if not hometown:
        hometown = get_musicbrainz_hometown(artist_name)

    lat, lon, display = geocode_hometown(hometown)

    base["hometown"] = display or hometown
    base["latitude"] = lat
    base["longitude"] = lon
    base["listeners"] = info["listeners"]
    base["summary"] = info["summary"]
    base["top_tracks"] = get_artist_top_tracks(artist_name, base["id"])

    if not base.get("image") and base["top_tracks"]:
        base["image"] = base["top_tracks"][0].get("album_image")

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "SELECT spotify_id FROM artists WHERE spotify_id = %s",
            (base["id"],)
        )

        if not cur.fetchone():
            import_artist(
                artist_name,
                hometown=display or hometown,
                lat=lat,
                lon=lon,
                spotify={
                    "id": base["id"],
                    "name": base["name"],
                    "image": base["image"]
                },
                import_tracks=True
            )

    finally:
        conn.close()

    return base

# =====================
# BUILD RELATIONS
# =====================
def build_artist_relations(artist_name, limit_related=8):
    conn = get_connection()
    cur = conn.cursor()

    print(f"\nBuilding relations for {artist_name}...")

    base = build_artist_profile(artist_name)
    if not base:
        return None

    base_id = base["id"]

    similar = get_lastfm_similar(artist_name)
    mb_relations = get_musicbrainz_relations(artist_name)

    candidates = []
    seen = set()

    def try_add(name, rel_type, mbid=None):
        if not is_valid_artist(name, artist_name):
            return

        if name.lower() in seen:
            return

        seen.add(name.lower())

        spotify = search_spotify_artist(name)

        if not spotify or spotify["id"] == base_id:
            return

        info = get_lastfm_artist_info(name)

        candidates.append({
            "name": name,
            "spotify_id": spotify["id"],
            "listeners": info["listeners"],
            "summary": info["summary"],
            "image": spotify.get("image"),
            "rel_type": rel_type,
            "mbid": mbid
        })

    for rel in mb_relations:
        try_add(rel["name"], rel["rel_type"], mbid=rel.get("mbid"))

    for mentor, discovered in DISCOVERED_PAIRS:
        if mentor.lower() == artist_name.lower():
            try_add(discovered, "discovered")
        elif discovered.lower() == artist_name.lower():
            try_add(mentor, "discovered by")

    for rel in similar:
        name = rel["name"]

        joint = extract_joint_artist(name, artist_name)

        if joint:
            try_add(joint, "collaboration")
        else:
            try_add(name, "similar")

    # sort by priority first, then by popularity
    candidates.sort(key=lambda x: (rel_priority(x["rel_type"]), -x["listeners"]))

    capped = []
    family_count = 0
    for c in candidates:
        if c["rel_type"] in ("sibling", "married"):
            if family_count >= 3:
                continue
            family_count += 1
        capped.append(c)
    candidates = capped

    related = []
    links = []
    i = 0

    while len(related) < limit_related and i < len(candidates):
        c = candidates[i]
        i += 1

        info = get_lastfm_artist_info(c["name"])
        hometown = info.get("hometown", "")

        if not hometown:
            hometown = get_musicbrainz_hometown(c["name"], known_mbid=c.get("mbid"))

        lat, lon, display = geocode_hometown(hometown)

        if lat is None or lon is None:
            print(c["name"], "- no hometown found, skipping")
            continue

        print(c["name"], "[", c["listeners"], "]", c["rel_type"])

        c["hometown"] = display or hometown
        c["latitude"] = lat
        c["longitude"] = lon

        import_artist(
            c["name"],
            hometown=display or hometown,
            lat=lat,
            lon=lon,
            spotify={
                "id": c["spotify_id"],
                "name": c["name"],
                "image": c["image"]
            },
            import_tracks=c["listeners"] >= 5000
        )

        if c["listeners"] >= 5000:
            c["top_tracks"] = get_artist_top_tracks(
                c["name"],
                c["spotify_id"]
            )
        else:
            c["top_tracks"] = []

        if not c.get("image") and c["top_tracks"]:
            c["image"] = c["top_tracks"][0].get("album_image")

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
def import_artist(artist_name, hometown=None, lat=None, lon=None, spotify=None, import_tracks=True):
    conn = get_connection()
    cur = conn.cursor()

    if spotify is None:
        spotify = search_spotify_artist(artist_name)

    if not spotify:
        conn.close()
        return None

    info = get_lastfm_artist_info(artist_name)

    if hometown is None:
        hometown = info.get("hometown", "")
        lat, lon, display = geocode_hometown(hometown)
        hometown = display or hometown

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

    top_tracks = []
    if import_tracks:
        top_tracks = get_artist_top_tracks(artist_name, spotify["id"])
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