"""Renkli konsol logger — projede `print()` yerine bu modul kullanilir."""

import logging
import sys

_RESET = "\x1b[0m"
_COLORS = {
    logging.DEBUG: "\x1b[36m",     # cyan
    logging.INFO: "\x1b[32m",      # yesil
    logging.WARNING: "\x1b[33m",   # sari
    logging.ERROR: "\x1b[31m",     # kirmizi
    logging.CRITICAL: "\x1b[1;41m",  # kirmizi zemin
}


class ColorFormatter(logging.Formatter):
    """Seviye adini ANSI rengiyle boyayan formatter."""

    _FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    _DATEFMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__(fmt=self._FMT, datefmt=self._DATEFMT)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        """Log kaydini biçimlendirir; TTY ise seviyeyi renklendirir."""
        if not self.use_color:
            return super().format(record)
        color = _COLORS.get(record.levelno, "")
        original = record.levelname
        record.levelname = f"{color}{original}{_RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


def get_logger(name: str = "gokhancoskun", level: int = logging.INFO) -> logging.Logger:
    """Adlandirilmis, tek handler'li logger dondurur."""
    log = logging.getLogger(name)
    if log.handlers:
        return log
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter(use_color=sys.stdout.isatty()))
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False
    return log


logger = get_logger()
