from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def index() -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}
