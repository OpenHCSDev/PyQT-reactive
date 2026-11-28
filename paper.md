---
title: 'pyqt-reactive: A Reactive Application Framework for PyQt6 Desktop Software'
tags:
  - Python
  - PyQt6
  - reactive
  - GUI
  - desktop applications
  - state management
authors:
  - name: Tristan Simas
    orcid: 0000-0002-6526-3149
    affiliation: 1
affiliations:
  - name: McGill University
    index: 1
date: 13 January 2026
bibliography: paper.bib
---

# Summary

`pyqt-reactive` is a PyQt6 library for desktop applications whose windows edit shared, hierarchical configuration. A form is a view of an `ObjectState` [@objectstate]. The state holds the values, the saved baseline, inheritance and history; the form holds widgets. Windows that show the same state, or states that inherit from one another, stay consistent without synchronization code in the application.

```python
from dataclasses import dataclass
from PyQt6.QtWidgets import QApplication
from objectstate import ObjectState, set_base_config_type
from pyqt_reactive.forms.parameter_form_manager import (
    FormManagerConfig, ParameterFormManager)
from pyqt_reactive.theming import ColorScheme

@dataclass
class MyConfig:
    name: str = "default"
    count: int = 10

app = QApplication([])
set_base_config_type(MyConfig)
state = ObjectState(MyConfig(), scope_id="example")
form = ParameterFormManager(
    state, config=FormManagerConfig(color_scheme=ColorScheme()))
form.show()
app.exec()
```

The library also provides a base class for list managers, a tabbed configuration window with a transactional save, navigation to the window that shows a given field, flash feedback for changed values, and a time-travel widget over ObjectState history. The parts that do not need Qt (form structure, service contracts, list-manager workflows) live in the companion package `formbridge` [@formbridge], which `pyqt-reactive` depends on.

# Statement of Need

Desktop applications with several windows over one configuration hierarchy need the same infrastructure each time: views that follow edits made elsewhere, fields that show the value they inherit, list managers, and feedback that shows what an edit changed. PyQt6 [@pyqt6] supplies widgets and signals, not this layer.

| Capability | Qt Designer | magicgui | Streamlit | pyqt-reactive |
|------------|:-----------:|:--------:|:---------:|:-------------:|
| Views of one state follow each other across windows | no | no | no | yes |
| Inherited values shown in the form | no | no | no | yes |
| List-manager base class | no | no | no | yes |
| Desktop native | yes | yes | no | yes |
| Widgets from type annotations | no | yes | yes | yes |

**Qt Designer** handles layout, not behavior. **magicgui** [@magicgui] builds a widget from a type annotation; `pyqt-reactive` calls it for leaf widgets it has no widget of its own for, and adds the state model around them. **Streamlit** [@streamlit] is reactive but runs in the browser. The design follows React [@react] in one respect: a view is derived from state and never holds its own copy.

# Software Design

## Cross-Window Reactivity

Every edit takes one path. `FieldChangeDispatcher.dispatch` writes the value to the form's `ObjectState`, refreshes the same-named field in sibling nested forms, notifies the listeners of `ObjectStateRegistry`, and emits `parameter_changed` and `context_changed` from the root form. A per-form flag drops a dispatch that arrives while that form is already dispatching.

Other windows do not listen to the edited form. Each root form subscribes to its own state (`state.on_resolved_changed`), and ObjectState calls it with the set of paths whose resolved values changed. The form refreshes the widgets for those paths and flashes them. List managers listen on the registry and refresh their rows.

**Example**: one window edits a Pipeline and another a Step that inherits from it. Setting `num_workers=8` in the Pipeline window changes the resolved value of the Step's unset `num_workers`; the Step window shows the new value as placeholder text and flashes the field.

## CRUD Abstractions

`AbstractManagerWidget` is a template-method base class for list managers. A subclass declares its structure:

```python
from formbridge.managers.item_hooks import (
    AttributeItemIdProjection, ManagerItemHooks)
from formbridge.managers.state_binding import ManagerStateBinding
from pyqt_reactive.widgets.shared.abstract_manager_widget import (
    AbstractManagerWidget)
from pyqt_reactive.widgets.shared.manager_item_display_builder import (
    ListItemFormat)

class StepList(AbstractManagerWidget):
    TITLE = "Steps"
    BUTTON_CONFIGS = [("Add", "add", "Add a step"),
                      ("Del", "del", "Delete selected steps")]
    STATE_BINDING = ManagerStateBinding(
        items_attr="steps", selection_attr="selected_step",
        selection_signal_attr="step_selected")
    ITEM_HOOKS = ManagerItemHooks(
        id_projection=AttributeItemIdProjection("name"))
    LIST_ITEM_FORMAT = ListItemFormat(first_line=("func",))

    def _action_handlers(self):
        return {"add": self.action_add, "del": self.action_delete}
```

