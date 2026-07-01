"""Proceso worker independiente que re-scrapea y re-indexa el catalogo cada N horas.

Uso: python -m worker.run_worker
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from scripts.ingest import run_ingest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gandys-bot.worker")

INGEST_INTERVAL_HOURS = 6


def job() -> None:
    logger.info("Iniciando scraping + ingest programado")
    try:
        run_ingest()
    except Exception:
        logger.exception("Fallo el ingest programado")


if __name__ == "__main__":
    job()  # corre una vez al iniciar
    scheduler = BlockingScheduler()
    scheduler.add_job(job, "interval", hours=INGEST_INTERVAL_HOURS)
    logger.info("Worker programado cada %d horas. Ctrl+C para salir.", INGEST_INTERVAL_HOURS)
    scheduler.start()
