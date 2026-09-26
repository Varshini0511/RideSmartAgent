"""Provider registry — discovers and loads all ride providers."""

from __future__ import annotations

from ride_smart.models import ProviderName
from ride_smart.providers.base import RideProvider
from ride_smart.providers.namma_yatri import NammaYatriProvider
from ride_smart.providers.ola import OlaProvider
from ride_smart.providers.rapido import RapidoProvider
from ride_smart.providers.uber import UberProvider

ALL_PROVIDERS: dict[ProviderName, type[RideProvider]] = {
    ProviderName.UBER: UberProvider,
    ProviderName.OLA: OlaProvider,
    ProviderName.RAPIDO: RapidoProvider,
    ProviderName.NAMMA_YATRI: NammaYatriProvider,
}


def get_providers(
    only: list[ProviderName] | None = None,
) -> list[RideProvider]:
    """Instantiate providers. Pass ``only`` to restrict to a subset."""
    if only:
        return [ALL_PROVIDERS[name]() for name in only if name in ALL_PROVIDERS]
    return [cls() for cls in ALL_PROVIDERS.values()]
