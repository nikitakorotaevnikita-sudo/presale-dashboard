from fastapi import FastAPI

app = FastAPI(title="Дашборд пресейла ОГВ")

@app.get("/api/health")
def health():
    return {"status": "ok"}
