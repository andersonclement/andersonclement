FROM python:3.12-slim

RUN groupadd -r smarttrader && useradd -r -g smarttrader smarttrader

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && chown -R smarttrader:smarttrader /app

USER smarttrader

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/login')" || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
