"""
Checks on links.csv (and links_small.csv): structure and format of the three ids, missing and
shared tmdbIds, link with movies_metadata.csv and with the ratings, links_small compared to links.
"""
import sys
from pathlib import Path

import pandas as pd
from tabulate import tabulate

# reuse the helpers written for movies_metadata
sys.path.append(str(Path(__file__).resolve().parents[1] / "movies_metadata"))
from load import is_truncated, is_valid_row, load_metadata, print_section, report

DATA = Path(__file__).resolve().parents[2] / "data"


def percent(part, total):
    return "%.2f%%" % (100 * part / total) if total else "-"


def load_links(name):
    """Read as strings: imdbId has leading zeros (0114709) that a conversion to number would lose"""
    return pd.read_csv(DATA / name, dtype=str, keep_default_na=False)


def load_rated_movies(name):
    """Number of ratings of each movieId, reading only that column of the ratings file"""
    return pd.read_csv(DATA / name, usecols=["movieId"])["movieId"].astype(str).value_counts()


def check_structure(links, name):
    print_section("1. Structure of %s" % name)
    content = (DATA / name).read_bytes()
    print("rows: %d, columns: %s, lines ending with \\r\\n (Windows): %d of %d"
          % (len(links), list(links.columns), content.count(b"\r\n"), content.count(b"\n")))
    table = []
    for column in links.columns:
        values = links[column]
        filled = values[values != ""]
        table.append([column, (values == "").sum(), (~filled.str.fullmatch(r"\d+")).sum(),
                      {int(k): int(v) for k, v in filled.str.len().value_counts().sort_index().items()},
                      filled.duplicated().sum()])
    print(tabulate(table, headers=["column", "empty", "not digits", "lengths (digits: rows)", "repeated values"],
                   tablefmt="simple"))
    print("movieId sorted: %s, from %s to %s" % (links["movieId"].astype(int).is_monotonic_increasing,
                                                links["movieId"].astype(int).min(), links["movieId"].astype(int).max()))


def check_missing_tmdb(links, ratings):
    print_section("2. movieIds without a tmdbId")
    missing = links[links["tmdbId"] == ""]
    print("movieIds without tmdbId: %d (%s)" % (len(missing), percent(len(missing), len(links))))
    lost = ratings[ratings.index.isin(missing["movieId"])].sum()
    print("ratings of these movies: %d of %d (%s): they cannot be linked to any film"
          % (lost, ratings.sum(), percent(lost, ratings.sum())))
    report("examples", missing, ["movieId", "imdbId", "tmdbId"])


def check_shared_tmdb(links, ratings, metadata):
    print_section("3. tmdbIds used by more than one movieId")
    filled = links[links["tmdbId"] != ""]
    shared = filled[filled["tmdbId"].duplicated(keep=False)].sort_values(["tmdbId", "movieId"])
    print("tmdbIds shared: %d (%d movieIds, %d more than one per tmdbId)"
          % (shared["tmdbId"].nunique(), len(shared), len(shared) - shared["tmdbId"].nunique()))
    print("tmdbIds whose movieIds have different imdbIds: %d"
          % shared.groupby("tmdbId")["imdbId"].nunique().gt(1).sum())

    # the same tmdbIds are the ids duplicated in movies_metadata
    duplicated_in_metadata = set(metadata.loc[metadata["id"].duplicated(), "id"])
    print("of these tmdbIds, duplicated in movies_metadata: %d of the %d duplicated there"
          % (len(set(shared["tmdbId"]) & duplicated_in_metadata), len(duplicated_in_metadata)))
    lost = ratings[ratings.index.isin(shared["movieId"])].sum()
    print("ratings of these movieIds: %d (%s)" % (lost, percent(lost, ratings.sum())))

    # which of the movieIds sharing a tmdbId has the same imdb id as the film in movies_metadata
    films = metadata.drop_duplicates("id").set_index("id")
    shared = shared.assign(title=shared["tmdbId"].map(films["title"]),
                           imdb_metadata=shared["tmdbId"].map(films["imdb_id"]).str.removeprefix("tt"))
    same = shared["imdbId"] == shared["imdb_metadata"]
    print("movieIds with the same imdb id as movies_metadata: %d, with a different one: %d"
          % (same.sum(), (~same).sum()))
    print("tmdbIds where exactly one movieId has the same imdb id: %d"
          % same.groupby(shared["tmdbId"]).sum().eq(1).sum())
    report("examples", shared.assign(same_imdb=same), ["movieId", "imdbId", "tmdbId", "imdb_metadata", "same_imdb", "title"],
           n=8)


