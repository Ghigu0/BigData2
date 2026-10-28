"""
Cleans the csv files of the dataset and inserts them in the collections movies and ratings,
with the structure described in Structure/db_structure.txt. The cleaning rules are in cleaning.py
and are explained in cleaning_report.txt.

    python Population_script/populate.py            full dataset (links.csv, ratings.csv)
    python Population_script/populate.py --small    links_small.csv and ratings_small.csv, for a quick test

The collections are dropped and created again (with their validator) before inserting, so the
script can be run more than once. The indexes are created at the end, after the inserts.
"""
import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd
from tabulate import tabulate

sys.path.append(str(Path(__file__).resolve().parents[1] / "Structure"))

import cleaning
from create_structure import COLLECTIONS, StructureBuilder

DATA = Path(__file__).resolve().parents[1] / "data"

# rows of ratings.csv read and inserted at a time
RATINGS_CHUNK = 1_000_000


class Populator:

    def __init__(self, small):
        self.small = small
        self.log = Counter()
        self.structure = StructureBuilder()
        self.db = self.structure.db

    def build_movies(self):
        """Cleaned movie documents, with keywords, cast and crew embedded, by tmdb id"""
        metadata = cleaning.read_metadata(DATA / "movies_metadata.csv", self.log)
        metadata = cleaning.drop_duplicated_movies(metadata, self.log)
        names = cleaning.language_names(metadata)
        movies = {}
        for row in metadata.to_dict("records"):
            movie = cleaning.movie_document(row, names, self.log)
            movies[movie["_id"]] = movie

        keywords = cleaning.read_keywords(DATA / "keywords.csv", self.log)
        mapping = cleaning.keyword_ids(keywords, self.log)
        for film, film_keywords in keywords.items():
            if film in movies:
                movies[film]["keywords"] = cleaning.clean_keywords(film_keywords, mapping, self.log)
            else:
                self.log["keywords: films not in movies, ignored"] += 1

        credits = cleaning.read_credits(DATA / "credits.csv", self.log)
        people = cleaning.people(credits, self.log)
        for film, (cast, crew) in credits.items():
            if film in movies:
                movies[film]["cast"] = cleaning.clean_cast(cast, people, self.log)
                movies[film]["crew"] = cleaning.clean_crew(crew, people, self.log)
            else:
                self.log["credits: films not in movies, ignored"] += 1

        self.log["movies: films without keywords"] = sum(1 for m in movies.values() if not m["keywords"])
        self.log["movies: films without a row in credits.csv"] = sum(1 for f in movies if f not in credits)
        return movies

    def link_movies(self, movies):
        """Translation movieId -> tmdbId for the ratings, and movielens_id of every film"""
        links = "links_small.csv" if self.small else "links.csv"
        imdb_of_movie = {film: movie["imdb_id"] for film, movie in movies.items()}
        movie_of, discarded = cleaning.read_links(DATA / links, imdb_of_movie, self.log)
        for movielens_id, film in movie_of.items():
            movies[film]["movielens_id"] = movielens_id
        return movie_of, discarded

    def reset_collections(self):
        for name in COLLECTIONS:
            self.db[name].drop()
        self.structure.create_collections()

    def insert_movies(self, movies):
        self.db["movies"].insert_many(list(movies.values()), ordered=False)
        self.log["movies: documents inserted"] = len(movies)
        print("Inserted %d movies" % len(movies))

    def insert_ratings(self, movie_of, discarded):
        name = "ratings_small.csv" if self.small else "ratings.csv"
        for chunk in pd.read_csv(DATA / name, chunksize=RATINGS_CHUNK):
            self.log["ratings: rows read"] += len(chunk)
            movie_id = chunk["movieId"].map(movie_of)
            lost = movie_id.isna()
            reasons = chunk.loc[lost, "movieId"].map(discarded).fillna("movieId not in links")
            for reason, n in reasons.value_counts().items():
                self.log["ratings: discarded, %s" % reason] += int(n)

            chunk = chunk[~lost]
            # python types, not numpy ones: pymongo cannot encode numpy integers
            dates = pd.to_datetime(chunk["timestamp"], unit="s").dt.to_pydatetime()
            documents = [
                {"user_id": user, "movie_id": movie, "rating": rating, "timestamp": date}
                for user, movie, rating, date in zip(chunk["userId"].tolist(), movie_id[~lost].astype(int).tolist(),
                                                     chunk["rating"].astype(float).tolist(), list(dates))
            ]
            if documents:
                self.db["ratings"].insert_many(documents, ordered=False)
            self.log["ratings: documents inserted"] += len(documents)
            print("Inserted %d ratings so far" % self.log["ratings: documents inserted"])

    def print_summary(self):
        print("\nCleaning summary")
        print(tabulate([[label, n] for label, n in self.log.items()], headers=["step", "count"],
                       tablefmt="simple", intfmt=","))


def main():
    parser = argparse.ArgumentParser(description="Cleans the dataset and populates the movies database")
    parser.add_argument("--small", action="store_true",
                        help="use links_small.csv and ratings_small.csv (quick test)")
    args = parser.parse_args()

    program = None
    try:
        program = Populator(args.small)
        start = time.time()
        print("Cleaning movies_metadata, keywords and credits...")
        movies = program.build_movies()
        movie_of, discarded = program.link_movies(movies)

        program.reset_collections()
        program.insert_movies(movies)
        program.insert_ratings(movie_of, discarded)
        print("Creating the indexes...")
        program.structure.create_indexes()

        program.print_summary()
        program.structure.show_structure()
        print("\nDone in %.0f seconds" % (time.time() - start))
    except Exception as e:
        print("ERROR: Failed to populate the database:", e)
        raise
    finally:
        if program:
            program.structure.connection.close_connection()


if __name__ == '__main__':
    main()
