"""
Checks on credits.csv: structure, duplicated films, missing cast/crew, consistency of the
cast and crew objects, people (ids, names, gender), link with movies_metadata.csv and a summary.
"""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from tabulate import tabulate

# reuse the helpers written for movies_metadata
sys.path.append(str(Path(__file__).resolve().parents[1] / "movies_metadata"))
from load import is_truncated, is_valid_row, load_metadata, parse_literal, print_section, report, to_number

CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "credits.csv"

# TMDB encodes the gender of a person as a number
GENDERS = {0: "0 (not set)", 1: "1 (female)", 2: "2 (male)"}


def percent(part, total):
    return "%.1f%%" % (100 * part / total) if total else "-"


def load_credits():
    """Every column as a string, plus cast and crew parsed into lists of objects"""
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
    df["cast_parsed"] = df["cast"].map(parse_literal)
    df["crew_parsed"] = df["crew"].map(parse_literal)
    return df


def flatten(films, column):
    """One row per object of the cast or crew lists, with the id of the film it belongs to"""
    rows = [dict(o, film=int(film)) for film, objects in zip(films["id"], films[column]) for o in objects or []]
    return pd.DataFrame(rows)


def check_structure(df):
    print_section("1. Structure")
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        csv.field_size_limit(sys.maxsize)
        reader = csv.reader(f)
        header = next(reader)
        fields = Counter(len(record) for record in reader)
    print("rows: %d, columns: %s" % (len(df), header))
    print("records by number of fields in the raw file: %s" % dict(fields))
    print("id not a number: %d" % (~df["id"].str.fullmatch(r"\d+")).sum())
    for column in ["cast", "crew"]:
        parsed = df[column + "_parsed"]
        objects = [o for objects in parsed for o in objects or []]
        types = defaultdict(Counter)
        for o in objects:
            for key, value in o.items():
                types[key][type(value).__name__] += 1
        print("\n%s: empty string %d, not parsable %d, not a list %d, objects %d"
              % (column, (df[column].str.strip() == "").sum(), parsed.isna().sum(),
                 parsed.map(lambda v: v is not None and not isinstance(v, list)).sum(), len(objects)))
        print("  keys of the objects: %s" % dict(Counter(tuple(sorted(o)) for o in objects)))
        print("  types: %s" % {key: dict(t) for key, t in types.items()})


def check_duplicated_films(df, metadata):
    print_section("2. Duplicated film ids")
    duplicated = df[df["id"].duplicated(keep=False)]
    copies = duplicated["id"].value_counts()
    identical = duplicated.groupby("id")[["cast", "crew"]].nunique().max(axis=1).eq(1)
    print("ids appearing more than once: %d (%d rows), extra rows to drop keeping one copy per id: %d"
          % (len(copies), len(duplicated), len(duplicated) - len(copies)))
    print("copies per id: %s" % dict(sorted(Counter(copies).items())))
    print("ids whose copies are identical: %d, ids whose copies differ: %d" % (identical.sum(), (~identical).sum()))

    # compare the copies that differ object by object, matching the objects by credit_id
    table = []
    for film_id in identical[~identical].index:
        group = duplicated[duplicated["id"] == film_id]
        for column in ["cast", "crew"]:
            versions = [{o["credit_id"]: o for o in objects} for objects in group[column + "_parsed"]]
            same_credits = all(set(v) == set(versions[0]) for v in versions)
            fields = sorted({key for v in versions[1:] for credit, o in v.items()
                             for key in o if credit in versions[0] and o[key] != versions[0][credit][key]})
            same_order = len(set(group[column])) == 1 or all(
                [o["credit_id"] for o in objects] == [o["credit_id"] for o in group[column + "_parsed"].iloc[0]]
                for objects in group[column + "_parsed"])
            table.append([film_id, column, same_credits, ", ".join(fields) or "-", same_order])
    print("\nhow the copies that differ are different:")
    print(tabulate(table, headers=["id", "list", "same credit_ids", "fields with a different value", "same order"],
                   tablefmt="simple"))

    metadata_copies = metadata["id"].value_counts()
    also_in_metadata = copies.index.isin(metadata_copies[metadata_copies > 1].index)
    print("\nduplicated also in movies_metadata: %d, duplicated only here: %d"
          % (also_in_metadata.sum(), (~also_in_metadata).sum()))


