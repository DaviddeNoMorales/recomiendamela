import os
import shutil
import requests
import re
import time
import datetime
import urllib.parse
import random

from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

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


# ══════════════════════════════════════════════════════════════════
#  NUEVO: APPLE BOOKS API  →  Libros y Cómics (Perfecto en español)
# ══════════════════════════════════════════════════════════════════

def buscar_libros(query: str):
    """Busca libros y cómics en la tienda de Apple España."""
    url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&country=es&entity=ebook&limit=12"
    try:
        r = requests.get(url, timeout=6).json()
        out = []
        for item in r.get("results", []):
            # Cambiamos la resolución de la portada a alta calidad
            cover = item.get("artworkUrl100", "").replace("100x100bb", "600x600bb")
            if not cover:
                continue
                
            out.append({
                "id": str(item.get("trackId")),
                "title": item.get("trackName", "Sin título"),
                "release_date": str(item.get("releaseDate", ""))[:4],
                "poster_url": cover,
                "media_type": "book"
            })
        return out
    except Exception as e:
        print("Error Apple Books search:", e)
        return []

def obtener_detalles_libro(book_id: str):
    url = f"https://itunes.apple.com/lookup?id={book_id}&country=es"
    try:
        r = requests.get(url, timeout=6).json()
        if not r.get("results"):
            return None
            
        item = r["results"][0]
        cover = item.get("artworkUrl100", "").replace("100x100bb", "600x600bb")
        
        # Limpiar etiquetas HTML feas que a veces vienen en la sinopsis
        desc_html = item.get("description", "No hay sinopsis disponible.")
        desc_limpia = re.sub('<[^<]+>', '', desc_html)
        
        vote_avg = round(item.get("averageUserRating", 0) * 2, 1) # Apple es sobre 5, lo pasamos a 10

        return {
            "id": book_id,
            "title": item.get("trackName", "Sin título"),
            "overview": desc_limpia,
            "vote_average": vote_avg,
            "fuente_nota": "Apple Books",
            "release_date": str(item.get("releaseDate", ""))[:4],
            "media_type": "book",
            "poster_url": cover,
            "backdrop_url": cover,
            "genres": [{"name": g} for g in item.get("genres", [])]
        }
    except Exception as e:
        print("Error Apple Books details:", e)
        return None


# ══════════════════════════════════════════════════════════════════
#  NUEVO: JIKAN API (MyAnimeList)  →  Manga 
# ══════════════════════════════════════════════════════════════════

def buscar_manga(query: str):
    """Busca manga en MyAnimeList (Jikan). Garantiza portadas de calidad."""
    url = f"https://api.jikan.moe/v4/manga?q={urllib.parse.quote(query)}&limit=10"
    try:
        r = requests.get(url, timeout=6).json()
        out = []
        for item in r.get("data", []):
            cover = item.get("images", {}).get("jpg", {}).get("large_image_url")
            if not cover:
                continue
                
            # Jikan a veces trae el título en español si existe, si no, usa el general
            title = item.get("title_spanish") or item.get("title", "Sin título")
            
            # Año de publicación
            year = ""
            published = item.get("published", {}).get("prop", {}).get("from", {})
            if published and published.get("year"):
                year = str(published.get("year"))

            out.append({
                "id": f"jikan_{item['mal_id']}",
                "title": title,
                "release_date": year,
                "poster_url": cover,
                "media_type": "manga"
            })
        return out
    except Exception as e:
        print("Error Jikan Manga search:", e)
        return []

