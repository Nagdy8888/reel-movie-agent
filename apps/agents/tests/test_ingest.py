"""Unit tests for CMU subset selection and ID quoting."""

from pathlib import Path

from agents.projection import movie_id_from_wikipedia, named_node_id, person_id_from_freebase
from ingestion.ingest import (
    CastMember,
    load_character_metadata,
    load_movie_metadata,
    load_plot_summaries,
    select_subset,
)


def test_person_id_percent_quotes_freebase_slashes() -> None:
    """Freebase actor IDs contain slashes and must be percent-quoted."""
    assert person_id_from_freebase("/m/0346l4") == "person:%2Fm%2F0346l4"


def test_genre_id_matches_named_node_convention() -> None:
    """Genre IDs use casefolded, percent-quoted names."""
    assert named_node_id("genre", "Science Fiction") == "genre:science%20fiction"


def test_movie_id_uses_wikipedia_id() -> None:
    """Movie keys are movie:{wikipedia_id}."""
    assert movie_id_from_wikipedia("31855") == "movie:31855"


def test_select_subset_is_deterministic(tmp_path: Path) -> None:
    """Subset ranking uses box_office desc then wikipedia_id asc."""
    (tmp_path / "plot_summaries.txt").write_text(
        "1\tSummary one\n2\tSummary two\n3\tSummary three\n4\tNo cast movie\n",
        encoding="utf-8",
    )
    (tmp_path / "movie.metadata.tsv").write_text(
        "\n".join(
            [
                '1\t/m/a\tAlpha\t2010\t100\t90\t{}\t{}\t{"/m/g":"Drama"}',
                '2\t/m/b\tBeta\t2011\t200\t90\t{}\t{}\t{"/m/g":"Action"}',
                '3\t/m/c\tGamma\t2012\t200\t90\t{}\t{}\t{"/m/g":"Comedy"}',
                '4\t/m/d\tDelta\t2013\t999\t90\t{}\t{}\t{"/m/g":"Drama"}',
                '5\t/m/e\tNoBox\t2014\t\t90\t{}\t{}\t{"/m/g":"Drama"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # character.metadata: wiki, freebase_movie, release, character, dob, gender,
    # height, ethnicity, actor_name, age, map_id, char_id, actor_id
    (tmp_path / "character.metadata.tsv").write_text(
        "\n".join(
            [
                "1\t/m/a\t2010\tHero\t\t\t\t\tActor A\t\t\t\t/m/aa",
                "2\t/m/b\t2011\tHero\t\t\t\t\tActor B\t\t\t\t/m/bb",
                "3\t/m/c\t2012\tHero\t\t\t\t\tActor C\t\t\t\t/m/cc",
                "5\t/m/e\t2014\tHero\t\t\t\t\tActor E\t\t\t\t/m/ee",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summaries = load_plot_summaries(tmp_path / "plot_summaries.txt")
    metadata = load_movie_metadata(tmp_path / "movie.metadata.tsv")
    cast = load_character_metadata(tmp_path / "character.metadata.tsv")
    selected = select_subset(summaries, metadata, cast, limit=2)

    assert [m.wikipedia_id for m in selected] == ["2", "3"]
    assert selected[0].title == "Beta"
    assert selected[0].cast[0] == CastMember(
        actor_name="Actor B",
        person_id="person:%2Fm%2Fbb",
        character="Hero",
        billing_order=0,
    )
