UI Integration
==============

Examples of building reactive forms with pyqt-reactor.

Basic Form Generation
---------------------

Create a form from a dataclass:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactor.forms import ParameterFormManager

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
   from pyqt_reactor.forms import ParameterFormManager
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
   from pyqt_reactor.forms import ParameterFormManager
   from pyqt_reactor.services import FieldChangeDispatcher

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
   from pyqt_reactor.forms import ParameterFormManager
   from pyqt_reactor.theming import ColorScheme, apply_theme

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
   from pyqt_reactor.forms import ParameterFormManager
   from pyqt_reactor.animation import FlashMixin

   @dataclass
   class Config:
       value: float = 0.5

   app = QApplication([])

   form = ParameterFormManager(Config)

   # Flash animations automatically trigger on value changes
   # Provides visual feedback similar to React component updates

   form.show()
   app.exec()
