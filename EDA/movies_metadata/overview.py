"""
Summary of what to expect from movies_metadata.csv: how the films are distributed
over the main fields and how complete each field is.
"""
from collections import Counter

import pandas as pd
from tabulate import tabulate

from load import is_valid_row, load_metadata, print_section, typed_metadata

# overviews used by TMDB when the plot is unknown
PLACEHOLDER_OVERVIEWS = {"No overview found.", "No Overview", "No movie overview available.", "No overview yet."}


def percent(part, total):
    return "%.1f%%" % (100 * part / total) if total else "-"


def print_counts(counts, total, label, n=None):
    """Prints a table value -> films, % of total, for a Series or Counter of counts"""
    counts = pd.Series(counts).sort_values(ascending=False) if isinstance(counts, Counter) else counts
    rows = [[value, count, percent(count, total)] for value, count in counts.head(n).items()]
    print(tabulate(rows, headers=[label, "films", "%"], tablefmt="simple"))


def print_buckets(values, bins, labels, total, label):
    """Prints how many films fall in each interval [bins[i], bins[i+1])"""
    buckets = pd.cut(values, bins=bins, labels=labels, right=False).value_counts(sort=False)
    print_counts(buckets, total, label)


def count_nested(column, key="name"):
    """Counts how many films contain each value of a nested list field"""
    return Counter(item[key] for items in column for item in items or [])


def summary_dataset(raw, movies):
    print_section("1. Dataset")
    valid = is_valid_row(raw)
    print(tabulate([
        ["rows in the CSV", len(raw)],
        ["malformed rows (records split in two)", (~valid).sum()],
        ["duplicated rows (same id)", valid.sum() - len(movies)],
        ["distinct valid films", len(movies)],
    ], tablefmt="simple"))


def summary_status(movies):
    print_section("2. Status")
    print_counts(movies["status"].replace("", "(empty)").value_counts(), len(movies), "status")


def summary_completeness(movies):
    print_section("3. Completeness: films with a known value")
    total = len(movies)
    overview = movies["overview"].str.strip()
    known = {
        "title": movies["title"] != "",
        "release_date": movies["release_date"].notna(),
        "runtime (> 0)": movies["runtime"] > 0,
        "genres": movies["genres"].map(bool),
        "overview (no placeholder)": (overview != "") & ~overview.isin(PLACEHOLDER_OVERVIEWS),
        "poster_path": movies["poster_path"] != "",
        "imdb_id": movies["imdb_id"] != "",
        "spoken_languages": movies["spoken_languages"].map(bool),
        "production_countries": movies["production_countries"].map(bool),
        "production_companies": movies["production_companies"].map(bool),
        "tagline": movies["tagline"] != "",
        "homepage": movies["homepage"] != "",
        "budget (> 0)": movies["budget"] > 0,
        "revenue (> 0)": movies["revenue"] > 0,
        "budget and revenue (> 0)": (movies["budget"] > 0) & (movies["revenue"] > 0),
        "belongs_to_collection": movies["belongs_to_collection"].map(bool),
        "at least one vote": movies["vote_count"] > 0,
    }
    rows = [[field, mask.sum(), percent(mask.sum(), total)] for field, mask in known.items()]
    print(tabulate(rows, headers=["field", "films", "%"], tablefmt="simple"))


