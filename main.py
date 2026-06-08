import os
import shutil
import requests
import re
import time
import datetime
from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import urllib.parse
import random

from database import inicializar_db, get_db_connection
from tmdb_api import *
from routes_auth import router as auth_router
from routes_acciones import router as acciones_router

app = FastAPI()

os.makedirs("static/avatars", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
inicializar_db()
app.include_router(auth_router)
app.include_router(acciones_router)

# --- FASE 3: FUNCIONES DE GOOGLE BOOKS (LIBROS Y CÓMICS) ---
def buscar_libros(query: str):
    url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}&maxResults=10&langRestrict=es"
    try:
        r = requests.get(url).json()
        items = r.get('items', [])
        libros = []
        for item in items:
            info = item.get('volumeInfo', {})
            if 'imageLinks' in info and 'thumbnail' in info['imageLinks']:
                # Forzamos HTTPS para evitar bloqueos de seguridad en el navegador
                poster = info['imageLinks']['thumbnail'].replace('http:', 'https:')
                libros.append({
                    'id': item['id'],
                    'title': info.get('title', 'Sin título'),
                    'release_date': info.get('publishedDate', '')[:4],
                    'poster_url': poster,
                    'media_type': 'book'
                })
        return libros
    except Exception as e:
        print("Error buscando libros:", e)
        return []

def obtener_detalles_libro(book_id: str):
    url = f"https://www.googleapis.com/books/v1/volumes/{book_id}"
    try:
        r = requests.get(url).json()
        if 'volumeInfo' in r:
            info = r['volumeInfo']
            libro = {
                'id': r['id'],
                'title': info.get('title', 'Sin título'),
                'overview': info.get('description', 'No hay sinopsis disponible para este libro.'),
                # Google Books puntúa sobre 5, multiplicamos por 2 para mantener la nota sobre 10
                'vote_average': info.get('averageRating', 0) * 2,
                'fuente_nota': 'Google Books',
                'release_date': info.get('publishedDate', '')[:4],
                'media_type': 'book',
            }
            if 'imageLinks' in info and 'thumbnail' in info['imageLinks']:
                img_url = info['imageLinks']['thumbnail'].replace('http:', 'https:').replace('&edge=curl', '')
                libro['poster_url'] = img_url
                libro['backdrop_url'] = img_url
            else:
                libro['poster_url'] = None
                libro['backdrop_url'] = None
            return libro
        return None
    except Exception as e:
        print("Error obteniendo detalles del libro:", e)
        return None


# --- FASE 2: FUNCIONES IGDB (VIDEOJUEGOS) ---
IGDB_TOKEN = None
IGDB_TOKEN_EXPIRY = 0

def get_igdb_token():
    global IGDB_TOKEN, IGDB_TOKEN_EXPIRY
    if time.time() < IGDB_TOKEN_EXPIRY and IGDB_TOKEN:
        return IGDB_TOKEN
    client_id = os.getenv('IGDB_CLIENT_ID')
    client_secret = os.getenv('IGDB_CLIENT_SECRET')
    if not client_id or not client_secret:
        return None
    url = f"https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials"
    try:
        r = requests.post(url).json()
        IGDB_TOKEN = r.get('access_token')
        IGDB_TOKEN_EXPIRY = time.time() + r.get('expires_in', 3600) - 60
        return IGDB_TOKEN
    except Exception as e:
        print("Error al obtener token de IGDB:", e)
        return None

def buscar_videojuegos(query: str):
    token = get_igdb_token()
    client_id = os.getenv('IGDB_CLIENT_ID')
    if not token or not client_id: 
        return []
    
    headers = {
        'Client-ID': client_id,
        'Authorization': f'Bearer {token}'
    }
    body = f'search "{query}"; fields name,cover.url,first_release_date; limit 10;'
    try:
        r = requests.post("https://api.igdb.com/v4/games", headers=headers, data=body).json()
        juegos = []
        if isinstance(r, list):
            for game in r:
                if 'cover' in game and 'url' in game['cover']:
                    game['media_type'] = 'game'
                    game['title'] = game.get('name')
                    if 'first_release_date' in game:
                        game['release_date'] = datetime.datetime.fromtimestamp(game['first_release_date']).strftime('%Y')
                    game['poster_url'] = "https:" + game['cover']['url'].replace('t_thumb', 't_cover_big')
                    juegos.append(game)
        return juegos
    except Exception as e:
        print("Error buscando videojuegos:", e)
        return []

