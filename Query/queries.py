import sys
import time
from pathlib import Path
from pprint import pprint
sys.path.append(str(Path(__file__).resolve().parents[1]))
from tabulate import tabulate
from DbConnector import DbConnector


"""
Exact median of an array, ignoring null values.
MongoDB's $median is approximate: for [1, 2, 3, 4] it returns 2 instead of 2.5.
"""

def median(values):
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


'''
takes the year of the date, divides it by 10, rounds it down and multiplies it by 10 again, so 1995 becomes 1990. Queries 5 and 6 use it to group films by decade.
'''
def decade(date_field):
    return {"$multiply": [{"$floor": {"$divide": [{"$year": date_field}, 10]}}, 10]}


'''
keeps only id and name of each person in a film's cast or crew list and removes duplicates. With condition the list can be filtered first, for example to keep only the directors (job = "Director"). Duplicates must go because an actor who plays two characters in the same film appears twice in the list, and that film would otherwise be counted twice for them.
'''
def people(array, condition=None):
    """Distinct {id, name} of the people in cast or crew: an actor with two characters in the same
    film appears there twice, but the film must be counted once"""
    if condition:
        array = {"$filter": {"input": array, "cond": condition}}
    return {"$setUnion": [{"$map": {"input": array, "in": {"id": "$$this.id", "name": "$$this.name"}}}]}


DIRECTORS = people("$crew", {"$eq": ["$$this.job", "Director"]})
ACTORS = people("$cast")


'''
prints the query results as a table using tabulate. Integers get thousands separators (1,234,567) and decimals are rounded to 2 digits. Pass a different intfmt when an integer column should not be formatted, such as years or ids, so 1995 does not print as 1,995.
'''
def show(rows, headers, intfmt=","):
    print(tabulate(rows, headers=headers, tablefmt="simple", intfmt=intfmt, floatfmt=",.2f"))


'''
prints the documents exactly as MongoDB returns them, with pprint as the assignment asks: field names and
values are not changed or formatted. One document per line when it fits, fields in the order of the pipeline.
'''
def show_raw(documents):
    print("Raw output (pprint):")
    for document in documents:
        pprint(document, width=120, sort_dicts=False)
    print("\nTable (tabulate):")


'''
 MongoDB returns dates as datetime values that include the time (1995-10-30 00:00:00). This function keeps only the date. Query 4 uses it to print the first and last release of each collection. If the date is missing it returns None instead of raising an error.
 '''
def day(date):
    return date.strftime("%Y-%m-%d") if date else None


