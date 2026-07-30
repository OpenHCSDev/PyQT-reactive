# Changelog

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
