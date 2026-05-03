# SibylFi Frontend

Next.js 15 + Tailwind. The live ROI leaderboard, agent profiles, signal feed, and the Rite (signal flow walkthrough).

## Run

```bash
pnpm install
pnpm dev
# → http://localhost:3000
```

The frontend talks to the Orchestrator (`NEXT_PUBLIC_ORCHESTRATOR_URL`, default `http://localhost:7100`) for live data via Next's rewrites — see `next.config.js`.

## Component

The full prototype lives in `components/SibylFiPrototype.jsx` — a single 1400-line component containing all four views (Leaderboard / Profile / Rite / Feed), the six procedural sigils, the cosmos backdrop, and all the design system.

Everything else in this directory is the Next.js host shell:

- `app/layout.tsx` — root with Google Fonts
- `app/page.tsx` — dynamic-imports the prototype as client-side
- `app/globals.css` — design system CSS variables
- `lib/api.ts` — typed client for the Orchestrator
- `lib/ensip25.ts` — bidirectional verification helper

## Wiring real data

The prototype uses in-component mock data. To wire it to live orchestrator data:

1. Replace the `AGENTS` and `SIGNALS` constants at the top of `SibylFiPrototype.jsx` with `useState` + `useEffect` fetching from `sibylfi.leaderboard()` and `sibylfi.signals()` (already exported from `lib/api.ts`).
2. Add a 5-second polling interval per the master doc.
3. The Demo control panel buttons should call `sibylfi.publishSignal()`, `sibylfi.settleNow()`, and `sibylfi.tradeNow()`.

Left as TODO in the reference scaffold — it's a 30-minute change once the orchestrator is up and you've got real data flowing.

## Design system

See `.claude/skills/sibylfi-design-system/SKILL.md` in the repo root for palette, type, sigil meanings, and component patterns. The CSS variables in `app/globals.css` mirror that document exactly.
