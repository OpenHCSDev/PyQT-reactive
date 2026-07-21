System monitor widget
=====================

``SystemMonitor`` is a Qt presentation over the generic metrics services.
``SystemMetricsSampler`` owns CPU, memory, and optional GPU sampling;
``SystemMonitorCore`` owns bounded history and update coordination;
``PersistentSystemMonitor`` owns application-level reuse.

Sampling runs outside paint handlers and emits immutable snapshots to the UI
thread. Missing optional GPU providers produce a CPU/memory-only view rather
than importing a concrete framework in the widget.

Applications choose placement, lifetime, and polling interval. They should not
read private graph state as a resource scheduler; the monitor is an observation
surface, not an execution authority.

See :doc:`system_monitor_core` and
:doc:`persistent_system_monitor`.
