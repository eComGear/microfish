# Single image used for BOTH the API and the worker.
# fly.api.toml runs `node dist/api/server.js`.
# fly.worker.toml is a no-op machine app; spawnWorkerMachine sets cmd dynamically.

FROM node:20-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev=false
COPY tsconfig.json ./
COPY src ./src
RUN npx tsc -p tsconfig.json

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
EXPOSE 8080
CMD ["node", "dist/api/server.js"]
