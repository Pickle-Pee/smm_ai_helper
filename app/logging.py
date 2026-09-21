import logging


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            # Framework exception rendering can include SQL parameters, complete
            # Telegram updates or chained provider envelopes. Keep the type only.
            record.msg = "Unhandled exception error_type=%s"
            record.args = (record.exc_info[0].__name__,)
            record.exc_info = record.exc_text = None
        elif record.name.startswith(("aiogram", "aiohttp")) and record.levelno >= logging.WARNING:
            # aiogram's polling errors interpolate str(exc) without exc_info.
            record.msg, record.args = "Telegram transport/lifecycle warning", ()
        for field in (
            "request_id",
            "user_id",
            "agent_type",
            "expert_core_version",
            "tokens",
            "image_mode",
        ):
            if not hasattr(record, field):
                setattr(record, field, "-")
        return True


def setup_logging() -> None:
    # Transport INFO/DEBUG includes complete URLs (Telegram embeds its token in
    # the URL; public source query strings may contain private context).
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s [%(levelname)s] %(name)s "
            "request_id=%(request_id)s user_id=%(user_id)s "
            "agent_type=%(agent_type)s expert_core_version=%(expert_core_version)s "
            "tokens=%(tokens)s "
            "image_mode=%(image_mode)s: %(message)s"
        ),
    )
    logging.getLogger().addFilter(ContextFilter())

    f = ContextFilter()

    # 1) Root logger
    root = logging.getLogger()
    root.addFilter(f)

    # 2) All existing handlers (важно: фильтр должен стоять на handler'ах,
    # которые форматируют record)
    for h in root.handlers:
        h.addFilter(f)

    # 3) Uvicorn loggers часто имеют свои handlers — добавим и туда
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(logger_name)
        lg.addFilter(f)
        for h in lg.handlers:
            h.addFilter(f)
