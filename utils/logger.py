"""
Logging utility for the NSE Automated Trading System.

Provides a configurable logger with rotating file handlers and
color-coded console output for easy monitoring during live trading.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional


# ---------------------------------------------------------------------------
# ANSI colour codes (work on Windows 10+ with VT enabled, and all *nix terms)
# ---------------------------------------------------------------------------
class _Colours:
    """ANSI escape sequences for coloured console output."""
    RESET = "\033[0m"
    GREY = "\033[38;5;244m"
    BLUE = "\033[34m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD_RED = "\033[1;31m"

    LEVEL_MAP = {
        logging.DEBUG: GREY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }


class _ColouredFormatter(logging.Formatter):
    """Formatter that injects ANSI colour codes around the log level."""

    def __init__(self, fmt: str, datefmt: Optional[str] = None) -> None:
        super().__init__(fmt, datefmt)

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        colour = _Colours.LEVEL_MAP.get(record.levelno, _Colours.RESET)
        record.levelname = f"{colour}{record.levelname:<8}{_Colours.RESET}"
        return super().format(record)


# ---------------------------------------------------------------------------
# Enable VT100 processing on Windows so ANSI codes actually render
# ---------------------------------------------------------------------------
def _enable_windows_ansi() -> None:
    """Enable virtual-terminal processing on Windows consoles."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # noqa: BLE001
        pass  # Fail silently – colours just won't render


_enable_windows_ansi()

# ---------------------------------------------------------------------------
# Default log format
# ---------------------------------------------------------------------------
_DEFAULT_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DEFAULT_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str = "TradeSystem",
    log_level: str = "INFO",
    log_dir: str = "logs",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    console_output: bool = True,
    colour: bool = True,
) -> logging.Logger:
    """Create and return a configured :class:`logging.Logger`.

    Parameters
    ----------
    name:
        Logger name (typically module or subsystem).
    log_level:
        Minimum log level as a string (``DEBUG``, ``INFO``, …).
    log_dir:
        Directory for log files.  Created automatically if missing.
    log_file:
        Explicit log-file name.  Defaults to ``<name>.log``.
    max_bytes:
        Maximum size (bytes) of a single log file before rotation.
    backup_count:
        Number of rotated log files to keep.
    console_output:
        Whether to attach a console (``StreamHandler``) to the logger.
    colour:
        Use ANSI colour codes on the console handler.

    Returns
    -------
    logging.Logger
        Fully configured logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers when called multiple times
    if logger.handlers:
        return logger

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    # ---- File handler (rotating) ----
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_name = log_file or f"{name}.log"
        file_path = os.path.join(log_dir, file_name)

        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_formatter = logging.Formatter(_DEFAULT_FMT, _DEFAULT_DATE_FMT)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        # Fall back to console-only if we can't write files
        sys.stderr.write(f"[logger] Failed to create file handler: {exc}\n")

    # ---- Console handler ----
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        if colour:
            console_formatter = _ColouredFormatter(_DEFAULT_FMT, _DEFAULT_DATE_FMT)
        else:
            console_formatter = logging.Formatter(_DEFAULT_FMT, _DEFAULT_DATE_FMT)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # Prevent propagation to the root logger
    logger.propagate = False

    return logger
