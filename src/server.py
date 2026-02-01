from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import subprocess
import sys

app = FastAPI()

class ScrapeRequest(BaseModel):
    url: str

def run_scraper(url: str):
    # This runs your existing scraper script
    print(f"🚀 Received command for: {url}")
    subprocess.run([sys.executable, "-m", "src.scraper", url])

@app.post("/start-scrape")
async def start_scrape(request: ScrapeRequest, background_tasks: BackgroundTasks):
    # Run in background so n8n doesn't get stuck waiting
    background_tasks.add_task(run_scraper, request.url)
    return {"status": "Scraper started", "target": request.url}

if __name__ == "__main__":
    import uvicorn
    # Listen on 0.0.0.0 so Docker can reach it
    uvicorn.run(app, host="0.0.0.0", port=8000)