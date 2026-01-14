from app.db.session import SessionLocal
from app.services.mercado_livre.ingest import MercadoLivreIngestService

db = SessionLocal()
service = MercadoLivreIngestService(db)

query = "Honda Civic SI"
count = service.ingest_search(query, limit=15)

print(f"✅ {count} novos anúncios encontrados e salvos.")