def obtener_detalles_videojuego(game_id: str):
    token = get_igdb_token()
    client_id = os.getenv('IGDB_CLIENT_ID')
    if not token or not client_id: 
        return None
    
    headers = {
        'Client-ID': client_id,
        'Authorization': f'Bearer {token}'
    }
    body = f'fields name,summary,cover.url,artworks.url,first_release_date,rating,platforms.name; where id = {game_id};'
    try:
        r = requests.post("https://api.igdb.com/v4/games", headers=headers, data=body).json()
        if r and isinstance(r, list):
            game = r[0]
            game['title'] = game.get('name')
            game['overview'] = game.get('summary', 'No hay sinopsis disponible para este juego.')
            game['vote_average'] = round(game.get('rating', 0) / 10, 1) if 'rating' in game else 0
            game['fuente_nota'] = 'IGDB'
            if 'first_release_date' in game:
                game['release_date'] = datetime.datetime.fromtimestamp(game['first_release_date']).strftime('%Y')
            if 'cover' in game and 'url' in game['cover']:
                game['poster_url'] = "https:" + game['cover']['url'].replace('t_thumb', 't_1080p')
            if 'artworks' in game and game['artworks']:
                game['backdrop_url'] = "https:" + game['artworks'][0]['url'].replace('t_thumb', 't_1080p')
            else:
                game['backdrop_url'] = game.get('poster_url')
            
            game['plataformas_nombres'] = [p['name'] for p in game.get('platforms', [])]
            game['media_type'] = 'game'
            return game
        return None
    except Exception as e:
        print("Error obteniendo detalles del videojuego:", e)
        return None

# --- FASE 1: FUNCIONES TMDB/IMDb (CINE Y SERIES) ---
def obtener_nota_imdb(imdb_id: str):
    if not imdb_id:
        return None
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        url = f"https://www.imdb.com/title/{imdb_id}/"
        r = requests.get(url, headers=headers, timeout=5)
        match = re.search(r'"ratingValue":\s*"?([0-9.]+)"?', r.text)
        if match:
            return float(match.group(1))
    except Exception as e:
        print(f"Error al extraer la nota de IMDb para {imdb_id}:", e)
    return None

def buscar_multimedia(query: str):
    api_key = os.getenv('API_KEY')
    url = f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={urllib.parse.quote(query)}&language=es-ES"
    try:
        r = requests.get(url).json()
        results = r.get('results', [])
        filtrados = [res for res in results if res.get('media_type') in ['movie', 'tv']]
        return filtrados
    except Exception as e:
        print("Error en búsqueda múltiple:", e)
        return []

def obtener_detalles_tv(tv_id: str):
    api_key = os.getenv('API_KEY')
    url = f"https://api.themoviedb.org/3/tv/{tv_id}?api_key={api_key}&language=es-ES&append_to_response=videos,watch/providers,external_ids"
    try:
        res = requests.get(url).json()
        if 'id' in res:
            res['title'] = res.get('name')
            res['release_date'] = res.get('first_air_date')
            res['imdb_id'] = res.get('external_ids', {}).get('imdb_id')
            return res
        return None
    except Exception as e:
        return None

def obtener_similares_tv(tv_id: str):
    api_key = os.getenv('API_KEY')
    url = f"https://api.themoviedb.org/3/tv/{tv_id}/similar?api_key={api_key}&language=es-ES"
    try:
        res = requests.get(url).json()
        results = res.get('results', [])
        for r in results:
            r['title'] = r.get('name')
            r['release_date'] = r.get('first_air_date')
            r['media_type'] = 'tv'
        return results
    except Exception as e:
        return []

def obtener_enlace_directo(plataforma, titulo):
    q = urllib.parse.quote(titulo)
    links = {
        "Netflix": f"https://www.netflix.com/search?q={q}",
        "Amazon Prime Video": f"https://www.primevideo.com/search/ref=atv_sr_sfs_c_unkr?phrase={q}",
        "Disney+": f"https://www.disneyplus.com/search?q={q}",
        "Max": f"https://play.max.com/search?q={q}",
        "Apple TV Plus": f"https://tv.apple.com/es/search?term={q}",
        "Filmin": f"https://www.filmin.es/busqueda?q={q}",
        "Crunchyroll": f"https://www.crunchyroll.com/es/search?q={q}",
        "Movistar Plus+": f"https://ver.movistarplus.es/busqueda/?q={q}"
    }
    return links.get(plataforma, f"https://www.justwatch.com/es/busqueda?q={q}")

