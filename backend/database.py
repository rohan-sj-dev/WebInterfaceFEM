import os
from contextlib import contextmanager

# Database configuration
# Defaults to SQLite for local development
DATABASE_URL = os.getenv('DATABASE_URL', 'users.db')

def is_postgres_db():
    """Check if using PostgreSQL"""
    return DATABASE_URL.startswith('postgresql://') or DATABASE_URL.startswith('postgres://')

def get_db_connection():
    """Get database connection - supports both SQLite and PostgreSQL"""
    if is_postgres_db():
        # PostgreSQL connection (for Render)
        import psycopg2
        from urllib.parse import urlparse
        
        # Fix for Render's postgres:// URL (needs to be postgresql://)
        db_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        result = urlparse(db_url)
        
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
        return conn
    else:
        # SQLite connection (for local development)
        import sqlite3
        conn = sqlite3.connect(DATABASE_URL)
        conn.row_factory = sqlite3.Row
        return conn

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_db():
    """Initialize database tables"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Create users table
        if is_postgres_db():
            # PostgreSQL syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    full_name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        else:
            # SQLite syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        conn.commit()
        print(f"✓ Database initialized successfully ({'PostgreSQL' if is_postgres_db() else 'SQLite'})")

if __name__ == '__main__':
    init_db()
