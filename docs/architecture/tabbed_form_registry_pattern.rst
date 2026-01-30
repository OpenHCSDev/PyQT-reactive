TabbedFormWidget Registry Pattern
===================================

**Dynamic tabbed forms with registry-based config discovery and reactive state management.**

*Status: STABLE*
*Module: pyqt_reactive.widgets.shared*

Overview
--------

The TabbedFormWidget provides a **registry-based, dynamic architecture** for creating tabbed configuration interfaces that automatically discover and adapt to registered config types. This pattern eliminates hardcoded config types and enables extensibility without UI code changes.

**The Hardcoding Problem**: Traditional tabbed UI implementations hardcode config types throughout the codebase, requiring code changes in multiple files for each new config type. This creates maintenance burden and tight coupling between config implementations and UI code.

**The pyqt-reactive Solution**: A registry-driven architecture where configs self-register via metaclass, and UI components dynamically discover and adapt to available configs. Adding a new config type requires only registering the config class—zero UI code changes.

**Key Innovation**: The config registry serves as the single source of truth, with display names, tab creation, button generation, and signal handling all derived dynamically from registry keys.

Core Architectural Patterns
----------------------------

Dynamic Config Discovery Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Hardcoded dataclasses require code changes for each new config type.

**Solution**: Dynamic config container built from a config registry

.. code-block:: python

   def _create_config_container(registry):
       """Create config container with configs from registry."""
       from types import SimpleNamespace
       
       config = SimpleNamespace()
       
       # Auto-discover configs from registry
       for field_name in registry.keys():
           config_class = registry[field_name]
           instance = config_class()  # May use lazy resolution
           setattr(config, field_name, instance)
       
       return config

**Key Points**:

- Uses ``SimpleNamespace`` for dynamic attribute assignment
- Registry keys are snake_case field names (e.g., ``'napari_streaming_config'``)
- Configs may use lazy resolution through ObjectState hierarchy
- Adding new config = just register the class, zero UI code changes

**Before**:

.. code-block:: python

   @dataclass
   class AppConfig:
       napari_config: NapariConfig = field(default_factory=...)
       fiji_config: FijiConfig = field(default_factory=...)

**After**:

.. code-block:: python

   self.config = _create_config_container(ConfigRegistry)  # Dynamic discovery

TabbedFormWidget Integration Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Manual QTabWidget creation requires duplicated code for each config.

**Solution**: Reusable ``TabbedFormWidget`` abstraction with dynamic tab generation

.. code-block:: python

   # Create a tab for each config type
   tabs = []
   for field_name in registry.keys():
       display_name = _get_display_name(field_name)
       tabs.append(TabConfig(
           label=display_name,
           field_id=field_name,
           exclude_params=[other for other in registry.keys() if other != field_name]
       ))

   tabbed_config = TabbedFormConfig(
       tabs=tabs,
       color_scheme=color_scheme,
       use_scroll_area=True,
       header_widgets=header_widgets  # Buttons on same row as tabs
   )

   tabbed_form = TabbedFormWidget(state=state, config=tabbed_config)

**Key Points**:

- Each tab shows a single config (one ``field_id`` per tab)
- ``exclude_params`` prevents other configs from appearing in each tab
- ``TabbedFormWidget`` creates ParameterFormManager for each tab automatically
- All tabs share the same root ``ObjectState``
- ``header_widgets`` feature places widgets in tab bar corner using Qt's ``setCornerWidget()``

**Benefits**:

- Eliminates duplicated form creation code
- Automatic scroll area wrapping per tab
- Consistent styling via ``color_scheme``
- Single signal connection point for all parameter changes

Registry-Based Type System
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Mixing short names, config keys, and registry keys caused type mismatches.

**Solution**: Use registry keys as canonical identifiers throughout

**Registry Key Format**: ``{type_name}_config`` (snake_case)

- Example: ``'napari_streaming_config'``, ``'fiji_streaming_config'``

**Display Name Derivation**:

.. code-block:: python

   def _get_display_name(field_name: str) -> str:
       \"\"\"Convert snake_case field name to display name.\"\"\"
       # Remove common suffixes
       name = field_name.replace('_config', '').replace('_streaming_config', '')
       return name.replace('_', ' ').title()
       # 'napari_streaming_config' -> 'Napari Streaming'

**Key Points**:

- Registry keys are the canonical identifier
- Display names derived from registry keys for UI
- Single source of truth prevents type mismatches
- Type-safe lookups via registry

Reactive State Management Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: UI widgets didn't update when user changed related parameters.

**Solution**: Connect ``parameter_changed`` signal to update widget states in real-time

