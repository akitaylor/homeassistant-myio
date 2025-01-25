"""Support for myIO sensors."""
from datetime import timedelta
import logging

from homeassistant.const import CONF_NAME, PERCENTAGE
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add a sensor entity from a config_entry."""

    _server_name = slugify(config_entry.data[CONF_NAME])
    _server_data = hass.data[DOMAIN][_server_name]
    _sensors = _server_data["sensors"]

    sensor_entities = []
    if hass.states.get(_server_name + ".available").state:
        try:
            for _sensor in _sensors:
                _actual_sensor = _sensors[_sensor]
                _sensor_id = _actual_sensor["id"]
                if (
                    0 < _sensor_id <= 100
                    or (100 < _sensor_id < 200 and _actual_sensor["hum"] != 0)
                    or (_sensor_id == 200)
                ):
                    sensor_entities.append(MyIOSensor(hass, _sensor_id, _server_name))
        except (ValueError, Exception):  # pylint: disable=broad-except
            _LOGGER.debug("%s - No sensor data", _server_name)

        async_add_entities(sensor_entities)


class MyIOSensor(Entity):
    """Implementation of a myIO-Server."""

    def __init__(self, hass, _sensor_id, _server_name):
        """Initialize the sensor."""
        self._sensor_id = _sensor_id
        self._server_name = _server_name
        self._server_data = hass.data[DOMAIN][_server_name]
        self._sensors = self._server_data["sensors"]
        self._number = 0
        self._state = 0

        # initialize the correct number in the sensors list of the sensor
        for _sensor in self._sensors:
            if self._sensors[_sensor]["id"] == _sensor_id:
                self._number = _sensor
                break
        self.entity_id = f"sensor.{_server_name}_{self._sensor_id}"
        if int(self._number) >= 200:
            self._name = "Imp.Counter"

        else:
            self._name = self._sensors[str(self._number)]["description"]
        # initialize if the sensor is thermo-, humidity-, or imp counter"""
        if int(self._number) < 100:
            self._state = self._sensors[str(self._number)]["temp"] / 100
        elif int(self._number) < 200:
            self._state = self._sensors[str(self._number)]["hum"] / 10
        else:
            self._state = self._sensors[str(self._number)]["imp"]

    @property
    def unique_id(self):
        """Return unique ID for sensor."""
        return f"{self._server_name}_{self._sensor_id}"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        if int(self._number) < 100:
            string_to_send = UnitOfTemperature.CELSIUS
        elif int(self._number) < 200:
            string_to_send = PERCENTAGE
        else:
            string_to_send = self._sensors[str(self._number)]["description"]
        return string_to_send

    def update(self):
        """Fetch new state data for the sensor."""
        self._server_data = self.hass.data[DOMAIN][self._server_name]
        self._sensors = self._server_data["sensors"]
        self._name = self._sensors[str(self._number)]["description"]
        if int(self._number) < 100:
            self._state = self._sensors[str(self._number)]["temp"] / 100
        elif int(self._number) < 200:
            self._state = self._sensors[str(self._number)]["hum"] / 10
        else:
            self._state = self._sensors[str(self._number)]["imp"]
