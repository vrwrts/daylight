"""Wrap a registered service handler.

This is the only module that touches Home Assistant's private service
registry (`hass.services._services`). Adaptive Lighting uses the same
approach. If the internals change, installing raises InterceptorError so the
problem surfaces as a failed setup instead of lights silently not adapting.
"""

from collections.abc import Awaitable, Callable
import logging
from typing import Any

from homeassistant.core import (
    CALLBACK_TYPE,
    HassJobType,
    HomeAssistant,
    Service,
    ServiceCall,
    callback,
)
from homeassistant.util.read_only_dict import ReadOnlyDict

_LOGGER = logging.getLogger(__name__)

type Hook = Callable[[ServiceCall], Awaitable[dict[str, Any] | None]]


class InterceptorError(Exception):
    """Home Assistant's service registry is not shaped as expected."""


def _registered(hass: HomeAssistant, domain: str, service: str) -> Service:
    registry = getattr(hass.services, "_services", None)
    if not isinstance(registry, dict):
        raise InterceptorError("hass.services._services is missing or not a dict")
    existing = registry.get(domain, {}).get(service)
    if existing is None:
        raise InterceptorError(f"{domain}.{service} is not registered")
    if not isinstance(existing, Service):
        raise InterceptorError(f"{domain}.{service} is not a core.Service")
    job = getattr(existing, "job", None)
    if not callable(getattr(job, "target", None)) or not isinstance(
        getattr(job, "job_type", None), HassJobType
    ):
        raise InterceptorError(f"{domain}.{service} has no usable job")
    return existing


async def _run(hass: HomeAssistant, original: Service, call: ServiceCall) -> Any:
    # Mirrors ServiceRegistry._execute_service.
    target = original.job.target
    match original.job.job_type:
        case HassJobType.Coroutinefunction:
            return await target(call)
        case HassJobType.Callback:
            return target(call)
        case _:
            return await hass.async_add_executor_job(target, call)


def async_install(
    hass: HomeAssistant, domain: str, service: str, hook: Hook
) -> CALLBACK_TYPE:
    """Run `hook` before the handler of domain.service. Return a remover.

    The hook returns replacement service data, or None to leave it as is.
    """
    original = _registered(hass, domain, service)

    async def proxy(call: ServiceCall) -> Any:
        try:
            data = await hook(call)
        except Exception:
            _LOGGER.exception("Error adapting %s.%s; calling it unchanged", domain, service)
        else:
            if data is not None:
                call.data = ReadOnlyDict(data)
        return await _run(hass, original, call)

    hass.services.async_register(
        domain,
        service,
        proxy,
        original.schema,
        original.supports_response,
        job_type=HassJobType.Coroutinefunction,
        description_placeholders=original.description_placeholders,
    )

    @callback
    def remove() -> None:
        registry = hass.services._services  # noqa: SLF001
        current = registry.get(domain, {}).get(service)
        if current is None or current.job.target is not proxy:
            _LOGGER.error(
                "%s.%s was replaced by something else; leaving it in place",
                domain,
                service,
            )
            return
        registry[domain][service] = original

    return remove
