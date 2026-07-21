# KylinBootLab Phase 9: Evidence Dashboard Implementation Plan

**Goal:** Build a zero-dependency static SPA (Vite + React + Recharts + Tailwind) consolidating Phase 1-8 evidence into a three-tab interactive dashboard.

## Execution Mode

This is a frontend project — Node.js toolchain, not subagent-driven. Controller executes inline.

## Tasks

1. Scaffold Vite + React + Recharts + Tailwind (npm create vite, npm install)
2. Build data module (static JSON imports from docs/evidence/)
3. Build BootTimeline tab (Recharts bar + reference line + pie)
4. Build Optimization tab (verdict cards with color coding)
5. Build Agent Dashboard tab (bottleneck list + skill cards + gauge)
6. Write components tests (Vitest)
7. Build production bundle (vite build) → dist/
8. Link from kbl report CLI

## Exit

- `npm run build` produces `dist/index.html` < 5MB
- Three tabs render with real Phase 1-8 data
- npm test passes
