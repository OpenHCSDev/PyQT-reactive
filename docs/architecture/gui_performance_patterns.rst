GUI performance patterns
========================

pyqt-reactive keeps interactive forms responsive by limiting work to the
changed projection.

- ``DebounceTimer`` coalesces bursty Qt events.
- dispatch-cycle caches reuse context and path projections within one edit.
- preview mixins update existing item text instead of rebuilding lists.
- background tasks isolate expensive non-Qt work and return results to the UI
  thread.
- tree rebuild coordination preserves selection and expansion state.

Optimizations may cache derived presentation data only. ObjectState remains the
authority for editable values, and host applications remain the authority for
domain semantics. Cache keys therefore include the state/scope token that makes
the projection valid; a timeout is not a correctness mechanism.

Measure the host workflow before adding a new cache and keep teardown paths
explicit. See :doc:`cross_window_update_optimization` and
:doc:`tree_state_sync_system`.
