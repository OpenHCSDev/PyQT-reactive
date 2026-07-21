API orientation
===============

pyqt-reactive keeps package ``__init__`` modules intentionally lightweight.
Import concrete APIs from their owning modules.

Forms
-----

``pyqt_reactive.forms.parameter_form_manager``
   ``ParameterFormManager`` and ``FormManagerConfig``.

``pyqt_reactive.forms.widget_strategies``
   Nominal widget creation strategies.

``pyqt_reactive.forms.parameter_value_contracts``
   Typed form contexts, parameter mappings, and widget values.

Services and protocols
----------------------

``pyqt_reactive.services`` contains reusable state-independent coordinators for
field changes, signals, windows, navigation, process status, search, and widget
trees. ``pyqt_reactive.protocols`` contains host-adapter ABCs.

Widgets, theming, and animation
-------------------------------

Reusable widgets live under ``pyqt_reactive.widgets``. ``ColorScheme`` and
``StyleSheetGenerator`` live under ``pyqt_reactive.theming``. Flash and visual
update mechanics live under ``pyqt_reactive.animation``.

Host applications should adapt their domain declarations to these APIs rather
than adding domain names or imports to the generic package.