def check_missing(films, movies):
    print_section("3. Films without cast or crew (one copy per film)")
    no_cast = films["cast"] == "[]"
    no_crew = films["crew"] == "[]"
    total = len(films)
    print(tabulate([
        ["empty cast", no_cast.sum(), percent(no_cast.sum(), total)],
        ["empty crew", no_crew.sum(), percent(no_crew.sum(), total)],
        ["both empty", (no_cast & no_crew).sum(), percent((no_cast & no_crew).sum(), total)],
    ], headers=["films: %d" % total, "films", "%"], tablefmt="simple"))

    joined = movies.set_index("id").join(
        films.assign(id=films["id"].astype(int), no_cast=no_cast, no_crew=no_crew).set_index("id")[["no_cast", "no_crew"]],
        how="inner")
    groups = pd.cut(joined["vote_count"], [0, 1, 10, 100, 1000, float("inf")], right=False,
                    labels=["0", "1-9", "10-99", "100-999", "1000+"])
    table = [[label, len(g), percent(g["no_cast"].sum(), len(g)), percent(g["no_crew"].sum(), len(g))]
             for label, g in joined.groupby(groups, observed=True)]
    print("\nfilms with empty cast / crew by number of votes:")
    print(tabulate(table, headers=["votes", "films", "empty cast", "empty crew"], tablefmt="simple"))


def check_cast(films, cast):
    print_section("4. Cast")
    total = len(cast)
    print("cast entries: %d" % total)
    print("character empty: %d (%s)" % ((cast["character"].str.strip() == "").sum(),
                                        percent((cast["character"].str.strip() == "").sum(), total)))
    print("profile_path missing (None): %d (%s)" % (cast["profile_path"].isna().sum(),
                                                   percent(cast["profile_path"].isna().sum(), total)))
    print("gender: %s" % {GENDERS[g]: "%d (%s)" % (n, percent(n, total))
                          for g, n in cast["gender"].value_counts().sort_index().items()})

    # the same person more than once in the cast of the same film
    per_person = cast.groupby(["film", "id"]).agg(entries=("credit_id", "size"), characters=("character", "nunique"))
    twice = per_person[per_person["entries"] > 1]
    same_character = twice[twice["characters"] < twice["entries"]]
    print("\nsame person more than once in the same film: %d films, %d people"
          % (twice.index.get_level_values("film").nunique(), len(twice)))
    print("  of which playing different characters: %d people, with the same character repeated: %d people"
          % (len(twice) - len(same_character), len(same_character)))
    examples = cast.set_index(["film", "id"]).loc[same_character.index].reset_index()
    report("same person with the same character in the same film", examples, ["film", "id", "name", "character"])

    cast_id = cast.groupby("film")["cast_id"].apply(lambda ids: ids.duplicated().any())
    print("\nfilms with the same cast_id used twice: %d" % cast_id.sum())

    # order is the position of the actor in the credits: we expect 0, 1, 2, ... without repetitions
    orders = cast.groupby("film")["order"].agg(list)
    repeated = orders.map(lambda o: len(set(o)) != len(o))
    first = orders.map(min)
    gaps = orders.map(lambda o: len(set(o)) == len(o) and sorted(o) != list(range(min(o), min(o) + len(o))))
    print("\norder (films with a cast: %d):" % len(orders))
    print("  same order value used by more than one actor: %d films" % repeated.sum())
    print("  first order value is not 0: %d films, first value found: %s"
          % ((first != 0).sum(), dict(Counter(first[first != 0].clip(upper=5).replace(5, "5+")).most_common())))
    print("  no repetitions but missing numbers (e.g. 0, 1, 3): %d films" % gaps.sum())
    film = repeated[repeated].index[0]
    report("example of repeated order (film %d)" % film,
           cast[cast["film"] == film].sort_values("order"), ["order", "name", "character"], n=6)


def check_crew(films, crew):
    print_section("5. Crew")
    total = len(crew)
    print("crew entries: %d" % total)
    print("profile_path missing (None): %d (%s)" % (crew["profile_path"].isna().sum(),
                                                   percent(crew["profile_path"].isna().sum(), total)))
    print("gender: %s" % {GENDERS[g]: "%d (%s)" % (n, percent(n, total))
                          for g, n in crew["gender"].value_counts().sort_index().items()})

    print("\ndepartments:")
    departments = crew["department"].value_counts()
    print(tabulate([[d, n, percent(n, total)] for d, n in departments.items()],
                   headers=["department", "entries", "%"], tablefmt="simple"))
    print("\njobs in the 'Actors' department: %s" % crew.loc[crew["department"] == "Actors", "job"].value_counts().to_dict())

    departments_of_job = crew.groupby("job")["department"].unique()
    many = departments_of_job[departments_of_job.map(len) > 1]
    print("\ndistinct jobs: %d, jobs found in more than one department: %d" % (len(departments_of_job), len(many)))
    for job, deps in many.items():
        print("  %-30s %s" % (job, sorted(deps)))
    print("departments of the job 'Director': %s" % crew.loc[crew["job"] == "Director", "department"].value_counts().to_dict())

    same_job = crew.duplicated(["film", "id", "job"]).sum()
    print("\nsame person with the same job twice in the same film: %d" % same_job)

    directors = crew[crew["job"] == "Director"].groupby("film").size()
    per_film = films["id"].astype(int).map(directors).fillna(0).astype(int)
    no_crew = films["crew"] == "[]"
    print("\nfilms without a Director: %d, of which with an empty crew: %d, with a crew but no Director: %d"
          % ((per_film == 0).sum(), ((per_film == 0) & no_crew).sum(), ((per_film == 0) & ~no_crew).sum()))
    groups = per_film.clip(upper=3).replace(3, "3+").value_counts().sort_index(key=lambda i: i.astype(str))
    print(tabulate([[n, f, percent(f, len(films))] for n, f in groups.items()],
                   headers=["directors", "films", "%"], tablefmt="simple"))


