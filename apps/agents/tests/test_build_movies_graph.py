"""Tests for the deterministic Kaggle movie bundle builder."""

from __future__ import annotations

from scripts.build_movies_graph import (
    MAX_CAST,
    MAX_CREW_PER_ROLE,
    build_movie,
    calculate_manifest,
    classify_crew,
    image_url,
    parse_structured,
    select_movies,
)


def test_select_movies_deduplicates_and_breaks_vote_ties_by_tmdb_id() -> None:
    """Selection should keep one movie per ID and use deterministic ordering."""
    rows = [
        {"id": "20", "title": "Twenty", "vote_count": "10"},
        {"id": "10", "title": "Ten", "vote_count": "10"},
        {"id": "20", "title": "Duplicate", "vote_count": "2"},
        {"id": "bad", "title": "Malformed", "vote_count": "999"},
        {"id": "30", "title": "", "vote_count": "999"},
    ]

    selected = select_movies(rows, 2)

    assert [row["_tmdb_id"] for row in selected] == [10, 20]
    assert [row["title"] for row in selected] == ["Ten", "Twenty"]


def test_parse_structured_returns_empty_for_malformed_rows() -> None:
    """Malformed structured fields should not stop bundle generation."""
    assert parse_structured("[{'id': 1, 'name': 'Drama'}]") == [
        {"id": 1, "name": "Drama"}
    ]
    assert parse_structured("{not valid") == []
    assert parse_structured(None) == []
    assert parse_structured("{'id': 1}") == []


def test_classify_crew_filters_deduplicates_and_caps_roles() -> None:
    """Crew classification should retain only supported jobs and stable IDs."""
    entries = [
        {"id": index, "name": f"Director {index}", "job": "Director"}
        for index in range(MAX_CREW_PER_ROLE + 2)
    ]
    entries += [
        {"id": 100, "name": "Writer", "job": "Screenplay"},
        {"id": 100, "name": "Writer duplicate", "job": "Story"},
        {"id": 101, "name": "Producer", "job": "Producer"},
        {"id": 102, "name": "Editor", "job": "Editor"},
    ]

    classified = classify_crew(entries)

    assert len(classified["directors"]) == MAX_CREW_PER_ROLE
    assert [person["tmdbId"] for person in classified["writers"]] == [100]
    assert [person["tmdbId"] for person in classified["producers"]] == [101]


def test_image_url_builds_tmdb_poster_url() -> None:
    """Poster paths should become complete HTTPS URLs."""
    assert image_url("/poster.jpg") == "https://image.tmdb.org/t/p/w500/poster.jpg"
    assert image_url("poster.jpg") == "https://image.tmdb.org/t/p/w500/poster.jpg"
    assert image_url(None) is None


def test_build_movie_caps_cast_keywords_and_preserves_ids() -> None:
    """One normalized movie should contain bounded relationships and stable IDs."""
    row = {
        "_tmdb_id": 862,
        "title": "Toy Story",
        "vote_count": "100",
        "vote_average": "7.5",
        "release_date": "1995-10-30",
        "poster_path": "/toy.jpg",
        "genres": "[{'id': 16, 'name': 'Animation'}]",
    }
    credits = {
        "cast": [
            {
                "id": index,
                "name": f"Actor {index}",
                "character": f"Role {index}",
                "order": index,
            }
            for index in range(MAX_CAST + 2)
        ],
        "crew": [{"id": 77, "name": "Director", "job": "Director"}],
    }
    keywords = [{"name": f"keyword-{index}"} for index in range(20)]

    movie = build_movie(row, credits, keywords)

    assert movie["tmdbId"] == 862
    assert movie["year"] == 1995
    assert len(movie["cast"]) == MAX_CAST
    assert len(movie["keywords"]) == 10
    assert movie["posterUrl"].endswith("/toy.jpg")


def test_calculate_manifest_counts_shared_people_once() -> None:
    """Manifest node totals should deduplicate people while preserving edges."""
    movies = [
        {
            "tmdbId": 1,
            "cast": [{"tmdbId": 10}],
            "directors": [{"tmdbId": 20}],
            "writers": [],
            "producers": [],
            "genres": ["Drama"],
            "keywords": ["friendship"],
        },
        {
            "tmdbId": 2,
            "cast": [{"tmdbId": 10}],
            "directors": [],
            "writers": [],
            "producers": [],
            "genres": ["Drama"],
            "keywords": ["friendship", "journey"],
        },
    ]

    manifest = calculate_manifest(movies)

    assert manifest["nodeCounts"] == {
        "Movie": 2,
        "Person": 2,
        "Genre": 1,
        "Keyword": 2,
    }
    assert manifest["relationshipCounts"]["ACTED_IN"] == 2
    assert manifest["totalRelationships"] == 8
    assert manifest["limits"]["withinAuraFree"] is True
