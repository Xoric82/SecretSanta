# Secret Santa Homelab Container
FROM python:3.12-alpine

WORKDIR /app

# Create non-root user for security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy application files
COPY database.py server.py manage.py ./
COPY public/ ./public/

# Create data directory for SQLite database persistence
RUN mkdir -p /data && chown -R appuser:appgroup /app /data

USER appuser

ENV PORT=8082
ENV HOST=0.0.0.0
ENV SECRETSANTA_DB=/data/secretsanta.db

EXPOSE 8082

VOLUME ["/data"]

CMD ["python", "server.py"]
