"""
Mechanical checks on movies_metadata.csv: shape, malformed rows, duplicated ids,
missing values, types, formats, nested fields, ranges and text fields.
"""
from collections import defaultdict

import pandas as pd
from tabulate import tabulate

from load import (DATASET_DATE, NESTED_COLUMNS, NUMERIC_COLUMNS, is_truncated, is_valid_row,
                  load_metadata, parse_literal, print_section, report, shorten, to_number)

EXPECTED_COLUMNS = [
    "adult", "belongs_to_collection", "budget", "genres", "homepage", "id", "imdb_id",
    "original_language", "original_title", "overview", "popularity", "poster_path",
    "production_companies", "production_countries", "release_date", "revenue", "runtime",
    "spoken_languages", "status", "tagline", "title", "video", "vote_average", "vote_count",
]

# columns where 0 means "unknown" rather than a real value
ZERO_AS_MISSING = ["budget", "revenue", "runtime", "vote_count"]


def check_shape(df):
    print_section("1. Shape")
    print("rows: %d, columns: %d (expected %d)" % (len(df), len(df.columns), len(EXPECTED_COLUMNS)))
    print("missing columns:", sorted(set(EXPECTED_COLUMNS) - set(df.columns)))
    print("unexpected columns:", sorted(set(df.columns) - set(EXPECTED_COLUMNS)))


def check_malformed_rows(df):
    print_section("2. Malformed rows")
    bad_id = ~df["id"].str.fullmatch(r"\d+", na=False)
    truncated = is_truncated(df)
    report("id is not a number (shifted columns)", df[bad_id], ["adult", "budget", "id", "title"])
    report("truncated rows with a numeric id (fewer fields than the header)", df[truncated & ~bad_id],
           ["id", "original_title", "overview", "popularity", "vote_count"])

    # a text field containing a line break can split one record in two lines:
    # a truncated row immediately followed by a row with shifted columns
    pairs = [i for i in df.index[truncated & ~bad_id] if i + 1 in df.index and bad_id[i + 1]]
    print("\ntruncated rows followed by a shifted row (same record split in two): %d" % len(pairs))
    for i in pairs:
        print("  row %d (id %s, %s) + row %d starting with %r"
              % (i, df.at[i, "id"], df.at[i, "original_title"], i + 1, df.at[i + 1, "adult"][:40]))


def check_ids(df):
    print_section("3. Duplicated ids")
    valid = df[is_valid_row(df)]

    duplicated = valid[valid["id"].duplicated(keep=False)].sort_values("id")
    copies = duplicated["id"].value_counts()
    print("ids appearing more than once: %d (%d rows), extra rows to drop keeping one copy per id: %d"
          % (len(copies), len(duplicated), len(duplicated) - len(copies)))

    print("\ncopies per id:")
    print(tabulate(list(copies.value_counts().sort_index().items()),
                   headers=["copies", "ids"], tablefmt="simple"))

    # group the ids by the set of columns whose value changes between their copies
    kinds = defaultdict(lambda: [0, 0])
    for _, group in duplicated.groupby("id"):
        differing = [column for column in group.columns if group[column].nunique() > 1]
        kind = " + ".join(differing) or "(none, identical copies)"
        kinds[kind][0] += 1
        kinds[kind][1] += len(group)
    print("\ncolumns that differ between the copies of the same id:")
    print(tabulate([[kind, ids, rows, rows - ids] for kind, (ids, rows) in kinds.items()],
                   headers=["differing columns", "ids", "rows", "extra rows"], tablefmt="simple"))

    report("ids with more than 2 copies", duplicated[duplicated["id"].isin(copies[copies > 2].index)],
           ["id", "title", "release_date", "popularity", "vote_count"])
    report("duplicated ids", duplicated, ["id", "title", "release_date", "popularity", "vote_count"], n=6)

    imdb = valid[(valid["imdb_id"] != "") & valid["imdb_id"].duplicated(keep=False)]
    imdb = imdb[~imdb["id"].duplicated(keep=False)]
    report("same imdb_id on different tmdb ids", imdb.sort_values("imdb_id"), ["id", "imdb_id", "title", "release_date"])

    same_film = valid[valid["title"] != ""].drop_duplicates("id")
    same_film = same_film[same_film.duplicated(["title", "release_date"], keep=False)]
    report("same title and release_date on different ids", same_film.sort_values("title"),
           ["id", "imdb_id", "title", "release_date", "runtime"])


def check_missing_values(df):
    print_section("4. Missing values (valid rows)")
    valid = df[is_valid_row(df)]
    table = []
    for column in df.columns:
        values = valid[column]
        empty = (values.str.strip() == "").sum()
        empty_list = (values == "[]").sum() if column in NESTED_COLUMNS else 0
        zero = (to_number(values) == 0).sum() if column in ZERO_AS_MISSING else 0
        missing = empty + empty_list + zero
        table.append([column, empty, empty_list, zero, missing, "%.1f%%" % (100 * missing / len(valid))])
    print(tabulate(table, headers=["column", "empty", "[]", "zero", "missing", "%"], tablefmt="simple"))


