# Stage 1: Build Next.js frontend
FROM node:20-alpine AS frontend-builder
# Build-identifiable version metadata. Passed by deploy.sh from git HEAD +
# the build timestamp, so the footer can show exactly which image is running.
ARG BUILD_SHA=local
ARG BUILD_TIME=""
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_PUBLIC_BUILD_SHA=$BUILD_SHA
ENV NEXT_PUBLIC_BUILD_TIME=$BUILD_TIME
WORKDIR /frontend
COPY app/frontend-next/package.json app/frontend-next/package-lock.json* ./
RUN npm install --legacy-peer-deps
COPY app/frontend-next/ ./
RUN npm run build

# Stage 2: Python backend
FROM python:3.11-slim AS backend
# Same build metadata, surfaced by the backend /version endpoint.
ARG BUILD_SHA=local
ARG BUILD_TIME=""
ENV TICKETY_BUILD_SHA=$BUILD_SHA
ENV TICKETY_BUILD_TIME=$BUILD_TIME
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Stage 3: Frontend runtime (Node)
FROM node:20-alpine AS frontend
WORKDIR /app
COPY --from=frontend-builder /frontend/package.json /frontend/package-lock.json* ./
COPY --from=frontend-builder /frontend/next.config.js ./
COPY --from=frontend-builder /frontend/server.js ./
COPY --from=frontend-builder /frontend/tsconfig.json ./
COPY --from=frontend-builder /frontend/tailwind.config.ts ./
COPY --from=frontend-builder /frontend/postcss.config.js ./
COPY --from=frontend-builder /frontend/.next ./.next
COPY --from=frontend-builder /frontend/app ./app
COPY --from=frontend-builder /frontend/public ./public
RUN npm install --legacy-peer-deps --omit=dev
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "server.js"]