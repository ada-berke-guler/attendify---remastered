FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Tiny final stage: copy the built SPA into the shared volume Caddy serves, then exit.
FROM busybox:1.36
COPY --from=build /app/dist /dist
CMD ["sh", "-c", "rm -rf /srv/* && cp -r /dist/. /srv/ && echo 'web: static files copied'"]
