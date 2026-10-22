"""
Checks on keywords.csv: structure, duplicated films, missing keywords, consistency of
keyword ids and names, link with movies_metadata.csv and a summary of the distribution.
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

CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "keywords.csv"


def percent(part, total):
    return "%.1f%%" % (100 * part / total) if total else "-"


def load_keywords():
    """Every column as a string, plus the keywords column parsed into a list of {id, name}"""
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
    df["parsed"] = df["keywords"].map(parse_literal)
    return df


def keyword_objects(df):
    """All the {id, name} objects of all the rows, one copy per film"""
    return [k for keywords in df.drop_duplicates("id")["parsed"] for k in keywords or []]


def check_structure(df):
    print_section("1. Structure")
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        fields = Counter(len(record) for record in reader)
    print("rows: %d, columns: %s" % (len(df), header))
    print("records by number of fields in the raw file: %s" % dict(fields))
    print("id not a number: %d" % (~df["id"].str.fullmatch(r"\d+")).sum())
    print("keywords empty string: %d" % (df["keywords"].str.strip() == "").sum())


def check_nested(df):
    print_section("2. keywords field")
    parsed = df["parsed"]
    print("not parsable with ast.literal_eval: %d" % parsed.isna().sum())
    print("not a list: %d" % parsed.map(lambda v: v is not None and not isinstance(v, list)).sum())
    objects = [k for keywords in parsed for k in keywords or []]
    print("objects: %d" % len(objects))
    print("keys of the objects: %s" % dict(Counter(tuple(sorted(k)) for k in objects)))
    print("types of id: %s, types of name: %s"
          % (dict(Counter(type(k["id"]).__name__ for k in objects)),
             dict(Counter(type(k["name"]).__name__ for k in objects))))


def check_duplicated_films(df, metadata):
    print_section("3. Duplicated film ids")
    duplicated = df[df["id"].duplicated(keep=False)]
    copies = duplicated["id"].value_counts()
    identical = duplicated.groupby("id")["keywords"].nunique().eq(1)
    print("ids appearing more than once: %d (%d rows), extra rows to drop keeping one copy per id: %d"
          % (len(copies), len(duplicated), len(duplicated) - len(copies)))
    print("copies per id: %s" % dict(sorted(Counter(copies).items())))
    print("ids whose copies are identical: %d, ids whose copies differ: %d" % (identical.sum(), (~identical).sum()))

    # are these the same films duplicated in movies_metadata?
    metadata_copies = metadata["id"].value_counts()
    also_in_metadata = copies.index.isin(metadata_copies[metadata_copies > 1].index)
    print("duplicated also in movies_metadata: %d, duplicated only here: %d"
          % (also_in_metadata.sum(), (~also_in_metadata).sum()))
    report("ids with more than 2 copies",
           duplicated[duplicated["id"].isin(copies[copies > 2].index)].sort_values("id"), ["id", "keywords"], width=60)


def check_missing(df, movies):
    print_section("4. Films without keywords")
    films = df.drop_duplicates("id")
    empty = films["parsed"].map(lambda keywords: not keywords)
    print("rows with an empty list: %d of %d" % ((df["keywords"] == "[]").sum(), len(df)))
    print("distinct films with an empty list: %d of %d (%s)" % (empty.sum(), len(films), percent(empty.sum(), len(films))))

    # films that nobody watches are less likely to have keywords
    films = films.assign(id=films["id"].astype(int), empty=empty).set_index("id")
    joined = movies.set_index("id").join(films["empty"], how="inner")
    groups = pd.cut(joined["vote_count"], [0, 1, 10, 100, 1000, float("inf")], right=False,
                    labels=["0", "1-9", "10-99", "100-999", "1000+"])
    table = [[label, len(group), group["empty"].sum(), percent(group["empty"].sum(), len(group))]
             for label, group in joined.groupby(groups, observed=True)]
    print("\nfilms without keywords by number of votes:")
    print(tabulate(table, headers=["votes", "films", "no keywords", "%"], tablefmt="simple"))


def check_keyword_names(df):
    print_section("5. Keyword ids and names")
    objects = keyword_objects(df)
    pairs = Counter((k["id"], k["name"]) for k in objects)
    names_of_id = defaultdict(set)
    ids_of_name = defaultdict(set)
    for keyword_id, name in pairs:
        names_of_id[keyword_id].add(name)
        ids_of_name[name].add(keyword_id)
    print("distinct keyword ids: %d, distinct names: %d" % (len(names_of_id), len(ids_of_name)))
    print("ids with more than one name: %d" % sum(1 for n in names_of_id.values() if len(n) > 1))
    print("names with more than one id: %d" % sum(1 for i in ids_of_name.values() if len(i) > 1))

    # spaces at the start or end of the name, either normal spaces or non-breaking spaces (\xa0)
    spaced = {(i, n): c for (i, n), c in pairs.items() if n != n.strip()}
    non_breaking = {key: c for key, c in spaced.items() if "\xa0" in key[1]}
    print("\nkeywords with spaces at the start or end of the name: %d (used %d times), "
          "of which with a non-breaking space \\xa0: %d"
          % (len(spaced), sum(spaced.values()), len(non_breaking)))
    print(tabulate([[i, repr(n), c] for (i, n), c in list(spaced.items())[:8]],
                   headers=["id", "name", "films"], tablefmt="simple"))

    empty = {(i, n): c for (i, n), c in pairs.items() if not n.strip()}
    print("\nkeywords whose name is only spaces: %s" % [(i, repr(n), "%d films" % c) for (i, n), c in empty.items()])

    # once the spaces are removed, the same word can turn out to have two different ids
    ids_of_word = defaultdict(set)
    for keyword_id, name in pairs:
        if name.strip():
            ids_of_word[name.strip().lower()].add(keyword_id)
    same_word = {word: ids for word, ids in ids_of_word.items() if len(ids) > 1}
    print("\nsame word with different ids (after removing spaces and lowercasing): %d" % len(same_word))
    rows = [[word, keyword_id, repr(name), pairs[(keyword_id, name)]]
            for word, ids in same_word.items() for keyword_id in sorted(ids) for name in names_of_id[keyword_id]]
    print(tabulate(rows, headers=["word", "id", "name", "films"], tablefmt="simple"))

    repeated = sum(1 for keywords in df.drop_duplicates("id")["parsed"]
                   if keywords and len(keywords) != len({k["id"] for k in keywords}))
    print("\nfilms with the same keyword more than once: %d" % repeated)


def check_link_with_metadata(df, metadata):
    print_section("6. Link with movies_metadata.csv")
    valid = metadata[is_valid_row(metadata)]
    valid_ids = set(valid["id"].astype(int))
    keyword_ids = set(df["id"].astype(int))

    not_valid = keyword_ids - valid_ids
    print("keyword ids not among the valid films of movies_metadata: %d" % len(not_valid))
    rows = metadata[metadata["id"].isin([str(i) for i in not_valid])]
    report("their row in movies_metadata", rows.assign(truncated=is_truncated(rows)),
           ["id", "original_title", "truncated"])

    without = valid[~valid["id"].astype(int).isin(keyword_ids)]
    report("valid films of movies_metadata without a row in keywords.csv", without,
           ["id", "title", "release_date", "vote_count"])


def summary(df, movies):
    print_section("7. Summary")
    films = df.drop_duplicates("id")
    per_film = films["parsed"].map(len)
    print("keywords per film: mean %.1f, median %.0f, max %d" % (per_film.mean(), per_film.median(), per_film.max()))
    groups = pd.cut(per_film, [0, 1, 2, 6, 11, 21, float("inf")], right=False,
                    labels=["0", "1", "2-5", "6-10", "11-20", "21+"]).value_counts(sort=False)
    print(tabulate([[label, n, percent(n, len(films))] for label, n in groups.items()],
                   headers=["keywords", "films", "%"], tablefmt="simple"))

    titles = movies.set_index("id")["title"]
    most = films.assign(n=per_film, id=films["id"].astype(int)).sort_values("n", ascending=False).head(5)
    print("\nfilms with the most keywords:")
    print(tabulate([[i, titles.get(i, "?"), n] for i, n in zip(most["id"], most["n"])],
                   headers=["id", "title", "keywords"], tablefmt="simple"))

    usage = Counter(k["name"] for k in keyword_objects(df))
    once = sum(1 for c in usage.values() if c == 1)
    print("\nkeywords used by a single film: %d of %d (%s)" % (once, len(usage), percent(once, len(usage))))
    print("\nmost used keywords:")
    print(tabulate([[name, c, percent(c, len(films))] for name, c in usage.most_common(15)],
                   headers=["keyword", "films", "% of films"], tablefmt="simple"))


def main():
    df = load_keywords()
    metadata = load_metadata()
    valid = metadata[is_valid_row(metadata)]
    movies = valid.assign(id=valid["id"].astype(int), vote_count=to_number(valid["vote_count"])).drop_duplicates("id")
    check_structure(df)
    check_nested(df)
    check_duplicated_films(df, valid)
    check_missing(df, movies)
    check_keyword_names(df)
    check_link_with_metadata(df, metadata)
    summary(df, movies)


if __name__ == "__main__":
    main()
