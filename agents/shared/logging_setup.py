"""
Structured logging configuration.

Every agent calls setup_logging() at startup to get JSON logs that can be
parsed by Better Stack / Datadog / whatever. In dev, a console renderer is
nicer for humans.
"""
import logging
import sys

import structlog

from .settings import get_settings


def setup_logging(service_name: str) -> None:
    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Pretty console in dev; JSON in prod
    if settings.MOCK_MODE or settings.LOG_LEVEL == "DEBUG":
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(service=service_name)
