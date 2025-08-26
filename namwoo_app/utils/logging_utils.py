# namwoo_app/utils/logging_utils.py
import logging
import json
import os
import threading
from logging.handlers import RotatingFileHandler

# Determine the absolute path of the directory containing this file (utils).
_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
# Go up one level to get the project's root directory (namwoo_app).
_PROJECT_ROOT = os.path.dirname(_UTILS_DIR)
# Create a guaranteed absolute path to the logs directory inside the project.
LOGS_BASE_DIR = os.path.join(_PROJECT_ROOT, "logs")

# This cache will store fully configured logger objects for each conversation ID.
# Format: { 'conversation_id': (server_logger, conversation_logger) }
_loggers_cache = {}
_lock = threading.Lock()


class ConversationIdFilter(logging.Filter):
    """A logging filter that injects the conversation_id into the LogRecord."""
    def __init__(self, conversation_id: str):
        super().__init__()
        self.conversation_id = conversation_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.conversation_id = self.conversation_id
        return True


class JsonFormatter(logging.Formatter):
    """Formats log records as a single line of JSON for server logs."""
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "conversation_id": getattr(record, 'conversation_id', 'unknown'),
            "name": record.name,
            "module": record.module,
            "funcName": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


class ConversationFormatter(logging.Formatter):
    """Formats logs in a simple, human-readable chat format."""
    def format(self, record: logging.LogRecord) -> str:
        # 'speaker' is passed in the 'extra' dict when logging
        speaker = getattr(record, 'speaker', 'System')
        timestamp = self.formatTime(record, self.datefmt)
        return f"[{timestamp}] {speaker.upper()}: {record.getMessage()}"


def get_conversation_loggers(conversation_id: str) -> tuple[logging.Logger, logging.Logger]:
    """
    Gets or creates two dedicated loggers for a specific conversation ID.
    This function is thread-safe and caches loggers for performance.

    Returns:
        A tuple of (server_logger, conversation_logger).
    """
    if not conversation_id or not str(conversation_id).strip():
        conversation_id = 'unassigned'
    else:
        conversation_id = str(conversation_id).strip()

    # First check is outside the lock for performance
    if conversation_id in _loggers_cache:
        return _loggers_cache[conversation_id]

    with _lock:
        # Second check is inside the lock to handle race conditions
        if conversation_id in _loggers_cache:
            return _loggers_cache[conversation_id]

        # Use the absolute LOGS_BASE_DIR constant to build the path
        log_dir = os.path.join(LOGS_BASE_DIR, conversation_id)
        os.makedirs(log_dir, exist_ok=True)

        # --- 1. Server Logger (JSON format) ---
        server_logger_name = f"conv.{conversation_id}.server"
        server_logger = logging.getLogger(server_logger_name)
        
        if not server_logger.handlers:
            server_logger.propagate = False
            server_logger.setLevel(logging.DEBUG)
            server_log_file = os.path.join(log_dir, "server_logs.json")
            server_handler = RotatingFileHandler(
                filename=server_log_file, maxBytes=5_242_880, backupCount=3, encoding="utf8"
            )
            server_handler.setLevel(logging.DEBUG)
            server_handler.setFormatter(JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
            server_handler.addFilter(ConversationIdFilter(conversation_id))
            server_logger.addHandler(server_handler)

        # --- 2. Conversation Logger (Chat transcript format) ---
        conversation_logger_name = f"conv.{conversation_id}.chat"
        conversation_logger = logging.getLogger(conversation_logger_name)

        if not conversation_logger.handlers:
            conversation_logger.propagate = False
            conversation_logger.setLevel(logging.INFO)
            conversation_log_file = os.path.join(log_dir, "conversation.log")
            conversation_handler = logging.FileHandler(filename=conversation_log_file, encoding="utf8")
            conversation_handler.setLevel(logging.INFO)
            conversation_handler.setFormatter(ConversationFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
            conversation_logger.addHandler(conversation_handler)
        
        loggers_tuple = (server_logger, conversation_logger)
        _loggers_cache[conversation_id] = loggers_tuple

        return loggers_tuple