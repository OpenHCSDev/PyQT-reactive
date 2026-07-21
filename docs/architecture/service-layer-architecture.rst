Service layer architecture
==========================

pyqt-reactive uses focused services to keep form coordination out of individual
widget classes.  These services support the Qt implementation; the package does
not currently promise a second UI-framework implementation.

Form composition
----------------

``ParameterFormManager`` receives an ``ObjectState`` and an optional
``FormManagerConfig``.  ObjectState remains the model and source of truth.  The
manager composes generic helpers for distinct jobs, including:

* ``ParameterFormService`` and form-initialization services for parameter
  analysis and form structure;
* ``ParameterOpsService`` for reset and placeholder-refresh operations;
* ``ValueCollectionService`` for collecting nested values;
* ``WidgetService`` and widget strategies for Qt widget access and updates;
* the Qt-free ``parameter_help_service`` functions for display-ready help
  content; and
* ``FieldChangeDispatcher`` and ``SignalService`` for UI synchronization.

Consumers normally create the form manager, not each internal service:

.. code-block:: python

   from objectstate import ObjectState
   from pyqt_reactive.forms.parameter_form_manager import (
       FormManagerConfig,
       ParameterFormManager,
   )

   state = ObjectState(settings, scope_id="settings")
   form = ParameterFormManager(
       state,
       FormManagerConfig(read_only=False),
   )

Service boundaries
------------------

Services take their dependencies explicitly or resolve package-owned
collaborators through a documented boundary.  ``ParameterServiceABC`` provides
nominal handler discovery for parameter-info variants; subclasses add handlers
through that family rather than copying a dispatch table.

``ServiceRegistry`` is a separate, type-keyed assembly tool for reusable UI
components.  It is not the source of truth for ObjectState fields, nominal
plugin families, or domain behavior.

Declaration-to-help projection
------------------------------

``pyqt_reactive.services.parameter_help_service`` is a Qt-free projection
boundary shared by forms, help windows, and agent-facing consumers. It accepts a
callable, authored dataclass, or registered ObjectState lazy dataclass and
returns typed records such as ``DocstringInfo`` and ``ParameterHelpContent``.

For a lazy dataclass, ``source_dataclass_type()`` requires the ObjectState
lazy-to-base registry and reads the authored class rather than presenting the
generated dataclass signature. Field descriptions come through
``UnifiedParameterAnalyzer``. For callables, ``docstring_info_for_target()``
combines parsed docstring parameters with declaration-owned introspection help
only when the docstring did not already provide that parameter.

``resolved_parameter_description()`` has one precedence rule: documentation on
the target, then explicit widget metadata, then the package's no-description
text. ``parameter_help_content()`` turns that declaration text into a compact
summary/body record, separates type/default and setting metadata, and removes a
duplicate default sentence. It does not open a window or import host knowledge-
base services.

Qt help controls and host-managed help windows consume these records. They may
choose window reuse and navigation policy, but they must not reparse annotations,
generated lazy types, or parameter docstrings in a parallel help pipeline.

Ownership
---------

* ObjectState owns values, defaults, dirty state, and history.
* pyqt-reactive owns Qt presentation, generic form coordination, and widget
  capability strategies.
* The host owns domain-specific editors, policies, services, and metadata.

When a host needs new semantics, expose them on the owning declaration or a
host-supplied protocol.  Do not add concrete application names, fallback chains,
or mirrored feature lists to the generic service layer.

See :doc:`parameter_form_service_architecture` and
:doc:`service_registry`.