def obtener_detalles_manga(manga_id: str):
    real_id = manga_id.replace("jikan_", "")
    url = f"https://api.jikan.moe/v4/manga/{real_id}"
    try:
        r = requests.get(url, timeout=6).json()
        item = r.get("data")
        if not item: return None
        
        cover = item.get("images", {}).get("jpg", {}).get("large_image_url")
        title = item.get("title_spanish") or item.get("title", "Sin título")
        
        year = ""
        published = item.get("published", {}).get("prop", {}).get("from", {})
        if published and published.get("year"):
            year = str(published.get("year"))

        return {
            "id": manga_id,
            "title": title,
            "overview": item.get("synopsis", "No hay sinopsis disponible."),
            "vote_average": round(item.get("score", 0) or 0, 1),
            "fuente_nota": "MyAnimeList",
            "release_date": year,
            "media_type": "manga",
            "poster_url": cover,
            "backdrop_url": cover,
            "genres": [{"name": g.get("name")} for g in item.get("genres", [])]
        }
    except Exception as e:
        print("Error Jikan details:", e)
        return None


def obtener_detalles_libro_o_manga(mid: str, media_type: str):
    """Dispatcher: Redirige a Apple (Libros) o Jikan (Manga) según el ID"""
    if mid.startswith("jikan_"):
        return obtener_detalles_manga(mid)
    return obtener_detalles_libro(mid)


def tiendas_libro(titulo: str, media_type: str):
    q = urllib.parse.quote(titulo)
    if media_type == "manga":
        return [
            {"nombre": "Amazon",        "link": f"https://www.amazon.es/s?k={q}+manga",                         "color": "#232F3E", "icono": "🛒"},
            {"nombre": "Norma Cómics",  "link": f"https://www.normacomics.com/catalogsearch/result/?q={q}",      "color": "#D42B2B", "icono": "🥷"},
            {"nombre": "Planet Manga",  "link": f"https://www.panini.es/shp_esp_es/catalogsearch/result/?q={q}", "color": "#0057A8", "icono": "🌐"},
        ]
    elif media_type == "comic":
        return [
            {"nombre": "Amazon",        "link": f"https://www.amazon.es/s?k={q}+comic",                          "color": "#232F3E", "icono": "🛒"},
            {"nombre": "Norma Cómics",  "link": f"https://www.normacomics.com/catalogsearch/result/?q={q}",      "color": "#D42B2B", "icono": "🦸"},
            {"nombre": "Casa del Libro","link": f"https://www.casadellibro.com/?q={q}",                          "color": "#009966", "icono": "📚"},
            {"nombre": "FNAC",          "link": f"https://www.fnac.es/SearchResult/ResultList.aspx?Search={q}",  "color": "#E5A800", "icono": "🏪"},
        ]
    else:
        return [
            {"nombre": "Amazon",         "link": f"https://www.amazon.es/s?k={q}+libro",                         "color": "#232F3E", "icono": "🛒"},
            {"nombre": "Casa del Libro", "link": f"https://www.casadellibro.com/?q={q}",                         "color": "#009966", "icono": "📖"},
            {"nombre": "FNAC",           "link": f"https://www.fnac.es/SearchResult/ResultList.aspx?Search={q}", "color": "#E5A800", "icono": "🏪"},
            {"nombre": "Todostuslibros", "link": f"https://www.todostuslibros.com/busqueda?keyword={q}",          "color": "#3A5A8C", "icono": "📘"},
        ]


# ══════════════════════════════════════════════════════════════════
#  IGDB  →  videojuegos
# ══════════════════════════════════════════════════════════════════

IGDB_TOKEN        = None
IGDB_TOKEN_EXPIRY = 0

def get_igdb_token():
    global IGDB_TOKEN, IGDB_TOKEN_EXPIRY
    if time.time() < IGDB_TOKEN_EXPIRY and IGDB_TOKEN:
        return IGDB_TOKEN
    client_id     = os.getenv("IGDB_CLIENT_ID")
    client_secret = os.getenv("IGDB_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    url = (
        f"https://id.twitch.tv/oauth2/token"
        f"?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials"
    )
    try:
        r = requests.post(url).json()
        IGDB_TOKEN        = r.get("access_token")
        IGDB_TOKEN_EXPIRY = time.time() + r.get("expires_in", 3600) - 60
        return IGDB_TOKEN
    except Exception as e:
        print("Error IGDB token:", e)
        return None

