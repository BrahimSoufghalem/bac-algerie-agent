# Masar UI components

Button, Input, Textarea, Card, Badge, Dialog, Select and Tooltip are vendored from
shadcn/ui's MIT-licensed `new-york` registry (https://ui.shadcn.com/r/styles/new-york/).
They are real application components, not an iframe, a screenshot or a mockup.
Upstream license: `LICENSE.shadcn`.

Masar adaptations: semantic design tokens, Arabic close label, logical RTL insets,
44px interaction targets, accessible focus/scroll handling and form-compatible
native select wrapper. Dialog/Select/Tooltip use Radix primitives. Existing form
handlers, refs, FormData, required fields and button submit semantics are retained.

Add further components with the root `components.json`. Tokens live in
`frontend/src/design/tokens.css`; product composition in `design/masar.css`.