class QueryRunner:

    def __init__(self):
        self.connection = DbConnector()
        self.db = self.connection.db
        self.movies = self.db["movies"]
        self.ratings = self.db["ratings"]


    def query_1(self):
        """Top 10 directors (>= 5 movies with revenue) by median revenue"""
        
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

        directors = list(self.movies.aggregate(pipeline))
        show_raw(directors)

        #pprint stamp
        rows = [[d["name"], d["movies"], d["movies_with_revenue"], d["median_revenue"], d["mean_vote_average"]]
                for d in directors]

        #tabulate stamp
        show(rows, ["director", "movies", "movies with revenue", "median revenue (USD)", "mean vote_average"])


    '''
    List actor pairs have co-starred in ≥ 3 movies together, their number of co-appearances, and their average movie vote_average. Sort by number of co-appearances.
    '''
    def query_2(self):
        """Actor pairs who co-starred in >= 3 movies, by number of co-appearances"""
      
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

        # the double $unwind creates about 6.5 million actor pairs: more than the 100 MB of RAM
        # a stage can use, so allowDiskUse lets MongoDB write temporary files to disk
        pairs = list(self.movies.aggregate(pipeline, allowDiskUse=True))
        print("Only the first 20 actor pairs are shown, out of a total of %d pairs with at least 3 movies together\n" % len(pairs))

        #pprint stamp
        show_raw(pairs[:20])

         #tabulate stamp
        show([[p["actor_a"], p["actor_b"], p["movies"], p["mean_vote_average"]] for p in pairs[:20]],
             ["actor", "actor", "co-appearances", "mean vote_average"])


    '''
     List the top 10 actors (with ≥ 10 credited movies) that have the widest genre breadth. Report the actor, the number of distinct genres they've appeared in, and up to 5 example genres.
    '''
    def query_3(self):
        """Top 10 actors (>= 10 movies) with the widest genre breadth"""
  
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
        show_raw(actors[:10])
        show([[a["name"], a["movies"], a["genre_count"], ", ".join(a["examples"])] for a in actors[:10]],
             ["actor", "movies", "distinct genres", "most frequent genres"])

    '''
    For film collections (belongs_to_collection.name not null) with ≥ 3 movies, which 10 collections have the largest total revenue?
    For each, report movie count, total revenue, median vote_average, and the earliest → latest release date.
    '''
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
        collections = list(self.movies.aggregate(pipeline))
        show_raw(collections)
        rows = [[c["name"], c["movies"], c["movies_with_revenue"], c["total_revenue"], c["median_vote_average"],
                 "%s -> %s" % (day(c["first"]), day(c["last"]))]
                for c in collections]
        show(rows, ["collection", "movies", "movies with revenue", "total revenue (USD)",
                    "median vote_average", "release dates"])

    '''
    By decade (e.g., 1970s, 1980s, ...) and primary genre (first element in genres),
    what is the median runtime and movie count?​
    List results sorted by decade then median runtime (desc).
    '''
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
        groups = list(self.movies.aggregate(pipeline))
        show_raw(groups)
        rows = [["%ds" % g["_id"]["decade"], g["_id"]["genre"], g["median_runtime"], g["movies"]] for g in groups]
        show(rows, ["decade", "primary genre", "median runtime (min)", "movies"])


    '''
    For each movie’s top-billed 5 cast (by order), what is the proportion of female
    cast?​
    Aggregate by decade and list decades sorted by average female proportion
    (desc), including movie counts used. Unknown gender may be ignored.
    '''
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
        decades = list(self.movies.aggregate(pipeline))
        show_raw(decades)
        rows = [["%ds" % d["_id"], d["female_proportion"], d["movies"]] for d in decades]
        show(rows, ["decade", "mean female proportion", "movies"])

    '''
    Using a text search over overview and tagline, which 20 movies matching “noir”
    or “neo-noir” (and vote_count ≥ 50) have the highest vote_average?​
    Return title, year, vote_average, and vote_count.
    '''
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
        movies = list(self.movies.aggregate(pipeline))
        show_raw(movies)
        rows = [[m["title"], m["year"], m["vote_average"], m["vote_count"]] for m in movies]
        # no thousands separator, or the years would be printed as 1,960
        show(rows, ["title", "year", "vote_average", "vote_count"], intfmt="")

    '''
    Which 20 director–actor pairs with ≥ 3 collaborations (same movie) have the
    highest mean vote_average, considering only movies with vote_count ≥ 100?​
    Include the pair’s films count and mean revenue.​
    '''
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
        pairs = list(self.movies.aggregate(pipeline, allowDiskUse=True))
        show_raw(pairs)
        rows = [[p["director"], p["actor"], p["movies"], p["mean_vote_average"], p["movies_with_revenue"],
                 p["mean_revenue"]]
                for p in pairs]
        show(rows, ["director", "actor", "movies", "mean vote_average", "movies with revenue", "mean revenue (USD)"])

    '''
    Among movies where original_language ≠ "en" but at least one production
    company or country is United States, which are the top 10 original languages by
    count?​
    For each language, report the count and one example title.
    '''
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
        languages = list(self.movies.aggregate(pipeline))
        show_raw(languages)
        rows = [[l["_id"], l["language"], l["movies"], l["example"]] for l in languages]
        show(rows, ["original_language", "name", "movies", "example title"])

    '''
    For each user, what is their ratings count, population variance of ratings, and
    number of distinct genres rated?​
    List the top 10 most genre-diverse users, and separately the top 10
    highest-variance users (only users with ≥ 20 ratings).
    '''
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
        top = sorted(stats, key=lambda s: (-s[3], -s[1]))[:10]
        # the documents of MongoDB contain the list of all the movies rated by the user (up to 18,276):
        # the raw output shows the final values, after the genres have been counted in Python
        show_raw([dict(zip(headers, s)) for s in top])
        show(top, headers, intfmt)
        # the highest possible variance is 5.0625: half of the ratings 0.5 and half 5
        print("\nTop 10 highest-variance users (ties broken by ratings count)")
        top = sorted(stats, key=lambda s: (-s[2], -s[1]))[:10]
        show_raw([dict(zip(headers, s)) for s in top])
        show(top, headers, intfmt)


QUERIES = range(1, 11)


def main():
    program = None
    try:
        program = QueryRunner()
        for n in QUERIES:
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
