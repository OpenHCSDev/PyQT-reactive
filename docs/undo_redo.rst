Time travel and branching
=========================

pyqt-reactive reflects state restored by ObjectState's history system.  History
is owned by ObjectState; ``ParameterFormManager`` is a view over the current
model and does not define a separate undo stack.

Snapshots
---------

Use an ObjectState atomic operation when several edits should become one
history entry.  Structural registration alone does not create a snapshot.

.. code-block:: python

   from dataclasses import dataclass

   from objectstate import ObjectState, ObjectStateRegistry
   from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager

   @dataclass
   class ProcessingSettings:
       threshold: float = 0.5
       iterations: int = 10

   state = ObjectState(ProcessingSettings(), scope_id="processing")
   ObjectStateRegistry.register(state)
   form = ParameterFormManager(state)

   with ObjectStateRegistry.atomic("tune processing", scope_id="processing"):
       state.update_parameter("threshold", 0.7)
       state.update_parameter("iterations", 20)

   ObjectStateRegistry.time_travel_back()
   ObjectStateRegistry.time_travel_forward()

ObjectState also provides ``time_travel_to_snapshot``, ``create_branch``, and
``switch_branch`` for non-linear history.  Scope-aware applications should pass
the appropriate ``scope_id`` where the ObjectState API accepts it.

UI synchronization
------------------

Forms update the model through normal field-change handling and refresh when
ObjectState changes are dispatched.  The lifecycle owner decides where atomic
boundaries belong—for example, per committed editor action or around a larger
multi-field command.  Do not assume that every keystroke automatically creates
an independent snapshot.

See the ObjectState documentation for snapshot storage, atomic-success
semantics, and branch behavior.
