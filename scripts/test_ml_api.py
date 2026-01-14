from app.services.mercado_livre.client import MercadoLivreClient

client = MercadoLivreClient()

data = client.search("Honda Civic SI", limit=5)

print("TOTAL:", data["paging"]["total"])
print("RETORNADOS:", len(data["results"]))

for item in data["results"]:
    print(
        item["id"],
        item["title"],
        item["price"],
        item.get("thumbnail")
    )
