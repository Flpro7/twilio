"""Historial de conversacion por remitente de WhatsApp, persistido en SQLite
para sobrevivir reinicios/redeploys.

Se guarda dentro del mismo directorio que ya usa ChromaDB (CHROMA_PERSIST_DIR),
que es el unico volumen persistente que tenemos montado en Railway -- asi no
hace falta pedir un segundo volumen solo para esto. No es un archivo de
Chroma, simplemente comparte el mismo disco.

Guarda tanto el mensaje del cliente como la respuesta del bot en cada turno,
para que preguntas de seguimiento (ej. "de que trata la cinta", refiriendose
a un producto mencionado en el mensaje anterior) tengan contexto real de la
conversacion en vez de buscarse como si fueran la primera pregunta.
"""

import sqlite3
from pathlib import Path

from app.config import settings

_DB_PATH = Path(settings.chroma_persist_dir) / "conversation_history.sqlite3"


def _get_connection() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    # WAL reduce bloqueos entre lecturas y escrituras concurrentes -- util
    # para un bot que puede recibir varios mensajes en paralelo.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def append_message(sender: str, role: str, content: str) -> None:
    """Guarda un turno de la conversacion. role es "user" o "assistant"."""
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO messages (sender, role, content) VALUES (?, ?, ?)",
            (sender, role, content),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_history(sender: str, max_exchanges: int) -> list[dict]:
    """Devuelve los ultimos max_exchanges intercambios (usuario+asistente)
    de ese remitente, en orden cronologico, listos para pasarle al LLM como
    mensajes previos: [{"role": "user"/"assistant", "content": "..."}].

    max_exchanges es facil de ajustar mas adelante -- ver
    settings.conversation_history_max_exchanges en app/config.py.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE sender = ? "
            "ORDER BY id DESC LIMIT ?",
            (sender, max_exchanges * 2),
        ).fetchall()
    finally:
        conn.close()

    rows.reverse()  # veniamos en orden descendente, lo volvemos cronologico
    return [{"role": role, "content": content} for role, content in rows]