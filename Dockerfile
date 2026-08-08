FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir ".[web]"

# Nicht als root laufen lassen — der Dienst braucht keinerlei Schreibzugriff.
RUN useradd --create-home --uid 10001 legowall
USER legowall

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()"

CMD ["uvicorn", "legowall.web:app", "--host", "0.0.0.0", "--port", "8000"]
