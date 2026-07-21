Flash callbacks
===============

Flash callbacks provide visual feedback for fields whose resolved value changed.
ObjectState determines which paths changed; pyqt-reactive maps those paths to
live widgets and invokes the configured animation surface.

Initialization and bulk restoration suppress flash notifications. User edits
publish one logical change after state has been updated. Nested managers prefix
their local field path so the root form can address the correct widget.

Widgets subscribe when created and unsubscribe during teardown. Animation
policy belongs to ``pyqt_reactive.animation``; state comparison and provenance
remain ObjectState responsibilities.

See :doc:`flash_animation_system` and
:doc:`parameter_form_lifecycle`.
