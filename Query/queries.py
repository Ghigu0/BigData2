"""
Answers the 10 questions of Part 2 with MongoDB queries on the collections movies and ratings
(structure in Structure/struttura_db.txt).

    python Query/queries.py          runs all the queries
    python Query/queries.py 1 7      runs only queries 1 and 7

Most of the work is done by aggregation pipelines. Only query 10 also uses Python, to translate
the movies rated by each user into genres with a dictionary movie_id -> genres.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from tabulate import tabulate

from DbConnector import DbConnector


def median(values):
    """Expression for the exact median of an array, null values are ignored.
    $median exists in MongoDB 7.0 but only with method "approximate": with an even number of
    values it returns the lower middle value (the median of [1, 2, 3, 4] is 2, not 2.5)"""
    numbers = {"$filter": {"input": values, "cond": {"$isNumber": "$$this"}}}
    return {"$let": {
        "vars": {"sorted": {"$sortArray": {"input": numbers, "sortBy": 1}}},
        "in": {"$let": {
            "vars": {"n": {"$size": "$$sorted"}},
            "in": {"$cond": [
                {"$eq": ["$$n", 0]},
                None,
                # middle value if n is odd, mean of the two middle values if n is even
                {"$avg": [
                    {"$arrayElemAt": ["$$sorted", {"$toInt": {"$floor": {"$divide": [{"$subtract": ["$$n", 1]}, 2]}}}]},
                    {"$arrayElemAt": ["$$sorted", {"$toInt": {"$ceil": {"$divide": [{"$subtract": ["$$n", 1]}, 2]}}}]},
                ]},
            ]},
        }},
    }}


def decade(date_field):
    return {"$multiply": [{"$floor": {"$divide": [{"$year": date_field}, 10]}}, 10]}


def people(array, condition=None):
    """Distinct {id, name} of the people in cast or crew: an actor with two characters in the same
    film appears there twice, but the film must be counted once"""
    if condition:
        array = {"$filter": {"input": array, "cond": condition}}
    return {"$setUnion": [{"$map": {"input": array, "in": {"id": "$$this.id", "name": "$$this.name"}}}]}


DIRECTORS = people("$crew", {"$eq": ["$$this.job", "Director"]})
ACTORS = people("$cast")


def show(rows, headers, intfmt=","):
    print(tabulate(rows, headers=headers, tablefmt="simple", intfmt=intfmt, floatfmt=",.2f"))


def day(date):
    return date.strftime("%Y-%m-%d") if date else None


class QueryRunner:

    def __init__(self):
        self.connection = DbConnector()
        self.db = self.connection.db
        self.movies = self.db["movies"]
        self.ratings = self.db["ratings"]

    def query_1(self):
        """Top 10 directors (>= 5 movies) by median revenue"""
        pipeline = [
            {"$project": {"revenue": 1, "vote_average": 1, "director": DIRECTORS}},
            {"$unwind": "$director"},
            {"$group": {
                "_id": "$director.id",
                "name": {"$first": "$director.name"},
                "movies": {"$sum": 1},
                "movies_with_revenue": {"$sum": {"$cond": [{"$ne": ["$revenue", None]}, 1, 0]}},
                "revenues": {"$push": "$revenue"},
                "mean_vote_average": {"$avg": "$vote_average"},
            }},
            # revenue is known only for 16% of the movies: the median must be computed on at
            # least 5 real revenues, not on 5 movies of which maybe only one has a revenue
            {"$match": {"movies_with_revenue": {"$gte": 5}}},
            {"$project": {"name": 1, "movies": 1, "movies_with_revenue": 1, "mean_vote_average": 1,
                          "median_revenue": median("$revenues")}},
            {"$sort": {"median_revenue": -1, "_id": 1}},
            {"$limit": 10},
        ]
        rows = [[d["name"], d["movies"], d["movies_with_revenue"], d["median_revenue"], d["mean_vote_average"]]
                for d in self.movies.aggregate(pipeline)]
        show(rows, ["director", "movies", "movies with revenue", "median revenue (USD)", "mean vote_average"])

    def query_2(self):
        """Actor pairs with >= 3 movies together"""
        pipeline = [
            {"$project": {"vote_average": 1, "a": ACTORS, "b": ACTORS}},
            {"$unwind": "$a"},
            {"$unwind": "$b"},
            # every pair once, and no actor paired with himself
            {"$match": {"$expr": {"$lt": ["$a.id", "$b.id"]}}},
            {"$group": {
                "_id": {"a": "$a.id", "b": "$b.id"},
                "actor_a": {"$first": "$a.name"},
                "actor_b": {"$first": "$b.name"},
                "movies": {"$sum": 1},
                "mean_vote_average": {"$avg": "$vote_average"},
            }},
            {"$match": {"movies": {"$gte": 3}}},
            {"$sort": {"movies": -1, "mean_vote_average": -1, "_id": 1}},
        ]
        pairs = list(self.movies.aggregate(pipeline, allowDiskUse=True))
        print("Actor pairs with at least 3 movies together: %d (the first 20 are shown)\n" % len(pairs))
        show([[p["actor_a"], p["actor_b"], p["movies"], p["mean_vote_average"]] for p in pairs[:20]],
             ["actor", "actor", "co-appearances", "mean vote_average"])

    def query_3(self):
        """Top 10 actors (>= 10 movies) by number of distinct genres"""
        pipeline = [
            {"$project": {"genres": "$genres.name", "actor": ACTORS}},
            {"$unwind": "$actor"},
            {"$group": {
                "_id": "$actor.id",
                "name": {"$first": "$actor.name"},
                "movies": {"$sum": 1},
                "genres": {"$push": "$genres"},
            }},
            {"$match": {"movies": {"$gte": 10}}},
            # genres is a list of lists, one per movie: counting the movies of every genre gives
            # the distinct genres, and as examples the 5 genres the actor appears in most
            {"$unwind": "$genres"},
            {"$unwind": "$genres"},
            {"$group": {
                "_id": {"actor": "$_id", "genre": "$genres"},
                "name": {"$first": "$name"},
                "movies": {"$first": "$movies"},
                "genre_movies": {"$sum": 1},
            }},
            {"$group": {
                "_id": "$_id.actor",
                "name": {"$first": "$name"},
                "movies": {"$first": "$movies"},
                "genre_count": {"$sum": 1},
                "examples": {"$topN": {"n": 5, "sortBy": {"genre_movies": -1, "_id.genre": 1},
                                       "output": "$_id.genre"}},
            }},
            {"$sort": {"genre_count": -1, "movies": -1, "_id": 1}},
        ]
        actors = list(self.movies.aggregate(pipeline, allowDiskUse=True))
        most_genres = actors[0]["genre_count"]
        print("Actors with at least 10 movies: %d, %d of them appeared in all the %d genres "
              "(ties broken by movies count)\n"
              % (len(actors), sum(1 for a in actors if a["genre_count"] == most_genres), most_genres))
        show([[a["name"], a["movies"], a["genre_count"], ", ".join(a["examples"])] for a in actors[:10]],
             ["actor", "movies", "distinct genres", "most frequent genres"])

    def query_4(self):
        """Top 10 collections (>= 3 movies) by total revenue"""
        pipeline = [
            {"$match": {"belongs_to_collection.name": {"$ne": None}}},
            {"$group": {
                "_id": "$belongs_to_collection.id",
                "name": {"$first": "$belongs_to_collection.name"},
                "movies": {"$sum": 1},
                "movies_with_revenue": {"$sum": {"$cond": [{"$ne": ["$revenue", None]}, 1, 0]}},
                # $sum, $min and $max ignore null values
                "total_revenue": {"$sum": "$revenue"},
                "votes": {"$push": "$vote_average"},
                "first": {"$min": "$release_date"},
                "last": {"$max": "$release_date"},
            }},
            {"$match": {"movies": {"$gte": 3}}},
            {"$sort": {"total_revenue": -1}},
            {"$limit": 10},
            {"$project": {"name": 1, "movies": 1, "movies_with_revenue": 1, "total_revenue": 1,
                          "first": 1, "last": 1, "median_vote_average": median("$votes")}},
        ]
        rows = [[c["name"], c["movies"], c["movies_with_revenue"], c["total_revenue"], c["median_vote_average"],
                 "%s -> %s" % (day(c["first"]), day(c["last"]))]
                for c in self.movies.aggregate(pipeline)]
        show(rows, ["collection", "movies", "movies with revenue", "total revenue (USD)",
                    "median vote_average", "release dates"])

    def query_5(self):
        """Median runtime and movie count by decade and primary genre"""
        pipeline = [
            {"$match": {"release_date": {"$ne": None}, "runtime": {"$ne": None}, "genres.0": {"$exists": True}}},
            {"$group": {
                "_id": {"decade": decade("$release_date"), "genre": {"$arrayElemAt": ["$genres.name", 0]}},
                "runtimes": {"$push": "$runtime"},
                "movies": {"$sum": 1},
            }},
            {"$project": {"movies": 1, "median_runtime": median("$runtimes")}},
            {"$sort": {"_id.decade": 1, "median_runtime": -1, "_id.genre": 1}},
        ]
        rows = [["%ds" % g["_id"]["decade"], g["_id"]["genre"], g["median_runtime"], g["movies"]]
                for g in self.movies.aggregate(pipeline)]
        show(rows, ["decade", "primary genre", "median runtime (min)", "movies"])

    def query_6(self):
        """Proportion of women among the 5 top-billed actors, by decade"""
        pipeline = [
            {"$match": {"release_date": {"$ne": None}, "cast.0": {"$exists": True}}},
            # order does not always start from 0 and has gaps: the first 5 are found by sorting
            {"$project": {"release_date": 1,
                          "top5": {"$slice": [{"$sortArray": {"input": "$cast", "sortBy": {"order": 1}}}, 5]}}},
            {"$project": {
                "release_date": 1,
                "known": {"$size": {"$filter": {"input": "$top5", "cond": {"$ne": ["$$this.gender", None]}}}},
                "women": {"$size": {"$filter": {"input": "$top5", "cond": {"$eq": ["$$this.gender", 1]}}}},
            }},
            # unknown gender is ignored: the proportion is over the actors with a known gender,
            # and movies where none of the 5 has a known gender are not used
            {"$match": {"known": {"$gt": 0}}},
            {"$group": {
                "_id": decade("$release_date"),
                "female_proportion": {"$avg": {"$divide": ["$women", "$known"]}},
                "movies": {"$sum": 1},
            }},
            {"$sort": {"female_proportion": -1}},
        ]
        rows = [["%ds" % d["_id"], d["female_proportion"], d["movies"]] for d in self.movies.aggregate(pipeline)]
        show(rows, ["decade", "mean female proportion", "movies"])

    def query_7(self):
        """Top 20 movies about noir / neo-noir (vote_count >= 50) by vote_average"""
        # the text index splits "neo-noir" in "neo" and "noir", so searching "noir" finds both.
        # Searching "neo" too would also match unrelated movies (e.g. Neo of The Matrix), and the
        # phrase "\"neo-noir\"" together with "noir" would mean AND, not OR
        pipeline = [
            {"$match": {"$text": {"$search": "noir"}, "vote_count": {"$gte": 50}}},
            {"$sort": {"vote_average": -1, "vote_count": -1}},
            {"$limit": 20},
            {"$project": {"title": 1, "year": {"$year": "$release_date"}, "vote_average": 1, "vote_count": 1}},
        ]
        print("Movies matching \"noir\": %d, with vote_count >= 50: %d\n" % (
            self.movies.count_documents({"$text": {"$search": "noir"}}),
            self.movies.count_documents({"$text": {"$search": "noir"}, "vote_count": {"$gte": 50}})))
        rows = [[m["title"], m["year"], m["vote_average"], m["vote_count"]] for m in self.movies.aggregate(pipeline)]
        # no thousands separator, or the years would be printed as 1,960
        show(rows, ["title", "year", "vote_average", "vote_count"], intfmt="")

    def query_8(self):
        """Top 20 director-actor pairs (>= 3 movies with vote_count >= 100) by mean vote_average"""
        pipeline = [
            {"$match": {"vote_count": {"$gte": 100}}},
            {"$project": {"vote_average": 1, "revenue": 1, "director": DIRECTORS, "actor": ACTORS}},
            {"$unwind": "$director"},
            {"$unwind": "$actor"},
            # a director acting in his own movie is not a collaboration
            {"$match": {"$expr": {"$ne": ["$director.id", "$actor.id"]}}},
            {"$group": {
                "_id": {"director": "$director.id", "actor": "$actor.id"},
                "director": {"$first": "$director.name"},
                "actor": {"$first": "$actor.name"},
                "movies": {"$sum": 1},
                "mean_vote_average": {"$avg": "$vote_average"},
                "movies_with_revenue": {"$sum": {"$cond": [{"$ne": ["$revenue", None]}, 1, 0]}},
                # $avg ignores null values: mean of the known revenues
                "mean_revenue": {"$avg": "$revenue"},
            }},
            {"$match": {"movies": {"$gte": 3}}},
            {"$sort": {"mean_vote_average": -1, "movies": -1, "_id": 1}},
            {"$limit": 20},
        ]
        rows = [[p["director"], p["actor"], p["movies"], p["mean_vote_average"], p["movies_with_revenue"],
                 p["mean_revenue"]]
                for p in self.movies.aggregate(pipeline, allowDiskUse=True)]
        show(rows, ["director", "actor", "movies", "mean vote_average", "movies with revenue", "mean revenue (USD)"])

    def query_9(self):
        """Top 10 original languages (not English) of movies produced in the United States"""
        # production_companies has only id and name in this dataset, without the country of the
        # company: "produced in the United States" can only be checked on production_countries
        pipeline = [
            {"$match": {"original_language": {"$nin": ["en", None]}, "production_countries.iso_3166_1": "US"}},
            # the example title is the best known movie of each language
            {"$sort": {"vote_count": -1, "_id": 1}},
            {"$group": {
                "_id": "$original_language",
                "movies": {"$sum": 1},
                "example": {"$first": "$title"},
                # the cleaning added original_language to spoken_languages when it was missing
                "language": {"$first": {"$arrayElemAt": [
                    "$spoken_languages.name",
                    {"$indexOfArray": ["$spoken_languages.iso_639_1", "$original_language"]}]}},
            }},
            {"$sort": {"movies": -1, "_id": 1}},
            {"$limit": 10},
        ]
        rows = [[l["_id"], l["language"], l["movies"], l["example"]] for l in self.movies.aggregate(pipeline)]
        show(rows, ["original_language", "name", "movies", "example title"])

    def query_10(self):
        """Ratings count, population variance and distinct genres of every user"""
        pipeline = [
            {"$group": {
                "_id": "$user_id",
                "ratings": {"$sum": 1},
                "std": {"$stdDevPop": "$rating"},
                "movies": {"$push": "$movie_id"},
            }},
        ]
        users = self.ratings.aggregate(pipeline, allowDiskUse=True)
        # the genres are in movies: a dictionary lookup in Python is much cheaper than a $lookup
        # for each of the 26 million ratings
        genres_of = {m["_id"]: [g["name"] for g in m["genres"]] for m in self.movies.find({}, {"genres.name": 1})}

        stats = []
        total = 0
        for user in users:
            total += 1
            if user["ratings"] < 20:
                continue
            genres = set()
            for movie in user["movies"]:
                genres.update(genres_of[movie])
            stats.append((user["_id"], user["ratings"], user["std"] ** 2, len(genres)))

        print("Users: %d, with at least 20 ratings: %d\n" % (total, len(stats)))
        headers = ["user_id", "ratings", "variance", "distinct genres"]
        # no thousands separator in the user ids
        intfmt = ["", ",", ",", ","]
        most_genres = max(s[3] for s in stats)
        print("Top 10 most genre-diverse users (%d users rated all the %d genres, ties broken by ratings count)"
              % (sum(1 for s in stats if s[3] == most_genres), most_genres))
        show(sorted(stats, key=lambda s: (-s[3], -s[1]))[:10], headers, intfmt)
        # the highest possible variance is 5.0625: half of the ratings 0.5 and half 5
        print("\nTop 10 highest-variance users (ties broken by ratings count)")
        show(sorted(stats, key=lambda s: (-s[2], -s[1]))[:10], headers, intfmt)


QUERIES = range(1, 11)


def main():
    parser = argparse.ArgumentParser(description="Runs the queries of Part 2")
    parser.add_argument("queries", nargs="*", type=int, choices=QUERIES, metavar="N",
                        help="numbers of the queries to run (1-10), all if omitted")
    args = parser.parse_args()

    program = None
    try:
        program = QueryRunner()
        for n in args.queries or QUERIES:
            query = getattr(program, "query_%d" % n)
            print("\n=== Query %d: %s ===\n" % (n, query.__doc__))
            start = time.time()
            query()
            print("\n(%.1f seconds)" % (time.time() - start))
    except Exception as e:
        print("ERROR: Failed to run the queries:", e)
        raise
    finally:
        if program:
            program.connection.close_connection()


if __name__ == '__main__':
    main()
