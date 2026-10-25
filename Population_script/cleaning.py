"""
Cleaning rules applied by populate.py while the data is loaded. Every rule, with the reason
behind it, is described in report_pulizia.txt.

Each function records in `log` (a Counter) how many rows or values it changed, so every number
of the report can be found in the output of populate.py.
"""
import ast
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd

# budget and revenue below this value are input errors (millions, thousands, typos), see EDA_movies_metadata
MIN_MONEY = 1000

# texts written in overview when the plot is not available, found by the EDA (overviews repeated on many films)
OVERVIEW_PLACEHOLDERS = {"no overview found.", "no overview", "no movie overview available.", "no overview yet."}

# the 59 language codes that never have a name in spoken_languages
MISSING_LANGUAGE_NAMES = {
    "ab": "Abkhazian", "am": "Amharic", "as": "Assamese", "ay": "Aymara", "bi": "Bislama",
    "bo": "Tibetan", "br": "Breton", "ce": "Chechen", "co": "Corsican", "cr": "Cree",
    "dz": "Dzongkha", "fo": "Faroese", "fy": "Western Frisian", "gd": "Scottish Gaelic", "gn": "Guarani",
    "gu": "Gujarati", "ht": "Haitian Creole", "hy": "Armenian", "ig": "Igbo", "iu": "Inuktitut",
    "jv": "Javanese", "ki": "Kikuyu", "km": "Khmer", "ku": "Kurdish", "kw": "Cornish",
    "lb": "Luxembourgish", "ln": "Lingala", "lo": "Lao", "mh": "Marshallese", "mi": "Maori",
    "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi", "my": "Burmese",
    "ne": "Nepali", "nv": "Navajo", "ny": "Chichewa", "oc": "Occitan", "qu": "Quechua",
    "sa": "Sanskrit", "sc": "Sardinian", "se": "Northern Sami", "sg": "Sango", "sh": "Serbo-Croatian",
    "si": "Sinhala", "sm": "Samoan", "sn": "Shona", "st": "Southern Sotho", "tg": "Tajik",
    "tk": "Turkmen", "tl": "Tagalog", "tn": "Tswana", "to": "Tongan", "tt": "Tatar",
    "ty": "Tahitian", "ug": "Uyghur", "xh": "Xhosa", "yi": "Yiddish",
}


# ---------------------------------------------------------------------------------------------
# generic helpers

def clean_text(value):
    """Removes spaces, tabs and \\xa0 at the start and at the end; an empty text becomes None"""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def to_int(value):
    """'81.0' -> 81, empty or not a number -> None"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_literal(value):
    """Nested fields are python literals (single quotes), not JSON. Empty or not parsable -> None"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return None


def parse_list(value):
    parsed = parse_literal(value)
    return parsed if isinstance(parsed, list) else []


# ---------------------------------------------------------------------------------------------
# movies_metadata.csv