.. code-block:: python

   # Signal connection
   tabbed_form.parameter_changed.connect(self._on_parameter_changed)

   # Handler
   def _on_parameter_changed(self, param_name: str, value: object):
       # Strip leading dot (root PFM emits paths like \".config_type.enabled\")
       normalized_param = param_name.lstrip('.')
       
       for config_type in self.buttons.keys():
           enabled_path = f\"{config_type}.enabled\"
           if normalized_param == enabled_path:
               self._update_button_state(config_type)
               break

   def _update_button_state(self, config_type: str):
       \"\"\"Update button based on conditions AND enabled state.\"\"\"
       meets_conditions = self._check_conditions()
       is_enabled = self._is_config_enabled(config_type)
       self.buttons[config_type].setEnabled(meets_conditions and is_enabled)

**Key Points**:

- Root PFM with ``field_id=''`` emits parameter names with leading dot
- Must normalize with ``lstrip('.')`` before comparison
- Uses ``get_resolved_value()`` to read live unsaved state from ObjectState
- Widgets update immediately on parameter changes (no manual refresh needed)

ObjectState-Driven Enable State Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Widget state was separate from config data, causing inconsistency.

**Solution**: Store state fields in ObjectState, query it for widget state

.. code-block:: python

   def _is_config_enabled(self, config_type: str) -> bool:
       """Check if config is enabled by querying ObjectState."""
       enabled_path = f"{config_type}.enabled"
       # Get resolved value (respects inheritance from parent_state)
       return self.state.get_resolved_value(enabled_path) is True

**Key Points**:

- State fields are regular fields in the config dataclass
- ``get_resolved_value()`` returns live UI state (unsaved changes)
- Respects lazy resolution from parent_state
- Single source of truth for all state

**Before**: Separate widget state

.. code-block:: python

   enabled = self.enable_checkbox.isChecked()

**After**: Query ObjectState

.. code-block:: python

   is_enabled = self._is_config_enabled('config_type')

Header Widgets Pattern
~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Action buttons were in a separate row, wasting vertical space.

**Solution**: Use Qt's ``setCornerWidget()`` to place widgets in tab bar corner

.. code-block:: python

   # Create action buttons for each config type
   header_widgets = []
   for field_name in registry.keys():
       display_name = _get_display_name(field_name)
       btn = QPushButton(f"Action for {display_name}")
       btn.clicked.connect(
           lambda checked, fn=field_name: self._on_action(fn)
       )
       btn.setEnabled(False)
       self.buttons[field_name] = btn
       header_widgets.append(btn)

   # Pass to TabbedFormConfig - they'll be placed in tab bar corner
   tabbed_config = TabbedFormConfig(
       tabs=tabs,
       header_widgets=header_widgets  # Qt places these in tab bar corner
   )

**Key Points**:

- ``TabbedFormWidget`` uses ``QTabWidget.setCornerWidget()`` internally
- Widgets appear right-aligned on same row as tab labels
- Saves vertical space in UI
- Cleaner, more professional appearance

Implementation Details
----------------------

Signal Flow
~~~~~~~~~~~

The reactive UI updates follow this signal flow:

1. **User Action**: User changes a parameter in the form
2. **ObjectState Update**: ParameterFormManager updates ObjectState with new value
3. **Signal Emission**: Root PFM emits ``parameter_changed`` signal with dotted path
4. **Signal Handler**: Handler receives signal, normalizes path
5. **Widget Update**: Handler queries ObjectState and updates dependent widgets
6. **UI Refresh**: Widgets update immediately

**Key Insight**: The signal flow uses ObjectState as the single source of truth. The UI never stores state in widgets—it always queries ObjectState for current values.

ObjectState Integration
~~~~~~~~~~~~~~~~~~~~~~~

The tabbed form pattern integrates deeply with ObjectState:

**Hierarchy**:

.. code-block:: text

   ParentState (parent_state)
   └── ChildState (child_state)
       ├── config_type_a.param1
       ├── config_type_a.param2
       ├── config_type_b.param1
       └── config_type_b.param2

**Lazy Resolution**: Configs use lazy resolution to inherit values from parent_state:

.. code-block:: python

   # If child_state doesn't have a value, it resolves from parent_state
   value = self.state.get_resolved_value('config_type.param')
   # Returns: parent_state.config_type.param if not overridden

**Benefits**:

- Configs inherit global defaults from parent state
- Local overrides possible per instance
- Changes to parent_state automatically propagate to children
- Single source of truth for all configuration values

Benefits and Impact
-------------------

Code Reduction
~~~~~~~~~~~~~~

**Eliminated Code**:

- Duplicated form creation code
- Duplicated action methods
- Separate widget state management
- **Typical Reduction**: 200-400 lines per implementation

**Added Code**:

