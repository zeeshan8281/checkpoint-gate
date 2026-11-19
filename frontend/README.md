# CheckpointGate UI

Three independently addressable pages built with **TypeScript, Tailwind CSS 4,
and Vite**, using Hallmark’s Console design system:

| Route | Contents |
| --- | --- |
| `/` | Results, accuracy intervals, query-family breakdown, tool-fault comparison, format violations, paired outcomes, figure downloads |
| `/explorer/` | Searchable task list, family and paired-outcome filters, checkpoint comparison, original model and tool transcripts |
| `/method/` | Protocol, dataset splits, training, compute accounting, evidence archive, limitations |

```bash
npm ci
npm run dev        # http://127.0.0.1:8791
npm run typecheck
npm run build      # emits the deployable ../web directory
```

Edit the three source HTML pages and `src/`, not generated `web/` files.
Shared color and font tokens live in `src/tokens.css`; Tailwind utilities and
component styles are in `src/styles.css`. The typed explorer implementation is
`src/explorer.ts`, with evidence interfaces in `src/types.ts`. `src/main.ts`
preserves links shared before the multipage redesign. The Vite build includes
all three HTML entry points. Direct loads and refreshes work with static hosting.

The explorer reads the completed public `pilot.json`. Model, task, family,
paired outcome, and search query persist in the URL. Both checkpoints remain
available for each task. There are 200 paired tasks and 400 original transcripts.
No training key or privileged Cloudflare token is shipped to the browser, and
viewing any page makes no model calls.

The results summary is static and remains readable without JavaScript. If the
pilot is replaced, update its summary and graph markup from the new evidence;
do not present the current pilot’s fixed values as a new run’s results. The
explorer requires JavaScript, with a raw-evidence download as a fallback.

`public/pilot.json` and `public/heldout-results.png` preserve the completed pilot.
The original scripted infrastructure self-test is in `public/self-test.html`.
Vite copies public assets unchanged. New downloadable PNG/SVG figures are
rendered from the frozen JSON using Matplotlib, with zero-based axes:

```bash
# From the repository root, in a Python environment with matplotlib installed:
python analysis/plot_dashboard.py
npm run build --prefix frontend
```

The three new PNGs are 2400 × 1500; SVG versions support vector editing.
No new training was run to create these figures. Keep credentials and private
evidence out of `public/`.

Both Cloudflare configurations serve generated `web/` assets:

```bash
cd ../worker
npm ci
npx wrangler deploy --config wrangler.site.toml
npx wrangler deploy --config wrangler.toml
```

The second command updates the existing authenticated evidence Worker and its
public assets, preserving its R2 and Durable Object bindings.
