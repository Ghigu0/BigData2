"""
Checks on ratings.csv (and ratings_small.csv): structure, values, duplicates, users and movies,
half-star ratings over time, ratings given before the release of the film, link with the films
and ratings_small compared to ratings.
"""
import sys
from pathlib import Path

import pandas as pd
from tabulate import tabulate

# reuse the helpers written for movies_metadata
sys.path.append(str(Path(__file__).resolve().parents[1] / "movies_metadata"))
from load import is_valid_row, load_metadata, print_section, report

DATA = Path(__file__).resolve().parents[2] / "data"


def percent(part, total):
    return "%.2f%%" % (100 * part / total) if total else "-"


def load_ratings(name):
    """pandas chooses the type of each column: if a value were not a number the column would not be numeric"""
    ratings = pd.read_csv(DATA / name)
    ratings["date"] = pd.to_datetime(ratings["timestamp"], unit="s")
    return ratings


def load_films():
    """movieId -> tmdbId, title, imdb id and release date of the film it is linked to"""
    links = pd.read_csv(DATA / "links.csv", dtype=str, keep_default_na=False)
    metadata = load_metadata()
    films = metadata[is_valid_row(metadata)].drop_duplicates("id").set_index("id")
    links = links.assign(movieId=links["movieId"].astype(int),
                         title=links["tmdbId"].map(films["title"]),
                         imdb_metadata=links["tmdbId"].map(films["imdb_id"]).str.removeprefix("tt"),
                         release=pd.to_datetime(links["tmdbId"].map(films["release_date"]), format="%Y-%m-%d",
                                                errors="coerce"))
    return links.set_index("movieId")


def check_structure(ratings, name):
    print_section("1. Structure of %s" % name)
    content = (DATA / name).read_bytes()
    print("rows: %d, columns: %s" % (len(ratings), list(ratings.columns[:4])))
    print("types chosen by pandas: %s" % {c: str(t) for c, t in ratings.dtypes.iloc[:4].items()})
    print("missing values: %s" % ratings.iloc[:, :4].isna().sum().to_dict())
    print("lines ending with \\r\\n (Windows): %d of %d" % (content.count(b"\r\n"), content.count(b"\n")))


def check_values(ratings):
    print_section("2. Values")
    counts = ratings["rating"].value_counts().sort_index()
    print(tabulate([[r, n, percent(n, len(ratings))] for r, n in counts.items()],
                   headers=["rating", "ratings", "%"], tablefmt="simple"))
    print("mean rating: %.3f" % ratings["rating"].mean())
    print("timestamps from %s to %s" % (ratings["date"].min(), ratings["date"].max()))


def check_duplicates(ratings):
    print_section("3. Duplicates")
    print("identical rows: %d" % ratings.duplicated(["userId", "movieId", "rating", "timestamp"]).sum())
    print("same user rating the same movie more than once: %d" % ratings.duplicated(["userId", "movieId"]).sum())


def check_users_and_movies(ratings):
    print_section("4. Users and movies")
    per_user = ratings.groupby("userId").size()
    per_movie = ratings.groupby("movieId").size()
    print("users: %d (ids from %d to %d), movies: %d"
          % (len(per_user), per_user.index.min(), per_user.index.max(), len(per_movie)))
    table = []
    for label, counts in [("ratings per user", per_user), ("ratings per movie", per_movie)]:
        table.append([label, counts.min(), counts.median(), "%.1f" % counts.mean(), counts.max(),
                      "%d (%s)" % ((counts == 1).sum(), percent((counts == 1).sum(), len(counts))),
                      "%d (%s)" % ((counts < 10).sum(), percent((counts < 10).sum(), len(counts)))])
    print(tabulate(table, headers=["", "min", "median", "mean", "max", "only 1", "less than 10"], tablefmt="simple"))

    print("\nusers with the most ratings: %s" % per_user.nlargest(5).to_dict())
    stats = ratings.groupby("userId")["rating"].agg(["nunique", "size", "first"])
    same = stats[(stats["nunique"] == 1) & (stats["size"] >= 20)]
    print("users with at least 20 ratings, all with the same value: %d, values: %s"
          % (len(same), same["first"].value_counts().sort_index().to_dict()))


def check_half_stars(ratings):
    print_section("5. Half-star ratings over time")
    half = ratings["rating"] % 1 == 0.5
    by_year = pd.DataFrame({"ratings": ratings.groupby(ratings["date"].dt.year).size(),
                            "half": half.groupby(ratings["date"].dt.year).sum()})
    print(tabulate([[y, int(r["ratings"]), percent(r["half"], r["ratings"])] for y, r in by_year.iterrows()],
                   headers=["year", "ratings", "half stars"], tablefmt="simple"))
    print("first half-star rating: %s" % ratings.loc[half, "date"].min())


