from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from database import get_db_connection

router = APIRouter(prefix="/accion")

@router.post("/{tipo}/{accion}")
async def manejar_accion(tipo: str, accion: str, request: Request, movie_id: int = Form(...), title: str = Form(...), poster_url: str = Form(...), genre_id: int = Form(None), genre_name: str = Form(None)):
    user_id = request.cookies.get("user_id")
    if not user_id: 
        return RedirectResponse(url="/")
        
    conn = get_db_connection()
    if accion == "add":
        if tipo == "fav": 
            conn.execute("INSERT OR IGNORE INTO favoritos (user_id, movie_id, title, poster_url, genre_id, genre_name) VALUES (?,?,?,?,?,?)", (user_id, movie_id, title, poster_url, genre_id, genre_name))
        else: 
            conn.execute("INSERT OR IGNORE INTO pendientes (user_id, movie_id, title, poster_url) VALUES (?,?,?,?)", (user_id, movie_id, title, poster_url))
    else:
        tabla = "favoritos" if tipo == "fav" else "pendientes"
        conn.execute(f"DELETE FROM {tabla} WHERE user_id=? AND movie_id=?", (user_id, movie_id))
        
    conn.commit()
    conn.close()
    return {"status": "ok"}

@router.post("/comentar")
async def comentar(request: Request, movie_id: int = Form(...), comentario: str = Form(...)):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    
    if user_id and comentario.strip():
        conn = get_db_connection()
        conn.execute("INSERT INTO comentarios (movie_id, user_id, username, comentario) VALUES (?, ?, ?, ?)", 
                     (movie_id, user_id, username, comentario.strip()))
        conn.commit()
        conn.close()
        
    # Redirigimos de vuelta a la página del foro de esta película
    return RedirectResponse(url=f"/foro/{movie_id}", status_code=303)