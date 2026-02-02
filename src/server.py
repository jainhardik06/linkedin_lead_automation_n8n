from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import os

import requests

from src.scraper import run_selenium_scraper
from src.orchestrator import sync_raw_to_final
from src.post_summary import run_summarizer

app = FastAPI()

class ScrapeRequest(BaseModel):
    url: str
    callback_url: str


def background_scrape_task(search_url: str, callback_url: str):
    try:
        print(f"🚀 Background Scrape Started for: {search_url}")
        print(f"📍 Callback URL registered: {callback_url}")
        run_selenium_scraper(search_url)

        print(f"✅ Scrape Complete. Resuming n8n at: {callback_url}")
        response = requests.post(
            callback_url,
            json={"status": "success"},
            timeout=15,
        )
        print(f"✅ Callback sent successfully. Status: {response.status_code}")
    except Exception as exc:
        print(f"❌ Scrape Failed: {exc}")
        try:
            response = requests.post(
                callback_url,
                json={"status": "error", "error": str(exc)},
                timeout=15,
            )
            print(f"❌ Error callback sent. Status: {response.status_code}")
        except Exception as callback_exc:
            print(f"❌ CRITICAL: Could not send callback to n8n: {callback_exc}")

@app.post("/start-scrape")
async def start_scrape_endpoint(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Phase 1: Start Scrape & Register Callback
    """
    background_tasks.add_task(background_scrape_task, request.url, request.callback_url)
    return {"status": "started", "message": "Scraper started. Will callback when done."}


@app.post("/run-orchestrator")
async def run_orchestrator_endpoint():
    try:
        sync_raw_to_final()
        return {"status": "ok", "message": "Orchestrator Sync Complete"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@app.post("/run-summarizer")
async def run_summarizer_endpoint():
    try:
        run_summarizer()
        return {"status": "ok", "message": "Post summary completed"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

if __name__ == "__main__":
    import uvicorn
    # Listen on 0.0.0.0 so Docker can reach it
    uvicorn.run(app, host="0.0.0.0", port=8000)