pyqt-reactive
==============

**React-quality reactive form generation framework for PyQt6**

Overview
--------

``pyqt-reactive`` is a Python framework for generating reactive, data-driven forms from dataclass definitions. It provides a clean, type-safe way to create PyQt6 user interfaces with automatic widget generation, theming, and animation support.

Key Features
------------

* **Dataclass-Driven Forms**: Automatically generate UI forms from Python dataclasses
* **Widget Protocol System**: Type-safe widget adapters with consistent interfaces
* **Reactive Updates**: Field change dispatcher for cross-widget updates
* **Theming System**:

  * ColorScheme-based styling
  * StyleSheetGenerator for consistent appearance
  * PaletteManager for dynamic theme switching

* **Animation System**:

  * Flash animations for value changes
  * OpenGL-accelerated overlays
  * Performance-optimized rendering

* **Service Architecture**: Clean separation of UI and business logic
* **Cross-Window Coordination**: Window manager for multi-window applications

Installation
------------

.. code-block:: bash

   pip install pyqt-reactive

Quick Example
-------------

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
       output_path: str = ""
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

Requirements
------------

* Python 3.11+
* PyQt6 >= 6.4.0
* ObjectState >= 1.0.18
* python-introspect >= 0.1.5

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   quickstart
   state_management
   undo_redo
   examples/index

.. toctree::
   :maxdepth: 2
   :caption: Architecture

   architecture/index

.. toctree::
   :maxdepth: 2
   :caption: Development

   development/index

.. toctree::
   :maxdepth: 1
   :caption: Additional components

   responsive_layout_widgets
   tear_off_tabs

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/modules

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
