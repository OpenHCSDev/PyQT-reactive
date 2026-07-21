Enableable form ownership
=========================

An enableable nested form has one semantic ``enabled`` field even though its
checkbox is displayed in the group title. PyQt-reactive preserves the normal
field/state registration and then relocates only the field's visual chrome.

Title relocation
----------------

``EnabledTitleWidgetMoveAuthority`` owns the relocation transaction. After the
nested form has built the ordinary enabled field, it:

* resolves the owning ``GroupBoxWithHelp`` and source row;
* releases the label, checkbox, and reset button from that row;
* creates the provenance action and places it with the checkbox and reset
  action in the title;
* binds title clicks to the owning checkbox;
* registers one structural flash target for the title chrome; and
* removes the empty responsive source row and invalidates widget-discovery
  caches.

The checkbox remains registered in the nested manager's ``widgets`` mapping and
continues to use the standard widget protocol, reset wiring, placeholder
resolution, and ObjectState field identity. The title is a presentation of that
field, not a duplicate boolean or special configuration model.

Enabled styling
---------------

``EnabledFieldStylingService`` owns the visual dimming projection. Initial
styling runs after title relocation, and refreshes read the checkbox's current
resolved state. When a lazy raw value is ``None``, the service asks ObjectState
for the resolved ``enabled`` value instead of treating absence as a second
boolean state.

The service distinguishes a manager's direct value widgets from declared child
form containers. A disabled top-level form dims its direct values and all child
containers. A nested form remains dimmed when either its own resolved value is
false or an enabled ancestor is false. Dimming changes opacity only; it does
not disable input or take ownership of values.

Widget discovery and the last resolved enabled value are cached per manager.
Title relocation invalidates those caches because it changes the widget tree.
The dimming marker is stored as a widget property so repeated refreshes avoid
replacing graphics effects unnecessarily.

Structural ownership
--------------------

The title flash target combines the title label, checkbox, reset button, and
provenance button behind one masked structural target. Scrolling uses the title
label as the stable geometry target while flashing remains limited to semantic
field chrome. This is the same structural-target protocol used by other
projected fields; consumers do not need an enableable-specific navigation
branch.

Extension rules
---------------

* Determine the semantic enabled field through the nominal enableable contract,
  then let normal widget creation register it before relocation.
* Reuse ``EnabledTitleWidgetMoveAuthority`` instead of hiding a body checkbox
  and creating another title checkbox.
* Read lazy enabled state through ObjectState resolution.
* Keep dimming a visual projection. Do not disable widgets or persist opacity
  as state.
* Invalidate styling discovery after any composition that reparents registered
  value widgets.

See :doc:`../responsive_layout_widgets` for responsive title composition and
:doc:`form_scroll_containment` for structural target navigation.
