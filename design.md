# DESIGN.md

Last updated: 2026-05-27

## How To Use This File

Use this file as a standalone design handoff. No Specra plugin, MCP server, or account context is required.
Place `DESIGN.md` in the project root or paste it into your coding agent. Use it alongside `theme.css` when available; if the project has an existing theme system, map these roles to the closest local tokens instead of replacing unrelated architecture.
The user prompt decides what to build. This file decides how the result should look and feel.

## 1. Visual Theme & Atmosphere

Dense, high-contrast, minimal, technical, terminal-like, utilitarian. Treat the screenshots as visual-system input, not as a mandate to recreate the same product surface. The user's requested screen type and existing app context decide whether the output should become a blog page, marketing page, dashboard, settings flow, editor, or another surface.

Thin, utilitarian chrome with compact control bands. Make new screens feel aligned through dense positions table with symbol-led rows and option-leg subrows; narrow watchlist rail with bid/ask ladder; single-row totals utility bar with green/red P&L chips, not through copied product structure, generic dashboard decoration, or broad ornamental color.

### Key Characteristics

- Density: compact; give the main workflow room while keeping repeated chrome efficient.
- Surface model: Calm, low-elevation surfaces; use tone, borders, and spacing before shadow.
- Chrome: Thin, utilitarian chrome with compact control bands.
- First-glance hierarchy: status header (attached) with account counters and P/L summary.
- Recurring modules: dense positions table with symbol-led rows and option-leg subrows; narrow watchlist rail with bid/ask ladder; single-row totals utility bar with green/red P&L chips.
- Accent: Sparse, purposeful accents for primary actions, active states, and small status signals.
- Typography: Product-native type: expressive enough for hierarchy, restrained enough for repeated UI.

## 2. Color Palette & Roles

Do not copy raw extracted color values into component code. `theme.css` owns the actual values; `DESIGN.md` describes how to use the roles.

- `background`: base canvas and persistent app shell.
- `foreground`: primary readable text and icon color.
- `card`: contained panels, grouped controls, and embedded list surfaces.
- `muted` / `muted-foreground`: secondary surfaces, metadata, helper text, and quiet labels.
- `border` / `input` / `ring`: separators, controls, and focus states.
- `primary`: main action, selected state, and sparse high-signal emphasis.
- `accent`: supporting hover, active, or local emphasis only when the extracted system supports it.

Sparse, purposeful accents for primary actions, active states, and small status signals.
Use semantic utilities such as `bg-background`, `bg-card`, `text-foreground`, `text-muted-foreground`, `border-border`, `bg-primary`, and `ring-ring` before reaching for hard-coded values.

## 3. Typography Rules

Use the extracted type rhythm around 10px, 11px, 12px, 14px, 16px. Product-native type: expressive enough for hierarchy, restrained enough for repeated UI.

| Role | Size | Guidance |
| --- | ---: | --- |
| Page title | 16px | Establish the active task without becoming a marketing hero. |
| Body | 11px | Use for rows, descriptions, and standard UI copy. |
| Label/metadata | 10px | Keep readable, sentence case, and quieter than content. |

- Keep app chrome quieter than the main content.
- Use sentence-case UI labels with normal tracking unless the references clearly require another style.
- Reserve monospace for code-like values, diagnostics, and technical labels.

## 4. Component Stylings

Recurring component families: badge, button, sidebar, navbar. Start from shadcn/ui primitives and tune spacing, containment, and token usage around the extracted system.

- Buttons: use the standard control radius around 2px. Reserve `primary` for the main action; use outline, ghost, or secondary variants for utility actions and filters.
- Cards and panels: use panel radius around 3px and vary containment strength by role instead of boxing every region equally.
- Lists and rows: align avatars, titles, metadata, and actions to shared edges; use dividers or embedded grouping before heavier card borders.
- Navigation/header: keep the shell posture proportional, with selected states visible but quieter than the primary task surface.
- Status and badges: pair color with label or icon; status color should not become the visual theme.
- Inputs and filters: keep them attached to the relevant region, not floating as unrelated islands.

| Component | Anatomy | Interaction and State | Avoid |
| --- | --- | --- | --- |
| Buttons | 2px radius, compact padding, clear label/icon pairing. | Primary only for the main action; secondary/ghost for utilities. | Multiple equally loud actions or one-off color fills. |
| Cards/panels | 3px panel radius, role-based containment, semantic surfaces. | Use border, tone, or subtle elevation according to level. | Boxing every region with the same detached card treatment. |
| Lists/rows | Shared left edges, quiet metadata, trailing actions aligned to a stable column. | Hover and selected states should use `muted`, `accent`, or `primary` sparingly. | Replacing list-led surfaces with KPI blocks or hero slabs. |
| Navigation/header | Proportional shell chrome with selected state visible but subordinate. | Keep focus and active states crisp with `ring-ring` and semantic borders. | Oversized branded topbars, tracked uppercase labels, or theatrical badges. |
| Inputs/filters | Attached to the region they refine, with clear labels and readable placeholder text. | Preserve touch targets and focus visibility. | Floating unrelated controls or cramped icon-only filters. |
| Badges/status | Small, labeled, and paired with icon or text when color carries meaning. | Status color supports state; it does not become the global palette. | Broad tinted status panels or unlabeled color-only signals. |

## 5. Layout Principles

Reference shell cue: workspace with a sidebar main shell. Use it only when it supports the requested workflow or existing route; otherwise translate its spacing, containment, and hierarchy into the target screen type.
Reference reading order cue: status header (attached) with account counters and P/L summary -> primary task main (attached) with option legs and positions table -> navigation sidebar (attached) with quotes and status lights -> actions toolbar (embedded) with filters and group-by dropdown. Adapt the hierarchy to the user's actual content before copying region order.
Recurring region cues: primary task main (attached) with option legs and positions table, navigation sidebar (attached) with quotes and status lights, status header (attached) with account counters and P/L summary, actions toolbar (embedded) with filters and group-by dropdown. Treat these as reusable relationships, not required page sections.

