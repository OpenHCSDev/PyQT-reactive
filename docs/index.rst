pyqt-reactor
============

**React-quality reactive form generation framework for PyQt6**

Overview
--------

``pyqt-reactor`` is a Python framework for generating reactive, data-driven forms from dataclass definitions. It provides a clean, type-safe way to create PyQt6 user interfaces with automatic widget generation, theming, and animation support.

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

   pip install pyqt-reactor

Quick Example
-------------

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

   # Get values back
   config = form.collect_values()
   app.exec()

Requirements
------------

* Python 3.11+
* PyQt6 >= 6.4.0
* objectstate >= 0.1.0

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

   architecture/parameter_form_service_architecture
   architecture/parameter_form_lifecycle
   architecture/parametric_widget_creation
   architecture/widget_protocol_system
   architecture/field_change_dispatcher
   architecture/ui_services_architecture
   architecture/service-layer-architecture

.. toctree::
   :maxdepth: 2
   :caption: Widgets & Components

   architecture/abstract_manager_widget
   architecture/abstract_table_browser
   architecture/list_item_preview_system
   architecture/scope_visual_feedback_system

.. toctree::
   :maxdepth: 2
   :caption: Animation & Performance

   architecture/flash_animation_system
   architecture/gui_performance_patterns
   architecture/cross_window_update_optimization

.. toctree::
   :maxdepth: 2
   :caption: Development

   development/ui-patterns
   development/window_manager_usage

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/modules

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
