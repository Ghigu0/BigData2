"""
Logical consistency checks on movies_metadata.csv: values that are valid on their own
but contradict each other (e.g. a film that is only "Planned" but already has a revenue).
"""
from collections import defaultdict

from tabulate import tabulate

from load import DATASET_DATE, load_metadata, print_section, report, typed_metadata

NOT_RELEASED = ["Rumored", "Planned", "In Production", "Post Production", "Canceled"]


def check_status_vs_data(movies):
    print_section("1. Films not released yet, but with data of a released film")
    checks = {
        "revenue > 0": movies["revenue"] > 0,
        "vote_count > 0": movies["vote_count"] > 0,
        "vote_average > 0": movies["vote_average"] > 0,
        "released before %s" % DATASET_DATE.date(): movies["release_date"] <= DATASET_DATE,
        "runtime > 0": movies["runtime"] > 0,
    }
    table = []
    for status in NOT_RELEASED:
        in_status = movies["status"] == status
        table.append([status, in_status.sum()] + [(in_status & mask).sum() for mask in checks.values()])
    print(tabulate(table, headers=["status", "films"] + list(checks), tablefmt="simple"))

    not_released = movies[movies["status"].isin(NOT_RELEASED)]
    columns = ["id", "title", "status", "release_date", "revenue", "vote_count", "runtime"]
    report("not released, with revenue > 0", not_released[not_released["revenue"] > 0], columns)
    report("Planned or Canceled, with runtime > 0",
           not_released[not_released["status"].isin(["Planned", "Canceled"]) & (not_released["runtime"] > 0)],
           columns)


def check_released(movies):
    print_section("2. Released films without the data of a released film")
    released = movies[movies["status"] == "Released"]
    columns = ["id", "title", "release_date", "runtime", "vote_count"]
    report("Released without release_date", released[released["release_date"].isna()], columns)
    report("Released with release_date after %s" % DATASET_DATE.date(),
           released[released["release_date"] > DATASET_DATE].sort_values("release_date"), columns)
    report("Released with runtime 0 or missing",
           released[(released["runtime"] == 0) | released["runtime"].isna()], columns)


def check_empty_status(movies):
    print_section("3. Films without status")
    empty = movies[movies["status"] == ""]
    print("films: %d, of which with release_date: %d, with vote_count > 0: %d, with revenue > 0: %d"
          % (len(empty), empty["release_date"].notna().sum(), (empty["vote_count"] > 0).sum(),
             (empty["revenue"] > 0).sum()))
    report("status is empty", empty, ["id", "title", "release_date", "runtime", "vote_count", "revenue"])


def check_votes(movies):
    print_section("4. Votes")
    columns = ["id", "title", "vote_average", "vote_count"]
    report("vote_count = 0 but vote_average > 0",
           movies[(movies["vote_count"] == 0) & (movies["vote_average"] > 0)], columns)
    report("vote_count > 0 but vote_average = 0",
           movies[(movies["vote_count"] > 0) & (movies["vote_average"] == 0)], columns)
    few_votes = movies["vote_count"].between(1, 9)
    report("vote_average = 10 with less than 10 votes",
           movies[few_votes & (movies["vote_average"] == 10)], columns)
    report("vote_average < 1 with less than 10 votes",
           movies[few_votes & (movies["vote_average"] < 1)], columns)


def check_money(movies):
    print_section("5. Budget and revenue")
    columns = ["id", "title", "release_date", "budget", "revenue"]
    report("revenue > 0 but budget = 0", movies[(movies["revenue"] > 0) & (movies["budget"] == 0)], columns)
    report("budget > 0 but revenue = 0", movies[(movies["budget"] > 0) & (movies["revenue"] == 0)], columns)
    # tiny amounts are probably written in millions or thousands of dollars
    report("budget between 1 and 999 dollars",
           movies[movies["budget"].between(1, 999)].sort_values("budget"), columns)
    report("revenue between 1 and 999 dollars",
           movies[movies["revenue"].between(1, 999)].sort_values("revenue"), columns)

    both = movies[(movies["budget"] > 0) & (movies["revenue"] > 0)].copy()
    both["ratio"] = both["revenue"] / both["budget"]
    report("revenue more than 100 times the budget",
           both[both["ratio"] > 100].sort_values("ratio", ascending=False), columns + ["ratio"])
    report("revenue less than 1% of the budget",
           both[both["ratio"] < 0.01].sort_values("ratio"), columns + ["ratio"])


def check_languages(movies):
    print_section("6. Languages")
    spoken = movies["spoken_languages"].map(lambda languages: [l["iso_639_1"] for l in languages or []])
    columns = ["id", "title", "original_language", "spoken"]
    movies = movies.assign(spoken=spoken)
    has_spoken = spoken.map(len) > 0
    original_not_spoken = movies.apply(lambda m: m["original_language"] not in m["spoken"], axis=1)
    report("original_language not among spoken_languages", movies[has_spoken & original_not_spoken], columns)
    report("spoken_languages empty but original_language set",
           movies[~has_spoken & (movies["original_language"] != "")], columns)


def check_popularity(movies):
    print_section("7. Popularity")
    columns = ["id", "title", "popularity", "vote_count", "vote_average"]
    report("popularity = 0 with at least 50 votes",
           movies[(movies["popularity"] == 0) & (movies["vote_count"] >= 50)], columns)
    report("popularity > 10 with 0 votes",
           movies[(movies["popularity"] > 10) & (movies["vote_count"] == 0)], columns)


def check_flags(movies):
    print_section("8. adult and video flags")
    columns = ["id", "title", "status", "runtime", "vote_count", "genres"]
    adult = movies[movies["adult"] == "True"]
    video = movies[movies["video"] == "True"]
    report("adult = True", adult, columns, n=10)
    report("video = True", video, columns)
    print("video = True: status %s, runtime 0: %d"
          % (video["status"].value_counts().to_dict(), (video["runtime"] == 0).sum()))
    report("adult = True and video = True", movies[(movies["adult"] == "True") & (movies["video"] == "True")], columns)


def check_collections(movies):
    print_section("9. Collections")
    names = defaultdict(set)
    films = defaultdict(set)
    for movie_id, collection in zip(movies["id"], movies["belongs_to_collection"]):
        if collection:
            names[collection["id"]].add(collection["name"])
            films[collection["id"]].add(movie_id)
    print("collections: %d, with more than one name: %d, with a single film in the dataset: %d"
          % (len(names), sum(1 for n in names.values() if len(n) > 1), sum(1 for f in films.values() if len(f) == 1)))


def main():
    movies = typed_metadata(load_metadata()).drop_duplicates("id")
    print("valid films (numeric id, all fields, duplicates removed): %d" % len(movies))
    check_status_vs_data(movies)
    check_released(movies)
    check_empty_status(movies)
    check_votes(movies)
    check_money(movies)
    check_languages(movies)
    check_popularity(movies)
    check_flags(movies)
    check_collections(movies)


if __name__ == "__main__":
    main()
