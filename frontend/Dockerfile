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

# The compose file mounts an anonymous volume at /app/.angular. Docker seeds a new anonymous
# volume from the image's copy of that path and inherits its ownership -- and when the path
# does not exist in the image, creates it **root-owned**. `node_modules` survives only by
# accident of `npm ci` creating it here as `node`; `.angular` existed nowhere, so every
# `--renew-anon-volumes` -- the recovery frontend/CLAUDE.md prescribes for dependency changes
# -- produced a cache directory `ng serve` could not write, and the container crash-looped on
# `EACCES: permission denied, mkdir '/app/.angular/cache/...'`.
RUN mkdir -p /app/.angular

EXPOSE 4200

# --host 0.0.0.0  : bind to all interfaces so the host port mapping works.
# --poll 1000     : polling watcher — chokidar's inotify path is unreliable
#                   across docker bind mounts on WSL2.
CMD ["npm", "start", "--", "--host", "0.0.0.0", "--poll", "1000"]
