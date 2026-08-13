# Changelog

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
