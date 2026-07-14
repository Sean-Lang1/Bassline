# 🎵 Bassline

Bassline is a music data project that explores connections between artists and builds a network based on relationships such as collaborations, influences, similarities, and other artist connections.

🌐 **Live Demo:** [Bassline](https://bassline-sean-lang.vercel.app)

The goal of this project is to create a different way to discover music by focusing on how artists are connected rather than only relying on genre recommendations. Future plans include introducing song samples and expanding the ways users can explore these relationships.

## Features

- Artist profiles with:
  - Images
  - Listener statistics
  - Biographies
  - Hometown/location data
  - Top tracks

- Artist relationship discovery through:
  - Similar artists
  - Collaborations
  - Band relationships
  - Family relationships
  - Curated artist connections

- PostgreSQL storage for artist data and relationships

## Data Sources

Bassline uses multiple APIs:

- Spotify API — artist data, tracks, images
- Last.fm API — similar artists, listener counts, biographies
- MusicBrainz API — artist relationships and metadata
- OpenStreetMap Nominatim — hometown geocoding

## How It Works

When an artist is searched, Bassline first checks existing database data.

If the artist is new:
1. Spotify identifies the artist
2. Last.fm and MusicBrainz gather additional information
3. Related artists are discovered and verified
4. Data is cleaned and stored in PostgreSQL

The project also uses caching and retry handling to reduce unnecessary API requests and handle rate limits.

## Challenges

Some of the biggest challenges were working with inconsistent music data across different platforms, handling API limitations, and deciding how to determine meaningful artist relationships.

Many artists have missing information, different names across services, or unclear connections, so a large part of the project involved cleaning data and building systems to handle those cases.

## Project Structure
Bassline/
├── etl.py # Main data pipeline
├── database.py # Database connection
├── config.py # API configuration
├── pairs.py # Curated artist relationships
└── README.md


## Future Plans

- Add song samples and previews
- Improve artist discovery
- Expand relationship types
- Create a more interactive artist map
- Add additional music analysis features

## Installation

```bash
git clone <repository-url>
cd Bassline
pip install -r requirements.txt

Bassline is an ongoing project exploring the intersection of music discovery, data collection, and artist relationships. This version serves as the foundation for future features and improvements.
