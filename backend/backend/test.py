import requests
import json

BASE = "https://musicbrainz.org/ws/2"


# 1. Get MBID from artist name
def get_artist_mbid(name):
    url = f"{BASE}/artist/"
    params = {
        "query": name,
        "fmt": "json",
        "limit": 1
    }

    r = requests.get(url, params=params)
    data = r.json()

    if "artists" not in data or len(data["artists"]) == 0:
        raise Exception("No artist found")

    artist = data["artists"][0]
    return artist["id"], artist["name"]


# 2. Fetch full relationships using MBID
def get_artist_relations(mbid):
    url = f"{BASE}/artist/{mbid}"
    params = {
        "inc": "artist-rels",
        "fmt": "json"
    }

    r = requests.get(url, params=params)
    return r.json()


# 3. Debug function (THIS is what you wanted)
def debug_artist_relations(expected_name, data):
    print("\n🔍 EXPECTED ARTIST:", expected_name)
    print("🔍 ACTUAL ARTIST:", data.get("name"))
    print("🔍 MBID:", data.get("id"))
    print("=" * 60)

    # 🚨 sanity check (this catches your Bowie confusion instantly)
    if expected_name.lower() not in data.get("name", "").lower():
        print("🚨 WARNING: Artist mismatch detected!")
        print("You probably queried the wrong MBID or reused old data.\n")

    relations = data.get("relations", [])

    if not relations:
        print("❌ No relations found")
        return

    for i, rel in enumerate(relations):
        target = rel.get("artist", {}).get("name", "UNKNOWN")
        rel_type = rel.get("type")
        direction = rel.get("direction")
        joinphrase = rel.get("joinphrase")

        print(f"\n[{i}] → {target}")
        print("   type:", rel_type)
        print("   direction:", direction)
        print("   joinphrase:", joinphrase)

        # flag missing joinphrases (your original issue)
        if not joinphrase:
            print("   ⚠️ missing joinphrase")


# 4. FULL PIPELINE RUN
def run_debug(name):
    mbid, resolved_name = get_artist_mbid(name)

    data = get_artist_relations(mbid)

    debug_artist_relations(resolved_name, data)


# RUN IT 👇
run_debug("Michael Jackson")