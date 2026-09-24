import psycopg2
import psycopg2.extras

def get_conn():
    return psycopg2.connect(
        host="127.0.0.1",
        dbname="eda_platform",
        user="postgres",
        password="postgres",
    )
