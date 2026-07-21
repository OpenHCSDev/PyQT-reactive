UI integration
==============

pyqt-reactive forms are views over an existing ObjectState. Construct the state
at the application lifecycle boundary, then pass that state to every form that
edits the same object.

Basic form
----------

.. code-block:: python

   from dataclasses import dataclass

   from PyQt6.QtWidgets import QApplication
   from objectstate import ObjectState, set_base_config_type
   from pyqt_reactive.forms.parameter_form_manager import (
       FormManagerConfig,
       ParameterFormManager,
   )
   from pyqt_reactive.theming import ColorScheme

   @dataclass
   class ProcessingConfig:
       input_path: str = ""
       num_workers: int = 4
       enable_gpu: bool = False

   app = QApplication([])
   set_base_config_type(ProcessingConfig)
   state = ObjectState(ProcessingConfig(), scope_id="processing")
   form = ParameterFormManager(
       state,
       config=FormManagerConfig(color_scheme=ColorScheme()),
   )
   form.show()
   app.exec()

``ParameterFormManager`` accepts ``(state, config=None)``. It does not accept a
dataclass type, and it does not own an independent value model. Read the edited
object from ``state.to_object()`` at the application boundary.

Responding to edits
-------------------

Use the manager's public signal rather than constructing the internal
``FieldChangeDispatcher``:

.. code-block:: python

   def on_parameter_changed(field_path, value):
       print(f"{field_path} changed to {value!r}")

   form.parameter_changed.connect(on_parameter_changed)

The dispatcher coordinates state writes, placeholder refresh, enabled-field
styling, and cross-window notifications inside the form lifecycle.

Tabbed forms
------------

``TabbedFormWidget`` shares one state across all child forms. Tabs declare the
top-level field paths they display:

.. code-block:: python

   from dataclasses import dataclass, field

   from objectstate import ObjectState
   from pyqt_reactive.widgets.shared.tabbed_form_widget import (
       TabConfig,
       TabbedFormConfig,
       TabbedFormWidget,
   )

   @dataclass
   class InputConfig:
       path: str = ""

   @dataclass
   class OutputConfig:
       directory: str = ""

   @dataclass
   class WorkflowConfig:
       inputs: InputConfig = field(default_factory=InputConfig)
       outputs: OutputConfig = field(default_factory=OutputConfig)

   state = ObjectState(WorkflowConfig(), scope_id="workflow")
   tabs = TabbedFormWidget(
       state=state,
       config=TabbedFormConfig(
           tabs=[
               TabConfig(name="Inputs", field_ids=["inputs"]),
               TabConfig(name="Outputs", field_ids=["outputs"]),
           ],
       ),
   )

Scoped windows
--------------

``WindowManager`` is a class-level registry. ``show_or_focus`` creates a window
only when the scope is not already open:

.. code-block:: python

   from PyQt6.QtWidgets import QMainWindow
   from pyqt_reactive.services.window_manager import WindowManager

   window = WindowManager.show_or_focus(
       "workflow",
       lambda: QMainWindow(),
   )

   WindowManager.focus_and_navigate("workflow")
   WindowManager.close_window("workflow")

Hosts that support field or item navigation should register an explicit
navigation driver with the window.

Service registration
--------------------

The generic service registry is keyed by a service type:

.. code-block:: python

   from typing import Protocol

   from pyqt_reactive.services.service_registry import ServiceRegistry

   class StatusSink(Protocol):
       def publish(self, message: str) -> None: ...

   class ConsoleStatusSink:
       def publish(self, message: str) -> None:
           print(message)

   ServiceRegistry.register(StatusSink, ConsoleStatusSink())
   sink = ServiceRegistry.get(StatusSink)
   if sink is not None:
       sink.publish("ready")
   ServiceRegistry.unregister(StatusSink)

Register host services during application composition and clear registrations
between isolated tests. Domain discovery and semantic registries belong to the
host or their nominal owning package, not this UI service registry.
