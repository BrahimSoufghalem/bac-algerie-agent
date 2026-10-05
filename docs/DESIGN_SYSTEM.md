# Masar design system

Masar is a learning workspace for Algerian baccalaureate students and teachers.
The identity follows the learning path: understand the idea, build the solution,
and return to the source. It does not promise perfect AI answers or guaranteed grades.

## Stack
- shadcn/ui: vendored, MIT-licensed New York Button, Input, Textarea, Card, Badge,
  Dialog, Select and Tooltip components. `components.json` and `@/` aliases are configured.
- Tailwind CSS 4: Vite plugin and semantic color/radius/font utility tokens.
- Radix: actual dialog and subject-selection primitives, focus trap, keyboard
  navigation and portal overlays. Native form selects remain where required
  validation and FormData semantics are useful; this is intentional.
- Lucide: a tree-shaken, explicit icon map. The original Masar path mark is retained.
- Motion: a subtle empty-conversation entrance; `reducedMotion="user"`.
- Arabic Noto Sans is self-hosted. No remote fonts, tracking, image assets or
  additional model/OCR requests are required by the design.

## Token contract
`frontend/src/design/tokens.css` is the source of truth for light/dark colors,
spacing (4/8/12/16/24/32/48/64), radii, typography and transition timings.
Forest-green actions, warm neutral surfaces and restrained amber accents communicate
learning, calm and continuity. Errors remain visibly labelled, not just color-coded.
Legacy layout variables alias these same tokens rather than defining another theme.
`design/masar.css` composes the application routes without replacing business logic.

## Surfaces
- Editorial sign-in/register/recovery; mandatory immutable track onboarding.
- RTL conversation chrome, Radix subject picker, focused composer and starter cards.
- Responsive sidebar/64px desktop rail; explicit owner-management navigation.
- Content upload/review workflow, multi-track cards, same/different-file answer pairing.
- Model connections, teacher preparation, preferences, notes, security and accounts.
- Actual usage counters and limits, with expandable raw details. Unavailable data is
  not displayed as zero; provider estimates are not invoices.

## Accessibility and responsiveness
Keyboard focus is visible. Modal/background isolation prevents accidental tabbing
into the hidden application. Escape closes dialogs and restores a visible control,
including the menu trigger when a desktop dialog is closed at mobile width. Read-only
screens and horizontal tables/code regions are keyboard-scrollable. Light/dark/system
preferences persist; reduced-motion disables non-essential transitions and animation.

Test desktop (1440px), tablet (768px), phones (390px/360px), short viewport/keyboard,
open subject menus, rename/delete dialogs, attachments, streamed replies, math and
scientific charts. Automated axe checks complement, not replace, visual/keyboard review
and are not a certification of exhaustive WCAG compliance.

## Updating a deployment
Pull the updated GitHub `main` and rebuild the frontend-containing API image using
your existing Compose files, environment and volume overrides. Standard local setup:

```sh
git pull --ff-only
docker compose up -d --build api worker
```

If using `compose.production.yaml` or a schoolbook override, keep that same `-f`
configuration instead of switching to the standard example. No migration, data reset,
book re-extraction, account changes or volume deletion is required. Do not use `down -v`.
The agent has not accessed or updated the user's Docker host.
