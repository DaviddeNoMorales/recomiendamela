import os
import shutil
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

# Aseguramos que exista la carpeta para guardar los avatares
os.makedirs("static/avatars", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
inicializar_db()
app.include_router(auth_router)
app.include_router(acciones_router)

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

@app.get("/", response_class=HTMLResponse)
async def inicio(request: Request, query: str = None, movie_id: int = None):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    peli, error, plataformas, trailer, is_fav, is_pen = None, None, [], None, False, False
    carrusel_titulo = ""
    carrusel_pelis = []
    resultados_busqueda = []
    user_avatar = None
    mid = movie_id # ID exacto de la película

    # 1. Obtener Avatar del usuario
    if user_id:
        conn = get_db_connection()
        usr = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        if usr and usr['profile_pic']:
            user_avatar = usr['profile_pic']
        else:
            user_avatar = f"https://ui-avatars.com/api/?name={username}&background=e50914&color=fff&rounded=true"

    # 2. Si el usuario realiza una búsqueda, mostramos el listado
    if query:
        resultados_busqueda = buscar_peliculas(query)
        for res in resultados_busqueda:
            res['poster_url'] = f"https://image.tmdb.org/t/p/w342{res['poster_path']}" if res.get('poster_path') else ""
        if not resultados_busqueda:
            error = f"No se han encontrado resultados para '{query}'."

    # 3. Si no hay búsqueda ni ID específico, cargamos el inicio por defecto
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
        else:
            carrusel_pelis = obtener_populares()
            carrusel_titulo = "Tendencias Mundiales"

        if carrusel_pelis:
            mid = random.choice(carrusel_pelis[:5])['id']

    # 4. Procesar la película principal (ya sea elegida al azar para el home o por click directo)
    if mid and not resultados_busqueda:
        peli = obtener_detalles_pelicula(mid)
        if peli:
            peli['vote_average'] = round(peli.get('vote_average', 0), 1)
            peli['poster_url'] = f"https://image.tmdb.org/t/p/w500{peli['poster_path']}" if peli.get('poster_path') else None
            peli['backdrop_url'] = f"https://image.tmdb.org/t/p/original{peli['backdrop_path']}" if peli.get('backdrop_path') else None

            # Si hizo clic en un ID concreto, cargamos similares
            if movie_id:
                carrusel_pelis = obtener_similares(mid)
                carrusel_titulo = f"Películas similares a {peli.get('title')}"

            for cp in carrusel_pelis:
                cp['poster_url'] = f"https://image.tmdb.org/t/p/w342{cp['poster_path']}" if cp.get('poster_path') else ""
                
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
            
            for v in peli.get('videos', {}).get('results', []):
                if v['type'] == 'Trailer': 
                    trailer = v['key']
                    break
                    
            if user_id:
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
            "trailer": trailer, 
            "error": error, 
            "is_fav": is_fav, 
            "is_pen": is_pen,
            "carrusel_titulo": carrusel_titulo,
            "carrusel_pelis": carrusel_pelis,
            "resultados_busqueda": resultados_busqueda,
            "query_actual": query,
            "busqueda_activa": bool(movie_id) # Usamos movie_id para activar la vista enfocada
        }
    )

@app.get("/foro/{movie_id}", response_class=HTMLResponse)
async def foro_pelicula(request: Request, movie_id: int):
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

# NUEVA RUTA: Recibir y guardar el archivo del avatar
@app.post("/perfil/avatar", response_class=RedirectResponse)
async def actualizar_avatar(request: Request, file: UploadFile = File(...)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)

    # Solo procesamos si es una imagen
    if file.content_type.startswith("image/"):
        # Construimos el nombre de archivo único para evitar sobreescrituras de otros usuarios
        extension = file.filename.split(".")[-1]
        filename = f"avatar_usuario_{user_id}.{extension}"
        filepath = f"static/avatars/{filename}"

        # Guardamos el archivo físico en el servidor
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Actualizamos la base de datos con la nueva ruta
        avatar_url = f"/{filepath}"
        conn = get_db_connection()
        conn.execute("UPDATE users SET profile_pic = ? WHERE id = ?", (avatar_url, user_id))
        conn.commit()
        conn.close()

    # Devolvemos al usuario a su perfil para que vea el cambio
    return RedirectResponse(url="/perfil", status_code=303)