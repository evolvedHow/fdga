---
name: frontend-design
description: Create distinctive, production-grade frontend interfaces with high design quality. Use when building dashboards, components, pages, charts, or any UI. Generates polished, modern code with intentional aesthetic choices — avoids generic AI aesthetics.
allowed-tools: Read, Write, Bash, Glob
---

Before coding, commit to a BOLD aesthetic direction:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick a clear direction — data-dense/utilitarian, editorial/refined, dark-mode analytical, civic/authoritative, minimal/precise. Execute with intention.
- **Differentiation**: What makes this memorable?

## Design Rules
- Typography: Use distinctive fonts. Avoid Inter/Roboto/Arial. Pair a strong display font with a refined body font.
- Color: CSS variables throughout. Dominant palette + sharp accent. Avoid purple-on-white gradient clichés.
- Motion: CSS transitions for hover/focus states. Staggered load animations. One well-orchestrated reveal > scattered micro-interactions.
- Layout: Use grid. Asymmetry where it adds clarity. Generous whitespace OR controlled density — never both timidly.
- Backgrounds: Subtle texture, gradient mesh, or noise overlay to create depth. Never flat white/gray defaults.

## Dashboard-Specific Patterns
- Sticky sidebar nav with active state indicators
- Metric cards with trend indicators (up/down arrows + delta %)
- Responsive 12-column grid that collapses gracefully to mobile
- Skeleton loading states for async data
- Filter bar that persists above scrollable content
- Toast notifications for async actions

NEVER: cookie-cutter layouts, overused color schemes, unstyled HTML defaults.