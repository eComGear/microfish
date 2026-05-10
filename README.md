# MiroFish Backend on Cloudflare Containers

Deploys the MiroFish Flask + camel-ai backend as a Cloudflare Container fronted by a Worker.

## Prerequisites
- Node 18+
- Cloudflare account with Containers enabled (Workers Paid plan)
- `npm i -g wrangler` and `wrangler login`

## Setup
1. Drop the MiroFish source into this folder so the layout looks like:
   ```
   mirofish-cf/
     Dockerfile
     wrangler.jsonc
     src/worker.ts
     package.json
     backend/        <-- from https://github.com/666ghj/MiroFish
   ```
   (Easiest: `git clone https://github.com/666ghj/MiroFish tmp && cp -r tmp/backend ./backend`.)

2. Install Worker deps:
   ```
   npm install
   ```

3. Add your LLM secrets (one per command, paste value when prompted):
   ```
   wrangler secret put OPENAI_API_KEY
   wrangler secret put OPENAI_BASE_URL
   wrangler secret put DEEPSEEK_API_KEY
   wrangler secret put ZEP_API_KEY
   ```
   Add any other secrets from `backend/.env.example`.

4. Deploy:
   ```
   npm run deploy
   ```
   Wrangler prints a URL like `https://mirofish-backend.<your-subdomain>.workers.dev`.

5. Paste that URL into the Lovable app:
   - Project Settings → Build Secrets → add `VITE_MIROFISH_API_URL` with that URL.
   - Trigger a rebuild.

## Notes
- Container scales to zero after 10 min idle; first request after sleep takes ~30s cold-start.
- `instance_type: standard-3` = 4 vCPU / 12 GB RAM. Bump to `standard-4` if simulations OOM.
- View live logs: `npm run tail`.
- Inbound CORS is wide open (`*`); tighten in `src/worker.ts` once you know your prod origin.
