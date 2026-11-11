FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY base.py modelos.py triagem.py esquemas.py armazenamento.py demo.py api.py gravar_demo.py ./
COPY dados_exemplo ./dados_exemplo

RUN chmod -R a+rX /app && useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/saude', timeout=2)"

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
