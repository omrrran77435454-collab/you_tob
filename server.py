import os
import asyncio
import uvicorn
from fastapi import FastAPI

from main import main as bot_main

app = FastAPI()

@app.get("/")
def home():
    return {"status": "ok", "bot": "running"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(bot_main())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
