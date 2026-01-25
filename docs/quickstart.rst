Quick Start Guide
==================

This guide will help you get started with pyqt-reactive in minutes.

Installation
------------

Install pyqt-reactive using pip:

.. code-block:: bash

   pip install pyqt-reactive

Basic Form from Dataclass
--------------------------

The simplest way to create a UI is from a dataclass:

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

   app = QApplication([])
   form = ParameterFormManager(ProcessingConfig)
   form.show()
   app.exec()

That's it! The form is automatically generated with:

- Text fields for strings
- Spinboxes for integers
- Checkboxes for booleans
- Appropriate validation and constraints

Collecting Values
-----------------

Get the user's input back as a typed dataclass:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication, QPushButton
   from pyqt_reactive.forms import ParameterFormManager

   @dataclass
   class Config:
       name: str = "default"
       count: int = 10

   app = QApplication([])
   form = ParameterFormManager(Config)

   # Add a button to collect values
   button = QPushButton("Get Config")
   button.clicked.connect(lambda: print(form.collect_values()))

   form.show()
   app.exec()

With ObjectState Integration
-----------------------------

For hierarchical configuration with lazy resolution:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactive.forms import ParameterFormManager
   from objectstate import config_context

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
   global_cfg = GlobalConfig(threshold=0.7, iterations=20)

   with config_context(global_cfg):
       form = ParameterFormManager(StepConfig)
       form.show()
       # Placeholder text shows inherited values
       app.exec()

Reactive Field Updates
----------------------

React to field changes with FieldChangeDispatcher:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactive.forms import ParameterFormManager
   from pyqt_reactive.services import FieldChangeDispatcher

   @dataclass
   class ImageConfig:
       width: int = 512
       height: int = 512

   app = QApplication([])
   form = ParameterFormManager(ImageConfig)
   dispatcher = FieldChangeDispatcher()

   def on_width_changed(event):
       print(f"Width changed to {event.value}")
       # Update height to maintain aspect ratio

   dispatcher.subscribe("width", on_width_changed)
   form.show()
   app.exec()

Theming
-------

Apply themes to your forms:

.. code-block:: python

   from dataclasses import dataclass
   from PyQt6.QtWidgets import QApplication
   from pyqt_reactive.forms import ParameterFormManager
   from pyqt_reactive.theming import ColorScheme, apply_theme

   @dataclass
   class Config:
       name: str = "MyApp"

   app = QApplication([])
   form = ParameterFormManager(Config)

   # Apply dark theme
   apply_theme(form, ColorScheme.DARK)

   form.show()
   app.exec()

Next Steps
----------

* Learn about :doc:`state_management` for advanced state handling
* Check out :doc:`examples/index` for more use cases
* Explore :doc:`architecture/index` for deep dives into components
* See :doc:`development/window_manager_usage` for multi-window applications
