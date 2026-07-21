Window manager usage
====================

``pyqt_reactive.services.window_manager.WindowManager`` tracks application
windows by explicit identities and specifications.

.. code-block:: python

   from pyqt_reactive.services.window_manager import WindowManager

   manager = WindowManager()

The host registers its own creation/focus/close callbacks through the manager's
current specification API. Keep the domain object and ObjectState outside the
generic registry; the window callback receives or resolves them from the host
composition root.

Use ``ScopeWindowFactory`` for form windows whose identity is an ObjectState
scope. Always unregister destroyed windows and use Qt-owned parentage so manager
references do not keep closed widgets alive.

See :doc:`../architecture/scope_window_factory`.
