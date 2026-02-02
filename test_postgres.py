import psycopg2

DB_PARAMS = {
    "host": "localhost",
    "database": "profiling_jobs",
    "user": "postgres",
    "password": "postgres",
    "port": 5433
}

def test_connection():
    print("Connecting to PostgreSQL...")
    
    conn = psycopg2.connect(**DB_PARAMS)
    print("Connection successful!")

    cur = conn.cursor()
    cur.execute("SELECT 1;")
    result = cur.fetchone()

    print("Query result:", result)

    cur.close()
    conn.close()
    print("Connection closed.")

if __name__ == "__main__":
    test_connection()
