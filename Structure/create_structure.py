"""
Creates the structure described in db_structure.txt: the collections movies and ratings,
each with a $jsonSchema validator, and their indexes.

    python Structure/create_structure.py              creates/updates the collections
    python Structure/create_structure.py --indexes    also creates the indexes

The indexes are meant to be created after the data has been inserted (inserting 26 million
ratings is faster without secondary indexes to update), so by default they are skipped.
Running the script again is safe: existing collections are not dropped, only their validator
is updated, and create_index does nothing if the index already exists.
"""
import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from pymongo import ASCENDING, TEXT

from DbConnector import DbConnector

# BSON types used by the validators. Python ints become "int" or "long" depending on their
# size (revenue can exceed 2^31), floats become "double"
INT = ["int", "long"]
NUMBER = ["int", "long", "double"]


def nullable(types):
    return types + ["null"]


def array_of(properties, required):
    return {
        "bsonType": "array",
        "items": {"bsonType": "object", "required": required, "properties": properties},
    }


ID_NAME = array_of({"id": {"bsonType": INT}, "name": {"bsonType": "string"}}, ["id", "name"])

MOVIE_FIELDS = {
    "_id": {"bsonType": INT, "description": "TMDB id of the movie"},
    "imdb_id": {"bsonType": nullable(["string"])},
    "movielens_id": {"bsonType": nullable(INT)},
    "title": {"bsonType": nullable(["string"])},
    "original_title": {"bsonType": nullable(["string"])},
    "original_language": {"bsonType": nullable(["string"])},
    "overview": {"bsonType": nullable(["string"])},
    "tagline": {"bsonType": nullable(["string"])},
    "status": {"bsonType": nullable(["string"])},
    "adult": {"bsonType": "bool"},
    "video": {"bsonType": "bool"},
    "budget": {"bsonType": nullable(INT)},
    "revenue": {"bsonType": nullable(INT)},
    "runtime": {"bsonType": nullable(INT)},
    "popularity": {"bsonType": nullable(NUMBER)},
    "vote_average": {"bsonType": nullable(NUMBER), "minimum": 0, "maximum": 10},
    "vote_count": {"bsonType": nullable(INT)},
    "release_date": {"bsonType": nullable(["date"])},
    "homepage": {"bsonType": nullable(["string"])},
    "poster_path": {"bsonType": nullable(["string"])},
    "genres": ID_NAME,
    "production_companies": ID_NAME,
    "production_countries": array_of(
        {"iso_3166_1": {"bsonType": "string"}, "name": {"bsonType": "string"}},
        ["iso_3166_1", "name"]),
    "spoken_languages": array_of(
        {"iso_639_1": {"bsonType": "string"}, "name": {"bsonType": "string"}},
        ["iso_639_1", "name"]),
    "belongs_to_collection": {
        "bsonType": ["object", "null"],
        "required": ["id", "name", "poster_path", "backdrop_path"],
        "properties": {
            "id": {"bsonType": INT},
            "name": {"bsonType": "string"},
            "poster_path": {"bsonType": nullable(["string"])},
            "backdrop_path": {"bsonType": nullable(["string"])},
        },
    },
    "keywords": ID_NAME,
    # inside cast and crew "id" is the person, not the movie
    "cast": array_of(
        {
            "id": {"bsonType": INT},
            "name": {"bsonType": "string"},
            "gender": {"enum": [1, 2, None], "description": "1 = female, 2 = male, null = not specified"},
            "character": {"bsonType": nullable(["string"])},
            "order": {"bsonType": INT},
            "cast_id": {"bsonType": INT},
            "credit_id": {"bsonType": "string"},
            "profile_path": {"bsonType": nullable(["string"])},
        },
        ["id", "name", "gender", "character", "order", "cast_id", "credit_id", "profile_path"]),
    "crew": array_of(
        {
            "id": {"bsonType": INT},
            "name": {"bsonType": "string"},
            "gender": {"enum": [1, 2, None], "description": "1 = female, 2 = male, null = not specified"},
            "department": {"bsonType": "string"},
            "job": {"bsonType": "string"},
            "credit_id": {"bsonType": "string"},
            "profile_path": {"bsonType": nullable(["string"])},
        },
        ["id", "name", "gender", "department", "job", "credit_id", "profile_path"]),
}

RATING_FIELDS = {
    "user_id": {"bsonType": INT},
    "movie_id": {"bsonType": INT, "description": "_id of the movie in movies (TMDB id, not MovieLens)"},
    "rating": {"bsonType": NUMBER, "minimum": 0.5, "maximum": 5},
    "timestamp": {"bsonType": "date"},
}

# collection -> validator. Every field is required: a missing value is stored as null,
# so all the documents of a collection have the same shape
COLLECTIONS = {
    "movies": {"$jsonSchema": {"bsonType": "object", "required": list(MOVIE_FIELDS), "properties": MOVIE_FIELDS}},
    "ratings": {"$jsonSchema": {"bsonType": "object", "required": list(RATING_FIELDS), "properties": RATING_FIELDS}},
}

# collection -> list of (keys, index name)
INDEXES = {
    # $text needs a text index, and a collection can have only one
    "movies": [([("overview", TEXT), ("tagline", TEXT)], "overview_tagline_text")],
    "ratings": [
        ([("user_id", ASCENDING)], "user_id"),
        ([("movie_id", ASCENDING)], "movie_id"),
    ],
}


class StructureBuilder:

    def __init__(self):
        self.connection = DbConnector()
        self.client = self.connection.client
        self.db = self.connection.db

    def create_collections(self):
        existing = self.db.list_collection_names()
        for name, validator in COLLECTIONS.items():
            if name in existing:
                # keep the data, only replace the validator
                self.db.command("collMod", name, validator=validator,
                                validationLevel="strict", validationAction="error")
                print("Updated validator of collection:", name)
            else:
                self.db.create_collection(name, validator=validator,
                                          validationLevel="strict", validationAction="error")
                print("Created collection:", name)

    def create_indexes(self):
        for name, indexes in INDEXES.items():
            collection = self.db[name]
            for keys, index_name in indexes:
                collection.create_index(keys, name=index_name)
                print("Created index %s on %s" % (index_name, name))

    def show_structure(self):
        print("\nCollections in %s:" % self.db.name)
        for info in self.db.list_collections():
            name = info["name"]
            schema = info["options"].get("validator", {}).get("$jsonSchema", {})
            print("- %s: %d documents, %d validated fields, indexes: %s" % (
                name,
                self.db[name].estimated_document_count(),
                len(schema.get("properties", {})),
                ", ".join(self.db[name].index_information())))


def main():
    parser = argparse.ArgumentParser(description="Creates the collections of the movies database")
    parser.add_argument("--indexes", action="store_true",
                        help="also create the indexes (run it after inserting the data)")
    args = parser.parse_args()

    program = None
    try:
        program = StructureBuilder()
        program.create_collections()
        if args.indexes:
            program.create_indexes()
        program.show_structure()
    except Exception as e:
        print("ERROR: Failed to create the structure:", e)
    finally:
        if program:
            program.connection.close_connection()


if __name__ == '__main__':
    main()
