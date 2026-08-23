# Stage 1: Build Next.js frontend
FROM node:24.19.0-alpine AS frontend-builder
ARG NPM_VERSION=12.0.2
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
RUN npm install --global "npm@$NPM_VERSION" && npm ci && npm ls --all
COPY app/frontend-next/ ./
RUN npm run build
RUN npm run verify:production-routes

# Stage 2: Python backend
FROM python:3.11.16-slim AS backend
ARG PIP_VERSION=26.2.1
ARG SETUPTOOLS_VERSION=84.0.0
ARG WHEEL_VERSION=0.48.0
# Same build metadata, surfaced by the backend /version endpoint.
ARG BUILD_SHA=local
ARG BUILD_TIME=""
ENV TICKETY_BUILD_SHA=$BUILD_SHA
ENV TICKETY_BUILD_TIME=$BUILD_TIME
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 tickety \
    && useradd --uid 10001 --gid tickety --no-create-home --shell /usr/sbin/nologin tickety

COPY requirements.txt requirements.lock ./
RUN python -m pip install --no-cache-dir --upgrade \
      "pip==$PIP_VERSION" "setuptools==$SETUPTOOLS_VERSION" "wheel==$WHEEL_VERSION" \
    && python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip check

COPY --chown=tickety:tickety . .

EXPOSE 8000
USER 10001:10001
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Stage 3: Frontend runtime (Node)
FROM node:24.19.0-alpine AS frontend
ARG NPM_VERSION=12.0.2
WORKDIR /app
COPY --from=frontend-builder /frontend/package.json /frontend/package-lock.json* ./
COPY --from=frontend-builder /frontend/next.config.js ./
COPY --from=frontend-builder /frontend/server.js ./
COPY --from=frontend-builder /frontend/lib/ws-proxy-security.js ./lib/ws-proxy-security.js
COPY --from=frontend-builder /frontend/tsconfig.json ./
COPY --from=frontend-builder /frontend/tailwind.config.ts ./
COPY --from=frontend-builder /frontend/postcss.config.js ./
COPY --from=frontend-builder /frontend/.next ./.next
COPY --from=frontend-builder /frontend/app ./app
COPY --from=frontend-builder /frontend/public ./public
RUN npm install --global "npm@$NPM_VERSION" && npm ci --omit=dev && npm ls --omit=dev --all
RUN chown -R node:node /app
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV NODE_ENV=production
EXPOSE 3000
USER node
CMD ["node", "server.js"]