# --- RUTAS DE LA APLICACIÓN ---
@app.get("/", response_class=HTMLResponse)
# CAMBIO CLAVE: movie_id ahora es un string (str) para poder aceptar IDs de Google Books ("zyTCAlFPjgYC")
async def inicio(request: Request, query: str = None, movie_id: str = None, media_type: str = "movie"):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    peli, error, plataformas, trailer, is_fav, is_pen = None, False, [], None, False, False
    carrusel_titulo = ""
    carrusel_pelis = []
    
    resultados_busqueda_cine = []
    resultados_busqueda_juegos = []
    resultados_busqueda_libros = []
    modo_busqueda = False
    
    podcasts_links = []
    user_avatar = None
    mid = movie_id

    if user_id:
        conn = get_db_connection()
        usr = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        if usr and usr['profile_pic']:
            user_avatar = usr['profile_pic']
        else:
            user_avatar = f"https://ui-avatars.com/api/?name={username}&background=e50914&color=fff&rounded=true"

    if query:
        modo_busqueda = True
        
        # 1. Buscamos Películas/Series
        resultados_busqueda_cine = buscar_multimedia(query)
        for res in resultados_busqueda_cine:
            res['poster_url'] = f"https://image.tmdb.org/t/p/w342{res['poster_path']}" if res.get('poster_path') else ""
        
        # 2. Buscamos Videojuegos
        resultados_busqueda_juegos = buscar_videojuegos(query)
        
        # 3. Buscamos Libros/Cómics
        resultados_busqueda_libros = buscar_libros(query)

        if not resultados_busqueda_cine and not resultados_busqueda_juegos and not resultados_busqueda_libros:
            error = True

    elif not mid:
        if user_id:
            conn = get_db_connection()
            favs = conn.execute("SELECT DISTINCT genre_id FROM favoritos WHERE user_id = ?", (user_id,)).fetchall()
            conn.close()
            if favs:
                genre_ids = [str(f['genre_id']) for f in favs[:3]]
                carrusel_pelis = descubrir_por_generos(genre_ids)
                carrusel_titulo = "Recomendado para ti"
            else:
                carrusel_pelis = descubrir_por_generos(["27", "14"])
                carrusel_titulo = "Nuestra selección para empezar"
            for cp in carrusel_pelis:
                cp['media_type'] = 'movie'
        else:
            carrusel_pelis = obtener_populares()
            carrusel_titulo = "Tendencias Mundiales"
            for cp in carrusel_pelis:
                cp['media_type'] = 'movie'

        if carrusel_pelis:
            mid = str(random.choice(carrusel_pelis[:5])['id'])
            media_type = "movie"

    # Procesamiento del elemento activo según su tipo
    if mid and not modo_busqueda:
        if media_type == "game":
            peli = obtener_detalles_videojuego(mid)
            carrusel_pelis = [] 
            carrusel_titulo = ""
            
            if peli:
                titulo_url = urllib.parse.quote(peli['title'])
                podcasts_links = [
                    {"nombre": "Directos en Twitch", "link": f"https://www.twitch.tv/directory/search?term={titulo_url}", "color": "#9146FF", "icono": "🟪"},
                    {"nombre": "YouTube", "link": f"https://www.youtube.com/results?search_query={titulo_url}+gameplay+podcast", "color": "#FF0000", "icono": "▶️"}
                ]
                
        elif media_type == "book":
            peli = obtener_detalles_libro(mid)
            carrusel_pelis = [] 
            carrusel_titulo = ""
            
            if peli:
                titulo_url = urllib.parse.quote(peli['title'])
                # Enlaces dinámicos de tiendas para los libros
                podcasts_links = [
                    {"nombre": "Comprar en Amazon", "link": f"https://www.amazon.es/s?k={titulo_url}+libro", "color": "#232F3E", "icono": "🛒"},
                    {"nombre": "Casa del Libro", "link": f"https://www.casadellibro.com/?q={titulo_url}", "color": "#009966", "icono": "📖"},
                    {"nombre": "Norma Cómics", "link": f"https://www.normacomics.com/catalogsearch/result/?q={titulo_url}", "color": "#E50914", "icono": "📚"}
                ]
                
        else:
            if media_type == "tv":
                peli = obtener_detalles_tv(mid)
                if peli and movie_id:
                    carrusel_pelis = obtener_similares_tv(mid)
                    carrusel_titulo = f"Series similares a {peli.get('title')}"
            else:
                peli = obtener_detalles_pelicula(mid)
                if peli and movie_id:
                    carrusel_pelis = obtener_similares(mid)
                    carrusel_titulo = f"Películas similares a {peli.get('title')}"

            if peli:
                peli['poster_url'] = f"https://image.tmdb.org/t/p/w500{peli['poster_path']}" if peli.get('poster_path') else None
                peli['backdrop_url'] = f"https://image.tmdb.org/t/p/original{peli['backdrop_path']}" if peli.get('backdrop_path') else None
                peli['fuente_nota'] = 'IMDb'

                nota_real_imdb = obtener_nota_imdb(peli.get('imdb_id'))
                if nota_real_imdb:
                    peli['vote_average'] = nota_real_imdb
                else:
                    peli['vote_average'] = round(peli.get('vote_average', 0), 1)

                for cp in carrusel_pelis:
                    cp['poster_url'] = f"https://image.tmdb.org/t/p/w342{cp['poster_path']}" if cp.get('poster_path') else ""
                    if 'media_type' not in cp:
                        cp['media_type'] = media_type
                    
                watch_data = peli.get('watch/providers', {}).get('results', {}).get('ES', {})
                plataformas_crudas = watch_data.get('flatrate', [])
                plataformas_vistas = set()
                
                for plat in plataformas_crudas:
                    nombre = plat['provider_name']
                    if "Netflix" in nombre: nombre_base = "Netflix"
                    elif "Prime Video" in nombre or "Amazon" in nombre: nombre_base = "Amazon Prime Video"
                    elif "Disney" in nombre: nombre_base = "Disney+"
                    elif "Max" in nombre or "HBO" in nombre: nombre_base = "Max"
                    elif "Movistar" in nombre: nombre_base = "Movistar Plus+"
                    elif "Apple" in nombre: nombre_base = "Apple TV Plus"
                    elif "Filmin" in nombre: nombre_base = "Filmin"
                    elif "Crunchyroll" in nombre: nombre_base = "Crunchyroll"
                    elif "SkyShowtime" in nombre: nombre_base = "SkyShowtime"
                    else: nombre_base = nombre.split(' with ')[0].split(' con ')[0]
                    
                    if nombre_base not in plataformas_vistas:
                        plataformas_vistas.add(nombre_base)
                        plat['provider_name'] = nombre_base 
                        plat['direct_link'] = obtener_enlace_directo(nombre_base, peli['title'])
                        plataformas.append(plat)
                
                titulo_url = urllib.parse.quote(peli['title'])
                podcasts_links = [
                    {"nombre": "Spotify", "link": f"https://open.spotify.com/search/{titulo_url}", "color": "#1DB954", "icono": "🎧"},
                    {"nombre": "iVoox", "link": f"https://www.ivoox.com/{titulo_url}_sb.html?sb={titulo_url}", "color": "#FF6600", "icono": "🎙️"}
                ]
                
                for v in peli.get('videos', {}).get('results', []):
                    if v['type'] == 'Trailer': 
                        trailer = v['key']
                        break

        # Estado en BD de la película/juego/libro
        if peli and user_id:
            conn = get_db_connection()
            is_fav = bool(conn.execute("SELECT id FROM favoritos WHERE user_id=? AND movie_id=?", (user_id, mid)).fetchone())
            is_pen = bool(conn.execute("SELECT id FROM pendientes WHERE user_id=? AND movie_id=?", (user_id, mid)).fetchone())
            conn.close()
            
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user_id": user_id, 
            "username": username, 
            "user_avatar": user_avatar,
            "peli": peli, 
            "plataformas": plataformas, 
            "podcasts": podcasts_links, 
            "trailer": trailer, 
            "error": error, 
            "is_fav": is_fav, 
            "is_pen": is_pen,
            "carrusel_titulo": carrusel_titulo,
            "carrusel_pelis": carrusel_pelis,
            "resultados_busqueda_cine": resultados_busqueda_cine,
            "resultados_busqueda_juegos": resultados_busqueda_juegos,
            "resultados_busqueda_libros": resultados_busqueda_libros,
            "modo_busqueda": modo_busqueda,
            "query_actual": query,
            "media_type": media_type,
            "busqueda_activa": bool(movie_id)
        }
    )