- Registry-based infrastructure (one-time cost)
- **Net Reduction**: Significant, especially with multiple config types

Type Safety
~~~~~~~~~~~

**Before**: String literals scattered throughout

.. code-block:: python

   if config_type == "type_a":
       config = TypeAConfig(**values)
   elif config_type == "type_b":
       config = TypeBConfig(**values)

**After**: Registry-based lookup with type safety

.. code-block:: python

   ConfigClass = registry.get(config_type)
   config = ConfigClass(**values)

**Benefits**:

- Eliminates bugs from typos
- IDE autocomplete works for registry keys
- Type checker can verify registry key usage
- Refactoring tools can find all usages

Extensibility
~~~~~~~~~~~~~

**Adding a New Config Type**:

**Before**: Required changes in multiple files

1. Create config class
2. Add to container dataclass
3. Create form panel method
4. Add tab to QTabWidget
5. Create action methods
6. Add widget state management
7. Update all type checks

**After**: Required changes in 1 place

1. Create config class with auto-registration

**That's it!** The UI automatically:

- Discovers the new config from registry
- Creates a tab for it
- Generates action buttons
- Connects signals
- Handles state management

Maintainability
~~~~~~~~~~~~~~~

**Single Source of Truth**: Registry keys are the canonical identifier

- No more mixing different naming conventions
- Display names derived consistently from registry keys
- Type selection uses consistent lookups

**Declarative Configuration**: UI structure defined by data, not code

- Tab structure defined by ``TabConfig`` list
- Button creation driven by registry keys
- Signal handling generic across all config types

**Testability**: Generic methods easier to test

- Single action method to test
- Parameterized tests can cover all config types
- Mock registry for isolated testing

Usage Example
-------------

Complete Example
~~~~~~~~~~~~~~~~

.. code-block:: python

   from pyqt_reactive.widgets.shared import TabbedFormWidget, TabbedFormConfig, TabConfig
   from pyqt_reactive.core import ObjectState
   from types import SimpleNamespace

   # 1. Define your config registry (using AutoRegisterMeta or manual)
   class ConfigRegistry:
       __registry__ = {
           'viewer_a_config': ViewerAConfig,
           'viewer_b_config': ViewerBConfig,
       }

   # 2. Create dynamic config container
   def create_config():
       config = SimpleNamespace()
       for field_name, config_class in ConfigRegistry.__registry__.items():
           setattr(config, field_name, config_class())
       return config

   # 3. Create ObjectState with configs
   config = create_config()
   state = ObjectState(config)

   # 4. Create tabs dynamically
   tabs = [
       TabConfig(
           label=field_name.replace('_config', '').title(),
           field_id=field_name,
           exclude_params=[k for k in ConfigRegistry.__registry__.keys() if k != field_name]
       )
       for field_name in ConfigRegistry.__registry__.keys()
   ]

   # 5. Create action buttons
   buttons = {}
   header_widgets = []
   for field_name in ConfigRegistry.__registry__.keys():
       btn = QPushButton(f"Action: {field_name}")
       btn.clicked.connect(lambda checked, fn=field_name: handle_action(fn))
       buttons[field_name] = btn
       header_widgets.append(btn)

   # 6. Create tabbed form
   tabbed_config = TabbedFormConfig(
       tabs=tabs,
       header_widgets=header_widgets,
       use_scroll_area=True
   )
   tabbed_form = TabbedFormWidget(state=state, config=tabbed_config)

   # 7. Connect reactive updates
   tabbed_form.parameter_changed.connect(
       lambda param, val: update_buttons(param, val, buttons)
   )

Summary
-------

The TabbedFormWidget registry pattern demonstrates how registry-based patterns enable extensibility without sacrificing type safety or maintainability. By using a config registry as the single source of truth, the system achieves:

- **Zero-code config addition**: New configs require only registration
- **Type safety**: Registry keys prevent typos and enable IDE support
- **Code reduction**: Eliminates duplicated form and action code
- **Reactive UI**: Widgets update immediately via ObjectState signals
- **Single source of truth**: ObjectState stores all config values
- **Testability**: Generic methods easier to test and maintain

This pattern is applicable to any PyQt application that needs dynamic, extensible tabbed configuration interfaces.

Related Patterns
----------------

**See Also**:

- :doc:`parameter_form_service_architecture` - ParameterFormManager architecture
- :doc:`widget_protocol_system` - Widget protocol patterns
- :doc:`field_change_dispatcher` - Field change handling

**Integration Points**:

- **ObjectState**: Stores all config values with lazy resolution
- **ParameterFormManager**: Creates forms for each config
- **TabbedFormWidget**: Manages tabs and header widgets
- **AutoRegisterMeta**: Metaclass for automatic registration


