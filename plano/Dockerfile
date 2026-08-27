FROM katanemo/plano:0.4.36

WORKDIR /app
RUN uv sync --frozen --no-dev && \
    sed -i 's#uv run python -m planoai.config_generator#/app/.venv/bin/python -m planoai.config_generator#' /etc/supervisor/conf.d/supervisord.conf
ENV UV_OFFLINE=1