@app.get("/foro/{movie_id}", response_class=HTMLResponse)
# También modificado a string para dar soporte al foro de los libros
async def foro_pelicula(request: Request, movie_id: str):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    user_avatar = None
    
    conn = get_db_connection()
    if user_id:
        usr = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
        if usr and usr['profile_pic']:
            user_avatar = usr['profile_pic']
        else:
            user_avatar = f"https://ui-avatars.com/api/?name={username}&background=e50914&color=fff&rounded=true"
            
    peli = obtener_detalles_pelicula(movie_id)
    if peli:
        peli['backdrop_url'] = f"https://image.tmdb.org/t/p/original{peli['backdrop_path']}" if peli.get('backdrop_path') else ""
        peli['poster_url'] = f"https://image.tmdb.org/t/p/w500{peli['poster_path']}" if peli.get('poster_path') else ""

    comentarios_db = conn.execute("""
        SELECT c.*, u.profile_pic 
        FROM comentarios c 
        LEFT JOIN users u ON c.user_id = u.id 
        WHERE c.movie_id = ? 
        ORDER BY c.fecha DESC
    """, (movie_id,)).fetchall()
    
    comentarios = []
    for c in comentarios_db:
        avatar = c['profile_pic'] if c['profile_pic'] else f"https://ui-avatars.com/api/?name={c['username']}&background=333&color=fff&rounded=true"
        comentarios.append({"username": c['username'], "comentario": c['comentario'], "fecha": c['fecha'][:16], "avatar": avatar})
        
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="foro.html",
        context={
            "user_id": user_id, 
            "username": username,
            "user_avatar": user_avatar,
            "peli": peli,
            "comentarios": comentarios
        }
    )

