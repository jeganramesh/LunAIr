# Multi-stage: build the Vite bundle, then serve it from nginx.
FROM node:20-alpine AS builder

WORKDIR /app

# VITE_* values are baked in at build time, not read at runtime.
ARG VITE_API_URL=http://localhost:8080
ARG VITE_GATEWAY_URL=http://localhost:8080
ENV VITE_API_URL=$VITE_API_URL \
    VITE_GATEWAY_URL=$VITE_GATEWAY_URL

COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY tsconfig.json vite.config.ts tailwind.config.js postcss.config.js index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000