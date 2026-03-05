---
name: dashboard-layout
description: Dashboard layout patterns, navigation structure, responsive grid, sidebar, filter bars, and component composition for analytics UIs. Use when scaffolding dashboard pages, building layout shells, creating navigation, or composing multi-panel views.
allowed-tools: Read, Write, Bash, Glob
---

## Layout Structure
```
AppShell
├── Sidebar (fixed, 240px)
│   ├── Logo / App name
│   ├── NavItems (icon + label)
│   └── Footer (version, user)
├── MainContent (flex-grow)
│   ├── TopBar (breadcrumb + actions)
│   ├── FilterBar (sticky, below TopBar)
│   └── PageContent (scrollable)
│       ├── MetricsRow (3-4 stat cards)
│       ├── PrimaryChart (60% width)
│       └── SecondaryPanels (40% width)
```

## Responsive Breakpoints
- Mobile (<768px): Sidebar collapses to bottom nav, single-column layout
- Tablet (768–1024px): Sidebar as drawer, 2-column grid
- Desktop (>1024px): Full sidebar, multi-column grid

## Component Patterns
- **StatCard**: metric value + label + trend delta + sparkline (optional)
- **FilterBar**: dropdowns for region/district/year + active filter chips + clear all
- **DataTable**: sortable columns, row hover, pagination, export CSV button
- **SectionHeader**: title + subtitle + right-aligned action button
- **EmptyState**: icon + message + CTA — always shown when data array is empty
- **LoadingSkeleton**: match exact shape of real component to prevent layout shift

## State Management
- Filter state: URL search params (shareable links) via `useSearchParams`
- Selected district: lifted to page-level state, passed down as props
- Chart data: fetched in page component, passed to chart children — no prop drilling beyond 2 levels

## Accessibility & UX
- Focus trap in modals/drawers
- Skip-to-content link at top of page
- All interactive elements reachable by keyboard
- Announce dynamic content updates with `aria-live` regions
```

---

**File structure to create:**
```
.claude/
└── skills/
    ├── frontend-design/SKILL.md
    ├── data-viz/SKILL.md
    ├── api-patterns/SKILL.md
    └── dashboard-layout/SKILL.md