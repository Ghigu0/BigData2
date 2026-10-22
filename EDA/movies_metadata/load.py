import ast
from pathlib import Path

import pandas as pd
from tabulate import tabulate

CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "movies_metadata.csv"

# The dataset is a snapshot: the most recent rating in ratings.csv is from this day,
# so a release date after it is in the future with respect to the data
DATASET_DATE = pd.Timestamp("2017-08-04")

NUMERIC_COLUMNS = ["budget", "revenue", "runtime", "popularity", "vote_average", "vote_count"]

# nested column -> (expected python type, keys expected in each object, key that identifies the object)
NESTED_COLUMNS = {
    "genres": (list, {"id", "name"}, "id"),
    "production_companies": (list, {"id", "name"}, "id"),
    "production_countries": (list, {"iso_3166_1", "name"}, "iso_3166_1"),
    "spoken_languages": (list, {"iso_639_1", "name"}, "iso_639_1"),
    "belongs_to_collection": (dict, {"id", "name", "poster_path", "backdrop_path"}, "id"),
}


def load_metadata():
    """
    Reads every column as a string and keeps empty cells as "", so dirty values stay
    visible instead of being converted or dropped by pandas.
    A row with fewer fields than the header gets "" in the missing ones.
    """
    return pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)


def is_truncated(df):
    """Rows cut before the end: vote_count, the last column, is never empty in a complete row"""
    return df["vote_count"] == ""


def is_valid_row(df):
    """Rows with a numeric id and all the 24 fields"""
    return df["id"].str.fullmatch(r"\d+", na=False) & ~is_truncated(df)


def to_number(series):
    """Converts to numbers, values that are not numbers become NaN"""
    return pd.to_numeric(series, errors="coerce")


def parse_literal(value):
    """
    Nested fields are written as python literals (single quotes), not JSON.
    Returns None when the value is empty or cannot be parsed.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return None


def typed_metadata(df):
    """Valid rows with numbers, dates and nested fields converted to python types"""
    typed = df[is_valid_row(df)].copy()
    typed["id"] = typed["id"].astype(int)
    for column in NUMERIC_COLUMNS:
        typed[column] = to_number(typed[column])
    typed["release_date"] = pd.to_datetime(typed["release_date"], format="%Y-%m-%d", errors="coerce")
    for column in NESTED_COLUMNS:
        typed[column] = typed[column].map(parse_literal)
    return typed


def print_section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def shorten(value, width=40):
    if isinstance(value, pd.Timestamp):
        return value.date()
    return value if len(str(value)) <= width else str(value)[:width] + "..."


def report(title, rows, columns, n=5, width=40):
    """Prints how many rows match a check and the first n of them"""
    print("\n-- %s: %d rows" % (title, len(rows)))
    if len(rows) == 0:
        return
    sample = rows[columns].head(n).map(shorten, width=width)
    print(tabulate(sample, headers="keys", tablefmt="simple", showindex=True))
