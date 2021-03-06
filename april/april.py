from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def index() -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}


@app.get("/test")
async def test() -> dict:
    """This is another test endpoint."""
    return {"Message": "test"}
