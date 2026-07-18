import os
import shutil
import requests
import re
import time
import datetime
import urllib.parse
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from database import inicializar_db, get_db_connection
from tmdb_api import *
from routes_auth import router as auth_router
from routes_acciones import router as acciones_router

app = FastAPI()

# ══════════════════════════════════════════════════════════════════
#  CIBERSEGURIDAD DE ALTO NIVEL (MIDDLEWARES)
# ══════════════════════════════════════════════════════════════════

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        if "set-cookie" in response.headers:
            cookie = response.headers["set-cookie"]
            if "HttpOnly" not in cookie:
                response.headers["set-cookie"] = f"{cookie}; HttpOnly; Secure; SameSite=Lax"
                
        return response

app.add_middleware(SecurityHeadersMiddleware)


os.makedirs("static/avatars", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
inicializar_db()
app.include_router(auth_router)
app.include_router(acciones_router)


# ══════════════════════════════════════════════════════════════════
#  MÓDULO DE EMAIL Y VERIFICACIÓN
# ══════════════════════════════════════════════════════════════════

def enviar_email_confirmacion(destinatario: str, token: str):
    remitente = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    
    if not remitente or not password:
        print("CUIDADO: Faltan credenciales SMTP. El email no se enviará.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Confirma tu cuenta en Recomiendamela"
    msg["From"] = f"Recomiendamela <{remitente}>"
    msg["To"] = destinatario

    html = f"""
    <html>
      <body style="font-family: Arial; background-color: #0d0d0f; color: #fff; padding: 40px; text-align: center;">
        <h2 style="color: #ff6b00;">¡Bienvenido a Recomiendamela!</h2>
        <p>Gracias por unirte a la mejor comunidad de recomendaciones.</p>
        <p>Por favor, confirma tu email haciendo clic en el siguiente enlace:</p>
        <a href="https://recomiendamela.onrender.com/verify?token={token}" style="display: inline-block; padding: 12px 25px; background: #ff6b00; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 20px;">Confirmar mi Cuenta</a>
      </body>
    </html>
    """
    msg.attach(MIMEText(html, "html"))
    
    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(remitente, password)
        server.sendmail(remitente, destinatario, msg.as_string())
        server.quit()
    except Exception as e:
        print("Error crítico al enviar email:", e)


@app.get("/verify")
async def verificar_cuenta(token: str):
    conn = get_db_connection()
    user = conn.execute("SELECT id FROM users WHERE verification_token = ?", (token,)).fetchone()
    if user:
        conn.execute("UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?", (user['id'],))
        conn.commit()
        conn.close()
        return HTMLResponse("<h1 style='color:green; text-align:center;'>¡Cuenta verificada! Ya puedes iniciar sesión.</h1><a href='/'>Volver al inicio</a>")
    conn.close()
    return HTMLResponse("<h1 style='color:red; text-align:center;'>Token inválido o expirado.</h1>")


@app.post("/ajustes/actualizar")
async def actualizar_ajustes(request: Request, nuevo_user: str = Form(""), nueva_pass: str = Form("")):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
        
    user_id = int(user_id) # Protección estricta para Postgres
    
    conn = get_db_connection()
    if nuevo_user:
        conn.execute("UPDATE users SET username = ? WHERE id = ?", (nuevo_user, user_id))
    if nueva_pass:
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (nueva_pass, user_id))
        
    conn.commit()
    conn.close()
    return RedirectResponse(url="/perfil", status_code=303)


# ══════════════════════════════════════════════════════════════════
#  GOOGLE BOOKS
# ══════════════════════════════════════════════════════════════════

def buscar_libros(query: str):
    url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}&maxResults=40"
    try:
        r = requests.get(url, timeout=6).json()
        out = []
        for item in r.get("items", []):
            info = item.get("volumeInfo", {})
            if "imageLinks" not in info or "thumbnail" not in info["imageLinks"]: continue
            lang = info.get("language", "").lower()
            if lang == "en": continue
            cover = info["imageLinks"]["thumbnail"].replace("http:", "https:").replace("&edge=curl", "")
            categories = " ".join(info.get("categories", [])).lower()
            if "manga" in categories or "japanese comic" in categories: mt = "manga"
            elif "comic" in categories or "graphic novel" in categories or "superhero" in categories: mt = "comic"
            else: mt = "book"
            out.append({"id": item["id"], "title": info.get("title", "Sin título"), "release_date": str(info.get("publishedDate", ""))[:4], "poster_url": cover, "media_type": mt})
        return out[:12]
    except Exception as e: return []

