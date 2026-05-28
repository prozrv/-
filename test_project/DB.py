import sqlite3
import csv

class CommandDB:
    """Класс для управления базой данных команд (SQLite)."""
    def __init__(self, db_path="commands.db", csv_path = "commands.csv"):
        self.conn = self.create_db(db_path)
        self.import_csv_to_db(csv_path)
        
    def create_db(self, db_path):
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

    def import_csv_to_db(self, csv_file):
        cur = self.conn.cursor()
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
        self.conn.commit()

    def get_command_by_name(self, name: str):
        """Возвращает словарь с параметрами команды по её имени."""
        cur = self.conn.cursor()
        cur.execute("SELECT code, tx_len, rx_len FROM commands WHERE name=?", (name,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Команда '{name}' не найдена в базе данных.")
        return {"code": int(row[0]), "tx_len": int(row[1]), "rx_len": int(row[2])}

    def list_commands(self):
        """Выводит список всех команд (для отладки)."""
        cur = self.conn.cursor()
        cur.execute("SELECT name, code, tx_len, rx_len, description FROM commands")
        return cur.fetchall()

    def close(self):
        self.conn.close()