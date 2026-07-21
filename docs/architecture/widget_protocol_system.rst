Widget protocols and strategies
===============================

pyqt-reactive normalizes PyQt's heterogeneous widget APIs through nominal
capability contracts and centralized strategy authorities. Generic form code
does not use ``hasattr`` fallbacks or duplicate widget-type dispatch tables.

Capability contracts
--------------------

``pyqt_reactive.protocols.widget_protocols`` declares focused ABCs for behavior
such as:

- reading and assigning values;
- emitting change signals;
- configuring ranges and enum choices;
- rendering resolved-value previews; and
- tracking placeholder chrome and cached placeholder data.

A custom widget implements only the contracts it owns. Missing required
behavior is an error at the generic form boundary.

Creation and runtime operations
-------------------------------

``pyqt_reactive.forms.widget_strategies`` contains the authorities that:

- choose a widget for a parameter declaration;
- bridge magicgui wrappers to native widgets;
- connect and disconnect change signals;
- assign values through typed operations; and
- render placeholder or resolved-value previews.

``ParameterFormManager`` and its services call these authorities. A host should
extend the owning registry/strategy boundary instead of teaching a form manager
about a concrete application widget.

Placeholder support
-------------------

``PyQt6WidgetEnhancer.supports_placeholder`` is the capability query for generic
callers:

.. code-block:: python

   from PyQt6.QtWidgets import QLineEdit
   from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer

   widget = QLineEdit()
   if PyQt6WidgetEnhancer.supports_placeholder(widget):
       PyQt6WidgetEnhancer.apply_placeholder_text(widget, "Inherited: sample")

Support is true for a ``ResolvedValuePreviewSettable`` widget or an exact widget
type registered in the placeholder strategy map. This is intentionally stricter
than checking for a similarly named Qt method: placeholder rendering also owns
styling, interaction hints, and cache state.

``has_placeholder_state`` answers a different question. It requires the nominal
``PlaceholderStateTrackable`` capability and reports whether placeholder chrome
or cached preview data currently exists.

Resolved-value previews
-----------------------

Container and structured widgets may implement
``ResolvedValuePreviewSettable``. For those widgets, callers use
``apply_placeholder_with_value`` so the raw unresolved value and typed resolved
preview remain distinct. Calling ``apply_placeholder_text`` on such a widget is
an error.

Widget-tree projection and tab selection
----------------------------------------

``WidgetDescriptorProjector`` is the nominal family for serializable widget-tree
descriptors. ``WidgetDescriptorProjectorRegistry`` selects the most-derived
registered Qt type by walking the widget class MRO; generic traversal does not
branch on class names.

``QTabWidgetDescriptorProjector`` and ``QTabBarDescriptorProjector`` expose the
same indexed selection contract. A descriptor contains ``current_index``, the
corresponding ``current_text`` when an index exists, ``item_count``, and the
ordered ``item_texts``. An enabled selector with more than one item declares
``WidgetActionKind.TAB_SELECTOR`` and is actionable.

The stable mutation identity is the item index. Text is display evidence and
must not be used to rediscover or dispatch a tab by label. A host action layer
that accepts a tab-selection request should validate the requested index against
``item_count`` and call the widget's indexed selection API; pyqt-reactive's
projector owns discovery, not host action routing.

Standalone ``QTabBar`` projection matters for composed windows that pair a tab
bar with a separate content stack. Treating only ``QTabWidget`` as selectable
would lose the active page and action surface from those trees.

Extension checklist
-------------------

1. Put generic widget behavior in pyqt-reactive, not a host application.
2. Implement the nominal value/signal/preview contracts the widget owns.
3. Register its creation and operation strategies at the existing authority.
4. Add focused tests for value assignment, signal connection, and placeholder
   state when supported.
5. Keep domain validation and semantic field-name policy in the host.

See :doc:`parameter_form_service_architecture` and
:doc:`../state_management`.
