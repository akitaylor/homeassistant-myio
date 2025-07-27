"""myIO light platform that implements relays and pwms, what don't have sensor driver."""
import colorsys
import logging
from datetime import timedelta

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
)
from homeassistant.const import ATTR_BRIGHTNESS, CONF_NAME
from homeassistant.util import slugify

from .comm.comms_thread import CommsThread2
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

LIGHT_EFFECT_LIST = ["none"]

SCAN_INTERVAL = timedelta(seconds=30)
COMMS_THREAD = CommsThread2()


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add a light entity from a config_entry."""
    _id = 0
    _server_name = slugify(config_entry.data[CONF_NAME])
    _server_status = hass.states.get(_server_name + ".state").state
    _server_data = hass.data[DOMAIN][_server_name]
    _relays = _server_data["relays"]
    _pwms = _server_data["PWM"]
    _groups = _server_data["group"]
    _light_entities = []
    if _server_status.startswith("Online"):
        for _relay in _relays:
            if _relays[_relay]["sensor"] == 0 and _relays[_relay]["description"] != "":
                _id = _relays[_relay]["id"]
                _light_entities.append(
                    MyIOlight(hass, config_entry, _id, _server_name))

        for _pwm in _pwms:
            try:
                _sensor = _pwms[_pwm]["sensor"]
            except (ValueError, Exception):  # pylint: disable=broad-except
                _sensor = 0
            finally:
                if _pwms[_pwm]["description"] != "" and _sensor == 0:
                    _id = _pwms[_pwm]["id"]
                    _light_entities.append(
                        MyIOlight(hass, config_entry, _id, _server_name)
                    )
        for _group in _groups:
            if _groups[_group]["description"].startswith("RGB"):
                _light_entities.append(
                    MyIOlightRGBW(hass, config_entry, _group, _server_name)
                )
        async_add_entities(_light_entities, True)


class MyIOlight(LightEntity):
    """Representation of a single myIO light."""

    def __init__(self, hass, config_entry, _id, _server_name):
        """Initialize the light."""
        self.hass = hass
        self._config_entry = config_entry
        self._server_name = _server_name
        self._server_data = hass.data[DOMAIN][_server_name]
        self._server_status = hass.states.get(_server_name + ".state").state
        self._id = _id
        self.entity_id = f"light.{_server_name}_{self._id}"
        self._state = 0
        self._name = ""
        self._effect_list = LIGHT_EFFECT_LIST

        if _id <= 64:
            self._state = self._server_data["relays"][str(
                self._id - 1)]["state"] * 255
            self._name = self._server_data["relays"][str(
                self._id - 1)]["description"]
            # Relay only supports on/off
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF
        if _id >= 100:
            self._state = self._server_data["PWM"][str(
                self._id - 101)]["state"]
            self._name = self._server_data["PWM"][str(
                self._id - 101)]["description"]
            # PWM supports brightness and color
            self._attr_supported_color_modes = {ColorMode.HS, ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.HS

        self._unique_id = _id
        self._hs_color = None
        self._brightness = self._state
        self._available = True

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self._server_name, self._unique_id)
            },
            "name": self.name,
        }

    @property
    def should_poll(self) -> bool:
        """Return true, Polling needed myIOlight for refreshing."""
        return True

    @property
    def name(self) -> str:
        """Return the name of the light if any."""
        return self._name

    @property
    def unique_id(self):
        """Return unique ID for light."""
        return f"server name = {self._server_name}, id = {self._unique_id}"

    @property
    def available(self) -> bool:
        """Return availability."""
        # This demo light is always available, but well-behaving components
        # should implement this to inform Home Assistant accordingly.
        return self._available

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return self._brightness

    @property
    def hs_color(self) -> tuple:
        """Return the hs color value."""
        return self._hs_color

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._state

    def server_status(self):
        """Return the server status."""
        return self.hass.states.get(f"{self._server_name}.state").state

    def server_data(self):
        """Return the server data dictionary database."""
        return self.hass.data[DOMAIN][self._server_name]

    async def send_post(self, post):
        """Send post to the myIO-server, and apply the response."""
        [
            self.hass.data[DOMAIN][self._server_name],
            self._server_status,
        ] = await COMMS_THREAD.send(
            server_data=self.server_data(),
            server_status=self.server_status(),
            config_entry=self._config_entry,
            _post=post,
            hass = self.hass
        )
        self.hass.states.async_set(f"{self._server_name}.state", self._server_status)
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        self._state = True

        if "hs_color" in kwargs:
            self._hs_color = kwargs["hs_color"]
        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]

        if self._id <= 64:
            await self.send_post(f"r_ON={self._id}")
        if self._id >= 101:
            await self.send_post(f"fet*{self._id-100}={self._brightness}")

        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        self._state = False
        if self._id <= 64:
            await self.send_post(f"r_OFF={self._id}")

        if self._id >= 101:
            await self.send_post(f"f_OFF={self._id-100}")

        self.async_schedule_update_ha_state()

    async def async_update(self):
        """Fetch new state data for the sensor."""

        self._server_data = self.hass.data[DOMAIN][self._server_name]
        if self._id <= 64:
            self._state = self._server_data["relays"][str(
                self._id - 1)]["state"] * 255
            self._name = self._server_data["relays"][str(
                self._id - 1)]["description"]
        if self._id >= 100:
            self._state = self._server_data["PWM"][str(
                self._id - 101)]["state"]
            self._name = self._server_data["PWM"][str(
                self._id - 101)]["description"]
        if self._state != 0:
            self._brightness = self._state

    @property
    def scan_interval(self):
        """Return the scan interval."""
        return SCAN_INTERVAL


class MyIOlightRGBW(LightEntity):
    """Representation of a single myIO light."""

    def __init__(self, hass, config_entry, _group, _server_name):
        """Initialize the light."""
        self.hass = hass
        self._config_entry = config_entry
        self._server_name = _server_name
        self._server_data = hass.data[DOMAIN][_server_name]
        self._server_status = hass.states.get(_server_name + ".state").state
        self._pwms = self._server_data["PWM"]
        self._group = self._server_data["group"][_group]
        self._id = self._group["id"]
        self.entity_id = f"light.{_server_name}_{self._id}"
        self._name = self._group["description"]
        
        # Set proper color modes
        self._attr_supported_color_modes = {ColorMode.HS}
        self._attr_color_mode = ColorMode.HS

        self._red_lights = []
        self._green_lights = []
        self._blue_lights = []
        self._white_lights = []
        self._state = False

        self._red_value = 0
        self._green_value = 0
        self._blue_value = 0
        self._white_value = 0

        """Initializing the group elements,
        sorting RGBW colors
        defining RGB values
        defining group state
        """
        for i in range(8):
            try:
                _element = self._group[f"element{i}"]
                _element_d = self._pwms[str(
                    int(_element) - 101)]["description"]
                _pwm_unit = self._pwms[str(int(_element) - 101)]
                if _element_d.startswith("R") and 100 < _element < 200:
                    self._red_lights.append(_element)
                    self._red_value = _pwm_unit["state"]
                    if self._red_value != 0:
                        self._state = True
                elif _element_d.startswith("G") and 100 < _element < 200:
                    self._green_lights.append(_element)
                    self._green_value = _pwm_unit["state"]
                    if self._green_value != 0:
                        self._state = True
                elif _element_d.startswith("B") and 100 < _element < 200:
                    self._blue_lights.append(_element)
                    self._blue_value = _pwm_unit["state"]
                    if self._blue_value != 0:
                        self._state = True
            except (ValueError, Exception):  # pylint: disable=broad-except
                continue

        # defining HSB values from RGB values"""
        self._hsb_values = colorsys.rgb_to_hsv(
            self._red_value / 255, self._green_value / 255, self._blue_value / 255
        )
        self._brightness = self._hsb_values[2]
        self._hs_color = [self._hsb_values[0], self._hsb_values[1]]
        self._unique_id = int(_group) + 501
        self._available = True

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self._server_name, self._unique_id)
            },
            "name": self.name,
        }

    @property
    def should_poll(self) -> bool:
        """No polling needed for a demo light."""
        return True

    @property
    def name(self) -> str:
        """Return the name of the light if any."""
        return self._name

    @property
    def unique_id(self):
        """Return unique ID for light."""
        return f"server name = {self._server_name}, id = {self._unique_id}"

    @property
    def available(self) -> bool:
        """Return availability."""
        return self._available

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return self._brightness

    @property
    def hs_color(self) -> tuple:
        """Return the hs color value."""
        return self._hs_color

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._state

    def server_status(self):
        """Return the server status."""
        return self.hass.states.get(f"{self._server_name}.state").state

    def server_data(self):
        """Return the server data dictionary database."""
        return self.hass.data[DOMAIN][self._server_name]

    async def send_post(self, post):
        """Send post to the myIO-server, and apply the response."""
        [
            self.hass.data[DOMAIN][self._server_name],
            self._server_status,
        ] = await COMMS_THREAD.send(
            server_data=self.server_data(),
            server_status=self.server_status(),
            config_entry=self._config_entry,
            _post=post,
        )
        self.hass.states.async_set(f"{self._server_name}.state", self._server_status)
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        self._state = True
        
        if "hs_color" in kwargs:
            self._hs_color = kwargs["hs_color"]
        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]
            
        # make RGB values from HSB color
        _rgb_values = colorsys.hsv_to_rgb(
            self._hs_color[0] / 360, self._hs_color[1] /
            100, self._brightness / 255
        )
        # making the post string to set rgb values
        _post = ""
        for pwm in self._red_lights:
            _post += f"fet*{pwm-100}={int(_rgb_values[0]*255)}&"
        for pwm in self._green_lights:
            _post += f"fet*{pwm-100}={int(_rgb_values[1]*255)}&"
        for pwm in self._blue_lights:
            _post += f"fet*{pwm-100}={int(_rgb_values[2]*255)}&"
            
        # send the post to the myIO server
        await self.send_post(_post)

        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        self._state = False
        # Make the _post string, what will turn off the myIO server group elements.
        _temp_string = ""
        for element in self._red_lights:
            _temp_string += f"f_OFF={int(element)-100}&"
        for element in self._green_lights:
            _temp_string += f"f_OFF={int(element)-100}&"
        for element in self._blue_lights:
            _temp_string += f"f_OFF={int(element)-100}&"
            
        # Send the _post to the myIO server
        await self.send_post(_temp_string)

        self.async_schedule_update_ha_state()

    async def async_update(self):
        """Fetch new state data for the sensor."""

        self._server_data = self.hass.data[DOMAIN][self._server_name]
        if self.hass.states.get(self._server_name + ".state").state.startswith(
            "Online"
        ):
            self._available = True
        else:
            self._available = False

        # Check the group elements,
        # if one of them is turned on, the state goes true and refreshing its value
        for i in range(8):
            try:
                _element = self._group[f"element{i}"]
                _element_d = self._pwms[str(
                    int(_element) - 101)]["description"]
                _pwm_unit = self._pwms[str(int(_element) - 101)]
                if _element_d.startswith("R") and 100 < _element < 200:
                    self._red_value = _pwm_unit["state"]
                    if self._red_value != 0:
                        self._state = True
                elif _element_d.startswith("G") and 100 < _element < 200:
                    self._green_value = _pwm_unit["state"]
                    if self._green_value != 0:
                        self._state = True
                elif _element_d.startswith("B") and 100 < _element < 200:
                    self._blue_value = _pwm_unit["state"]
                    if self._blue_value != 0:
                        self._state = True
            except (ValueError, Exception):  # pylint: disable=broad-except
                continue

        # defining HSB values from RGB values"""
        if self._state:
            self._hsb_values = colorsys.rgb_to_hsv(
                self._red_value / 255, self._green_value / 255, self._blue_value / 255
            )
            self._brightness = self._hsb_values[2] * 255
            self._hs_color = [self._hsb_values[0]
                              * 360, self._hsb_values[1] * 100]

    @property
    def scan_interval(self):
        """Return the scan interval."""
        return SCAN_INTERVAL