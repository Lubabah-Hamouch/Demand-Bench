# DemandBench dashboard

The browser front end for DemandBench: pick one of the 30,490 M5 item/store series and see its four-week forecast with an 80% likely range next to its recent sales, try promotion and price scenarios re-scored by the API, and check how far to trust the model. Every metric and control has a plain-language explanation behind a "?" button.

React 19, TypeScript, Vite, Tailwind CSS 4 and Recharts. There is no backend of its own: the browser calls the DemandBench API directly. The project overview, the API and deployment are described in the [root README](../README.md).

## Running it

Start the API first (see [Serving API](../README.md#serving-api)), then:

```bash
npm install
npm run dev        # http://localhost:5173
```

The app calls the API at `VITE_API_BASE_URL`, default `http://localhost:8020`. To use another address, copy `.env.example` to `.env.local` and change it there. The API must allow the dashboard's origin (`DEMANDBENCH_CORS_ORIGINS`); the dev server's origin is allowed by default.

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Dev server with hot reload on port 5173 |
| `npm run build` | Typecheck, then production build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | oxlint |
| `npm run typecheck` | `tsc -b` |
| `npm test` | Run the tests once (Vitest) |
| `npm run test:watch` | Tests in watch mode |
| `npm run check` | Lint, typecheck and tests: run before committing |

## Tests

The tests run in jsdom with Testing Library, against [MSW](https://mswjs.io/) handlers that return fixture responses shaped like the real API's JSON, so they need neither the API nor any M5 data. The fixture figures are made up; only the ids follow M5's naming.

- `src/api/client.test.ts`: URLs, methods and bodies for every endpoint, response parsing and error handling
- `src/components/*.test.tsx`: the series sidebar, chart rows and legend, and the "?" explanations
- `src/App.test.tsx`: the whole app: switching series, what-if requests (including the price slider's debounce), loading and error states, and that every metric has an explanation worded the same everywhere
- `src/test/`: fixtures, MSW handlers and shared setup

## Layout

- `src/api/client.ts`: typed client for the API
- `src/App.tsx`: page layout, data loading and scenario state
- `src/components/`: the page sections (header, sidebar, summary, scenario band, chart, 28-day table, drivers, model quality), plus `Explain` (the "?" explanations) and shared loading/error states
- `src/lib/glossary.ts`: the text of every explanation, kept in one place so the wording matches wherever a term appears
- `src/lib/content.ts`: backtest figures quoted on the page and readable names for the model's inputs. The figures are copied by hand from the last backtest run, so update them after rerunning `demandbench.backtest.compare`
- `src/lib/`: also number and date formatting, chart row building and data-loading hooks
- `src/theme.ts`, `src/index.css`: colours and fonts

## Building for deployment

Vite bakes `VITE_API_BASE_URL` into the bundle at build time, so set it when building, for example `VITE_API_BASE_URL=https://<api-host> npm run build`. The `Dockerfile` does the same with a build argument and serves `dist/` with nginx. See [Deployment](../README.md#deployment).
