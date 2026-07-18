import os
import requests

API_KEY = os.getenv('API_KEY')
def buscar_peliculas(query):
    url = f"https://api.themoviedb.org/3/search/movie?api_key={API_KEY}&query={query}&language=es-ES&include_adult=false"
    res = requests.get(url).json()
    return res.get('results', [])

def obtener_detalles_pelicula(movie_id):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={API_KEY}&language=es-ES&append_to_response=watch/providers,videos"
    return requests.get(url).json()

def obtener_recomendaciones(movie_id):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/recommendations?api_key={API_KEY}&language=es-ES"
    return requests.get(url).json().get('results', [])[:3]

def obtener_populares():
    url = f"https://api.themoviedb.org/3/movie/popular?api_key={API_KEY}&language=es-ES&page=1"
    return requests.get(url).json().get('results', [])[:15]

def descubrir_por_generos(generos_ids):
    ids_str = "|".join(map(str, generos_ids))
    url = f"https://api.themoviedb.org/3/discover/movie?api_key={API_KEY}&language=es-ES&with_genres={ids_str}&sort_by=popularity.desc"
    return requests.get(url).json().get('results', [])[:15]

def obtener_similares(movie_id):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/similar?api_key={API_KEY}&language=es-ES"
    return requests.get(url).json().get('results', [])[:15]