def obtener_detalles_libro_o_manga(book_id: str, media_type: str):
    url = f"https://www.googleapis.com/books/v1/volumes/{book_id}"
    try:
        r = requests.get(url, timeout=6).json()
        if "volumeInfo" not in r: return None
        info = r["volumeInfo"]
        cover = info["imageLinks"]["thumbnail"].replace("http:", "https:").replace("&edge=curl", "") if "imageLinks" in info and "thumbnail" in info["imageLinks"] else None
        desc = info.get("description", "No hay sinopsis disponible.")
        if isinstance(desc, dict): desc = desc.get("value", "No hay sinopsis disponible.")
        return {"id": book_id, "title": info.get("title", "Sin título"), "overview": desc, "vote_average": round(info.get("averageRating", 0) * 2, 1), "fuente_nota": "Google Books", "release_date": str(info.get("publishedDate", ""))[:4], "media_type": media_type, "poster_url": cover, "backdrop_url": cover, "genres": [{"name": g} for g in info.get("categories", [])]}
    except Exception as e: return None


# ══════════════════════════════════════════════════════════════════
#  RESTO DEL CÓDIGO (RUTAS)
# ══════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def inicio(request: Request, query: str = None, movie_id: str = None, media_type: str = "movie"):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    
    # Casteo seguro para PostgreSQL
    if user_id: user_id = int(user_id)
        
    peli, error, plataformas, trailer, is_fav, is_pen = None, False, [], None, False, False
    carrusel_titulo, carrusel_pelis = "", []
    resultados_busqueda_cine, resultados_busqueda_juegos, resultados_busqueda_libros = [], [], []
    modo_busqueda, podcasts_links, user_avatar, mid = False, [], None, movie_id

    if user_id:
        conn = get_db_connection()
        usr = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        user_avatar = usr["profile_pic"] if usr and usr["profile_pic"] else f"https://ui-avatars.com/api/?name={username}&background=ff6b00&color=fff&rounded=true"

    if query:
        modo_busqueda = True
        resultados_busqueda_cine = buscar_multimedia(query)
        for res in resultados_busqueda_cine: res["poster_url"] = f"https://image.tmdb.org/t/p/w342{res['poster_path']}" if res.get("poster_path") else ""
        resultados_busqueda_libros = buscar_libros(query)
        if not resultados_busqueda_cine and not resultados_busqueda_libros: error = True

    elif not mid:
        carrusel_pelis = obtener_populares()[:20]
        carrusel_titulo = "Tendencias Mundiales"
        for cp in carrusel_pelis: cp["media_type"] = "movie"
        if carrusel_pelis: mid = str(random.choice(carrusel_pelis[:5])["id"]); media_type = "movie"

    if mid and not modo_busqueda:
        if media_type in ("book", "comic", "manga"):
            peli = obtener_detalles_libro_o_manga(mid, media_type)
        else:
            peli = obtener_detalles_pelicula(mid)
            if peli:
                peli["poster_url"] = f"https://image.tmdb.org/t/p/w500{peli['poster_path']}" if peli.get("poster_path") else None
                peli["backdrop_url"] = f"https://image.tmdb.org/t/p/original{peli['backdrop_path']}" if peli.get("backdrop_path") else None
                peli["vote_average"] = round(peli.get("vote_average", 0), 1)

        if peli and user_id:
            conn = get_db_connection()
            is_fav = bool(conn.execute("SELECT id FROM favoritos WHERE user_id=? AND movie_id=?", (user_id, mid)).fetchone())
            is_pen = bool(conn.execute("SELECT id FROM pendientes WHERE user_id=? AND movie_id=?", (user_id, mid)).fetchone())
            conn.close()

    return templates.TemplateResponse(request=request, name="index.html", context={"user_id": user_id, "username": username, "user_avatar": user_avatar, "peli": peli, "plataformas": plataformas, "podcasts": podcasts_links, "trailer": trailer, "error": error, "is_fav": is_fav, "is_pen": is_pen, "carrusel_titulo": carrusel_titulo, "carrusel_pelis": carrusel_pelis, "resultados_busqueda_cine": resultados_busqueda_cine, "resultados_busqueda_juegos": resultados_busqueda_juegos, "resultados_busqueda_libros": resultados_busqueda_libros, "modo_busqueda": modo_busqueda, "query_actual": query, "media_type": media_type, "busqueda_activa": bool(movie_id)})


