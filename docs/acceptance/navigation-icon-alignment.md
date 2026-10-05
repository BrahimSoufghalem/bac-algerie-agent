# Navigation icon alignment hotfix

Base main: `a360eee6eb53bd40d25a0901e037a444f3f20548`.

## Cause and targeted fix
shadcn Button centers its children by default. Navigation rows did not override
that default, so icons moved with the width of their labels. Align navigation
content at logical flex-start (right in RTL), reserve a non-shrinking 20px icon
column, and give logout the same 12px inline inset as account navigation.
Theme-choice buttons and the desktop collapsed rail retain their centered layout.
No component handlers, content, backend, data or Docker files are modified.

## Validation
- Reproduced the alignment failure before the CSS fix.
- New geometry regression compares icon columns to within 1px in administration,
  teacher navigation and account settings, including logout. It also verifies
  20px icons, label gaps, 44px row targets and no page overflow.
- Checked light/dark at desktop 1440px, tablet 740px, phones 390px and 360px;
  the 64px collapsed desktop rail remains centered.
- TypeScript/Vite build passed; full offline browser suite: **29 passed**.
- Individual light/dark desktop/mobile previews inspected. Offline HTML captures
  exclude password values; Playwright full-page masks may cover controls behind
  the account popover, so clean offline previews are used for visual review.
- Existing production source hashes remain unchanged except the targeted stylesheet
  and browser regression test. No paid provider calls or access to user Docker.

## Tested source hashes
- `frontend/src/design/masar.css`: `c17d8181f80a7788d2d906b3707fb5e623083fc5768a878d21cc283ad1a02fb8`
- `tests/browser/design-system.spec.ts`: `bdac053afbd8aa859d0041f7a208385e7c073fb5e6df3861ccf41f0fc697bc56`