def check_people(cast, crew):
    print_section("6. People (cast and crew together)")
    people = pd.concat([cast[["id", "name", "gender", "credit_id"]], crew[["id", "name", "gender", "credit_id"]]])
    print("distinct person ids: %d, credit_id repeated: %d" % (people["id"].nunique(), people["credit_id"].duplicated().sum()))

    names = people.groupby("id")["name"].unique()
    many_names = names[names.map(len) > 1]
    print("\nperson ids with more than one name: %d" % len(many_names))
    for person, n in many_names.items():
        print("  %-8d %s" % (person, list(n)))

    genders = people.groupby("id")["gender"].agg(lambda g: dict(Counter(g)))
    many_genders = genders[genders.map(len) > 1]
    print("\nperson ids with more than one gender: %d, of which with both 1 and 2: %d"
          % (len(many_genders), many_genders.map(lambda g: 1 in g and 2 in g).sum()))
    print(tabulate([[p, names[p][0], {GENDERS[k]: v for k, v in g.items()}] for p, g in many_genders.items()],
                   headers=["id", "name", "entries by gender"], tablefmt="simple"))

    ids_of_name = people.groupby("name")["id"].nunique()
    homonyms = ids_of_name[ids_of_name > 1].sort_values(ascending=False)
    print("\nnames shared by more than one person id: %d, e.g. %s" % (len(homonyms), homonyms.head(5).to_dict()))

    distinct = people.drop_duplicates(["id", "name"])
    spaced = distinct[distinct["name"] != distinct["name"].str.strip()]
    print("\nnames with spaces at the start or end: %d (with \\xa0: %d, with a tab: %d), e.g. %s"
          % (len(spaced), spaced["name"].str.contains("\xa0").sum(), spaced["name"].str.contains("\t").sum(),
             [repr(n) for n in spaced["name"].head(4)]))
    clean = distinct.assign(clean=distinct["name"].str.strip())
    clash = clean[clean["clean"].isin(spaced["name"].str.strip())].groupby("clean")["id"].nunique()
    print("of these, names that once cleaned match a different person id: %d" % (clash > 1).sum())


def check_link_with_metadata(df, metadata):
    print_section("7. Link with movies_metadata.csv")
    valid = metadata[is_valid_row(metadata)]
    valid_ids = set(valid["id"].astype(int))
    credit_ids = set(df["id"].astype(int))

    not_valid = credit_ids - valid_ids
    print("credits ids not among the valid films of movies_metadata: %d" % len(not_valid))
    rows = metadata[metadata["id"].isin([str(i) for i in not_valid])]
    report("their row in movies_metadata", rows.assign(truncated=is_truncated(rows)), ["id", "original_title", "truncated"])

    without = valid[~valid["id"].astype(int).isin(credit_ids)]
    report("valid films of movies_metadata without a row in credits.csv", without,
           ["id", "title", "release_date", "vote_count"])


def summary(films, cast, crew):
    print_section("8. Summary")
    for column, label in [("cast_parsed", "cast"), ("crew_parsed", "crew")]:
        size = films[column].map(len)
        print("%s size per film: mean %.1f, median %.0f, max %d" % (label, size.mean(), size.median(), size.max()))

    films_of_actor = cast.drop_duplicates(["film", "id"]).groupby(["id", "name"]).size().nlargest(10)
    print("\nactors in the most films:")
    print(tabulate([[i, n, f] for (i, n), f in films_of_actor.items()], headers=["id", "name", "films"], tablefmt="simple"))

    directors = crew[crew["job"] == "Director"].drop_duplicates(["film", "id"]).groupby(["id", "name"]).size().nlargest(10)
    print("\ndirectors of the most films:")
    print(tabulate([[i, n, f] for (i, n), f in directors.items()], headers=["id", "name", "films"], tablefmt="simple"))


def main():
    df = load_credits()
    films = df.drop_duplicates("id")
    cast = flatten(films, "cast_parsed")
    crew = flatten(films, "crew_parsed")
    metadata = load_metadata()
    valid = metadata[is_valid_row(metadata)]
    movies = valid.assign(id=valid["id"].astype(int), vote_count=to_number(valid["vote_count"])).drop_duplicates("id")

    check_structure(df)
    check_duplicated_films(df, valid)
    check_missing(films, movies)
    check_cast(films, cast)
    check_crew(films, crew)
    check_people(cast, crew)
    check_link_with_metadata(df, metadata)
    summary(films, cast, crew)


if __name__ == "__main__":
    main()
