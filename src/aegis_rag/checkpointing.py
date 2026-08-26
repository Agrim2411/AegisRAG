"""LangGraph checkpoint configuration for resumable incident workflows."""

import os
import sqlite3

from langgraph.checkpoint.memory import InMemorySaver


def build_checkpointer(path: str | None):
    if not path:
        return InMemorySaver()
    from langgraph.checkpoint.sqlite import SqliteSaver

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(connection)
