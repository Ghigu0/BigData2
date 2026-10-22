import os
from urllib.parse import quote_plus

from pymongo import MongoClient


class DbConnector:
    """
    Connects to MongoDB, either on a local docker container or on the NTNU VM.
    The container is meant to be created like this (same MongoDB version as the VM):
    docker run --name movies-mongo \
        -e MONGO_INITDB_ROOT_USERNAME=root \
        -e MONGO_INITDB_ROOT_PASSWORD=root \
        -p 27017:27017 \
        -v movies-mongo-data:/data/db \
        -d mongo:7.0.1

    Every connection parameter can be overridden with an environment variable
    (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_AUTH_SOURCE), so each of us
    can use a different host/port without editing this file, e.g.:
        DB_PORT=27018 python example.py
    """

    def __init__(self):

        print("Choose where to run the program:")
        print("1 - Local MongoDB (docker)")
        print("2 - NTNU VM")

        choice = input("Enter 1 or 2: ")

        if choice == "1":
            HOST = "localhost"
            DATABASE = "gruppo_25"
            USER = "root"
            PASSWORD = "root"
            # the root user of the container is created in the admin database
            AUTH_SOURCE = "admin"

        elif choice == "2":
            HOST = "tdt4225-25.idi.ntnu.no"
            DATABASE = "gruppo_25"
            USER = "gruppo25"
            PASSWORD = "gruppo25"
            AUTH_SOURCE = DATABASE

        else:
            raise ValueError("Invalid choice. Please enter 1 or 2.")

        HOST = os.getenv("DB_HOST", HOST)
        PORT = int(os.getenv("DB_PORT", "27017"))
        DATABASE = os.getenv("DB_NAME", DATABASE)
        USER = os.getenv("DB_USER", USER)
        PASSWORD = os.getenv("DB_PASSWORD", PASSWORD)
        AUTH_SOURCE = os.getenv("DB_AUTH_SOURCE", AUTH_SOURCE)

        uri = "mongodb://%s:%s@%s:%d/%s?authSource=%s" % (
            quote_plus(USER), quote_plus(PASSWORD), HOST, PORT, DATABASE, AUTH_SOURCE)

        # Connect to the database
        # MongoClient connects lazily, so ping the server to check that it is reachable
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.client.admin.command("ping")
            self.db = self.client[DATABASE]
        except Exception as e:
            print("ERROR: Failed to connect to db:", e)
            raise

        print("Connected to MongoDB", self.client.server_info()["version"], "on %s:%d" % (HOST, PORT))
        # get database information
        print("You are connected to the database:", self.db.name)
        print("-----------------------------------------------\n")

    def close_connection(self):
        # close the DB connection
        self.client.close()
        print("\n-----------------------------------------------")
        print("Connection to %s-db is closed" % self.db.name)
