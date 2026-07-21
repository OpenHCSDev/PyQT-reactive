Scope-window factory
====================

``ScopeWindowFactory`` creates and reuses form windows identified by an
application-provided scope token. It centralizes window identity, parentage,
navigation, color assignment, and close cleanup.

The host supplies a window specification and the editable object/ObjectState.
The factory does not construct domain configuration or inspect application
registries. Reopening a scope focuses its existing window; closing it removes
the registration and disconnects form subscriptions.

Use ``ScopeWindowNavigation`` for cross-window focus and
``WindowManager`` when an application needs a broader catalog of managed
windows. See :doc:`scope_visual_feedback_system` and
:doc:`../development/window_manager_usage`.
