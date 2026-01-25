Time Travel and Branching
=========================

pyqt-reactive integrates with ObjectState's git-like time-travel system. When forms are bound
to ObjectState, all user edits are automatically recorded in a DAG-based history.

Overview
--------

ObjectState provides a DAG-based history system (not just a linear undo/redo stack). When you edit
form fields, changes are recorded as snapshots. You can:

- **Time Travel**: Navigate back and forth through history (like git checkout)
- **Jump to Snapshots**: Jump to any point in history by ID
- **Branching**: Create alternative timelines for experimentation
- **Atomic Operations**: Group multiple changes into a single snapshot

Integration with Forms
----------------------

When a form is bound to ObjectState:

1. **Automatic Recording**: Each field change triggers a snapshot
2. **Dirty Tracking**: Unsaved changes are tracked automatically
3. **Time Travel**: Navigate to any previous state without losing work
4. **Branching**: Create experiment branches to explore alternatives

Example
-------

.. code-block:: python

   from pyqt_reactive.forms import ParameterFormManager
   from objectstate import ObjectStateRegistry, config_context

   @dataclass
   class ProcessingConfig:
       threshold: float = 0.5
       iterations: int = 10

   # Create form with ObjectState context
   with config_context(global_config):
       form = ParameterFormManager(ProcessingConfig)
       form.show()

       # User edits are automatically recorded
       # Time travel available through ObjectStateRegistry
       ObjectStateRegistry.time_travel_back()   # Go one step back
       ObjectStateRegistry.time_travel_forward()  # Go one step forward

       # Create experiment branch
       ObjectStateRegistry.create_branch("experiment_v2")
       # ... make changes ...
       ObjectStateRegistry.switch_branch("main")  # Back to original
