FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==9.1.1 mypy==2.4.0 ruff==0.17.0
ENV PYTHONDONTWRITEBYTECODE=1 MYPY_CACHE_DIR=/tmp/mypy RUFF_CACHE_DIR=/tmp/ruff
WORKDIR /workspace
