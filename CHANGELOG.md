# Changelog

## 0.9.0

Requires `objectstate>=5.0.0,<6` and `formbridge>=0.2.0,<0.3` (#33).

Field paths come from ObjectState's `DottedFieldPath` (`parent`, `lineage`,
`field_name`) instead of splitting dotted strings, and each form manager's
`_object_state_path_for_field` returns a `DottedFieldPath`. Parameter
conversion takes three arguments, matching FormBridge 0.2.

## 0.8.0

Requires ObjectState 4 (`objectstate>=4.0.0,<5`) and `formbridge>=0.1.4,<0.2`.

In ObjectState 4 the state registered at the global scope holds the global
config: an edit of that state is the live global config, `mark_saved` is the
saved one, `restore_saved` and a checkpoint restore put both back. The config
window therefore keeps nothing beside the state.

Removed from `pyqt_reactive.windows.config_window`, and what to use instead:

- `GlobalConfigContextCheckpoint`, `ConfigEditSession.capture_global_context`,
  `ConfigEditSession.restore_global_context`: nothing;
  `ObjectStateTransactionCheckpoint.capture(state)` / `.restore(state)` of the
  global state restores the global config.
- `ConfigEditSession.publish_saved_global_config`: nothing; `state.mark_saved()`
  is the save.
- `ConfigEditSession.apply_code_edit_context`: nothing; applying a code edit to
  the form edits the state.
- `ConfigEditSession.restore_global_context_if_dirty`,
  `ConfigEditSession.global_context_dirty`,
  `ConfigEditSession.mark_global_field_changed`: nothing; restoring the state
  (`restore_saved`) restores the live global config. Ask `state.dirty_fields`
  whether there are unsaved edits.
- `ConfigEditSession.saving`, `begin_save_callback`, `end_save_callback`:
  nothing; they only guarded `mark_global_field_changed`.
- `ConfigEditSession.is_global_config`: `is_global_config_type(session.config_class)`.

Behaviour: a config window whose global-config state is not registered at the
global scope no longer changes the global config when it is edited or saved.

## 0.7.2

Requires `metaclass-registry>=0.4.0`, `objectstate>=3.0.1,<4`,
`formbridge>=0.1.3,<0.2` and `zmqruntime>=0.6.4,<0.7`.

Changed:

- A widget id names one widget class. Registering a different class under an
  id that is already taken raises `ValueError`; it used to log a warning and
  replace the first class. The same class statement run again (a reload)
  takes its id back.
- A form output type has one builder: `InitializationServiceCatalog` raises
  `ValueError` when a second builder declares an output type that already
  has one.

## 0.7.1

Requires ObjectState 3 (`objectstate>=3.0,<4`) and `formbridge>=0.1.2,<0.2`.
No public name is removed.

Changed:

