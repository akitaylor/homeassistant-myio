"""This is a communicaton class to myIO-Server."""
import logging
import aiohttp
import json
import asyncio
import base64

from slugify import slugify

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
)
from .const import CONF_PORT_APP

_DESCRIPTIONS = {
    "r": "relays",
    "f": "PWM",
    "g": "group",
    "t": "sensors",
    "h": "sensors",
}
_SENSORS = {
    "T": "temp",
    "H": "hum",
}

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=5)


class CommsThread2:
    """CommsThread can poll data from myIO Server, and send post to it"""

    async def validate(self, host, port, app_port, name, password):
        """this function checks if the parameters are valid"""
        _toencode = f"{name}:{password}"
        _encoded = base64.b64encode(bytes(_toencode, encoding="utf8"))
        _invalid = False
        _host = host.replace("https://", "").replace("http://", "")
        message = "cannot_connect"

        async def tcp_echo_client(message, port):
            """ this code opens a socket to the host, send the message
            and returns the response
            """
            fut = asyncio.open_connection(_host, port)
            try:  # Wait for 3 seconds, then raise TimeoutError
                reader, writer = await asyncio.wait_for(fut, timeout=3)
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout, skipping")

            writer.write(message.encode())
            await writer.drain()

            data = await reader.read()
            #_LOGGER.debug("Received: %s", data.decode())

            writer.close()
            await writer.wait_closed()
            return data.decode()

        try:
            response = await tcp_echo_client(
                f"GET /relay.json HTTP/1.1\nAuthorization: Basic {_encoded.decode()}\n\n",
                port,
            )
            message = "app_port_problem"
            response = await tcp_echo_client(f"{_encoded.decode()}\n?R\n", app_port)
            message = "ok"
            if response == ("." or "!"):
                message = "invalid_auth"

        except:  # pylint: disable=bare-except
            _LOGGER.debug("valid - Except")

        return message

    async def send(self, server_data, server_status, config_entry, _post):
        """this function of CommsThread can send a post request to the myIO server,
        the response from the server will update the state,
        and merged to the previous database.
        """
        _server_name = slugify(config_entry.data[CONF_NAME])
        _host = (
            config_entry.data[CONF_HOST].replace("https://", "").replace("http://", "")
        )
        _port_http = config_entry.data[CONF_PORT]
        _port_app = config_entry.data[CONF_PORT_APP]
        _toencode = (
            f"{config_entry.data[CONF_USERNAME]}:{config_entry.data[CONF_PASSWORD]}"
        )
        _encoded = base64.b64encode(bytes(_toencode, encoding="utf8"))

        _invalid = False
        _host_with_http = config_entry.data[CONF_HOST]
        if not _host_with_http.startswith("http://"):
            _host_with_http = f"http://{_host_with_http}"

        authenticate = aiohttp.BasicAuth(
            config_entry.data[CONF_USERNAME], config_entry.data[CONF_PASSWORD],
        )

        async def tcp_echo_client(message, port):
            """ this code opens a socket to the host, send the message
            and returns the response
            """
            reader, writer = await asyncio.open_connection(_host, port)

            writer.write(message.encode())
            await writer.drain()

            data = await reader.read()
            # _LOGGER.debug("Received: %s", data.decode())

            writer.close()
            await writer.wait_closed()
            return data.decode()

        if not server_status.startswith("Online"):
            try:  # try build the server_data dictionary
                async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                    try:  # try to get sens_out.json
                        async with session.get(
                            f"{_host_with_http}/sens_out.json",
                            auth=authenticate,
                            data=_post,
                        ) as response:
                            if response.status == 200:
                                server_data = json.loads(await response.text())
                                server_status = "Online-2"
                            else:
                                _LOGGER.debug("Invalid sens_out.json")
                                server_status = "Invalid"
                                _invalid = True
                    except:  # pylint: disable=bare-except
                        try:  # try to get output.json
                            async with session.get(
                                f"{_host_with_http}/output.json",
                                auth=authenticate,
                                data=_post,
                            ) as response:
                                if response.status == 200:
                                    server_data = json.loads(await response.text())
                                    if server_data.get("relay") is not None:
                                        # repair database key relay->relays
                                        server_data["relays"] = server_data.pop("relay")
                                    server_status = "Online-1"
                                else:
                                    _LOGGER.debug("Invalid output.json")
                                    server_status = "Invalid"
                                    _invalid = True
                        except:  # pylint: disable=bare-except
                            if not _invalid:
                                server_status = "Offline"
                if server_status == "Online-1":  # add sensors key to the database
                    server_data["sensors"] = {}
                    for sensor in _SENSORS:
                        response = await tcp_echo_client(
                            f"{_encoded.decode()}\n?{sensor}\n", _port_app
                        )
                        _length = len(response)
                        if _length > 6:
                            response = response.replace(sensor, '{"')
                            response = response.replace("=", '":"')
                            response = response.replace(";", '","')
                            _list = list(response)
                            _length = len(_list)
                            _list[_length - 4] = "}"
                            _list[_length - 3] = " "
                            _list[_length - 2] = " "
                            _list[_length - 1] = " "
                            response = "".join(_list)
                            _temp_json = json.loads(response)
                            _mod = 0
                            _id = 0
                            if sensor == "H":
                                _mod = 101

                            for element in _temp_json:
                                server_data["sensors"][str(_id + _mod)] = {}
                                __id = 0
                                if sensor == "T":
                                    __id = int(element)
                                if sensor == "H":
                                    __id = _id + _mod
                                server_data["sensors"][str(_id + _mod)]["id"] = __id
                                server_data["sensors"][str(_id + _mod)][
                                    _SENSORS[sensor]
                                ] = int(_temp_json[element])
                                _id = _id + 1

                for desc in _DESCRIPTIONS:  # try to add descriptions from xml files
                    _desc_data = server_data[_DESCRIPTIONS[desc]]
                    for element in _desc_data:
                        if _desc_data[element].get("description", -1) == -1:
                            _desc_data[element]["description"] = ""

                    try:
                        response = await tcp_echo_client(
                            f"GET /{desc}_desc.xml HTTP/1.1\nAuthorization: Basic {_encoded.decode()}\n\n",
                            _port_http,
                        )

                        # convert xml data to _temp_json
                        for i in range(0, 100):
                            response = response.replace(f"</{str(i)}>", '",')
                        response = response.replace("<", '"')
                        response = response.replace(">", '":"')
                        _length = len(response)
                        _list = list(response)
                        _list[_length - 2] = "}"
                        response = "".join(_list)
                        response = "{" + response
                        _temp_json = json.loads(response)

                        # merge descriptions (_temp_json) to server_data dictionary
                        for element in _temp_json:
                            el_mod = 0
                            if desc == "h" or desc == "f":
                                el_mod = 100
                            elif desc == "g":
                                el_mod = 500
                            for json_id in _desc_data:
                                if int(element) + el_mod == _desc_data[json_id]["id"]:
                                    _desc_data[json_id]["description"] = _temp_json[
                                        element
                                    ]
                                    break
                        server_data[_DESCRIPTIONS[desc]] = _desc_data.copy()
                    except:  # pylint: disable=bare-except
                        if not _invalid:
                            _LOGGER.debug("descriptions - except")

            except:  # pylint: disable=bare-except
                _LOGGER.debug("Except")
                if not _invalid:
                    server_status = "Offline"

        else:  # if server was online
            try:
                async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                    if server_status == "Online-2":
                        try:  # try to get sens_out.json
                            async with session.get(
                                f"{_host_with_http}/sens_out.json",
                                auth=authenticate,
                                data=_post,
                            ) as response:
                                if response.status == 200:
                                    _temp_data = server_data
                                    _temp_json = json.loads(await response.text())
                                    # Merge fresh server status to server_data
                                    for key in _temp_data:
                                        for number in _temp_data[key]:
                                            _temp_data[key][number].update(
                                                _temp_json[key][number]
                                            )
                                    server_data = _temp_data.copy()
                                else:
                                    _LOGGER.debug("Invalid")
                                    server_status = "Invalid"
                                    _invalid = True
                        except:  # pylint: disable=bare-except
                            _LOGGER.debug("except online sens_out.json")
                            if not _invalid:
                                server_status = "Offline"

                    else:
                        try:  # try to get output.json
                            async with session.get(
                                f"{_host_with_http}/output.json",
                                auth=authenticate,
                                data=_post,
                            ) as response:
                                if response.status == 200:
                                    _temp_data = server_data
                                    _temp_json = json.loads(await response.text())
                                    if _temp_json.get("relay") != None:
                                        # repair database key relay->relays
                                        _temp_json["relays"] = _temp_json.pop("relay")
                                    # Merge fresh server status to server_data
                                    for key in _temp_data:
                                        if key != "sensors":
                                            for number in _temp_data[key]:
                                                _temp_data[key][number].update(
                                                    _temp_json[key][number]
                                                )
                                    server_data = _temp_data.copy()
                                else:
                                    _LOGGER.debug("Invalid output.json")
                                    server_status = "Invalid"
                                    _invalid = True
                        except:  # pylint: disable=bare-except
                            _LOGGER.debug("except Online-output.json")
                            server_status = "Offline"
                        try:
                            # try to get sensors datas
                            for sensor in _SENSORS:
                                response = await tcp_echo_client(
                                    f"{_encoded.decode()}\n?{sensor}\n", _port_app
                                )
                                _length = len(response)
                                if _length > 6:
                                    response = response.replace(sensor, '{"')
                                    response = response.replace("=", '":"')
                                    response = response.replace(";", '","')
                                    _list = list(response)
                                    _length = len(_list)
                                    _list = list(response)
                                    _list[_length - 4] = "}"
                                    _list[_length - 3] = " "
                                    _list[_length - 2] = " "
                                    _list[_length - 1] = " "
                                    response = "".join(_list)
                                    _temp_json = json.loads(response)
                                    _mod = 0
                                    _id = 0
                                    if sensor == "H":
                                        _mod = 101
                                    for element in _temp_json:
                                        __id = 0
                                        if sensor == "T":
                                            __id = int(element)
                                        if sensor == "H":
                                            __id = _id + _mod
                                        server_data["sensors"][str(_id + _mod)][
                                            "id"
                                        ] = __id
                                        server_data["sensors"][str(_id + _mod)][
                                            _SENSORS[sensor]
                                        ] = int(_temp_json[element])
                                        _id = _id + 1
                        except:  # pylint: disable=bare-except
                            _LOGGER.debug("Online-sensors")
                            server_status = "Offline"

            except:  # pylint: disable=bare-except
                if not _invalid:
                    server_status = "Offline"
        return [server_data, server_status]