def buscar_videojuegos(query: str):
    token     = get_igdb_token()
    client_id = os.getenv("IGDB_CLIENT_ID")
    if not token or not client_id:
        return []
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
    body    = f'search "{query}"; fields name,cover.url,first_release_date; limit 10;'
    try:
        r = requests.post("https://api.igdb.com/v4/games", headers=headers, data=body).json()
        juegos = []
        if isinstance(r, list):
            for game in r:
                if "cover" in game and "url" in game["cover"]:
                    game["media_type"] = "game"
                    game["title"]      = game.get("name")
                    if "first_release_date" in game:
                        game["release_date"] = datetime.datetime.fromtimestamp(
                            game["first_release_date"]
                        ).strftime("%Y")
                    game["poster_url"] = "https:" + game["cover"]["url"].replace("t_thumb", "t_cover_big")
                    juegos.append(game)
        return juegos
    except Exception as e:
        print("Error IGDB search:", e)
        return []

def obtener_detalles_videojuego(game_id: str):
    token     = get_igdb_token()
    client_id = os.getenv("IGDB_CLIENT_ID")
    if not token or not client_id:
        return None
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
    body    = f"fields name,summary,cover.url,artworks.url,first_release_date,rating,platforms.name; where id = {game_id};"
    try:
        r = requests.post("https://api.igdb.com/v4/games", headers=headers, data=body).json()
        if r and isinstance(r, list):
            game              = r[0]
            game["title"]     = game.get("name")
            game["overview"]  = game.get("summary", "No hay sinopsis disponible para este juego.")
            game["vote_average"] = round(game.get("rating", 0) / 10, 1) if "rating" in game else 0
            game["fuente_nota"]  = "IGDB"
            if "first_release_date" in game:
                game["release_date"] = datetime.datetime.fromtimestamp(
                    game["first_release_date"]
                ).strftime("%Y")
            if "cover" in game and "url" in game["cover"]:
                game["poster_url"]   = "https:" + game["cover"]["url"].replace("t_thumb", "t_1080p")
            if "artworks" in game and game["artworks"]:
                game["backdrop_url"] = "https:" + game["artworks"][0]["url"].replace("t_thumb", "t_1080p")
            else:
                game["backdrop_url"] = game.get("poster_url")
            game["plataformas_nombres"] = [p["name"] for p in game.get("platforms", [])]
            game["media_type"]          = "game"
            return game
        return None
    except Exception as e:
        print("Error IGDB details:", e)
        return None


# ══════════════════════════════════════════════════════════════════
#  TMDB / IMDb  →  cine y series
# ══════════════════════════════════════════════════════════════════

def obtener_nota_imdb(imdb_id: str):
    if not imdb_id:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r       = requests.get(f"https://www.imdb.com/title/{imdb_id}/", headers=headers, timeout=5)
        match   = re.search(r'"ratingValue":\s*"?([0-9.]+)"?', r.text)
        if match:
            return float(match.group(1))
    except Exception as e:
        print(f"Error IMDb rating {imdb_id}:", e)
    return None

def buscar_multimedia(query: str):
    api_key = os.getenv("API_KEY")
    try:
        r       = requests.get(
            f"https://api.themoviedb.org/3/search/multi"
            f"?api_key={api_key}&query={urllib.parse.quote(query)}&language=es-ES"
        ).json()
        return [res for res in r.get("results", []) if res.get("media_type") in ["movie", "tv"]]
    except Exception as e:
        print("Error TMDB search:", e)
        return []

