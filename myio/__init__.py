"""The myIO integration."""
import asyncio
from datetime import timedelta
import logging

from homeassistant.const import CONF_NAME
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import slugify

from .const import CLIMATE, CONF_REFRESH_TIME, COVER, DOMAIN, LIGHT, SENSOR, DEFAULT_REFRESH_TIME
from .comm.comms_thread import CommsThread2

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    SENSOR,
    LIGHT,
    COVER,
    CLIMATE,
]

COMMS_THREAD = CommsThread2()

_LOGGER.debug("MYIO module is initiating")

async def async_setup(hass, config):
    """Set up the myIO-server component."""
    _LOGGER.debug("async_setup is called")
    return True


async def async_setup_entry(hass, config_entry):
    """Set up config entry."""
    confstr = str(config_entry)
    _LOGGER.debug(f'async_setup_entry is called: {confstr}')

    _server_name = slugify(config_entry.data[CONF_NAME])

    hass.data.setdefault(DOMAIN, {})[_server_name] = {}

    hass.states.async_set(f"{_server_name}.state", "Offline")
    hass.states.async_set(f"{_server_name}.first_contact", "True")

    _refresh_timer = config_entry.options.get(CONF_REFRESH_TIME, DEFAULT_REFRESH_TIME)

    _LOGGER.debug("MYIO Config:")
    for key in config_entry.options:
        _LOGGER.debug(f"{key}: {config_entry.options(key)}")

    def server_data():
        """Return the server data dictionary database."""
        return hass.data[DOMAIN][_server_name]

    async def setup_config_entries():
        """Set up myIO platforms with config entry."""
        _temp_server_first_contact = hass.states.get(
            f"{_server_name}.first_contact"
        ).state
        if _temp_server_first_contact == "True":
            for component in PLATFORMS:
                hass.async_create_task(
                    hass.config_entries.async_forward_entry_setup(
                        config_entry, component
                    )
                )

    async def async_update_data():
        """Fetch data from API endpoint."""

        was_offline = False
        _timeout = 4
        _comms_thread_timeout = False
        _temp_server_state = hass.states.get(f"{_server_name}.state").state

        if _temp_server_state == "Offline":
            hass.states.async_set(f"{_server_name}.available", False)
            was_offline = True
            _timeout = 20

        # Pull fresh data from server.
        try:
            [
                hass.data[DOMAIN][_server_name],
                _temp_server_state,
            ] = await asyncio.wait_for(
                COMMS_THREAD.send(
                    server_data=server_data(),
                    server_status=_temp_server_state,
                    config_entry=config_entry,
                    _post=None
                ),
                timeout=_timeout,
            )
        except asyncio.TimeoutError:
            _comms_thread_timeout = True
            _LOGGER.debug(f"{_server_name} - Comms_Thread timeout")

        hass.states.async_set(f"{_server_name}.state", _temp_server_state)

        if _temp_server_state.startswith("Online") and was_offline:
            hass.states.async_set(f"{_server_name}.available", True)
            await setup_config_entries()
            hass.states.async_set(f"{_server_name}.first_contact", "False")
        elif not was_offline and _temp_server_state == "Offline":
            _LOGGER.debug(f"{_server_name} - Platform Not Ready")
            hass.states.async_set(f"{_server_name}.available", False)
            hass.states.async_set(f"{_server_name}.state", "Offline")
            # raise PlatformNotReady

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        # Name of the data. For logging purposes.pip
        name=f"{_server_name} status",
        update_method=async_update_data,
        # Polling interval.
        update_interval=timedelta(seconds=_refresh_timer),
    )

    def listener():
        """Listen to coordinator."""

    await coordinator.async_refresh()

    coordinator.async_add_listener(listener)

    return True


async def async_unload_entry(
    hass, config_entry
):  # async_add_devices because platforms
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *(
                hass.config_entries.async_forward_entry_unload(config_entry, component)
                for component in PLATFORMS
            )
        )
    )
    return unload_ok
