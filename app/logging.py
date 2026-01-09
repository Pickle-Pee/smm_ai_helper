import logging


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for field in ("request_id", "user_id", "agent_type", "tokens", "image_mode"):
            if not hasattr(record, field):
                setattr(record, field, "-")
        return True


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s [%(levelname)s] %(name)s "
            "request_id=%(request_id)s user_id=%(user_id)s "
            "agent_type=%(agent_type)s tokens=%(tokens)s "
            "image_mode=%(image_mode)s: %(message)s"
        ),
    )
    logging.getLogger().addFilter(ContextFilter())