def obtener_detalles_tv(tv_id: str):
    api_key = os.getenv("API_KEY")
    try:
        res = requests.get(
            f"https://api.themoviedb.org/3/tv/{tv_id}"
            f"?api_key={api_key}&language=es-ES&append_to_response=videos,watch/providers,external_ids"
        ).json()
        if "id" in res:
            res["title"]       = res.get("name")
            res["release_date"] = res.get("first_air_date")
            res["imdb_id"]     = res.get("external_ids", {}).get("imdb_id")
            return res
    except Exception:
        pass
    return None

def obtener_similares_tv(tv_id: str):
    api_key = os.getenv("API_KEY")
    try:
        res = requests.get(
            f"https://api.themoviedb.org/3/tv/{tv_id}/similar?api_key={api_key}&language=es-ES"
        ).json()
        results = res.get("results", [])
        for r in results:
            r["title"]        = r.get("name")
            r["release_date"] = r.get("first_air_date")
            r["media_type"]   = "tv"
        return results
    except Exception:
        return []

def obtener_enlace_directo(plataforma, titulo):
    q     = urllib.parse.quote(titulo)
    links = {
        "Netflix":             f"https://www.netflix.com/search?q={q}",
        "Amazon Prime Video":  f"https://www.primevideo.com/search/ref=atv_sr_sfs_c_unkr?phrase={q}",
        "Disney+":             f"https://www.disneyplus.com/search?q={q}",
        "Max":                 f"https://play.max.com/search?q={q}",
        "Apple TV Plus":       f"https://tv.apple.com/es/search?term={q}",
        "Filmin":              f"https://www.filmin.es/busqueda?q={q}",
        "Crunchyroll":         f"https://www.crunchyroll.com/es/search?q={q}",
        "Movistar Plus+":      f"https://ver.movistarplus.es/busqueda/?q={q}",
    }
    return links.get(plataforma, f"https://www.justwatch.com/es/busqueda?q={q}")


