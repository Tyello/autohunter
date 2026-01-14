from app.services.mercado_livre.client import MercadoLivreClient
from bs4 import BeautifulSoup

client = MercadoLivreClient()

url = "https://lista.mercadolivre.com.br/Honda-Civic-SI"
response = client.session.get(url)

print("STATUS:", response.status_code)
print("HTML SIZE:", len(response.text))

soup = BeautifulSoup(response.text, "lxml")

items = soup.select("li")
print("Total <li>:", len(items))

search_items = soup.select("li.ui-search-result")
print("Search items:", len(search_items))

if search_items:
    print("FIRST ITEM CLASSES:", search_items[0].get("class"))

# Dump das classes reais dos primeiros <li>
seen = set()

for li in soup.select("li"):
    classes = li.get("class")
    if classes:
        seen.add(" ".join(classes))

    if len(seen) >= 10:
        break

print("\nCLASSES ENCONTRADAS:")
for c in seen:
    print(c)