The subclass also implements seven abstract methods: `action_add`, `update_button_states`, `show_item_editor`, `_format_item_content`, `_get_list_item_tooltip`, `_get_scope_for_item` and `_get_item_scope_id`. The base class supplies the list widget with drag-and-drop reordering, the button panel, selection handling, the delete and edit actions, a code-editor action, row refresh when a state changes, row flashes, and refresh after time travel.

## Hierarchical Configuration

Inheritance is ObjectState's: a value resolves through the scope hierarchy (Step → Pipeline → Global) and the class hierarchy of the configuration types. `pyqt-reactive` displays it. `None` means "inherit". An unset field shows `state.get_resolved_value(path)` as placeholder text; typing a value overrides it and resetting returns the field to its default. The label of an inherited field can navigate to the state that supplied the value, read from `state.get_provenance(path)`.

## One Owner per Field

Each fact has one owner. The values are owned by the state: since 0.8.0 the configuration window keeps no copy of the global configuration. Save is `state.mark_saved()` for every tab inside one `ObjectStateRegistry.atomic_success` block. If a tab's save participant raises, the participants already applied are rolled back and every state is restored from a checkpoint taken before the save.

Which window shows a field is owned by the thing that shows it. `ParameterFormManager.owns_field_path` answers from the fields the form displays, not from every parameter of its state, so a field the form hides belongs to whichever editor shows it. `sole_owner` is the one rule for overlap: if two owners in a window claim the same target it raises `NavigationTargetClaimedTwiceError` and names them.

## Registered Extensibility

The package does not import its host application. A host supplies implementations of abstract classes: `UiHostServices` (dialogs, color scheme, asynchronous execution) is passed to every manager widget, `ConfigDocumentFormat` renders a configuration as source for the configuration window, and `EditorTab` and `EditedObject` define the tabs of a `TabbedEditorWindow`. `CodegenProviderABC` and `PreviewFormatterRegistry` are registered through `formbridge`.

## Flash Animation Architecture

Changed fields and list rows flash. One coordinator runs a single `QTimer` for all windows, at the screen refresh rate capped at 60 frames per second by default, and computes the current color of each flashing key on each tick. `WindowFlashOverlay`, one transparent widget per top-level window, paints every flash rectangle of that window in one `paintEvent` from cached geometry. Work per tick grows with the number of flashing elements, not with the number of widgets. The repository contains no timing measurements of this path.

## Universal Callable Introspection

A form is built from whatever object its state wraps. `ParameterFormManager` obtains parameter names and types from one call, `UnifiedParameterAnalyzer.analyze`, in `python-introspect` [@pythonintrospect], and has no branch per kind of object.

## Type Dispatch

Each parameter is classified into a `ParameterInfo` class from `formbridge` (`OptionalDataclassInfo`, `DirectDataclassInfo`, `InlineDataclassWidgetInfo`, `GenericInfo`). Each class has a `matches()` predicate and registers itself when it is defined; the factory returns the first class that matches. Services dispatch on the class name (`_reset_OptionalDataclassInfo`) and raise if a handler is missing. There is no hand-written dispatch table.

# Research Application

`pyqt-reactive` is the GUI layer of OpenHCS, an open-source high-content screening platform for automated microscopy. OpenHCS's plate manager and pipeline editor subclass `AbstractManagerWidget`, its step and configuration editors are `ParameterFormManager` forms, and its main window embeds the time-travel widget. Step settings inherit from pipeline defaults, which inherit from the global configuration.

## Broader Applicability

The same structure occurs wherever several windows edit one hierarchy of settings: effect parameters in a video editor, entity inspectors in a game engine, assembly parameters in CAD software.

# AI Usage Disclosure

Generative AI (Claude claude-sonnet-4-5) assisted with code generation and documentation. All content was reviewed, tested, and integrated by human developers. Core architectural decisions (CRUD abstractions, cross-window reactivity, game-engine animation, ObjectState integration) were human-designed based on production requirements from OpenHCS development.

# Acknowledgements

This work was supported in part by the Fournier lab at the Montreal Neurological Institute, McGill University.

# References