def summary_release(movies):
    print_section("4. Release date by decade")
    decade = (movies["release_date"].dt.year // 10 * 10).astype("Int64").astype(str) + "s"
    decade = decade.where(movies["release_date"].notna(), "(missing)")
    print_counts(decade.value_counts().sort_index(), len(movies), "decade")


def summary_genres(movies):
    print_section("5. Genres")
    total = len(movies)
    print_counts(count_nested(movies["genres"]), total, "genre")
    print("\nGenres per film:")
    per_film = movies["genres"].map(len).clip(upper=4).replace(4, "4+")
    print_counts(per_film.value_counts().sort_index(key=lambda i: i.astype(str)), total, "genres")


def summary_languages(movies):
    print_section("6. Languages")
    total = len(movies)
    print("Original language (top 10):")
    print_counts(movies["original_language"].replace("", "(empty)").value_counts(), total, "language", n=10)

    spoken = movies["spoken_languages"].map(lambda languages: {l["iso_639_1"] for l in languages or []})
    has_spoken = spoken.map(bool)
    not_spoken = has_spoken & pd.Series([o not in s for o, s in zip(movies["original_language"], spoken)],
                                        index=movies.index)
    print()
    print(tabulate([
        ["spoken_languages empty", (~has_spoken).sum(), percent((~has_spoken).sum(), total)],
        ["original language not among the spoken ones", not_spoken.sum(), percent(not_spoken.sum(), total)],
        ["more than one spoken language", (spoken.map(len) > 1).sum(), percent((spoken.map(len) > 1).sum(), total)],
    ], headers=["", "films", "%"], tablefmt="simple"))

    # some language codes never come with a name (e.g. {'iso_639_1': 'yi', 'name': ''})
    codes = {l["iso_639_1"] for languages in movies["spoken_languages"] for l in languages or []}
    named = {l["iso_639_1"] for languages in movies["spoken_languages"] for l in languages or [] if l["name"].strip()}
    unnamed = codes - named
    with_unnamed = spoken.map(lambda s: bool(s & unnamed))
    only_unnamed = spoken.map(lambda s: bool(s) and s <= unnamed)
    print()
    print(tabulate([
        ["spoken language codes", len(codes), "100.0%"],
        ["codes always with a name", len(named), percent(len(named), len(codes))],
        ["codes never with a name", len(unnamed), percent(len(unnamed), len(codes))],
    ], headers=["", "languages", "%"], tablefmt="simple"))
    print()
    print(tabulate([
        ["at least one spoken language without a name", with_unnamed.sum(), percent(with_unnamed.sum(), total)],
        ["only spoken languages without a name", only_unnamed.sum(), percent(only_unnamed.sum(), total)],
    ], headers=["", "films", "%"], tablefmt="simple"))


def summary_production(movies):
    print_section("7. Production")
    total = len(movies)
    print("Production countries (top 10):")
    print_counts(count_nested(movies["production_countries"]), total, "country", n=10)
    print("\nProduction companies (top 10):")
    print_counts(count_nested(movies["production_companies"]), total, "company", n=10)
    print("\nCountries per film:")
    per_film = movies["production_countries"].map(len).clip(upper=3).replace(3, "3+")
    print_counts(per_film.value_counts().sort_index(key=lambda i: i.astype(str)), total, "countries")


def summary_votes(movies):
    print_section("8. Votes")
    total = len(movies)
    print("vote_count:")
    print_buckets(movies["vote_count"], [0, 1, 10, 100, 1000, float("inf")],
                  ["0", "1-9", "10-99", "100-999", "1000+"], total, "votes")

    reliable = movies[movies["vote_count"] >= 10]["vote_average"]
    print("\nvote_average of the %d films with at least 10 votes: median %.1f, 25%% %.1f, 75%% %.1f"
          % (len(reliable), reliable.median(), reliable.quantile(0.25), reliable.quantile(0.75)))
    extreme = movies["vote_count"].between(1, 9) & movies["vote_average"].isin([0, 10])
    print("vote_average exactly 0 or 10 with less than 10 votes: %d films (%s)"
          % (extreme.sum(), percent(extreme.sum(), total)))


def summary_money(movies):
    print_section("9. Budget and revenue (only known values, > 0)")
    rows = []
    for column in ["budget", "revenue"]:
        known = movies[column][movies[column] > 0]
        tiny = (known < 1000).sum()
        rows.append([column, len(known), percent(len(known), len(movies)), "{:,.0f}".format(known.median()),
                     "{:,.0f}".format(known.max()), tiny, percent(tiny, len(known))])
    print(tabulate(rows, headers=["", "films", "% of all", "median $", "max $", "< $1000", "% of known"],
                   tablefmt="simple"))


def summary_runtime(movies):
    print_section("10. Runtime")
    runtime = movies["runtime"].fillna(0)
    print_buckets(runtime, [0, 1, 40, 70, 120, 180, float("inf")],
                  ["0 or missing", "1-39 (short)", "40-69", "70-119", "120-179", "180+"], len(movies), "minutes")


def summary_other(movies):
    print_section("11. Collections and flags")
    total = len(movies)
    collection = movies["belongs_to_collection"].map(lambda c: c["name"] if c else None)
    print(tabulate([
        ["in a collection", collection.notna().sum(), percent(collection.notna().sum(), total)],
        ["adult = True", (movies["adult"] == "True").sum(), percent((movies["adult"] == "True").sum(), total)],
        ["video = True", (movies["video"] == "True").sum(), percent((movies["video"] == "True").sum(), total)],
    ], headers=["", "films", "%"], tablefmt="simple"))
    print("\nLargest collections:")
    print_counts(collection.value_counts(), total, "collection", n=10)


def main():
    raw = load_metadata()
    movies = typed_metadata(raw).drop_duplicates("id")
    summary_dataset(raw, movies)
    summary_status(movies)
    summary_completeness(movies)
    summary_release(movies)
    summary_genres(movies)
    summary_languages(movies)
    summary_production(movies)
    summary_votes(movies)
    summary_money(movies)
    summary_runtime(movies)
    summary_other(movies)


if __name__ == "__main__":
    main()