def check_before_release(ratings, films):
    print_section("6. Ratings given before the release date of the film")
    release = ratings["movieId"].map(films["release"])
    before = ratings[ratings["date"] < release].assign(release=release)
    before["days"] = (before["release"] - before["date"]).dt.days
    print("ratings before the release date: %d (%s), movies: %d, users: %d"
          % (len(before), percent(len(before), len(ratings)), before["movieId"].nunique(), before["userId"].nunique()))
    groups = pd.cut(before["days"], [0, 8, 31, 366, float("inf")], right=False,
                    labels=["0-7", "8-30", "31-365", "more than 365"]).value_counts(sort=False)
    print(tabulate([[label, n, percent(n, len(before))] for label, n in groups.items()],
                   headers=["days before", "ratings", "%"], tablefmt="simple"))

    # a film rated years before its release is often linked to the wrong film in links.csv:
    # check if the imdb id of links and of movies_metadata are different for these movies
    far = before[before["days"] > 365]
    movies = far.groupby("movieId").agg(ratings=("days", "size"), first_rating=("date", "min"),
                                        release=("release", "first"))
    movies = movies.join(films[["tmdbId", "title", "imdbId", "imdb_metadata"]])
    movies["same_imdb"] = movies["imdbId"] == movies["imdb_metadata"]
    print("\nmovies rated more than a year before their release: %d (%d ratings)" % (len(movies), len(far)))
    print("of these, with a different imdb id in links.csv and movies_metadata: %d (%d ratings)"
          % ((~movies["same_imdb"]).sum(), movies.loc[~movies["same_imdb"], "ratings"].sum()))
    report("movies with the most ratings more than a year before release",
           movies.sort_values("ratings", ascending=False).reset_index(),
           ["movieId", "title", "first_rating", "release", "ratings", "same_imdb"], n=8)


def check_link_with_films(ratings, films):
    print_section("7. Ratings that can be linked to a film of movies_metadata")
    tmdb = ratings["movieId"].map(films["tmdbId"])
    no_tmdb = tmdb == ""
    no_film = ~no_tmdb & ratings["movieId"].map(films["title"]).isna()
    shared = films.loc[films["tmdbId"] != "", "tmdbId"]
    wrong = films["imdbId"] != films["imdb_metadata"]
    shared_wrong = ratings["movieId"].isin(shared[shared.duplicated(keep=False) & wrong].index)
    total = len(ratings)
    groups = {
        "movieId without tmdbId": no_tmdb,
        "tmdbId not in movies_metadata": no_film,
        "movieId on a shared tmdbId, with the wrong imdb id": shared_wrong,
        "linkable": ~no_tmdb & ~no_film & ~shared_wrong,
    }
    print(tabulate([[label, int(mask.sum()), percent(mask.sum(), total)] for label, mask in groups.items()],
                   headers=["ratings: %d" % total, "ratings", "%"], tablefmt="simple"))


def check_small(ratings, small):
    print_section("8. ratings_small.csv compared to ratings.csv")
    print("ratings_small: %d ratings, %d users, %d movies, from %s to %s"
          % (len(small), small["userId"].nunique(), small["movieId"].nunique(), small["date"].min(), small["date"].max()))
    print("mean rating: small %.3f, full %.3f" % (small["rating"].mean(), ratings["rating"].mean()))

    columns = ["userId", "movieId", "rating", "timestamp"]
    identical = small.merge(ratings[columns], on=columns)
    print("\nrows of small identical in full (same userId, movieId, rating, timestamp): %d" % len(identical))

    # look for the same rating given in the same second to the same movie, by any user
    same = small[columns].merge(ratings[columns], on=["movieId", "rating", "timestamp"], suffixes=("_small", "_full"))
    found = same.drop_duplicates(["userId_small", "movieId", "timestamp"])
    print("rows of small found in full with the same movieId, rating and timestamp but another userId: %d (%s)"
          % (len(found), percent(len(found), len(small))))

    # if the rows are the same, each user of small should correspond to one user of full
    pairs = same.groupby(["userId_small", "userId_full"]).size().rename("rows").reset_index()
    best = pairs.sort_values("rows", ascending=False).drop_duplicates("userId_small")
    rows_per_user = small.groupby("userId").size()
    best["share"] = best["rows"] / best["userId_small"].map(rows_per_user)
    print("users of small: %d, for which one user of full has at least 90%% of their ratings: %d"
          % (small["userId"].nunique(), (best["share"] >= 0.9).sum()))
    report("examples of corresponding users", best.sort_values("userId_small"),
           ["userId_small", "userId_full", "rows", "share"])


def main():
    ratings = load_ratings("ratings.csv")
    small = load_ratings("ratings_small.csv")
    films = load_films()

    check_structure(ratings, "ratings.csv")
    check_structure(small, "ratings_small.csv")
    check_values(ratings)
    check_duplicates(ratings)
    check_users_and_movies(ratings)
    check_half_stars(ratings)
    check_before_release(ratings, films)
    check_link_with_films(ratings, films)
    check_small(ratings, small)


if __name__ == "__main__":
    main()
