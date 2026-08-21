# Development image — runs `ng serve` with hot reload.
# Source is bind-mounted from the host via docker-compose; node_modules
# is kept in an anonymous container volume so the host's (possibly
# absent or platform-mismatched) copy doesn't shadow it.

FROM node:24-alpine

WORKDIR /app

# node:24-alpine ships a non-root "node" user (uid 1000); give it /app.
RUN chown node:node /app

# Install deps in the image so `docker compose up` is one step.
COPY --chown=node:node package.json package-lock.json ./

USER node

RUN npm ci

EXPOSE 4200

# --host 0.0.0.0  : bind to all interfaces so the host port mapping works.
# --poll 1000     : polling watcher — chokidar's inotify path is unreliable
#                   across docker bind mounts on WSL2.
CMD ["npm", "start", "--", "--host", "0.0.0.0", "--poll", "1000"]
