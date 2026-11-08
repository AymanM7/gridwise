# GridWise dashboard: production image (Next.js standalone).
# Build from frontend/:  docker build -t gridwise-web --build-arg NEXT_PUBLIC_API_BASE_URL=/ .
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
# "/" = call the API on the same origin (Caddy routes /api/* to FastAPI). Baked in at build time.
ARG NEXT_PUBLIC_API_BASE_URL=/
ARG NEXT_PUBLIC_USE_FIXTURES=0
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_USE_FIXTURES=$NEXT_PUBLIC_USE_FIXTURES \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 3000
CMD ["node", "server.js"]
