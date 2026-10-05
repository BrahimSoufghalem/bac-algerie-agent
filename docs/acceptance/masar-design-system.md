# Masar design-system acceptance

Base main: `cb0ec41db849d411f6c1f8a976e99c71117f3b30`.

## Delivered
- Forest-green / warm-neutral Masar identity, retained path mark, self-hosted Arabic font.
- Real shadcn/ui New York components, Tailwind CSS 4, Radix dialogs and subject picker,
  tree-shaken Lucide icons, semantic tokens and restrained Motion entrance.
- RTL desktop, tablet and mobile layouts; persistent light/dark/system themes.
- Sign-in/register/recovery/onboarding, chat/history/composer, content library and review,
  models, teacher preparation, preferences, private notes, accounts, security and usage.
- Owner administrative navigation is explicit. Shared-book multi-track choices remain
  distinct from immutable first-time student track selection.
- Form submit, validation, refs, uploads and same/separate solution pairing are retained.
  Usage summaries use actual server counts, not fabricated zero costs or token totals.

## Local validation
- TypeScript and production Vite build: passed.
- Python suite: **283 passed**, two existing ZIP-validation warnings.
- Browser suite on the final built frontend: **28 passed**, including three design checks.
- Exact CI Ruff F-rule lint: passed.
- Clean `npm ci`: passed; npm production audit: zero reported vulnerabilities.
- Browser regression tests cover upload/extraction/review/publication, matched solutions,
  multi-track source identity, immutable student track, subject-isolated retrieval,
  private uploads, role isolation, scientific tools/math/charts, conversation actions,
  IME/multiline draft safety, attachments and security/recovery.
- Automated axe checks on actual light/dark routes, keyboard/Escape/focus-return checks,
  reduced-motion checks, 740px drawer regression and no-page-overflow checks passed.
- Inspected individual desktop/mobile screenshots of authentication, onboarding, chat,
  subject menus, dialogs, content/review, settings, usage, notes, accounts, security,
  teacher drafts, attachments and scientific answers. Corrected checkbox sizing,
  panel/action spacing, multi-track width and preferences layout before delivery.

This is not a certification of exhaustive WCAG compliance. Screenshots use isolated
local test accounts and explicit offline provider fixtures, not production student data.
No paid model, OCR or connection test was performed for this redesign. An independent
owner fixture keeps design tests from consuming the existing sign-in rate budget;
production sign-in security was not relaxed.

## Preservation and deployment
No production backend, data, source books, Docker configuration, accounts or volumes
were changed. Protected backend hashes are recorded in the adjacent manifest.
No migration, reset or re-extraction is required. Pull main and rebuild with the same
Compose files/environment/volume overrides already used by the deployment. Never
use `down -v`. The user's Docker machine was neither accessed nor updated.

See [Design system](../DESIGN_SYSTEM.md) for component/token and deployment guidance.
