# Cloudflare Tunnel Setup

## Quick tunnel (no domain — for local testing)

No configuration needed. Leave `CLOUDFLARE_TUNNEL_TOKEN` unset and start
the service:

```bash
docker compose --profile tunnel up -d cloudflared
docker compose logs cloudflared   # URL is printed here, e.g.:
                                  # Your quick Tunnel has been created! Visit it at https://xxxxx.trycloudflare.com
```

The URL is valid HTTPS but changes every restart.

## Named tunnel (stable hostname — for production)

Requires a domain added to your Cloudflare account.

### One-time setup

1. Install `cloudflared` locally: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

2. Authenticate:
   ```bash
   cloudflared tunnel login
   ```

3. Create the tunnel:
   ```bash
   cloudflared tunnel create fairy-api
   ```
   Note the tunnel ID in the output.

4. In the Cloudflare Zero Trust dashboard (one.dash.cloudflare.com):
   - Go to **Networks → Tunnels → fairy-api → Configure → Public Hostnames**
   - Add a hostname: `api.<your-domain>` → `http://localhost:8001`
   - (The hostname and routing can also be configured via `config.yml` if
     you mount it into the container, but the dashboard approach is simpler
     when using token-based auth.)

5. Copy the tunnel token from the dashboard (**Networks → Tunnels → fairy-api →
   Configure → Overview → Install connector → Docker**) — it looks like a long
   JWT string.

6. Add to `.env` (gitignored):
   ```
   CLOUDFLARE_TUNNEL_TOKEN=eyJ...
   ```

### Running the named tunnel

```bash
docker compose --profile tunnel up -d cloudflared
```

The backend is now reachable at `https://api.<your-domain>` with a valid
Cloudflare-managed TLS certificate.

### Updating `ALLOWED_ORIGINS`

Once the frontend hostname is known, add it to `.env`:
```
ALLOWED_ORIGINS=https://fairy.pages.dev,https://your-custom-domain.com
```

The backend CORS middleware reads this at startup (see `app/main.py`).
