import asyncio
from crawl4ai import AsyncWebCrawler

async def test():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url="https://example.com")
        print("Crawl4AI is working! Length:", len(result.markdown))

if __name__ == "__main__":
    asyncio.run(test())