def read_metadata(path, log):
    """
    Reads the file with the csv module and joins back the films split in two records by a line
    break inside overview: a record with fewer fields than the header, followed by a record whose
    fields complete it (the last field of the first and the first of the second are the same text).
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        records = list(reader)

    rows = []
    i = 0
    while i < len(records):
        head = records[i]
        if (len(head) < len(header) and i + 1 < len(records)
                and len(head) + len(records[i + 1]) - 1 == len(header)):
            tail = records[i + 1]
            rows.append(head[:-1] + [head[-1] + "\n" + tail[0]] + tail[1:])
            log["movies_metadata: films split in two rows, joined back"] += 1
            i += 2
            continue
        rows.append(head)
        i += 1

    df = pd.DataFrame(rows, columns=header)
    log["movies_metadata: rows read"] = len(df)
    return df


def drop_duplicated_movies(df, log):
    """Duplicated ids: the last copy in the file is the most recent one (see EDA_movies_metadata)"""
    clean = df.drop_duplicates("id", keep="last")
    log["movies_metadata: duplicated ids"] = df.loc[df["id"].duplicated(), "id"].nunique()
    log["movies_metadata: duplicated rows dropped (keep the last copy)"] = len(df) - len(clean)
    return clean


def language_names(df):
    """
    iso_639_1 code -> name. Every code has always the same name in the file, except the 59 codes
    that never have one: their name comes from MISSING_LANGUAGE_NAMES
    """
    names = dict(MISSING_LANGUAGE_NAMES)
    for languages in df["spoken_languages"]:
        for language in parse_list(languages):
            name = clean_text(language.get("name"))
            if name:
                names.setdefault(language["iso_639_1"], name)
    return names


def clean_money(value, column, log):
    amount = to_int(value)
    if amount == 0:
        log["movies_metadata: %s 0 -> null" % column] += 1
        return None
    if amount is not None and amount < MIN_MONEY:
        log["movies_metadata: %s between 1 and %d -> null" % (column, MIN_MONEY - 1)] += 1
        return None
    return amount


def clean_runtime(value, log):
    runtime = to_int(value)
    if runtime == 0:
        log["movies_metadata: runtime 0 -> null"] += 1
        return None
    return runtime


def clean_vote_average(value, vote_count, log):
    """A mean of 0 with at least one vote is impossible (the lowest vote on TMDB is 0.5): not computed"""
    average = to_float(value)
    if average == 0 and vote_count:
        log["movies_metadata: vote_average 0 with vote_count > 0 -> null"] += 1
        return None
    return average


def clean_overview(value, log):
    overview = clean_text(value)
    if overview and overview.lower() in OVERVIEW_PLACEHOLDERS:
        log["movies_metadata: placeholder overview -> null"] += 1
        return None
    return overview


def clean_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def clean_spoken_languages(value, original_language, names, log):
    """Fills the missing names and adds original_language when it is not among the spoken languages"""
    languages = []
    for language in parse_list(value):
        name = clean_text(language.get("name"))
        if not name:
            name = names[language["iso_639_1"]]
            log["movies_metadata: empty language names rebuilt from the code"] += 1
        languages.append({"iso_639_1": language["iso_639_1"], "name": name})

    if original_language and original_language not in {l["iso_639_1"] for l in languages}:
        if languages:
            log["movies_metadata: original_language added to spoken_languages (list not empty)"] += 1
        else:
            log["movies_metadata: original_language added to spoken_languages (empty list)"] += 1
        languages.append({"iso_639_1": original_language, "name": names[original_language]})
    return languages


def clean_collection(value):
    collection = parse_literal(value)
    if not isinstance(collection, dict):
        return None
    return {
        "id": collection["id"],
        "name": clean_text(collection["name"]),
        "poster_path": clean_text(collection.get("poster_path")),
        "backdrop_path": clean_text(collection.get("backdrop_path")),
    }


def movie_document(row, names, log):
    """One row of movies_metadata -> movie document, without keywords, cast and crew"""
    vote_count = to_int(row["vote_count"])
    original_language = clean_text(row["original_language"])
    return {
        "_id": int(row["id"]),
        "imdb_id": clean_text(row["imdb_id"]),
        "movielens_id": None,
        "title": clean_text(row["title"]),
        "original_title": clean_text(row["original_title"]),
        "original_language": original_language,
        "overview": clean_overview(row["overview"], log),
        "tagline": clean_text(row["tagline"]),
        "status": clean_text(row["status"]),
        "adult": row["adult"] == "True",
        "video": row["video"] == "True",
        "budget": clean_money(row["budget"], "budget", log),
        "revenue": clean_money(row["revenue"], "revenue", log),
        "runtime": clean_runtime(row["runtime"], log),
        "popularity": to_float(row["popularity"]),
        "vote_average": clean_vote_average(row["vote_average"], vote_count, log),
        "vote_count": vote_count,
        "release_date": clean_date(row["release_date"]),
        "homepage": clean_text(row["homepage"]),
        "poster_path": clean_text(row["poster_path"]),
        # the order of the arrays is the one of the file: the first genre is the primary one
        "genres": parse_list(row["genres"]),
        "production_companies": parse_list(row["production_companies"]),
        "production_countries": parse_list(row["production_countries"]),
        "spoken_languages": clean_spoken_languages(row["spoken_languages"], original_language, names, log),
        "belongs_to_collection": clean_collection(row["belongs_to_collection"]),
        "keywords": [],
        "cast": [],
        "crew": [],
    }


# ---------------------------------------------------------------------------------------------
# keywords.csv

def read_keywords(path, log):
    """film id -> list of {id, name}. The copies of a duplicated id are identical: keep one"""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    clean = df.drop_duplicates("id")
    log["keywords: rows read"] = len(df)
    log["keywords: duplicated rows dropped"] = len(df) - len(clean)
    return {int(film): parse_list(keywords) for film, keywords in zip(clean["id"], clean["keywords"])}


def keyword_ids(keywords_by_film, log):
    """
    keyword id -> (id, name) to use instead, or None if the keyword is dropped.
    Names are stripped; a name left empty (id 13091, only '\\xa0') drops the keyword; when the same
    stripped name has more than one id, the id of the version written without spaces is used.
    """
    original_names = {k["id"]: k["name"] for keywords in keywords_by_film.values() for k in keywords}
    ids_of_name = defaultdict(list)
    for keyword_id, name in original_names.items():
        if clean_text(name):
            ids_of_name[clean_text(name)].append(keyword_id)

    mapping = {}
    for keyword_id, name in original_names.items():
        name = clean_text(name)
        if name is None:
            mapping[keyword_id] = None
            log["keywords: keywords with an empty name dropped"] += 1
            continue
        if name != original_names[keyword_id]:
            log["keywords: names with spaces at the start or end stripped"] += 1
        ids = ids_of_name[name]
        # prefer the id whose original name had no spaces
        clean_ids = [i for i in ids if original_names[i] == name] or sorted(ids)
        mapping[keyword_id] = (clean_ids[0], name)
        if clean_ids[0] != keyword_id:
            log["keywords: keyword ids merged into the id of the same name without spaces"] += 1
    return mapping


def clean_keywords(keywords, mapping, log):
    clean = []
    seen = set()
    for keyword in keywords:
        new = mapping[keyword["id"]]
        if new is None:
            log["keywords: film-keyword links removed (empty name)"] += 1
            continue
        if new[0] in seen:
            log["keywords: same keyword twice in a film after the merge, removed"] += 1
            continue
        seen.add(new[0])
        clean.append({"id": new[0], "name": new[1]})
    return clean


# ---------------------------------------------------------------------------------------------
# credits.csv

def read_credits(path, log):
    """
    film id -> (cast, crew). The copies of a duplicated id are identical or differ only in the
    order of the crew (same credit_ids, same values): keep the first one
    """
    csv.field_size_limit(sys.maxsize)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    clean = df.drop_duplicates("id")
    log["credits: rows read"] = len(df)
    log["credits: duplicated rows dropped"] = len(df) - len(clean)
    return {int(film): (parse_list(cast), parse_list(crew))
            for film, cast, crew in zip(clean["id"], clean["cast"], clean["crew"])}


def people(credits, log):
    """
    Person id -> (name, gender) used in every film, so that the same person is written the same way:
    - name: stripped, the most frequent among the films of the person (the first found on a tie);
      it matters for the 15 people written in two alphabets
    - gender: 1 or 2 when it is set in at least one film, otherwise None (TMDB uses 0 for "not set")
    """
    names = defaultdict(Counter)
    genders = defaultdict(set)
    for cast, crew in credits.values():
        for person in cast + crew:
            names[person["id"]][clean_text(person["name"]) or ""] += 1
            genders[person["id"]].add(person["gender"])

    result = {}
    for person_id, counter in names.items():
        set_genders = genders[person_id] - {0}
        if len(counter) > 1:
            log["credits: people with more than one name, one name chosen"] += 1
        if set_genders and 0 in genders[person_id]:
            log["credits: people with gender set only in some films, set gender used everywhere"] += 1
        gender = set_genders.pop() if len(set_genders) == 1 else None
        result[person_id] = (counter.most_common(1)[0][0], gender)
    return result


def count_person_changes(person, name, gender, log, kind):
    if person["name"] != name:
        log["credits: %s entries whose name changed (spaces or other alphabet)" % kind] += 1
    if person["gender"] == 0 and gender is None:
        log["credits: %s entries with gender 0 -> null" % kind] += 1
    elif person["gender"] == 0:
        log["credits: %s entries with gender 0 -> set gender of the person" % kind] += 1


def clean_cast(cast, people_data, log):
    clean = []
    seen = set()
    for actor in cast:
        character = clean_text(actor["character"])
        # the same person twice with the same character in the same film is a real duplicate
        if (actor["id"], character) in seen:
            log["credits: cast entries duplicated (same person and character in a film), removed"] += 1
            continue
        seen.add((actor["id"], character))
        name, gender = people_data[actor["id"]]
        count_person_changes(actor, name, gender, log, "cast")
        if character is None:
            log["credits: cast entries with empty character -> null"] += 1
        clean.append({
            "id": actor["id"],
            "name": name,
            "gender": gender,
            "character": character,
            "order": actor["order"],
            "cast_id": actor["cast_id"],
            "credit_id": actor["credit_id"],
            "profile_path": clean_text(actor["profile_path"]),
        })
    return clean


def clean_crew(crew, people_data, log):
    clean = []
    for member in crew:
        name, gender = people_data[member["id"]]
        count_person_changes(member, name, gender, log, "crew")
        clean.append({
            "id": member["id"],
            "name": name,
            "gender": gender,
            "department": member["department"],
            "job": member["job"],
            "credit_id": member["credit_id"],
            "profile_path": clean_text(member["profile_path"]),
        })
    return clean


# ---------------------------------------------------------------------------------------------
# links.csv and ratings.csv

DISCARDED_NO_TMDB = "movieId without tmdbId"
DISCARDED_NOT_IN_MOVIES = "tmdbId not in movies"
DISCARDED_WRONG_LINK = "movieId on a shared tmdbId with a different imdb id"


def read_links(path, imdb_of_movie, log):
    """
    Returns movieId -> tmdbId for the movieIds whose ratings are kept, and movieId -> reason
    for the discarded ones. imdb_of_movie is tmdb id -> imdb_id of the cleaned movies.
    imdbId is read as text: as a number it would lose its leading zeros.
    """
    links = pd.read_csv(path, dtype=str, keep_default_na=False)
    log["links: rows read"] = len(links)
    discarded = {}

    for movie_id in links.loc[links["tmdbId"] == "", "movieId"]:
        discarded[int(movie_id)] = DISCARDED_NO_TMDB
    links = links[links["tmdbId"] != ""].assign(tmdbId=lambda l: l["tmdbId"].astype(int))

    not_found = ~links["tmdbId"].isin(imdb_of_movie.keys())
    for movie_id in links.loc[not_found, "movieId"]:
        discarded[int(movie_id)] = DISCARDED_NOT_IN_MOVIES
    links = links[~not_found]

    # a tmdbId used by more than one movieId: only the movieId with the same imdb id as the film is right
    shared = links["tmdbId"].duplicated(keep=False)
    log["links: tmdbIds shared by more than one movieId"] = links.loc[shared, "tmdbId"].nunique()
    same_imdb = links["imdbId"] == links["tmdbId"].map(
        lambda tmdb: (imdb_of_movie[tmdb] or "").removeprefix("tt"))
    for movie_id in links.loc[shared & ~same_imdb, "movieId"]:
        discarded[int(movie_id)] = DISCARDED_WRONG_LINK
    links = links[~shared | same_imdb]

    for reason, n in Counter(discarded.values()).items():
        log["links: movieIds discarded, %s" % reason] = n
    log["links: movieIds kept"] = len(links)
    return dict(zip(links["movieId"].astype(int), links["tmdbId"])), discarded