def check_types(df):
    print_section("5. Types (valid rows)")
    valid = df[is_valid_row(df)]
    for column in NUMERIC_COLUMNS:
        values = valid[column][valid[column] != ""]
        not_number = values[to_number(values).isna()]
        print("%-14s non numeric values: %d %s" % (column, len(not_number), not_number.unique()[:5].tolist()))

    dates = valid["release_date"][valid["release_date"] != ""]
    not_date = dates[pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce").isna()]
    print("%-14s not a YYYY-MM-DD date: %d %s" % ("release_date", len(not_date), not_date.unique()[:5].tolist()))

    for column in ["adult", "video"]:
        print("%-14s values: %s" % (column, valid[column].value_counts().to_dict()))


def check_formats(df):
    print_section("6. Formats (valid, non empty values)")
    valid = df[is_valid_row(df)]
    patterns = {
        "imdb_id": r"tt\d{7}",
        "original_language": r"[a-z]{2}",
        "homepage": r"https?://\S+",
        "poster_path": r"/\S+\.(jpg|jpeg|png)",
    }
    for column, pattern in patterns.items():
        values = valid[valid[column] != ""]
        wrong = values[~values[column].str.fullmatch(pattern)]
        report("%s not matching %s" % (column, pattern), wrong, ["id", "title", column])
        if len(wrong):
            print("most frequent wrong values:", wrong[column].value_counts().head(5).to_dict())


def check_nested_fields(df):
    print_section("7. Nested fields (valid rows)")
    valid = df[is_valid_row(df)]
    table = []
    for column, (expected_type, expected_keys, key) in NESTED_COLUMNS.items():
        values = valid[column][valid[column] != ""]
        parsed = values.map(parse_literal)
        not_parsed = parsed.isna().sum()
        wrong_type = parsed.map(lambda v: v is not None and not isinstance(v, expected_type)).sum()

        objects = []
        for value in parsed.dropna():
            objects.extend(value if isinstance(value, list) else [value])
        wrong_keys = sum(1 for o in objects if not isinstance(o, dict) or set(o) != expected_keys)
        empty_name = defaultdict(int)
        names = defaultdict(set)
        for o in objects:
            if isinstance(o, dict) and key in o:
                names[o[key]].add(o.get("name"))
                if not str(o.get("name", "")).strip():
                    empty_name[o[key]] += 1
        many_names = {k: sorted(v) for k, v in names.items() if len(v) > 1}

        table.append([column, len(values), not_parsed, wrong_type, len(objects), wrong_keys,
                      len(names), len(many_names), len(empty_name)])
        if many_names:
            print("%s: same %s with different names, e.g. %s" % (column, key, list(many_names.items())[:3]))
        if empty_name:
            print("%s: %s with an empty name: %s" % (column, key, sorted(empty_name)))
    print()
    print(tabulate(table, headers=["column", "non empty", "not parsed", "wrong type", "objects",
                                   "wrong keys", "distinct", "id->many names", "empty names"],
                   tablefmt="simple"))


def check_ranges(df):
    print_section("8. Ranges (valid rows)")
    valid = df[is_valid_row(df)].copy()
    for column in NUMERIC_COLUMNS:
        valid[column] = to_number(valid[column])
    valid["release_date"] = pd.to_datetime(valid["release_date"], format="%Y-%m-%d", errors="coerce")

    print(tabulate(valid[NUMERIC_COLUMNS].describe().T, headers="keys", tablefmt="simple", floatfmt=".2f"))

    report("vote_average outside 0-10", valid[~valid["vote_average"].between(0, 10) & valid["vote_average"].notna()],
           ["id", "title", "vote_average"])
    for column in NUMERIC_COLUMNS:
        negative = valid[valid[column] < 0]
        if len(negative):
            report("negative %s" % column, negative, ["id", "title", column])
    report("runtime > 600 minutes", valid[valid["runtime"] > 600].sort_values("runtime", ascending=False),
           ["id", "title", "runtime", "release_date"])
    report("release_date before 1888", valid[valid["release_date"] < "1888-01-01"], ["id", "title", "release_date"])
    report("release_date after the dataset date (%s)" % DATASET_DATE.date(),
           valid[valid["release_date"] > DATASET_DATE].sort_values("release_date"),
           ["id", "title", "release_date", "status"])


def check_text(df):
    print_section("9. Text fields (valid rows)")
    valid = df[is_valid_row(df)]
    for column in ["title", "original_title", "overview", "tagline"]:
        values = valid[column]
        empty = (values.str.strip() == "").sum()
        spaces = ((values != values.str.strip()) & (values.str.strip() != "")).sum()
        print("%-15s empty: %5d, leading/trailing spaces: %d" % (column, empty, spaces))

    # the same overview on many different films is likely a placeholder
    overviews = valid[valid["overview"].str.strip() != ""].drop_duplicates("id")["overview"]
    repeated = overviews.value_counts()
    print("\noverviews repeated on different films:")
    print(tabulate(repeated[repeated > 1].head(10).reset_index().map(shorten, width=70), headers=["overview", "films"],
                   tablefmt="simple", showindex=False))


def main():
    df = load_metadata()
    check_shape(df)
    check_malformed_rows(df)
    check_ids(df)
    check_missing_values(df)
    check_types(df)
    check_formats(df)
    check_nested_fields(df)
    check_ranges(df)
    check_text(df)


if __name__ == "__main__":
    main()
