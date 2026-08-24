# Changelog

## 0.3.5

- Carry ObjectState's field declaration into manager-preview formatting so
  abbreviations resolve through that declaration rather than a global registry
  scan.
- Normalise lazy declaration provenance for all preview metadata, require
  explicit callable value formatters, and remove duplicated grouping state and
  diagnostic logging from the preview pipeline.
- Group previews by ObjectState container path so separate fields with the same
  config declaration remain distinct. ObjectState 1.1.4 supplies the shared
  parameter-owner authority used by this projection.

## 0.3.4

- Resolve preview labels from canonical ObjectState declarations so generated
  lazy wrapper types preserve metadata provenance instead of becoming a second
  apparent owner.

## 0.3.3

- Keep repeated status polling out of application INFO logs while retaining the
  external lifecycle observation as the sole connection-state authority.

## 0.3.2

- Derive the table-filter sidebar width from its actual controls and platform
  scrollbar geometry so column filters remain readable without host-specific
  sizing.

## 0.3.1

- Replace structural host-provider, tree-payload, function-row, callable, and
  docstring shapes with nominal ABCs, concrete presentation declarations, or
  their actual callable and introspection authorities.
- Make each inferred path-name role own its tokens and selection behavior
  instead of maintaining a parallel role-specification table.
- Remove the unused function/window registries and legacy I/O package that
  duplicated the active scope-window and host-owned storage systems.
- Validate releases against the actual Hatchling metadata and trusted-publishing
  workflow, then build and check both distribution artifacts.

## 0.3.0

- Remove the embedded LLM chat panel and global LLM service registry so host
  applications can expose agent workflows through their own supported boundary.
- Keep the generic code editor focused on declaration-backed editing, validation,
  clean-mode normalization, and revision-aware window documents.
- Replace the structural code-generation provider with the fail-loud
  `CodegenProviderABC` nominal contract. Host providers must inherit the ABC.

## 0.2.13

- Keep each ZMQ browser scan tied to one immutable declaration and observation
  authority so superseded background results cannot overwrite current state.
- Use ZMQRuntime's typed endpoint shutdown outcomes and endpoint identities
  instead of maintaining browser-local lifecycle policy.
- Own background coroutine execution and Qt-thread dispatch through reusable,
  shutdown-aware services.

## 0.2.12

- Route process termination signals through the Qt event loop so terminal
  interrupts request a clean application exit instead of surfacing inside an
  arbitrary Python callback.

## 0.2.11

- Derive callable-default declaration semantics from python-introspect instead
  of maintaining a second framework-local implementation.

## 0.2.10

- Preserve function-pattern occurrence identity across equivalent callable
  wrappers and clean documents that omit signature-default kwargs.

## 0.2.9

- Expose root-form completion and failure as public lifecycle state.
- Emit one completion signal after the form tree finishes semantic finalization.

## 0.2.5

- Preserve live callable objects when typed parameter forms apply edited code.
- Paint reset and provenance feedback on the changed nested input as well as
  its containing form context.
- Keep repeated application theming idempotent against the live
  ``QApplication`` stylesheet, avoiding redundant native Qt repolishing.

## 0.2.4

- Preserve function-pattern occurrence identity across complete-document reorders
  and edits by reconciling declaration and callable authorities.
- Require ObjectState 1.1.2 for shared nested value-comparison semantics.

## 0.2.3

- Make the log-tailer's monotonic stop request the sole shutdown authority so
  rapid log switches cannot lose a request during QThread startup.

## 0.2.2

- Use one immutable endpoint-observation snapshot as the authority for responsive
  servers and typed startup lifecycle observations.
- Keep locally proven live endpoints visible through transient control-channel
  scan misses without maintaining copied connection flags.
- Reject stale background scans whose base snapshot was superseded by a newer
  lifecycle observation.

## 0.2.1

- Harden native Qt theming across menus, previews, progress bars, and boolean
  editors.
- Correlate live process records with their owning logs and endpoint status.
- Keep shared system-monitor sampling and presentation responsive under load.

## 0.2.0

- Align the shared function table browser with typed endpoint catalog entries so
  consumers can pass the authoritative projection directly without metadata adapters.
- Replace string code-document kinds with the nominal declaration type already owned by
  each editor and make declaration typing generic through the editor, LLM, and driver
  protocols.
- Collapse the code-generation provider onto assignment rendering and declaration-owned
  source normalization; remove the obsolete parallel code-generator compatibility API.

## [0.1.30] - 2026-07-30

### Fixed

- Keep `Annotated` validation metadata available to form construction while
  presenting the compact owning type in parameter help.

## [0.1.29] - 2026-07-30

### Changed

- Apply placeholder and enabled-state chrome as form fields materialize.
- Preserve and project annotated dataclass widget types, including dedicated
  key-sequence capture and finite system-monitor color choices.
- Make reset operations discard invalid transient editor text safely.
- Support functions without an image-memory backend in generic selectors.

### Dependencies

- python-introspect >= 0.1.8

## [0.1.28] - 2026-07-30

### Changed

- Reuse ObjectState's indexed nested-field topology instead of rescanning flat
  paths for each form manager.
- Coalesce responsive-row construction into one layout transaction while
  preserving reflow when group geometry changes.
- Resolve placeholders from canonical full ObjectState paths.

### Dependencies

- objectstate >= 1.0.21

## [0.1.0] - 2025-01-10

### Added
- Initial release extracted from OpenHCS
- Core utilities layer (DebounceTimer, ReorderableListWidget, BackgroundTask, etc.)
- Theming system (ColorScheme, PaletteManager, StyleSheetGenerator)
- Widget protocols and adapters (ABC-based contracts)
- Extended widgets (NoScrollSpinBox, NoneAwareCheckBox, etc.)
- Animation system (FlashMixin, WindowFlashOverlay, GlobalFlashCoordinator)
- Service layer (SignalService, WidgetService, ValueCollectionService, etc.)
- Widget factory infrastructure
- ParameterFormManager with ObjectState integration
- Comprehensive test suite
- Sphinx documentation

### Dependencies
- PyQt6 >= 6.4.0
- objectstate >= 0.1.0
- python-introspect >= 0.1.0
