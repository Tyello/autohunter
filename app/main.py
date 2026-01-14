from fastapi import FastAPI

app = FastAPI(
    title="AutoHunter",
    version="0.1.0"
)

@app.get("/health")
def healthcheck():
    return {"status": "ok"}
