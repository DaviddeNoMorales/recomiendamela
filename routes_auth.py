import os
from fastapi import APIRouter, Form, Response, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from database import get_db_connection, hash_password

router = APIRouter(prefix="/auth")

@router.post("/login")
async def login(response: Response, username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, hash_password(password))).fetchone()
    conn.close()
    if user:
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie("user_id", str(user["id"]))
        resp.set_cookie("username", user["username"])
        resp.set_cookie("is_admin", str(user["is_admin"]))
        return resp
    return RedirectResponse(url="/", status_code=303)

@router.get("/logout")
async def logout():
    res = RedirectResponse(url="/", status_code=303)
    res.delete_cookie("user_id")
    res.delete_cookie("username")
    res.delete_cookie("is_admin")
    return res

@router.post("/register")
async def register(username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, 0)", (username, hash_password(password)))
        conn.commit()
        uid = cur.lastrowid
        res = RedirectResponse(url="/", status_code=303)
        res.set_cookie("user_id", str(uid))
        res.set_cookie("username", username)
        res.set_cookie("is_admin", "0")
        return res
    finally: 
        conn.close()

@router.post("/admin-create")
async def admin_create(request: Request, username: str = Form(...), password: str = Form(...)):
    is_admin = request.cookies.get("is_admin") == "1"
    if is_admin:
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, 0)", (username, hash_password(password)))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
    return RedirectResponse(url="/perfil", status_code=303)

@router.post("/avatar")
async def upload_avatar(request: Request, file: UploadFile = File(...)):
    user_id = request.cookies.get("user_id")
    if user_id:
        os.makedirs("static/avatars", exist_ok=True)
        # Guardamos la imagen con el nombre del usuario
        file_path = f"static/avatars/{user_id}_{file.filename}"
        with open(file_path, "wb") as f:
            f.write(await file.read())
            
        conn = get_db_connection()
        conn.execute("UPDATE users SET profile_pic = ? WHERE id = ?", (f"/{file_path}", user_id))
        conn.commit()
        conn.close()
    return RedirectResponse(url="/perfil", status_code=303)