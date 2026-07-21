Quick start
===========

Installation
------------

.. code-block:: console

   python -m pip install pyqt-reactive

ObjectState-backed form
-----------------------

``ParameterFormManager`` is a view over an existing ``ObjectState``:

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

ObjectState owns the model, hierarchy, dirty state, and history. The manager
builds widgets, projects resolved values, and writes edits to that state.

Application integration
-----------------------

Register long-lived states with ``ObjectStateRegistry`` when multiple windows
must share them. Use pyqt-reactive services and managers for generic UI
lifecycle, but keep domain workflows and semantic declarations in the host
application.
