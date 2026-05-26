import sqlite3
import hashlib

def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_connection():
    conn = sqlite3.connect("favoritos.db")
    conn.row_factory = sqlite3.Row
    return conn

def inicializar_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Tabla Usuarios (Ahora soporta foto de perfil)
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0, profile_pic TEXT)")
    
    # Tablas de Películas
    cursor.execute("CREATE TABLE IF NOT EXISTS favoritos (id INTEGER PRIMARY KEY, user_id INTEGER, movie_id INTEGER, title TEXT, poster_url TEXT, genre_id INTEGER, genre_name TEXT, UNIQUE(user_id, movie_id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS pendientes (id INTEGER PRIMARY KEY, user_id INTEGER, movie_id INTEGER, title TEXT, poster_url TEXT, UNIQUE(user_id, movie_id))")
    
    # NUEVA: Tabla de Comentarios
    cursor.execute("CREATE TABLE IF NOT EXISTS comentarios (id INTEGER PRIMARY KEY, movie_id INTEGER, user_id INTEGER, username TEXT, comentario TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, 1)", ("admin", hash_password("admin123")))
    
    conn.commit()
    conn.close()