Flash Callback System
======================

**How ObjectState notifies pyqt-reactive of parameter changes for flash animations.**

*Modules: objectstate.object_state, pyqt_reactive.widgets.shared.abstract_manager_widget*

Overview
--------

The flash callback system connects ObjectState's parameter change detection with pyqt-reactive's
visual feedback system. When a user edits a field, ObjectState detects the change and notifies
registered callbacks, which trigger flash animations across all windows displaying that parameter.

This is distinct from the flash animation system (:doc:`flash_animation_system`) which handles
the actual rendering. The callback system is about **when** flashes are triggered, not **how**
they're rendered.

Architecture
------------

The system consists of three layers:

.. code-block:: text

   User edits field (e.g., well_filter = "12")
           ↓
   FieldChangeDispatcher.dispatch()
           ↓
   ObjectState.update_parameter("well_filter", "12")
           ↓
   ObjectState._ensure_live_resolved()
           ↓
   ObjectState._recompute_invalid_fields()
           ↓
   ObjectState calls on_resolved_changed callbacks
           ↓
   AbstractManagerWidget.on_change(changed_paths)
           ↓
   AbstractManagerWidget.queue_flash(scope_id)
           ↓
   FlashMixin queues flash animation
           ↓
   WindowFlashOverlay renders flash

.. _callback-registration:

Callback Registration
---------------------

AbstractManagerWidget registers a callback with ObjectState to receive change notifications:

.. code-block:: python

    # In AbstractManagerWidget._subscribe_flash_for_item()
    from objectstate import ObjectStateRegistry

    state = ObjectStateRegistry.get_by_scope(scope_id)
    if not state:
        return

    def on_change(changed_paths: Set[str]):
        # Callback receives set of dotted paths that changed
        # e.g., {"well_filter_config.well_filter", "streaming_defaults.well_filter"}
        logger.debug(f"FLASH_DEBUG on_change CALLBACK FIRED: paths={changed_paths}")
        self.queue_flash(scope_id)  # Trigger flash in ALL windows
        self.queue_visual_update()   # Refresh list item text

    state.on_resolved_changed(on_change)
    self._flash_subscriptions[scope_id] = (state, on_change)

Multiple widgets can register callbacks for the same scope. All callbacks are notified when
any field in that scope changes.

.. _change-detection:

Change Detection in ObjectState
--------------------------------

ObjectState detects changes through a two-phase process:

**Phase 1: Field Invalidation**

When ``update_parameter()`` is called:

.. code-block:: python

    def update_parameter(self, param_name: str, value: Any) -> None:
        # Update the parameter value
        self.parameters[param_name] = value

        # Mark field as needing recomputation
        if param_name in self.parameters:
            self._invalid_fields.add(param_name)

        # Invalidate cache
        self._cached_object = None

**Phase 2: Recomputation**

When ``_ensure_live_resolved()`` is called (triggered by invalidation):

.. code-block:: python

    def _ensure_live_resolved(self, notify_flash: bool = True) -> Set[str]:
        if self._invalid_fields:
            # Recompute only the invalid fields (performance optimization)
            changed_paths = self._recompute_invalid_fields()
            self._invalid_fields.clear()
        else:
            # No fields need recomputation
            changed_paths = set()

        # Notify callbacks about which paths actually changed
        if notify_flash and changed_paths and self._on_resolved_changed_callbacks:
            for callback in self._on_resolved_changed_callbacks:
                callback(changed_paths)  # This triggers the flash!

        return changed_paths

**Explicit vs Inherited Fields**

``_recompute_invalid_fields()`` handles two types of fields differently:

.. code-block:: python

    def _recompute_invalid_fields(self) -> Set[str]:
        changed_paths: Set[str] = set()

        for name in self._invalid_fields:
            raw_value = self.parameters[name]

            if raw_value is not None:
                # EXPLICIT: User set this field directly
                # Compare old value vs new explicit value
                old_val = self._live_resolved.get(name)
                if old_val != raw_value:
                    changed_paths.add(name)
                    logger.debug(f"RECOMPUTE EXPLICIT CHANGED: {name}")
                self._live_resolved[name] = raw_value
            else:
                # INHERITED: Field is None, need lazy resolution
                # Walk ancestor scopes to find inherited value
                value, source_scope, source_type = resolve_with_provenance(...)
                if old_val != value:
                    changed_paths.add(name)
                    logger.debug(f"RECOMPUTE INHERITED CHANGED: {name}")
                self._live_resolved[name] = value

        return changed_paths

Common Pitfalls
---------------

