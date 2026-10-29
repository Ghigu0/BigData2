# Big Data Assignment 3 – The Movies Dataset (MongoDB)

This repository contains the implementation developed for Assignment 3 of **TDT4225 – Very Large, Distributed Data Volumes**, based on **The Movies Dataset** (TMDB metadata + MovieLens ratings).

The project covers an exploratory data analysis (EDA) of the original CSV files, the design of a MongoDB document schema, the cleaning and insertion of the data, and a set of 10 analytical queries written as aggregation pipelines.

## Project structure

```text
DbConnector.py                  connection to MongoDB (local Docker or NTNU VM)
example.py                      example file provided with the assignment
requirements.txt                Python dependencies

EDA/                            exploratory analysis scripts and notes, one folder per CSV file
Structure/create_structure.py   creates the collections with their JSON Schema validators and indexes
Structure/db_structure.txt      schema design and design choices

Population_script/cleaning.py   cleaning rules, one function per rule
Population_script/populate.py   reads the CSVs, cleans them and populates MongoDB
Population_script/cleaning_report.txt   cleaning report with all the counts

Query/queries.py                the 10 queries of Part 2
Query/query_notes.txt           explanation of every query and of the choices made

data/                           the dataset CSV files (not tracked by git)
```

The dataset is not included in the repository. 
It can be downloaded from Kaggle: 
[The Movies Dataset](https://www.kaggle.com/datasets/rounakbanik/the-movies-dataset).
The CSV files must be placed in the `data/` folder:

```text
credits.csv
keywords.csv
links.csv
links_small.csv
movies_metadata.csv
ratings.csv
ratings_small.csv
```

### `DbConnector.py`

This file manages the connection to MongoDB.

When a script starts, the user can choose where to execute the project:

```text
1 - Local MongoDB (docker)
2 - NTNU VM
```

- **Option 1** connects to a local MongoDB instance running inside Docker.
- **Option 2** connects to the MongoDB database hosted on the NTNU virtual machine.


## Setup

Install the dependencies (Python 3, preferably inside a virtual environment):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Local MongoDB with Docker

For local execution, the project expects a MongoDB 7.0.1 container available on:

```text
host: localhost
port: 27017
database: gruppo_25
user: root
password: root
```

A compatible Docker container can be created with:

```bash
docker run --name movies-mongo \
  -e MONGO_INITDB_ROOT_USERNAME=root \
  -e MONGO_INITDB_ROOT_PASSWORD=root \
  -p 27017:27017 \
  -v movies-mongo-data:/data/db \
  -d mongo:7.0.1
```

The Docker volume keeps the database persistent even if the container is stopped or removed.


## How to run

All commands are run from the root folder of the project.

```bash
# 1. (optional) create the collections with their validators and indexes
python Structure/create_structure.py --indexes

# 2. clean the CSV files and populate the database
python Population_script/populate.py --small    # quick test with ratings_small and links_small (~1 minute)
python Population_script/populate.py            # full dataset (~7 minutes)

# 3. run the 10 queries of Part 2 (database already populated)
python Query/queries.py                         # ~1.5 minutes on the full dataset
```

`populate.py` drops and recreates the `movies` and `ratings` collections by itself and builds the indexes at the end, so it can be run directly, even multiple times, without running `create_structure.py` first.

The database can be inspected from the MongoDB shell inside the container:

```bash
docker exec -it movies-mongo mongosh -u root -p root --authenticationDatabase admin gruppo_25
```


## Database structure

MongoDB has no joins and no foreign keys, so relationships are modelled either with **embedding** (related data stored inside the parent document) or with **referencing** (only the id of the other document is stored).

Almost all the queries of Part 2 start from the movie (directors, actors, genres, collection, languages, overview), so the database is composed of two collections:

- `movies` – about 45,400 documents, one per movie (TMDB);
- `ratings` – about 26 million documents, one per rating (MovieLens).

```text
movies 1 ---- N ratings        (ratings.movie_id = movies._id)
```

### `movies`

One document per movie, merging `movies_metadata.csv`, `credits.csv`, `keywords.csv` and the MovieLens id from `links.csv`.

- `_id` is the **TMDB id** of the movie instead of an automatic `ObjectId`: it is already unique and it is the key used by every file of the dataset.
- Simple fields: `title`, `original_title`, `original_language`, `overview`, `tagline`, `status`, `adult`, `video`, `budget`, `revenue`, `runtime`, `popularity`, `vote_average`, `vote_count`, `release_date`, `homepage`, `poster_path`, `imdb_id`, `movielens_id`.
- Embedded fields: `genres`, `production_companies`, `production_countries`, `spoken_languages`, `belongs_to_collection`, `keywords`, `cast`, `crew`.

Cast, crew, keywords and genres are **embedded** because:

1. they are *one-to-few* relationships

2. they are always read together with the movie:

3. the dataset is static, so repeating the name and gender of a person in every movie does not create update anomalies.


### `ratings`

One document per rating, from the full `ratings.csv`:

Ratings are **referenced** and not embedded because movies → ratings is a *one-to-squillions* relationship (a single movie has up to 91,921 ratings). Embedding about 1.7 GB of ratings inside `movies` would make every other query about 10 times slower, and query 10 groups ratings by user, not by movie.

During loading, `movieId` (MovieLens) is translated into the TMDB id through `links.csv`: `ratings.movieId → links.movieId → links.tmdbId = movies._id`.

### Indexes

Besides the automatic index on `_id`, three indexes are created (defined in `Structure/create_structure.py`):

| Collection | Index | Keys | Why |
|------------|-------|------|-----|
| `movies` | `overview_tagline_text` | `{overview: "text", tagline: "text"}` | text index for query 7 ("noir" / "neo-noir"): `$text` only works with a text index, and MongoDB allows only one per collection, so it covers both fields |
| `ratings` | `user_id` | `{user_id: 1}` | query 10 groups the ratings by user |
| `ratings` | `movie_id` | `{movie_id: 1}` | finding the ratings of a movie and linking them to `movies` |

The `_id` of `movies` is the TMDB id, so looking up a movie by id (e.g. from `ratings.movie_id`) already uses the default `_id` index.

The indexes are created by `populate.py` after all the documents have been inserted, because inserting 26 million ratings is faster without secondary indexes to update. They can also be created on an existing database with `python Structure/create_structure.py --indexes`.


## EDA scripts

The `EDA` folder contains one sub-folder of scripts for each CSV file (`movies_metadata`, `credits`, `keywords`, `links`, `ratings`) and one notes file (`EDA_<file>`) describing every column and the problems found.

The exploratory analysis includes checks such as:

- structure of each file, column types and missing values;
- rows broken in two by an unquoted newline inside `overview`;
- duplicated ids, and whether the copies are identical or conflicting;
- `0` values used to mean "unknown" in `budget`, `revenue` and `runtime`, and implausible values (e.g. a budget of 5 dollars);
- placeholder overviews such as `"No overview found."`;
- spoken languages with an empty name;
- people with different names or genders in different movies, and duplicated cast entries;
- keywords with leading/trailing spaces and the same word under two ids;
- MovieLens ids without a TMDB id, or with a TMDB id shared by several movies;
- logical inconsistencies (e.g. ratings given before the release date, `Rumored` movies with past release dates).

The results of this analysis were used to design the schema and to decide how invalid, incomplete and duplicated records should be handled during population.

## Data cleaning and population

`cleaning.py` contains one function per cleaning rule, and every rule counts how many rows or values it modifies. These counts are printed at the end of `populate.py` in a **Cleaning summary**, and are explained in detail in `Population_script/cleaning_report.txt`.

General conventions:

- a missing single value becomes `null` (the field is always present, so all documents have the same shape);
- an empty list becomes `[]`;
- strings are stripped of leading and trailing spaces, tabs and `\xa0`, and an empty string becomes `null`;
- `gender`: `1` = female, `2` = male, `null` = not specified (TMDB's `0`);
- dates are stored as MongoDB `Date` values.

Main cleaning rules:

- **broken rows**: 3 movies split over two lines are stitched back together;
- **duplicated ids**: the last copy in the file is kept for `movies_metadata`, one copy for `keywords` and `credits`;
- **budget and revenue**: `0` and values between 1 and 999 become `null`;
- **runtime**: `0` becomes `null`;
- **vote_average**: `0` with at least one vote becomes `null`;
- **placeholder overviews** become `null`, so that the text search of query 7 does not match them;
- **spoken languages**: empty language names are rebuilt from the ISO code, and `original_language` is added when missing;
- **keywords**: names are stripped and the same word under two ids is merged;
- **people**: a single name and a single gender are chosen for each person id;
- **links**: MovieLens ids without a TMDB id, pointing to movies not in the dataset, or wrongly sharing a TMDB id are discarded, together with their ratings (49,767 ratings, about 0.19%).

The insertion order is: cleaning of the movie files, cleaning of the links, drop and creation of the collections with their validators, insertion of the movies, insertion of the ratings in batches of 1 million rows, and finally creation of the indexes (inserting 26 million documents without indexes is faster).

Final result:

```text
movies     45,433 documents
ratings    25,974,522 documents
```

## Query script

`Query/queries.py` contains the 10 analytical tasks required by the assignment, one method per query (`query_1` … `query_10`).

Every question requires grouping, counting, averages, medians or rankings, so every query is written as an **aggregation pipeline** (`$match`, `$project`, `$unwind`, `$group`, `$sort`, `$limit`, …). Thanks to embedding, queries 1–9 work on the `movies` collection only, without any `$lookup`.

| Query | Question |
|-------|----------|
| Q1 | Top 10 directors (≥ 5 movies) by median revenue |
| Q2 | Actor pairs who co-starred in ≥ 3 movies |
| Q3 | Top 10 actors (≥ 10 movies) with the widest genre breadth |
| Q4 | Top 10 collections (≥ 3 movies) by total revenue |
| Q5 | Median runtime by decade and primary genre |
| Q6 | Proportion of women among the top-billed 5 cast, by decade |
| Q7 | Top 20 "noir" / "neo-noir" movies (text search) by vote_average |
| Q8 | Top 20 director–actor pairs (≥ 3 collaborations) by mean vote_average |
| Q9 | Top 10 non-English original languages among US-produced movies |
| Q10 | Per-user ratings count, variance and distinct genres |


A detailed explanation of every pipeline, stage by stage, with the reasoning and the results, is in `Query/query_notes.txt`.

## Notes

On the local Docker container, query 2 takes about 50 seconds (6.5 million intermediate actor pairs) and query 10 about 23 seconds; all the other queries run in less than 3 seconds. Execution times on the NTNU VM are longer, since the virtual machine has limited resources.
