from etl import get_musicbrainz_relations, get_lastfm_similar, get_lastfm_artist_info, search_spotify_artist, is_valid_artist

artist_name = "Michael Jackson"

print("=== MUSICBRAINZ RELATIONS ===")
mb_relations = get_musicbrainz_relations(artist_name)
for rel in mb_relations:
    name = rel["name"]
    if not is_valid_artist(name, artist_name):
        print(f"[skip, invalid] {name} ({rel['rel_type']})")
        continue
    spotify = search_spotify_artist(name)
    if not spotify:
        print(f"[skip, no spotify match] {name} ({rel['rel_type']})")
        continue
    info = get_lastfm_artist_info(name)
    print(f"{name} | {rel['rel_type']} | {info['listeners']} listeners")

print("\n=== LASTFM SIMILAR ===")
similar = get_lastfm_similar(artist_name)
for rel in similar:
    name = rel["name"]
    if not is_valid_artist(name, artist_name):
        print(f"[skip, invalid] {name}")
        continue
    spotify = search_spotify_artist(name)
    if not spotify:
        print(f"[skip, no spotify match] {name}")
        continue
    info = get_lastfm_artist_info(name)
    print(f"{name} | similar | {info['listeners']} listeners")