@app.get("/perfil", response_class=HTMLResponse)
async def perfil(request: Request):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    if not user_id: 
        return RedirectResponse(url="/", status_code=303)
        
    conn = get_db_connection()
    usr = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
    user_avatar = usr['profile_pic'] if usr and usr['profile_pic'] else f"https://ui-avatars.com/api/?name={username}&background=e50914&color=fff&rounded=true"

    favs = conn.execute("SELECT * FROM favoritos WHERE user_id = ?", (user_id,)).fetchall()
    pendientes = conn.execute("SELECT * FROM pendientes WHERE user_id = ?", (user_id,)).fetchall()
    usuarios = conn.execute("SELECT * FROM users WHERE is_admin = 1").fetchall() if request.cookies.get("is_admin") == "1" else []
    conn.close()
    
    fav_por_gen = {}
    for fav in favs:
        gen = fav['genre_name']
        if gen not in fav_por_gen: 
            lista_recom = obtener_recomendaciones(fav['movie_id'])
            if lista_recom:
                for r in lista_recom:
                    r['poster_url'] = f"https://image.tmdb.org/t/p/w342{r['poster_path']}" if r.get('poster_path') else ""
            
            fav_por_gen[gen] = {"peliculas": [], "recomendaciones": lista_recom}
        fav_por_gen[gen]["peliculas"].append(fav)
        
    return templates.TemplateResponse(
        request=request,
        name="perfil.html",
        context={
            "username": username, 
            "user_avatar": user_avatar,
            "is_admin": request.cookies.get("is_admin") == "1", 
            "favoritos_por_genero": fav_por_gen, 
            "pendientes": pendientes, 
            "usuarios": usuarios
        }
    )

@app.post("/perfil/avatar", response_class=RedirectResponse)
async def actualizar_avatar(request: Request, file: UploadFile = File(...)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)

    if file.content_type.startswith("image/"):
        extension = file.filename.split(".")[-1]
        filename = f"avatar_usuario_{user_id}.{extension}"
        filepath = f"static/avatars/{filename}"

        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        avatar_url = f"/{filepath}"
        conn = get_db_connection()
        conn.execute("UPDATE users SET profile_pic = ? WHERE id = ?", (avatar_url, user_id))
        conn.commit()
        conn.close()

    return RedirectResponse(url="/perfil", status_code=303)