Use spacing steps around 4px, 8px, 12px, 16px, 24px and keep interior component spacing smaller than section spacing. Favor operational lists, queues, tables, and utility panels over large storytelling hero sections.
Context priority: user intent, existing product IA, and route semantics override the screenshot archetype. A dashboard reference should not make a blog page become a dashboard; transfer the visual language instead.

### What Transfers

- The target screen type comes from the user request and current codebase. Transfer visual decisions into that context instead of replacing the context.
- When adapting the system to a different screen type, preserve the shell anchors, region ordering, and supporting-vs-primary relationships before inventing new module framing.
- Preserve sidebar main shell as a shell posture cue, not as a fixed screen requirement.
- Carry forward the dense positions table with symbol-led rows and option-leg subrows relationship when it fits the requested workflow.
- Carry forward the narrow watchlist rail with bid/ask ladder relationship when it fits the requested workflow.
- Carry forward the single-row totals utility bar with green/red P&L chips relationship when it fits the requested workflow.
- Carry forward the stacked section header with tabs and dropdown filters relationship when it fits the requested workflow.
- Keep semantic token usage, surface ladder, radius rhythm, and accent discipline stable across new screens.

### What Does Not Transfer

- Do not copy screenshot-specific brand names, project labels, initials, marketing copy, or literal data values into new product screens.
- Do not copy the reference product category, dashboard metrics, sidebar IA, data tables, or chart-heavy structure into a task that asks for another screen type.
- Do not force every future screen into the exact reference layout when the requested workflow calls for a different surface type.
- Do not promote one-off status colors, illustration colors, avatars, charts, or media colors into global theme rules.
- Do not treat local posture exceptions, such as a floating composer or detached panel, as a universal rule for every region.

## 6. Depth & Elevation

Calm, low-elevation surfaces; use tone, borders, and spacing before shadow.

| Level | Treatment | Use |
| --- | --- | --- |
| Base | `bg-background`, no shadow | Page canvas and persistent shell. |
| Embedded | `bg-card` or `bg-muted`, subtle separators | Main regions, lists, and quiet modules. |
| Panel | Border or tone step, restrained radius | Cards, grouped controls, and secondary modules. |
| Overlay | Stronger shadow plus focus ring | Dialogs, popovers, menus, and transient focus. |

Radius rhythm: 2px, 3px, 4px. Persistent shell regions should stay flatter than overlays. Use borders, tone shifts, and spacing before strong shadow. Reserve stronger elevation for popovers, dialogs, sheets, and temporary focus.

## 7. Do's and Don'ts

### Do

- Import and use `theme.css` as the semantic token source.
- Preserve the extracted shell hierarchy before polishing local modules.
- Use shadcn/ui primitives first, then compose with Tailwind utilities.
- Keep accent usage intentional: primary actions, active states, and small status signals.
- Match the repeated module families from the references before inventing new ones.

### Don't

- Avoid oversized branded header blocks.
- Avoid thick detached topbars or hero containers.
- Avoid ornamental metric-card walls that restate simple values.
- Avoid replacing icon-led or thumbnail-led module rows with text-heavy hero slabs.
- Avoid turning content-first product surfaces into internal ops or approval dashboards without a task reason.
- Do not turn every region into the same detached card treatment.
- Do not use gradients, tracked uppercase labels, or broad tinted panels unless the references clearly support them.
- Do not replace icon-led, thumbnail-led, or list-led modules with KPI walls unless the task asks for dashboard scanning.

## 8. Responsive Behavior

- Preserve the primary task path as rails collapse or stack.
- Collapse navigation and support regions before shrinking the main content past readability.
- Keep touch targets comfortable and avoid cramped icon-only controls without labels or tooltips.
- Maintain the same surface ladder and type hierarchy across breakpoints.

## 9. Agent Prompt Guide

### Quick Reference

- User request and existing route context decide the screen type; references decide the visual system.
- Use `theme.css` tokens before local colors.
- Layout posture: sidebar main shell.
- Density: compact.
- Surface model: Calm, low-elevation surfaces; use tone, borders, and spacing before shadow.
- Accent rule: Sparse, purposeful accents for primary actions, active states, and small status signals.

### Component Prompts

- If the requested workflow calls for a similar app surface, build toward workspace with a sidebar main shell; otherwise translate the extracted hierarchy into the requested page type.
- Create cards/panels with the extracted surface model: embedded containment, section divider only borders, and radius from the theme ladder.
- Compose collection rows around dense positions table with symbol-led rows and option-leg subrows, narrow watchlist rail with bid/ask ladder, single-row totals utility bar with green/red P&L chips, stacked section header with tabs and dropdown filters. Align row starts, metadata, and actions to a small set of shared anchors.
- Before finishing, check that the screen uses semantic tokens, preserves the shell hierarchy, keeps accent sparse, and avoids generic dashboard filler.

### Definition of Done

- The implementation imports `theme.css` and uses semantic Tailwind roles before local values.
- The implemented screen matches the user's requested screen type and existing product context before matching the reference screenshot's product category.
- The first screen preserves the extracted shell hierarchy, density, and primary/supporting region balance.
- Buttons, panels, rows, navigation, inputs, and badges follow the component recipes above.
- Responsive states keep touch targets usable and collapse secondary regions before compressing the primary task.
- The screen avoids gradients, tracked uppercase labels, slash-opacity defaults, arbitrary raw colors, and generic metric-card filler unless the task explicitly requires them.