.. _pitfall-indentation:

Pitfall #1: Callback Notification Indentation

**CRITICAL:** The callback notification code must run for BOTH the ``if`` and ``else`` branches
of ``_ensure_live_resolved()``. A common bug is indenting the notification inside the ``else`` block:

.. code-block:: python

    # ❌ BUG: Callback only notified when there are NO invalid fields!
    if self._invalid_fields:
        changed_paths = self._recompute_invalid_fields()
        self._invalid_fields.clear()
    else:
        changed_paths = set()

        # WRONG: This is inside the else block!
        if notify_flash and changed_paths and self._on_resolved_changed_callbacks:
            callback(changed_paths)  # Never runs when editing!
        return changed_paths

    return set()  # Unreachable when editing!

**Correct implementation:**

.. code-block:: python

    # ✅ CORRECT: Callback notified for both branches
    if self._invalid_fields:
        changed_paths = self._recompute_invalid_fields()
        self._invalid_fields.clear()
    else:
        changed_paths = set()

    # OUTSIDE the if/else - runs for both cases
    if notify_flash and changed_paths and self._on_resolved_changed_callbacks:
        callback(changed_paths)  # Runs when editing!

    return changed_paths

**Symptoms of this bug:**
- First edit (None → concrete) triggers flash ✅
- Subsequent edits (concrete → concrete) don't trigger flash ❌
- Reset (concrete → None) triggers flash ✅

**Why:** When editing, the ``if`` branch runs (has invalid fields), ``changed_paths`` is
computed correctly, but code falls through to ``return set()`` without notifying callbacks.

Pitfall #2: Forgetting ``notify_flash=False`` During Initialization

ObjectState initialization should suppress flash notifications:

.. code-block:: python

    # ❌ BUG: Flashes all fields during initialization!
    def __init__(self, ...):
        self._ensure_live_resolved(notify_flash=True)  # Wrong!

    # ✅ CORRECT: Suppress flashes during init
    def __init__(self, ...):
        self._ensure_live_resolved(notify_flash=False)  # Correct!

Pitfall #3: Not Cleaning Up Callbacks

Always unsubscribe callbacks when widgets are destroyed:

.. code-block:: python

    def cleanup(self):
        # ❌ BUG: Leaked callbacks cause crashes
        pass

    # ✅ CORRECT: Clean up subscriptions
    def cleanup(self):
        for scope_id, (state, callback) in self._flash_subscriptions.items():
            state.off_resolved_changed(callback)
        self._flash_subscriptions.clear()

Pitfall #4: Modifying ``changed_paths`` in Callback

Callbacks receive the actual ``changed_paths`` set (not a copy). Modifying it can cause issues:

.. code-block:: python

    # ❌ BUG: Modifying the set affects other callbacks
    def on_change(changed_paths):
        changed_paths.clear()  # Don't do this!

    # ✅ CORRECT: Treat it as read-only
    def on_change(changed_paths):
        my_paths = changed_paths.copy()  # Copy if you need to modify
        # or just read from it

.. _debugging:

Debugging Flash Issues
----------------------

When flashes don't trigger as expected, follow this debugging checklist:

**Step 1: Check ObjectState Logs**

Look for these log messages:

.. code-block:: text

   🔄 _ensure_live_resolved: scope=XXX, recomputing N invalid fields: [...]
   RECOMPUTE EXPLICIT CHANGED: field_name: old=X -> new=Y
   🔔 CALLBACK_LEAK_DEBUG: Notifying N callbacks...
   ⚡ FLASH_DEBUG on_change CALLBACK FIRED: scope=XXX, paths={...}

If you see ``RECOMPUTE EXPLICIT CHANGED`` but NOT ``CALLBACK LEAK_DEBUG: Notifying``,
there's a bug in the callback notification code (check indentation).

If you see ``Notifying`` but NOT ``CALLBACK FIRED``, the callback isn't calling ``queue_flash()``.

**Step 2: Check Callback Registration**

Verify the callback was registered:

.. code-block:: text

   ⚡ FLASH_DEBUG: Subscribed to XXX, total subscriptions=N

If this is missing, ``_subscribe_flash_for_item()`` wasn't called.

**Step 3: Check Scope ID Mismatch**

Flashes are scope-based. If you're editing ``/plate_a`` but expecting a flash in ``/plate_b``,
it won't work. Each scope has independent flash subscriptions.

**Step 4: Check ``notify_flash`` Parameter**

Some code paths pass ``notify_flash=False`` to suppress flashes:

