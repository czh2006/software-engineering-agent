# ---------- 构建阶段 ----------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.4 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    PATH="/opt/poetry/bin:$PATH"

# 安装 Poetry（官方安装脚本）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /app

# 先拷贝依赖清单以利用 Docker 层缓存
COPY pyproject.toml ./
RUN poetry install --no-interaction --no-ansi --no-root

# ---------- 运行阶段 ----------
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
