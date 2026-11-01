# syntax=docker/dockerfile:1
#
# DemandBench dashboard: a static Vite build served by nginx.
#
#   docker build --build-arg VITE_API_BASE_URL=https://api.example.com -t demandbench-web frontend
#
# Vite inlines VITE_API_BASE_URL into the bundle at build time, so pointing the dashboard
# at a different API means rebuilding the image. nginx listens on $PORT (default 8080).

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8020
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build


FROM nginx:1.27-alpine
ENV PORT=8080
# The nginx image renders templates with envsubst at startup (only defined variables,
# so nginx's own $uri etc. are left alone).
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
