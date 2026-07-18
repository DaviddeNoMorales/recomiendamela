import os
import psycopg
from psycopg.rows import dict_row

# Recupera la URL de la base de datos desde las variables de entorno de Render
DATABASE_URL = os.getenv("DATABASE_URL")

class PgConnectionWrapper:
    """
    Este envoltorio simula el comportamiento de SQLite para PostgreSQL usando el moderno Psycopg 3.
    Traduce automáticamente los '?' a '%s' para que no tengas que reescribir tus rutas.
    """
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=None):
        # Convertimos la sintaxis de variables
        pg_query = query.replace('?', '%s')
        
        # En psycopg 3, el formato de diccionario se pide al crear el cursor
        cursor = self.conn.cursor(row_factory=dict_row)
        
        if params:
            cursor.execute(pg_query, params)
        else:
            cursor.execute(pg_query)
            
        return cursor

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("CRÍTICO: No se ha configurado la variable de entorno DATABASE_URL.")
    
    conn = psycopg.connect(DATABASE_URL)
    return PgConnectionWrapper(conn)

def inicializar_db():
    if not DATABASE_URL:
        print("Aviso: DATABASE_URL no detectada. Omitiendo inicialización de PostgreSQL.")
        return

    conn = psycopg.connect(DATABASE_URL)
    c = conn.cursor()
    
    # 1. Tabla de Usuarios
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE,
            profile_pic TEXT,
            is_admin INTEGER DEFAULT 0,
            is_verified INTEGER DEFAULT 0,
            verification_token VARCHAR(255)
        )
    ''')
    
    # 2. Tabla de Favoritos
    c.execute('''
        CREATE TABLE IF NOT EXISTS favoritos (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            movie_id VARCHAR(255) NOT NULL,
            title VARCHAR(255) NOT NULL,
            poster_url TEXT,
            genre_id VARCHAR(255),
            genre_name VARCHAR(255)
        )
    ''')
    
    # 3. Tabla de Pendientes
    c.execute('''
        CREATE TABLE IF NOT EXISTS pendientes (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            movie_id VARCHAR(255) NOT NULL,
            title VARCHAR(255) NOT NULL,
            poster_url TEXT
        )
    ''')
    
    # 4. Tabla de Comentarios
    c.execute('''
        CREATE TABLE IF NOT EXISTS comentarios (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            movie_id VARCHAR(255) NOT NULL,
            comentario TEXT NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("PostgreSQL inicializado correctamente con Psycopg 3.")
    
    import hashlib

def hash_password(password: str) -> str:
    """Convierte una contraseña a formato hash SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()