.. code-block:: python

    # During save/reset operations
    self._ensure_live_resolved(notify_flash=False)

If you're not seeing expected flashes, check if they're being intentionally suppressed.

**Step 5: Check for Callback Leaks**

Look for these warnings:

.. code-block:: text

   🔴 CALLBACK_LEAK_DEBUG: Dead callback #N detected!
   🔴 CALLBACK_LEAK_DEBUG: Error unsubscribing from XXX: ...

These indicate callbacks weren't properly cleaned up, which can cause crashes or missed flashes.

Integration with Other Systems
-------------------------------

FieldChangeDispatcher
~~~~~~~~~~~~~~~~~~~~

FieldChangeDispatcher updates ObjectState, which triggers callbacks:

.. code-block:: python

    # In FieldChangeDispatcher.dispatch()
    ObjectState.update_parameter(field_name, value)

    # This triggers:
    # 1. _invalid_fields.add(field_name)
    # 2. _ensure_live_resolved()
    # 3. on_resolved_changed callbacks
    # 4. Flash animations

Cross-Window Preview System
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The flash callback system is separate from cross-window previews:

- **Flash callbacks:** Triggered by ``on_resolved_changed()``
- **Preview updates:** Triggered by ``LiveContextService.collect()``

Both systems subscribe to ObjectState changes but for different purposes.

Dirty Tracking
~~~~~~~~~~~~~~

Dirty tracking (``on_state_changed``) is separate from flash callbacks:

- **``on_state_changed``:** Fired when dirty SET changes (field becomes dirty/clean)
- **``on_resolved_changed``:** Fired when resolved VALUES change (even if already dirty)

A field can be dirty and still trigger additional flashes when its value changes again:

.. code-block:: python

   # User edits field (None → "1")
   update_parameter("well_filter", "1")
   # Field becomes dirty, flash triggers ✅

   # User edits again ("1" → "12")
   update_parameter("well_filter", "12")
   # Field still dirty, but flash triggers again ✅
   # (because resolved value changed)

Performance Considerations
--------------------------

**Optimization: Field-Level Invalidation**

ObjectState only recomputes invalid fields, not the entire snapshot:

.. code-block:: python

    # Only the edited field is recomputed
    _invalid_fields = {"well_filter_config.well_filter"}
    changed_paths = _recompute_invalid_fields()  # Fast: only 1 field

This is critical for performance with large configs (20+ fields).

**Optimization: Callback Throttling**

Consider debouncing rapid successive edits:

.. code-block:: python

    class DebouncedFlasher:
        def __init__(self, callback, delay_ms=100):
            self.callback = callback
            self.delay_ms = delay_ms
            self._timer = None

        def __call__(self, changed_paths):
            if self._timer:
                self._timer.stop()
            self._timer = QTimer.singleShot(self.delay_ms, lambda: self.callback(changed_paths))

    # Register debounced callback
    debounced = DebouncedFlasher(on_change)
    state.on_resolved_changed(debounced)

**Optimization: Early Exit**

Check if there are actually changes before notifying:

.. code-block:: python

    # ObjectState already does this
    if notify_flash and changed_paths and self._on_resolved_changed_callbacks:
        # Only notify if there are actual changes
        callback(changed_paths)

API Reference
-------------

ObjectState Callback Methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**``on_resolved_changed(callback: Callable[[Set[str]], None])``**

Register a callback to be notified when resolved values change.

:param callback: Function that takes a set of changed dotted paths
:type callback: Callable[[Set[str]], None]

**``off_resolved_changed(callback: Callable[[Set[str]], None])``**

Unregister a previously registered callback.

:param callback: The callback to unregister
:type callback: Callable[[Set[str]], None]

AbstractManagerWidget Flash Methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**``queue_flash(scope_id: str)``**

Queue a flash animation for all widgets displaying the given scope.

:param scope_id: The scope ID to flash (e.g., ``/plate_path::functionstep_0``)
:type scope_id: str

**``_subscribe_flash_for_item(scope_id: str)``**

Subscribe to ObjectState changes for the given scope and register flash elements.

:param scope_id: The scope ID to subscribe to
:type scope_id: str

**``_cleanup_flash_subscriptions()``**

Unsubscribe all flash callbacks and clean up flash elements.

See Also
--------

- :doc:`flash_animation_system` - Rendering of flash animations
- :doc:`field_change_dispatcher` - How field changes are dispatched
- :doc:`scope_visual_feedback_system` - Scope-based color coding
- :doc:`abstract_manager_widget` - Widget flash integration
- :doc:`state_management` - ObjectState integration overview