# ══════════════════════════════════════════════════════════════════
#  RUTAS
# ══════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def inicio(
    request:    Request,
    query:      str = None,
    movie_id:   str = None,
    media_type: str = "movie",
):
    user_id  = request.cookies.get("user_id")
    username = request.cookies.get("username")

    peli, error, plataformas, trailer, is_fav, is_pen = None, False, [], None, False, False
    carrusel_titulo = ""
    carrusel_pelis  = []

    resultados_busqueda_cine   = []
    resultados_busqueda_juegos = []
    resultados_busqueda_libros = [] 
    modo_busqueda = False

    podcasts_links = []
    user_avatar    = None
    mid            = movie_id

    if user_id:
        conn = get_db_connection()
        usr  = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        user_avatar = (
            usr["profile_pic"] if usr and usr["profile_pic"]
            else f"https://ui-avatars.com/api/?name={username}&background=e50914&color=fff&rounded=true"
        )

    # ── MODO BÚSQUEDA ──────────────────────────────────────────────
    if query:
        modo_busqueda = True

        resultados_busqueda_cine = buscar_multimedia(query)
        for res in resultados_busqueda_cine:
            res["poster_url"] = (
                f"https://image.tmdb.org/t/p/w342{res['poster_path']}"
                if res.get("poster_path") else ""
            )

        resultados_busqueda_juegos = buscar_videojuegos(query)
        
        # Combinamos Apple Books y Jikan (Manga) en la misma fila
        resultados_busqueda_libros = buscar_libros(query) + buscar_manga(query)

        if not resultados_busqueda_cine and not resultados_busqueda_juegos and not resultados_busqueda_libros:
            error = True

    # ── SIN BÚSQUEDA: carrusel de inicio ──────────────────────────
    elif not mid:
        if user_id:
            conn  = get_db_connection()
            favs  = conn.execute(
                "SELECT DISTINCT genre_id FROM favoritos WHERE user_id = ?", (user_id,)
            ).fetchall()
            conn.close()
            if favs:
                genre_ids       = [str(f["genre_id"]) for f in favs[:3]]
                carrusel_pelis  = descubrir_por_generos(genre_ids)[:20]
                carrusel_titulo = "Recomendado para ti"
            else:
                carrusel_pelis  = descubrir_por_generos(["27", "14"])[:20]
                carrusel_titulo = "Nuestra selección para empezar"
        else:
            carrusel_pelis  = obtener_populares()[:20]
            carrusel_titulo = "Tendencias Mundiales"

        for cp in carrusel_pelis:
            cp["media_type"] = "movie"

        if carrusel_pelis:
            mid        = str(random.choice(carrusel_pelis[:5])["id"])
            media_type = "movie"

    # ── DETALLE DEL ELEMENTO ACTIVO ───────────────────────────────
    if mid and not modo_busqueda:

        # ── Videojuego ──
        if media_type == "game":
            peli            = obtener_detalles_videojuego(mid)
            carrusel_pelis  = []
            carrusel_titulo = ""
            if peli:
                tu = urllib.parse.quote(peli["title"])
                podcasts_links = [
                    {"nombre": "Directos en Twitch", "link": f"https://www.twitch.tv/directory/search?term={tu}", "color": "#9146FF", "icono": "🟪"},
                    {"nombre": "YouTube",            "link": f"https://www.youtube.com/results?search_query={tu}+gameplay", "color": "#FF0000", "icono": "▶️"},
                ]

        # ── Libro / Cómic / Manga ──
        elif media_type in ("book", "comic", "manga"):
            peli            = obtener_detalles_libro_o_manga(mid, media_type)
            carrusel_pelis  = []
            carrusel_titulo = ""
            if peli:
                media_type     = peli.get("media_type", media_type)
                podcasts_links = tiendas_libro(peli["title"], media_type)

        # ── Serie ──
        elif media_type == "tv":
            peli = obtener_detalles_tv(mid)
            if peli and movie_id:
                carrusel_pelis  = obtener_similares_tv(mid)[:20]
                carrusel_titulo = f"Series similares a {peli.get('title')}"
            if peli:
                peli["poster_url"]   = f"https://image.tmdb.org/t/p/w500{peli['poster_path']}"   if peli.get("poster_path")   else None
                peli["backdrop_url"] = f"https://image.tmdb.org/t/p/original{peli['backdrop_path']}" if peli.get("backdrop_path") else None
                peli["fuente_nota"]  = "IMDb"
                nota = obtener_nota_imdb(peli.get("imdb_id"))
                peli["vote_average"] = nota if nota else round(peli.get("vote_average", 0), 1)
                for cp in carrusel_pelis:
                    cp["poster_url"] = f"https://image.tmdb.org/t/p/w342{cp['poster_path']}" if cp.get("poster_path") else ""
                    cp.setdefault("media_type", "tv")
                watch_data         = peli.get("watch/providers", {}).get("results", {}).get("ES", {})
                plataformas        = _procesar_plataformas(watch_data, peli["title"])
                tu                 = urllib.parse.quote(peli["title"])
                podcasts_links     = [
                    {"nombre": "Spotify", "link": f"https://open.spotify.com/search/{tu}", "color": "#1DB954", "icono": "🎧"},
                    {"nombre": "iVoox",   "link": f"https://www.ivoox.com/{tu}_sb.html?sb={tu}", "color": "#FF6600", "icono": "🎙️"},
                ]
                for v in peli.get("videos", {}).get("results", []):
                    if v["type"] == "Trailer":
                        trailer = v["key"]
                        break

        # ── Película ──
        else:
            peli = obtener_detalles_pelicula(mid)
            if peli and movie_id:
                carrusel_pelis  = obtener_similares(mid)[:20]
                carrusel_titulo = f"Películas similares a {peli.get('title')}"
            if peli:
                peli["poster_url"]   = f"https://image.tmdb.org/t/p/w500{peli['poster_path']}"   if peli.get("poster_path")   else None
                peli["backdrop_url"] = f"https://image.tmdb.org/t/p/original{peli['backdrop_path']}" if peli.get("backdrop_path") else None
                peli["fuente_nota"]  = "IMDb"
                nota = obtener_nota_imdb(peli.get("imdb_id"))
                peli["vote_average"] = nota if nota else round(peli.get("vote_average", 0), 1)
                for cp in carrusel_pelis:
                    cp["poster_url"] = f"https://image.tmdb.org/t/p/w342{cp['poster_path']}" if cp.get("poster_path") else ""
                    cp.setdefault("media_type", "movie")
                watch_data     = peli.get("watch/providers", {}).get("results", {}).get("ES", {})
                plataformas    = _procesar_plataformas(watch_data, peli["title"])
                tu             = urllib.parse.quote(peli["title"])
                podcasts_links = [
                    {"nombre": "Spotify", "link": f"https://open.spotify.com/search/{tu}", "color": "#1DB954", "icono": "🎧"},
                    {"nombre": "iVoox",   "link": f"https://www.ivoox.com/{tu}_sb.html?sb={tu}", "color": "#FF6600", "icono": "🎙️"},
                ]
                for v in peli.get("videos", {}).get("results", []):
                    if v["type"] == "Trailer":
                        trailer = v["key"]
                        break

        if peli and user_id:
            conn   = get_db_connection()
            is_fav = bool(conn.execute("SELECT id FROM favoritos  WHERE user_id=? AND movie_id=?", (user_id, mid)).fetchone())
            is_pen = bool(conn.execute("SELECT id FROM pendientes WHERE user_id=? AND movie_id=?", (user_id, mid)).fetchone())
            conn.close()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user_id":                   user_id,
            "username":                  username,
            "user_avatar":               user_avatar,
            "peli":                      peli,
            "plataformas":               plataformas,
            "podcasts":                  podcasts_links,
            "trailer":                   trailer,
            "error":                     error,
            "is_fav":                    is_fav,
            "is_pen":                    is_pen,
            "carrusel_titulo":           carrusel_titulo,
            "carrusel_pelis":            carrusel_pelis,
            "resultados_busqueda_cine":  resultados_busqueda_cine,
            "resultados_busqueda_juegos":resultados_busqueda_juegos,
            "resultados_busqueda_libros":resultados_busqueda_libros,
            "modo_busqueda":             modo_busqueda,
            "query_actual":              query,
            "media_type":                media_type,
            "busqueda_activa":           bool(movie_id),
        },
    )

