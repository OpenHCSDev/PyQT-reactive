Undo / Redo
===========

pyqt-reactor integrates with ObjectState's git-like undo/redo system. When forms are bound
to ObjectState, all user edits are automatically recorded in the history.

Overview
--------

ObjectState provides a DAG-based history system (not just a linear stack). When you edit
form fields, changes are recorded as snapshots. You can:

- **Undo/Redo**: Navigate back and forth through changes
- **Time Travel**: Jump to any point in history
- **Branching**: Create alternative timelines for experimentation
- **Atomic Operations**: Group multiple changes into a single undo step

Integration with Forms
----------------------

When a form is bound to ObjectState:

1. **Automatic Recording**: Each field change triggers a snapshot
2. **Dirty Tracking**: Unsaved changes are tracked automatically
3. **Restore**: Undo restores the form to previous state
4. **Branching**: Create experiment branches without losing original work

Example
-------

.. code-block:: python

   from pyqt_reactor.forms import ParameterFormManager
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
       # Undo/redo available through ObjectStateRegistry
       ObjectStateRegistry.undo()
       ObjectStateRegistry.redo()

       # Create experiment branch
       ObjectStateRegistry.create_branch("experiment_v2")
       # ... make changes ...
       ObjectStateRegistry.switch_branch("main")  # Back to original
