# CheckpointGate results UI

TypeScript, Tailwind CSS 4, and Vite. The layout uses Hallmark's Console theme.
The browser reads the completed, public `pilot.json`; it has no training keys or
privileged Cloudflare token and makes no model calls.

```bash
npm ci
npm run dev        # http://127.0.0.1:8791
npm run typecheck
npm run build      # emits the deployable ../web directory
```

Edit `index.html` and `src/`, not the generated `web/` bundle. Shared colour and
font tokens live in `src/tokens.css`; Tailwind utilities and component styles
are in `src/styles.css`. The transcript renderer and URL selection state are
typed in `src/main.ts` and `src/types.ts`.

`public/pilot.json` and `public/heldout-results.png` are the real completed pilot.
The original scripted self-test lives in `public/self-test.html` and is explicitly
labelled. Vite copies these assets unchanged. To publish a new completed export,
point `analysis/export_results.py --web` at `frontend/public`, then rebuild.
Keep credentials and private evidence out of `public/`.

Both Cloudflare configurations serve the generated `web/` directory:

```bash
cd ../worker
npm ci
npx wrangler deploy --config wrangler.site.toml
npx wrangler deploy --config wrangler.toml
```

The second command updates the existing authenticated evidence Worker as well as
its public assets. It preserves its R2 and Durable Object bindings.
