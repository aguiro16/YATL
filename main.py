import asyncio
import logging
from scanner import run_scanner
from reporter import run_reporter
from database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

async def main():
    init_db()
    logging.info("🚀 F35 Signal Bot started")
    await asyncio.gather(
        run_scanner(),
        run_reporter()
    )

if __name__ == "__main__":
    asyncio.run(main())
