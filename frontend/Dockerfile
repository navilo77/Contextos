FROM node:24-alpine AS dependencies

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:24-alpine AS builder

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_CONTEXT_OS_API_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_CONTEXT_OS_API_URL=${NEXT_PUBLIC_CONTEXT_OS_API_URL}
COPY --from=dependencies /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

FROM node:24-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=builder --chown=node:node /app ./
USER node

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0"]
