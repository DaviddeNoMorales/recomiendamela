import requests
from bs4 import BeautifulSoup

def buscar_documentales(query):
    url = f"https://www.documaniatv.com/?s={query.replace(' ', '+')}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    docs = []
    # Buscamos los contenedores de los documentales en la web
    items = soup.select('.post-item') # Ajusta esto según el selector de Documania
    for item in items[:10]:
        title = item.select_one('h2').text.strip()
        link = item.select_one('a')['href']
        img = item.select_one('img')['src']
        docs.append({'title': title, 'link': link, 'poster_url': img, 'id': hash(title)})
    return docs