@app.get("/foro/{movie_id}", response_class=HTMLResponse)
async def foro_pelicula(request: Request, movie_id: str):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    user_avatar = None

    if user_id: user_id = int(user_id)

    conn = get_db_connection()
    if user_id:
        usr = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
        user_avatar = usr["profile_pic"] if usr and usr["profile_pic"] else f"https://ui-avatars.com/api/?name={username}&background=ff6b00&color=fff&rounded=true"

    peli = obtener_detalles_pelicula(movie_id)
    if peli:
        peli["backdrop_url"] = f"https://image.tmdb.org/t/p/original{peli['backdrop_path']}" if peli.get("backdrop_path") else ""
        peli["poster_url"] = f"https://image.tmdb.org/t/p/w500{peli['poster_path']}" if peli.get("poster_path") else ""

    # Ajuste para Postgres: Pedimos explícitamente u.username
    comentarios_db = conn.execute(
        "SELECT c.comentario, c.fecha, u.username, u.profile_pic FROM comentarios c LEFT JOIN users u ON c.user_id = u.id WHERE c.movie_id = ? ORDER BY c.fecha DESC",
        (movie_id,)
    ).fetchall()
    conn.close()

    comentarios = [
        {"username": c["username"], "comentario": c["comentario"], "fecha": str(c["fecha"])[:16], "avatar": c["profile_pic"] or f"https://ui-avatars.com/api/?name={c['username']}&background=333&color=fff&rounded=true"}
        for c in comentarios_db
    ]

    return templates.TemplateResponse(request=request, name="foro.html", context={"user_id": user_id, "username": username, "user_avatar": user_avatar, "peli": peli, "comentarios": comentarios})

@app.get("/perfil", response_class=HTMLResponse)
async def perfil(request: Request):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    if not user_id: return RedirectResponse(url="/", status_code=303)
    user_id = int(user_id)

    conn = get_db_connection()
    usr = conn.execute("SELECT profile_pic FROM users WHERE id = ?", (user_id,)).fetchone()
    user_avatar = usr["profile_pic"] if usr and usr["profile_pic"] else f"https://ui-avatars.com/api/?name={username}&background=ff6b00&color=fff&rounded=true"

    favs = conn.execute("SELECT * FROM favoritos WHERE user_id = ?", (user_id,)).fetchall()
    pendientes = conn.execute("SELECT * FROM pendientes WHERE user_id = ?", (user_id,)).fetchall()
    usuarios = conn.execute("SELECT * FROM users WHERE is_admin = 1").fetchall() if request.cookies.get("is_admin") == "1" else []
    conn.close()

    fav_por_gen = {}
    for fav in favs:
        gen = fav["genre_name"]
        if gen not in fav_por_gen: fav_por_gen[gen] = {"peliculas": [], "recomendaciones": []}
        fav_por_gen[gen]["peliculas"].append(fav)

    return templates.TemplateResponse(request=request, name="perfil.html", context={"username": username, "user_avatar": user_avatar, "is_admin": request.cookies.get("is_admin") == "1", "favoritos_por_genero": fav_por_gen, "pendientes": pendientes, "usuarios": usuarios})

@app.post("/perfil/avatar", response_class=RedirectResponse)
async def actualizar_avatar(request: Request, file: UploadFile = File(...)):
    user_id = request.cookies.get("user_id")
    if not user_id: return RedirectResponse(url="/", status_code=303)
    
    if file.content_type.startswith("image/"):
        extension = file.filename.split(".")[-1]
        filename = f"avatar_usuario_{user_id}.{extension}"
        filepath = f"static/avatars/{filename}"
        with open(filepath, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        
        conn = get_db_connection()
        conn.execute("UPDATE users SET profile_pic = ? WHERE id = ?", (f"/{filepath}", int(user_id)))
        conn.commit()
        conn.close()
        
    return RedirectResponse(url="/perfil", status_code=303)