def _procesar_plataformas(watch_data: dict, titulo: str) -> list:
    plataformas_crudas = watch_data.get("flatrate", [])
    vistas, out        = set(), []
    for plat in plataformas_crudas:
        nombre = plat["provider_name"]
        if   "Netflix"        in nombre: nb = "Netflix"
        elif "Prime Video"    in nombre or "Amazon" in nombre: nb = "Amazon Prime Video"
        elif "Disney"         in nombre: nb = "Disney+"
        elif "Max"            in nombre or "HBO" in nombre: nb = "Max"
        elif "Movistar"       in nombre: nb = "Movistar Plus+"
        elif "Apple"          in nombre: nb = "Apple TV Plus"
        elif "Filmin"         in nombre: nb = "Filmin"
        elif "Crunchyroll"    in nombre: nb = "Crunchyroll"
        elif "SkyShowtime"    in nombre: nb = "SkyShowtime"
        else: nb = nombre.split(" with ")[0].split(" con ")[0]
        if nb not in vistas:
            vistas.add(nb)
            plat["provider_name"] = nb
            plat["direct_link"]   = obtener_enlace_directo(nb, titulo)
            out.append(plat)
    return out


# ══════════════════════════════════════════════════════════════════
#  RESTO DE RUTAS
# ══════════════════════════════════════════════════════════════════

