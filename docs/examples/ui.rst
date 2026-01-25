UI Integration
==============

Examples of building reactive forms with pyqt-reactor.

Basic Form Generation
---------------------

Create a form from a dataclass:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactive.forms import ParameterFormManager

   @dataclass
   class ProcessingConfig:
       input_path: str = ""
       output_path: str = ""
       num_workers: int = 4
       enable_gpu: bool = False
       threshold: float = 0.5

   app = QApplication([])

   # Create form from dataclass
   form = ParameterFormManager(ProcessingConfig)
   form.show()

   # Collect values back as typed dataclass
   config = form.collect_values()
   print(f"Config: {config}")

   app.exec()

Form with ObjectState Integration
----------------------------------

Bind a form to ObjectState for lazy configuration and inheritance:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactive.forms import ParameterFormManager
   from objectstate import config_context, ObjectStateRegistry

   @dataclass
   class GlobalConfig:
       threshold: float = 0.5
       iterations: int = 10

   @dataclass
   class StepConfig:
       threshold: float = None  # Inherit from global
       iterations: int = None   # Inherit from global
       name: str = "step_0"

   app = QApplication([])

   # Setup ObjectState context
   global_cfg = GlobalConfig(threshold=0.7, iterations=20)

   with config_context(global_cfg):
       # Create form - fields with None will show inherited values as placeholders
       form = ParameterFormManager(StepConfig)
       form.show()

       # Placeholder text shows: "0.7 (from GlobalConfig)"
       # User can override by entering a value

       app.exec()

Reactive Field Updates
----------------------

Use FieldChangeDispatcher to react to field changes:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactive.forms import ParameterFormManager
   from pyqt_reactive.services import FieldChangeDispatcher

   @dataclass
   class ImageConfig:
       width: int = 512
       height: int = 512
       aspect_ratio: str = "1:1"

   app = QApplication([])

   form = ParameterFormManager(ImageConfig)
   dispatcher = FieldChangeDispatcher()

   # React to width changes
   def on_width_changed(event):
       print(f"Width changed to {event.value}")
       # Update aspect ratio or height

   dispatcher.subscribe("width", on_width_changed)
   form.show()

   app.exec()

Theming and Styling
-------------------

Apply themes to forms:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactive.forms import ParameterFormManager
   from pyqt_reactive.theming import ColorScheme, apply_theme

   @dataclass
   class AppConfig:
       name: str = "MyApp"
       debug: bool = False

   app = QApplication([])

   form = ParameterFormManager(AppConfig)

   # Apply dark theme
   apply_theme(form, ColorScheme.DARK)

   form.show()
   app.exec()

Flash Animations
----------------

Visual feedback when values change:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactive.forms import ParameterFormManager

   @dataclass
   class Config:
       value: float = 0.5

   app = QApplication([])

   form = ParameterFormManager(Config)

   # Flash animations automatically trigger on value changes
   # Provides visual feedback similar to React component updates

   form.show()
   app.exec()

Window Management
-----------------

Manage multiple windows with WindowManager:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
   from pyqt_reactive.services import WindowManager
   from pyqt_reactive.forms import ParameterFormManager

   @dataclass
   class Config:
       name: str = "default"

   class ConfigWindow(QMainWindow):
       def __init__(self, scope_id: str):
           super().__init__()
           self.scope_id = scope_id
           layout = QVBoxLayout()
           form = ParameterFormManager(Config)
           layout.addWidget(form)
           widget = QWidget()
           widget.setLayout(layout)
           self.setCentralWidget(widget)

   app = QApplication([])

   # Show or focus window
   window = WindowManager.show_or_focus(
       "config:main",
       lambda: ConfigWindow("config:main")
   )

   # Navigate to specific field
   WindowManager.navigate_to("config:main", field="name")

   app.exec()

Service Registration
--------------------

Register custom providers with pyqt-reactor:

.. code-block:: python

   from pyqt_reactive.protocols import (
       set_form_config,
       register_llm_service,
       register_codegen_provider,
       FormGenConfig
   )

   # Configure form generation
   config = FormGenConfig()
   config.log_dir = "/tmp/logs"
   set_form_config(config)

   # Register custom LLM service
   class MyLLMService:
       def generate_pipeline(self, description: str) -> str:
           return "# Generated pipeline"

   register_llm_service(MyLLMService())

   # Register custom code generator
   class MyCodegenProvider:
       def generate_code(self, config) -> str:
           return "# Generated code"

   register_codegen_provider(MyCodegenProvider())

Custom Widgets
--------------

Create custom widgets that work with ParameterFormManager:

.. code-block:: python

   from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider
   from PyQt6.QtCore import Qt, pyqtSignal
   from pyqt_reactive.protocols import ValueGettable, ValueSettable

   class CustomSliderWidget(QWidget, ValueGettable, ValueSettable):
       """Custom slider widget with label."""

       value_changed = pyqtSignal(int)

       def __init__(self):
           super().__init__()
           layout = QVBoxLayout()
           self.label = QLabel("0")
           self.slider = QSlider(Qt.Orientation.Horizontal)
           self.slider.setRange(0, 100)
           self.slider.valueChanged.connect(self._on_value_changed)
           layout.addWidget(self.label)
           layout.addWidget(self.slider)
           self.setLayout(layout)

       def get_value(self):
           return self.slider.value()

       def set_value(self, value):
           self.slider.setValue(int(value))

       def _on_value_changed(self, value):
           self.label.setText(str(value))
           self.value_changed.emit(value)
