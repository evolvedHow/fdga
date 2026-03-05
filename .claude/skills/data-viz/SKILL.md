---
name: data-viz
description: Build charts, maps, and data visualizations. Use when creating bar charts, line charts, choropleth maps, scatter plots, histograms, or any visual representation of data. Covers Recharts, Chart.js, D3, Mapbox GL JS, and DeckGL patterns.
allowed-tools: Read, Write, Bash, Glob
---

## Chart Library Selection
- **Recharts**: Default for React dashboards. Simple, declarative, responsive.
- **Chart.js**: Use when Recharts lacks needed chart type or for canvas-based perf.
- **D3**: Only for custom/bespoke visualizations not covered by above libs.
- **Mapbox GL JS**: All geographic/choropleth visualizations. Use existing project token from env.
- **DeckGL**: Large-scale geospatial layers (100k+ features).

## Chart Best Practices
- Always set `ResponsiveContainer` width=100% in Recharts
- Use `aspect` prop instead of fixed height when possible
- Tooltips must show: label, value, formatted unit
- Axes: hide right/top spines, light gray gridlines only on value axis
- Color palettes must be color-blind safe (use ColorBrewer sequential/diverging scales)
- Always handle empty/null data states with a placeholder message
- Animate on mount, not on every re-render (use `isAnimationActive` wisely)

## Map Patterns (Redistricting Project)
- Default map style: `mapbox://styles/mapbox/light-v11` for data overlays
- District fills: use `fill-opacity: 0.6` to show underlying geography
- Always include a legend component for choropleth layers
- Hover state: raise `fill-opacity` to 0.85, show popup with district stats
- Click state: highlight selected district, emit event to parent component
- Layer order: base tiles → fill → line boundaries → labels → popups

## Accessibility
- Never use color as the only encoding — add pattern or label
- Provide `aria-label` on all SVG/canvas chart containers
- Keyboard-navigable tooltips for critical data points