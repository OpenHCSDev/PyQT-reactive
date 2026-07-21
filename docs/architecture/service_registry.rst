Service registry
================

``pyqt_reactive.services.service_registry.ServiceRegistry`` is a type-keyed
application assembly tool.  Register an instance with ``register(type,
instance)`` and resolve that exact type with ``get(type)``.  ``get`` returns
``None`` when a type is absent; callers that require a service should validate
that result at their boundary.

.. code-block:: python

   from pyqt_reactive.services.service_registry import ServiceRegistry

   ServiceRegistry.register(SearchProvider, search_provider)
   provider = ServiceRegistry.get(SearchProvider)
   if provider is None:
       raise RuntimeError("SearchProvider is not registered")

   ServiceRegistry.unregister(SearchProvider)

``AutoRegisterServiceMixin`` registers a widget under its concrete type by
default.  Set ``SERVICE_TYPE`` to an interface type to select another exact key,
or to ``None`` to disable registration.  ``ServiceRegistry.clear()`` is useful
for isolating tests.

This registry is not a discovery mechanism for domain behavior.  Nominal plugin
families should use their owning metaclass registry, while ObjectState and form
semantics should be queried from their owning objects rather than mirrored as
service entries.
