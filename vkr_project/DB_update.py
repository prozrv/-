import csv
import sqlite3

def create_db(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        code INTEGER NOT NULL,
        tx_len INTEGER NOT NULL,
        rx_len INTEGER NOT NULL,
        description TEXT
    )
    """)
    conn.commit()
    return conn

def import_csv_to_db(csv_file, conn):
    cur = conn.cursor()
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute("""
                INSERT OR REPLACE INTO commands (name, code, tx_len, rx_len, description)
                VALUES (?, ?, ?, ?, ?)
            """, (
                row['name'],
                int(row['code']),
                int(row['tx_len']),
                int(row['rx_len']),
                row['description']
            ))
    conn.commit()

def main():
    db_path = "commands.db"
    csv_file = "commands.csv"
    conn = create_db(db_path)
    import_csv_to_db(csv_file, conn)
    print("✅ Импорт из CSV выполнен успешно!")
    conn.close()

if __name__ == "__main__":
    main()