- An unset field's placeholder is one read: `WidgetService.
  show_resolved_value_as_placeholder` shows `state.get_resolved_value(path)`.
  The value-update path used to build its own context stack
  (`build_context_stack(ancestor_objects=...)`, removed in ObjectState 3) and
  read the object's attribute, and it used the default prefix instead of the
  form's `placeholder_prefix`; the two refresh paths in `ParameterOpsService`
  each repeated the resolve-and-format step. All three call the one method.
- Provenance navigation reads `state.get_provenance(path)` once per action
  (`ProvenanceNavigationMixin._provenance_source`). When another config of the
  same object supplies the value, the source state is the widget's own state.
  ObjectState 3 reports that source as `(None, source_type)` for a state
  without a scope id; the target path used to be looked up in the global
  state for that scope.
- `AbstractManagerWidget` no longer builds a `LiveContextResolver` it never
  called.

## 0.7.0

Generic machinery moved here from three OpenHCS GUI classes. Needs
`formbridge>=0.1.1,<0.2` (`RawDisplayValue`).

Removed:

- `widgets.shared.image_table_browser` (`ImageTableBrowser`). Use
  `widgets.shared.record_table_browser.RecordTableBrowser` with declared
  `ColumnDef`s.

Added:

- `windows.tabbed_editor_window`: `TabbedEditorWindow`, `EditorTab`,
  `EditedObject`, `SaveRefused`, `TabbedEditorNavigationDriver`.
- `widgets.shared.cancel_save_window.CancelSaveWindow`: the Cancel/Save header,
  first-show default size, dirty-marker widgets, commit accent and agent save
  actions shared by `ConfigWindow` and `TabbedEditorWindow`.
- `widgets.sectioned_dataclass_editor`: `SectionedDataclassEditor` and the
  `EditorSection` family (`ReadOnlyTableSection`, `TupleSummarySection`,
  `RowTableSection`, `TupleFieldSection`); `TitleCheckbox` family.
- `forms.inline_dataclass_chrome`: `ChildFieldChrome` with
  `StandaloneChildChrome` beside `InlineDataclassChildChrome`.
- `widgets.shared.record_table_browser` (`RecordTableBrowser`, `ValueLabels`,
  `LabelledValue`), `folder_tree` (`FolderTreeWidget`, `FolderSelection`,
  `FolderRowFilter`), `grid_column_filter` (`GridColumnFilterLink`),
  `detachable_panel` (`DetachablePanel`, `PanelPlacement`) and
  `config_action_tabs` (`ConfigActionTabs`, `ConfigAction`).
- `AbstractTableBrowser`: `RowFilter`, `add_row_filter`, `apply_row_filters`,
  `reveal_key`, `reveal_path`, `item_noun`.
- `ActionTabbedWindowBody.apply_accent`.

Changed:

- One column declaration. `ReadOnlyTableSection` and `TupleSummarySection`
  take `ColumnDef` columns and row records instead of header and cell tuples.
  `ColumnDef` gains `value` (what a row shows in the column; the attribute
  named `key` when left out), and `AbstractTableBrowser.extract_row_data` is
  derived from the columns. `DataclassFieldColumn.read_only()` gives an
  editable field's read-only column.
- One `owns_field_path(field_path) -> bool`, asked of the thing that shows the
  fields. `FieldWindowNavigationDriver` requires it (no accept-everything
  default). `ParameterFormManager.owns_navigation_field_path` is
  `owns_field_path` and answers from the fields the form shows, not from every
  parameter of its ObjectState. `ObjectStateNavigationTargetAuthority` is
  removed.
- One rule for a navigation target claimed by several owners, in
  `services.window_navigation.sole_owner`: it raises
  `NavigationTargetClaimedTwiceError`. `CompositeWindowNavigationDriver` (so
  `TabbedEditorWindow`) and `ConfigWindow` both use it. `TabbedEditorWindow` no
  longer prefers the later tab, and `ConfigWindow` no longer rejects silently.
- `AbstractTableBrowser.set_items` keeps the search text.
- `ConfigWindow` is a `CancelSaveWindow`; its private `_save_button` and
  `_header_label` are `save_button` and `header_label`.

## 0.6.0

The Qt-free tier moved to [formbridge](https://github.com/OpenHCSDev/formbridge),
which pyqt-reactive now depends on (`formbridge>=0.1,<0.2`). Import each moved
module from `formbridge` with the same path; nothing is re-exported here.

Removed (now in formbridge): `forms.parameter_form_service`,
`forms.parameter_info_types`, `forms.parameter_type_utils` and the other
Qt-free form modules; `services.help_document`, `services.parameter_help_service`,
`services.function_pattern_code_document`, `services.window_code_document`,
`services.scope_token_service`, `services.pattern_data_manager`,
`services.async_operation_executor` and the other Qt-free services;
`protocols.form_config`, `codegen_provider`, `component_selection`,
`log_providers`, `preview_formatter`; `strategies`; `utils.preview_formatters`
and the log utilities; `core.path_cache`, `core.log_utils`,
`core.performance_monitor`, `core.sort_utils`; `flash_trace`,
`pattern_metadata`, `weak_events`; the Qt-free manager hooks in
`widgets.shared` (now `formbridge.managers`) and the scope colour strategy
(now `formbridge.theming`). The unused `animation.flash_trace` shim is deleted.

Changed:

- `UiThreadDispatcher` is the Qt delivery of formbridge's `MainThreadDispatcher`;
  its errors are formbridge's `MainThreadDispatch*` errors.
- `services.window_snapshot` keeps the Qt capture service. The request,
  frame condition and receipt types are formbridge's; each capture scope and
  frame-observation kind has a registered Qt implementation
  (`QtCaptureScope`, `QtFrameObservation`) instead of a callable stored in an
  enum member.

Added:

- `bridge.windows`, `bridge.object_state_documents` and `bridge.host`: the Qt
  window, widget-tree and snapshot projections and the ObjectState code-document
  providers of formbridge's running-UI bridge. An application's main window
  mixes in `UiBridgeHostWindow`.

## 0.5.0

Generic Qt machinery moved here from OpenHCS, with the application's choices
injected instead of named:

- `widgets.editable_table`: editable tables whose columns and cell editors
  derive from a row dataclass (labels from python-introspect's `FieldLabel`).
- `widgets.grid_selector`: `GridSelectorWidget` selects cells of a row-and-column
  grid; the application implements `GridAddressing`.
- `widgets.time_travel` (`TimeTravelCommands`, `TimeTravelWidget`),
  `windows.snapshot_browser_window` and `services.time_travel_navigation`
  (`TimeTravelNavigator`, navigation targets as a class family).
- `windows.config_window`: tabbed config windows over ObjectState
  (`ConfigWindow`, `ConfigEditSession`, `ConfigCodeDocumentDriver`); the
  application implements `ConfigDocumentFormat`. `services.code_editor_form_updater`.
- `widgets.shared.dock_layout` (`DockPane`, `DockFloatController`, `DockPanes`,
  `DockLayoutStore`) and `services.application_shortcuts` (`ShortcutLifecycle`).

Changed:

- `PathCacheKey` is an open class family; each context is a subclass whose
  stored key is its snake-case class name. `PathNameRole` is a class family.
  Removed: the enum members naming one application's file kinds, the unused
  keys, `get_cached_path`, `clear_cache`, `remove_cached_path` and the four
  backward-compatibility alias functions.
- `use_external_code_editor()` reads the environment variable named by
  `FormGenConfig.external_editor_env_var`; library widgets no longer read an
  application's variable.
- Scope hierarchy operations use `objectstate.ScopeKey`; containment is by
  whole segments.
- `AbstractManagerWidget` no longer requires `service_adapter.get_event_bus()`.
- `PatternDataManager.extract_func_and_kwargs` raises `TypeError` for a
  malformed entry instead of returning `(None, {})`.

Fixed:

- The manager header's status marquee reuses one timer; each long status
  message used to leave another live `QTimer` on the manager widget.

Requires objectstate 1.4 and python-introspect 0.2.6.

## 0.4.0

- Remove `pyqt_reactive.process_launch`. The background process launch policy
  is runtime machinery and now lives in zmqruntime 0.6
  (`zmqruntime.process_launch`); import it from there. Host families are
  subclasses of `BackgroundProcessPlatform` (`WindowsBackgroundProcesses`,
  `SessionBackgroundProcesses`) instead of enum members.
- Require zmqruntime 0.6 (`zmqruntime>=0.6,<0.7`).

## 0.3.30

- A flash registration waiting for its widget to reach a flash window is
  dropped when Qt destroys any widget it closes over. Before, the coordinator
  kept such registrations for the life of the process and called into their
  widgets on every local flash; a wrapper of a Qt-created widget (such as a
  scroll area's viewport) is not marked deleted by sip, so that call read
  freed memory and segfaulted.

## 0.3.29

- Accept zmqruntime 0.5 (`zmqruntime>=0.3.0,<0.6`). zmqruntime 0.5 deletes
  the flat viewer placement-mode enum, which pyqt-reactive does not use.
- Require python-introspect 0.2.5, which extracts inline dataclass field
  documentation on Python 3.13 and later.

## 0.3.28

- Render fields declared with `python_introspect.AnnotationChoices` as a combo
  box (scalar, with "Default" when optional) or a checkbox group (list) over
  the declared choices and labels. Requires python-introspect 0.2.3.
- `ComponentSelectionProviderABC` answers `is_grouped`, `grouping_label` and
  `grouping_overlaps_variable_components` for an opaque group-by value, replacing
  `get_groupby_enum`; `GroupBySelectorDialog` takes a `group_label`.

## 0.3.26

- Let the original Qt dispatcher project a queued cancellation through its own
  error-construction hook. Started callback exceptions retain their original
  outcome, including callback-raised dispatch timeouts after a side effect.

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