def check_link_with_metadata(links, ratings, metadata, raw_metadata):
    print_section("4. Link with movies_metadata.csv")
    filled = links[links["tmdbId"] != ""]
    films = metadata.drop_duplicates("id")

    not_found = filled[~filled["tmdbId"].isin(films["id"])]
    lost = ratings[ratings.index.isin(not_found["movieId"])].sum()
    print("tmdbIds not among the valid films of movies_metadata: %d, with %d ratings (%s)"
          % (len(not_found), lost, percent(lost, ratings.sum())))
    split = raw_metadata[is_truncated(raw_metadata) & raw_metadata["id"].isin(not_found["tmdbId"])]
    print("of these, films with a split row in movies_metadata: %d %s"
          % (len(split), split["original_title"].tolist()))
    print("valid films of movies_metadata without a row in links.csv: %d" % (~films["id"].isin(filled["tmdbId"])).sum())

    # links.imdbId has no "tt" prefix, movies_metadata.imdb_id has it
    joined = filled.merge(films[["id", "imdb_id", "title"]], left_on="tmdbId", right_on="id")
    joined["imdb_metadata"] = joined["imdb_id"].str.removeprefix("tt")
    different = joined[(joined["imdb_metadata"] != "") & (joined["imdb_metadata"] != joined["imdbId"])]
    shared = different["tmdbId"].isin(filled.loc[filled["tmdbId"].duplicated(), "tmdbId"])
    print("\nsame tmdbId but different imdb id in links and in movies_metadata: %d" % len(different))
    print("  of which on a tmdbId shared by more than one movieId: %d, on the other tmdbIds: %d"
          % (shared.sum(), (~shared).sum()))
    report("examples on not shared tmdbIds", different[~shared],
           ["movieId", "tmdbId", "imdbId", "imdb_metadata", "title"], n=8)


def check_link_with_ratings(links, ratings, name):
    print_section("5. Link between %s and the ratings" % name)
    print("rated movieIds: %d, not in %s: %d" % (len(ratings), name, (~ratings.index.isin(links["movieId"])).sum()))
    print("movieIds of %s without any rating: %d" % (name, (~links["movieId"].isin(ratings.index)).sum()))


def check_small(links, small):
    print_section("6. links_small.csv compared to links.csv")
    joined = small.merge(links, on="movieId", how="left", suffixes=("_small", ""), indicator=True)
    only_small = joined[joined["_merge"] == "left_only"]
    both = joined[joined["_merge"] == "both"]
    print("movieIds of links_small: %d, also in links: %d, only in links_small: %d"
          % (len(small), len(both), len(only_small)))
    print("same imdbId and tmdbId in both files: %d of %d"
          % (((both["imdbId_small"] == both["imdbId"]) & (both["tmdbId_small"] == both["tmdbId"])).sum(), len(both)))
    report("movieIds only in links_small", only_small, ["movieId", "imdbId_small", "tmdbId_small"], n=10)


def main():
    links = load_links("links.csv")
    small = load_links("links_small.csv")
    ratings = load_rated_movies("ratings.csv")
    ratings_small = load_rated_movies("ratings_small.csv")
    raw_metadata = load_metadata()
    metadata = raw_metadata[is_valid_row(raw_metadata)]

    check_structure(links, "links.csv")
    check_structure(small, "links_small.csv")
    check_missing_tmdb(links, ratings)
    check_shared_tmdb(links, ratings, metadata)
    check_link_with_metadata(links, ratings, metadata, raw_metadata)
    check_link_with_ratings(links, ratings, "links.csv")
    check_link_with_ratings(small, ratings_small, "links_small.csv")
    check_small(links, small)


if __name__ == "__main__":
    main()
