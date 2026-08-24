# Email Template Builder — Frontend

React 18 + TypeScript single-page application that powers the visual email template builder. Built with Vite and served by Frappe at `/builder?template=<name>`.

> 📖 For full usage and developer documentation, see the [Technical Guide](../docs/EMAIL_BUILDER_TECHNICAL_GUIDE.md) and [User Guide](../docs/EMAIL_BUILDER_USER_GUIDE.md).

---

## Tech Stack

| Library | Version | Purpose |
|---------|---------|---------|
| React | 18 | UI rendering |
| TypeScript | ~5.9 | Type safety |
| Vite | 5 | Build tool + dev server |
| frappe-react-sdk | ^1.17 | Frappe API calls, auth, SWR |
| @dnd-kit/core | ^6 | Drag-and-drop primitives |
| @dnd-kit/sortable | ^10 | Sortable block/row lists |
| lucide-react | ^1.24 | Icons |
| Oxlint | ^1.71 | Linting |

---

## Project Structure

```
src/
├── App.tsx                        # Root — FrappeProvider, auth guard, controller
├── types.ts                       # All shared TypeScript types
├── hooks/
│   ├── useEmailBuilderController.ts   # Root hook — composes everything
│   ├── useBuilderDocumentState.ts     # Document state + undo/redo history
│   ├── useBuilderTemplateState.ts     # Save state, mode, conflict flags
│   ├── useBuilderData.ts              # SWR data fetchers + API call wrappers
│   ├── useBuilderPanels.ts            # Panel layout + selection state
│   ├── useBuilderDialogState.ts       # Modal/dialog management
│   ├── useBuilderDnd.ts               # @dnd-kit drag-and-drop handlers
│   ├── useBuilderImageUpload.ts       # Image upload + library pagination
│   ├── useBuilderPreviewTest.ts       # Preview + test email state
│   ├── useBuilderRealtime.ts          # WebSocket subscriptions
│   ├── useBuilderKeyboardShortcuts.ts # Keyboard event bindings
│   ├── useRevisionPreview.ts          # Revision preview + restore
│   └── useTextEditorBridge.ts         # Rich text editor integration
├── lib/
│   ├── builder.ts             # Schema helpers: createBlock, moveBlock, cloneNode, etc.
│   ├── api.ts                 # API method names + SWR cache key builder
│   ├── builderConstants.ts    # HISTORY_LIMIT, breakpoints, block labels, panel widths
│   ├── errors.ts              # Error parsing: getErrorMessage, isConcurrencyError
│   ├── tokens.ts              # Frontend merge-field token regex + validation
│   ├── suggestions.ts         # Merge field autocomplete suggestion engine
│   └── panelState.ts          # Panel layout state machine (wide/desktop/tablet/mobile)
└── components/
    ├── Canvas.tsx             # Email canvas with DndContext
    ├── Inspector.tsx          # Right-hand property panel (content/style/visibility)
    ├── Sidebar.tsx            # Left-hand block picker, rows, layers, saved components
    └── BuilderDialogs.tsx     # All modals (conflict, preview, overwrite, history, etc.)
```

---

## Development

### Prerequisites

- Node.js 18.18–22.x (20.19.2 recommended for Frappe v15)
- Yarn
- A running local Frappe bench (for API proxy)

### Setup

```bash
cd apps/finbyzreach/builder
yarn install
```

### Start dev server

```bash
yarn dev
```

Starts Vite at **http://localhost:8080** and proxies all `/api` and `/assets` requests to your local Frappe bench.

Open the builder with:
```
http://localhost:8080/builder?template=<Email Template name>
```

### Type checking

```bash
yarn typecheck
```

Runs `tsc --noEmit` against `tsconfig.app.json`. No output means no errors.

### Unit tests

```bash
yarn test
```

Runs TypeScript type check (`tsconfig.test.json`) then the Node test runner through `tsx` against all `src/lib/*.test.ts` files.

**Test files:**

| File | What it tests |
|------|--------------|
| `lib/builder.test.ts` | `moveBlock`, `normalizeColumnWidths`, `rebalanceColumnWidths`, `cloneNode` |
| `lib/errors.test.ts` | `getErrorMessage`, `isConcurrencyError`, `getErrorStatus` |
| `lib/tokens.test.ts` | Merge field token validation (mirrors backend logic) |
| `lib/suggestions.test.ts` | Merge field autocomplete suggestion engine |
| `lib/panelState.test.ts` | Panel layout state machine transitions |

### Lint

```bash
yarn lint
```

Runs [Oxlint](https://oxc.rs/docs/guide/usage/linter.html) with React and TypeScript rules.

### Production build

```bash
yarn build
```

Runs in sequence:
1. `yarn typecheck` — fail fast on type errors
2. `vite build --base=/assets/finbyzreach/builder/` — outputs to `../finbyzreach/public/builder/`
3. `yarn copy-html-entry` — copies `index.html` → `../finbyzreach/www/builder.html`

After building, run `bench build --app finbyzreach` on the Frappe side to collect static assets.

---

## Key Concepts

### Hook composition

All state and logic lives in hooks. `useEmailBuilderController` is the single root hook used by `App.tsx` — it composes ~12 sub-hooks, each with a single responsibility. No global stores (Redux, Zustand, etc.).

### State split

| Hook | What it owns |
|------|-------------|
| `useBuilderDocumentState` | The email schema + undo/redo stacks |
| `useBuilderTemplateState` | Save state, template mode, conflict flags |
| `useBuilderData` | Server data via SWR (components, merge fields, revisions, images) |
| `useBuilderPanels` | Panel open/closed state, selected node, viewport |

### Autosave

- 4-second idle delay after last edit
- Maximum 30-second forced save during continuous editing
- 3-strike circuit breaker: disables autosave after 3 consecutive failures
- All post-`await` state updates guarded with `mounted.current` ref

### Concurrency

Every save sends `expected_modified` (the server timestamp from the last load/save). The server returns HTTP 409 if another user saved in between. The frontend detects this via `isConcurrencyError()` and shows a conflict modal.

### Realtime

Uses Frappe's Socket.IO socket from `FrappeContext`. Subscribes to `email_builder_saved`, `email_builder_revision_created`, and `email_builder_assets_changed` events scoped to the current template. Own events are filtered out using a session-stable `client_id`.

---

## Build Chunks

Vite splits the bundle into separate chunks for efficient caching:

| Chunk | Contents |
|-------|---------|
| `react-vendor` | react + react-dom |
| `frappe-sdk` | frappe-react-sdk + frappe-js-sdk + swr |
| `drag-drop` | @dnd-kit/core + sortable + utilities |
| `icons` | lucide-react |
| (main) | Application code |

---

## Linting Configuration

Oxlint is configured in `.oxlintrc.json`. To enable type-aware rules, install `oxlint-tsgolint` and set `"typeAware": true`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": { "typeAware": true },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list.
