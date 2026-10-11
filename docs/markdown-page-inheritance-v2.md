# Source page inheritance and the revised math benchmark

Page provenance comes from literal page headings in the Markdown source, not
from the routing-only `source_pages` YAML string. A subsection beginning midway
through a page inherits the most recent preceding source page. Content before a
later page marker belongs to that inherited page; empty separators do not.
The same rule applies when a lesson is divided into smaller reference parts.
Markers inside fenced code, YAML or HTML comments do not change page context.
Unpaginated Markdown retains its non-PDF reference kind.

No educational text or page heading is inserted or rewritten by this change.
It applies to newly imported versions; existing published snapshots are immutable
and are not silently rewritten. An existing library document requires a reviewed
new import/version to obtain the corrected references.

The owner-approved live mathematics benchmark keeps the original 24 questions,
model settings, Docker execution and token guards. Its live source is now the
user-supplied `transcription_livre_sciences_math_3AS_v2.md`, stored as a bounded
gzip/base64 fixture with a byte count and SHA256 check:

- bytes: 1,340,252
- SHA256: `b701277cc87f61260d98163c9309b94658e42223756f30375e20378be2643a39`
- 107 unique trailing-YAML sections
- the original fixture and its hash checks remain available separately

Regression coverage includes both previously markerless sections (`3.16` on PDF
109 and `4.9` on PDF 135), source-prefix ownership, code/comment isolation,
nonmonotonic markers, chunk inheritance and persisted snapshot references.
The manual Actions workflow is still the only path to paid model calls;
normal CI is offline. No production library is replaced by running this benchmark.