@app.get("/foro/{movie_id}", response_class=HTMLResponse)
async def foro_pelicula(request: Request, movie_id: str):
    user_id  = request.cookies.get("user_id")
    username = request.cookies.get("username")
    user_avatar = None

    conn = get_db_connection()
    if user_id:
        usr = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
        user_avatar = (
            usr["profile_pic"] if usr and usr["profile_pic"]
            else f"https://ui-avatars.com/api/?name={username}&background=e50914&color=fff&rounded=true"
        )

    peli = obtener_detalles_pelicula(movie_id)
    if peli:
        peli["backdrop_url"] = f"https://image.tmdb.org/t/p/original{peli['backdrop_path']}" if peli.get("backdrop_path") else ""
        peli["poster_url"]   = f"https://image.tmdb.org/t/p/w500{peli['poster_path']}"       if peli.get("poster_path")   else ""

    comentarios_db = conn.execute(
        "SELECT c.*, u.profile_pic FROM comentarios c LEFT JOIN users u ON c.user_id = u.id WHERE c.movie_id = ? ORDER BY c.fecha DESC",
        (movie_id,),
    ).fetchall()
    conn.close()

    comentarios = [
        {
            "username":   c["username"],
            "comentario": c["comentario"],
            "fecha":      c["fecha"][:16],
            "avatar":     c["profile_pic"] or f"https://ui-avatars.com/api/?name={c['username']}&background=333&color=fff&rounded=true",
        }
        for c in comentarios_db
    ]

    return templates.TemplateResponse(
        request=request,
        name="foro.html",
        context={"user_id": user_id, "username": username, "user_avatar": user_avatar, "peli": peli, "comentarios": comentarios},
    )


@app.get("/perfil", response_class=HTMLResponse)
async def perfil(request: Request):
    user_id  = request.cookies.get("user_id")
    username = request.cookies.get("username")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)

    conn        = get_db_connection()
    usr         = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
    user_avatar = (
        usr["profile_pic"] if usr and usr["profile_pic"]
        else f"https://ui-avatars.com/api/?name={username}&background=e50914&color=fff&rounded=true"
    )

    favs      = conn.execute("SELECT * FROM favoritos  WHERE user_id = ?", (user_id,)).fetchall()
    pendientes = conn.execute("SELECT * FROM pendientes WHERE user_id = ?", (user_id,)).fetchall()
    usuarios  = (
        conn.execute("SELECT * FROM users WHERE is_admin = 1").fetchall()
        if request.cookies.get("is_admin") == "1" else []
    )
    conn.close()

    fav_por_gen = {}
    for fav in favs:
        gen = fav["genre_name"]
        if gen not in fav_por_gen:
            lista_recom = obtener_recomendaciones(fav["movie_id"])
            if lista_recom:
                for r in lista_recom:
                    r["poster_url"] = f"https://image.tmdb.org/t/p/w342{r['poster_path']}" if r.get("poster_path") else ""
            fav_por_gen[gen] = {"peliculas": [], "recomendaciones": lista_recom}
        fav_por_gen[gen]["peliculas"].append(fav)

    return templates.TemplateResponse(
        request=request,
        name="perfil.html",
        context={
            "username":             username,
            "user_avatar":          user_avatar,
            "is_admin":             request.cookies.get("is_admin") == "1",
            "favoritos_por_genero": fav_por_gen,
            "pendientes":           pendientes,
            "usuarios":             usuarios,
        },
    )


@app.post("/perfil/avatar", response_class=RedirectResponse)
async def actualizar_avatar(request: Request, file: UploadFile = File(...)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    if file.content_type.startswith("image/"):
        extension = file.filename.split(".")[-1]
        filename  = f"avatar_usuario_{user_id}.{extension}"
        filepath  = f"static/avatars/{filename}"
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        avatar_url = f"/{filepath}"
        conn = get_db_connection()
        conn.execute("UPDATE users SET profile_pic = ? WHERE id = ?", (avatar_url, user_id))
        conn.commit()
        conn.close()
    return RedirectResponse(url="/perfil", status_code=303)