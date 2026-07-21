Form scroll containment and navigation
======================================

PyQt-reactive separates two related responsibilities: keeping form content
inside a vertical scroll viewport, and navigating to a semantic field without
destroying the user's current context.

Viewport-owned width
--------------------

``ReflowingVerticalScrollArea`` is the shared containment owner for forms that
scroll vertically but must reflow horizontally. It configures a resizable
child, disables horizontal scrolling, and changes the child's horizontal size
policy to ``Ignored``. The viewport therefore owns content width even when a
vertical scrollbar appears.

That contract reserves the scrollbar outside the viewport instead of allowing
form controls to extend beneath it. Child rows express their own minimum usable
geometry and responsive layouts reflow within the remaining viewport width.
Callers should not subtract scrollbar widths or patch margins per form.

Nested scrolling
----------------

A nested control that genuinely needs horizontal access, such as a list of
long filter values, may own its own horizontal scrollbar. Its scrollbar belongs
inside that control's layout and must not change the outer form's
viewport-owned width contract.

Semantic field navigation
-------------------------

``ScrollableFormMixin`` maps dotted field paths to ``ScrollTarget`` objects.
An exact target may be a normal field or a structural table leaf. If an exact
leaf no longer has a widget, the mixin resolves the nearest available ancestor
section as context.

Navigation captures one ``ScrollViewport`` geometry snapshot and follows these
rules:

* an exact target already fully visible does not move the viewport;
* a visible ancestor fallback also preserves the viewport and current focus;
* an off-screen fallback moves only enough to reveal its nearest edge;
* an off-screen exact field is centered when practical; and
* a section taller than the viewport is aligned or minimally revealed rather
  than repeatedly recentered.

The associated ``ScrollableFormWindowNavigationDriver`` waits for both the
field target and stable layout geometry before dispatch. This prevents a
navigation request from racing responsive reflow or scrolling to the top
because an exact structural leaf is temporarily unavailable.

Flashing is a view reaction after target resolution. Structural fields may
provide a distinct masked flash target and scroll target, so navigation can
reveal the section while highlighting only the semantic field chrome.

Extension rules
---------------

* Use ``ReflowingVerticalScrollArea`` for vertical-only form containers.
* Let the viewport own width; do not overlay the scrollbar on child controls or
  maintain per-window compensation values.
* Register semantic or structural field targets with the form manager instead
  of deriving widget paths in a window.
* Preserve the viewport when the exact target or its fallback context is
  already visible.
* Put necessary horizontal scrolling at the nested control that owns the wide
  content.

See :doc:`abstract_table_browser` for the generic column-filter layout and
:doc:`../responsive_layout_widgets` for responsive row ownership.
