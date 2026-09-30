# =============================================================================
# Stage 1: Build React Dashboard
# =============================================================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app/dashboard

# Install frontend dependencies
COPY dashboard/package.json ./
RUN npm install

# Build static assets
COPY dashboard/ ./
RUN npm run build

# =============================================================================
# Stage 2: Python Trading Engine & API Server
# =============================================================================
FROM python:3.11-slim AS production

WORKDIR /app

# Install system dependencies & timezone data
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    tzdata \
    && ln -fs /usr/share/zoneinfo/Asia/Kolkata /etc/localtime \
    && dpkg-reconfigure --frontend noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Kolkata

# Install Python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY config/ ./config/
COPY core/ ./core/
COPY broker/ ./broker/
COPY strategy/ ./strategy/
COPY risk/ ./risk/
COPY engine/ ./engine/
COPY utils/ ./utils/
COPY backtest/ ./backtest/
COPY data/ ./data/
COPY api/ ./api/
COPY main.py ./

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /app/dashboard/dist ./dashboard/dist

# Create logs directory
RUN mkdir -p logs

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=8050 \
    LOG_LEVEL=INFO

# Expose API and Dashboard port
EXPOSE 8050

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8050/api/status || exit 1

# Start FastAPI server (serves both API & React Dashboard)
CMD ["python", "-m", "uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8050"]
