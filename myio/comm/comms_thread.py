"""This is a communicaton class to myIO-Server."""
import asyncio
import base64
import json
import logging
import sys
import traceback

import requests
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
)
from slugify import slugify

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

_LOGGER.debug("Loading CommsThread2 (v1.9b1)")


class Object(object):
    pass


class CommsThread2:
    """CommsThread can poll data from myIO Server, and send post to it"""

    async def tcp_echo_client(_self, message, host, port):
        """ this code opens a socket to the host, send the message
        and returns the response
        """
        _LOGGER.debug(f"TCP echo: {message}, {host}, {port}")
        fut = asyncio.open_connection(host, port)
        try:  # Wait for 3 seconds, then raise TimeoutError
            reader, writer = await asyncio.wait_for(fut, timeout=10)

            writer.write(message.encode())
            await writer.drain()

            data = await reader.read()
            # _LOGGER.debug("Received: %s", data.decode())

            writer.close()
            await writer.wait_closed()
            return data.decode()
        except:
            _LOGGER.debug("validation - TCP echo")
            _LOGGER.debug(f"Exception in TCP echo: {traceback.format_exception(*sys.exc_info())}")

    async def validate(self, host, port, app_port, name, password):
        """this function checks if the parameters are valid"""
        _toencode = f"{name}:{password}"
        _encoded = base64.b64encode(bytes(_toencode, encoding="utf8"))
        _invalid = False
        _host = host.replace("https://", "").replace("http://", "")
        message = "cannot_connect"

        _LOGGER.debug("Running validation query")
        try:
            response = await self.tcp_echo_client(
                f"GET /relay.json HTTP/1.1\r\nAuthorization: Basic {_encoded.decode()}\r\n", _host, port
            )
            message = "app_port_problem"
            response = await self.tcp_echo_client(f"{_encoded.decode()}\n?R\n", _host, app_port)

            if response == ("." or "!"):
                message = "invalid_auth"
            else:
                message = "ok"

        except:  # pylint: disable=bare-except
            _LOGGER.debug("validation - Except")
            _LOGGER.debug(f"Exception in validation call: {traceback.format_exception(*sys.exc_info())}")

        return message

    async def send(self, server_data, server_status, config_entry, _post, hass):
        """this function of CommsThread can send a post request to the myIO server,
        the response from the server will update the state,
        and merged to the previous database.
        """
        _LOGGER.debug(f"Send is called")
        # for key in config_entry.data:
        #     _LOGGER.debug(f"Send - config: {key}: {config_entry.data[key]}")
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

        def call_http(uri, data):
            try:
                _LOGGER.debug(f"Starting HTTP request: {uri}")
                res = requests.get(url=f"http://{_host}:{config_entry.data[CONF_PORT]}/{uri}",
                                   auth=(config_entry.data[CONF_USERNAME], config_entry.data[CONF_PASSWORD]), data=data,
                                   timeout=5)
                _LOGGER.debug(f"HTTP response: status={res.status_code}, length={len(res.text)}")
                return res
            except:
                try:
                    _LOGGER.debug(f"Retrying HTTP request: {uri}")
                    res = requests.get(url=f"http://{_host}:{config_entry.data[CONF_PORT]}/{uri}",
                                       auth=(config_entry.data[CONF_USERNAME], config_entry.data[CONF_PASSWORD]), data=data,
                                       timeout=5)
                    _LOGGER.debug(f"HTTP response: status={res.status_code}, length={len(res.text)}")
                    _LOGGER.debug(f"HTTP response: {res}")
                    return res
                except:
                    _LOGGER.debug(f"Exception in HTTP request: {traceback.format_exception(*sys.exc_info())}")
                    res = Object()
                    res.status_code = -1
                    return res

        _LOGGER.debug(f"Server status: {server_status}")
        if not server_status.startswith("Online"):
            try:  # try build the server_data dictionary
                _LOGGER.debug(f"Server status not online, building data dictionary")
                res = await hass.async_add_executor_job(call_http, "sens_out.json", _post)
                _LOGGER.debug(f"HTTP result: {res.status_code}")
                if res.status_code == 200:
                    response_body = res.text
                    _LOGGER.debug(f"Response length: {len(response_body)}")
                    server_data = json.loads(response_body)
                    server_status = "Online-2"
                else:
                    server_status = "Invalid"
                    _invalid = True

                if server_status == "Online-1":  # add sensors key to the database
                    server_data["sensors"] = {}
                    for sensor in _SENSORS:
                        response = await self.tcp_echo_client(
                            f"{_encoded.decode()}\n?{sensor}\n\n", _host, _port_app
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

                _LOGGER.debug(f"Server_data printing...")
                for k in server_data:
                    _LOGGER.debug(f"Server_data[{k}]= {server_data[k]}")
                _LOGGER.debug(f"Server_data end.")

                for desc in _DESCRIPTIONS:  # try to add descriptions from xml files
                    _LOGGER.debug(f"Getting server_data {desc}")
                    _LOGGER.debug(f"Getting _DESCRIPTIONS[desc] = {_DESCRIPTIONS[desc]}")
                    _desc_data = server_data[_DESCRIPTIONS[desc]]
                    for element in _desc_data:
                        if _desc_data[element].get("description", -1) == -1:
                            _desc_data[element]["description"] = ""

                    _LOGGER.debug(f"Calling description query for '{desc}'")
                    message = f"GET /{desc}_desc.xml HTTP/1.1\nAuthorization: Basic {_encoded.decode()}\n\n"
                    try:
                        _LOGGER.debug(f"Desc query: message={message}")
                        _LOGGER.debug(f"Desc query: _port_http={_port_http}")
                        response = await self.tcp_echo_client(
                            message,
                            _host,
                            _port_http
                        )

                        if len(response) > 0:
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
                            _LOGGER.debug(f"Descriptions - exception - message: {message}")
                            _LOGGER.debug(
                                f"Descriptions query: An error occurred: {traceback.format_exception(*sys.exc_info())}")

            except Exception as e:  # pylint: disable=bare-except
                _LOGGER.debug(f"Exception in send: {e}")
                _LOGGER.debug(f"An error occurred: {traceback.format_exception(*sys.exc_info())}")
                if not _invalid:
                    server_status = "Offline"

        else:  # if server was online
            try:
                if server_status == "Online-2":
                    try:  # try to get sens_out.json
                        _LOGGER.debug("Online-2 data refresh started")
                        res = await hass.async_add_executor_job(call_http, "sens_out.json", _post)
                        _LOGGER.debug(f"HTTP result: {res.status_code}")
                        if res.status_code == 200:
                            body = res.text
                            _LOGGER.debug(f"Response length: {len(body)}")

                            # Merge fresh server status to server_data
                            _temp_data = server_data
                            _temp_json = json.loads(body)
                            for key in _temp_data:
                                for number in _temp_data[key]:
                                    _temp_data[key][number].update(
                                        _temp_json[key][number]
                                    )
                            server_data = _temp_data.copy()
                        else:
                            server_status = "Invalid"
                            _invalid = True
                    except Exception as e:  # pylint: disable=bare-except
                        _LOGGER.debug(f"Exception in sens_out.json: {e}")
                        _LOGGER.debug(f"An error occurred: {traceback.format_exception(*sys.exc_info())}")
                        if not _invalid:
                            server_status = "Offline"

                else:
                    try:  # try to get output.json
                        _LOGGER.debug("Online-1 data refresh started")
                        res = await hass.async_add_executor_job(call_http, "output.json", _post)
                        _LOGGER.debug(f"HTTP result: {res.status_code}")
                        if res.status_code == 200:
                            body = res.text
                            _LOGGER.debug(f"Response length: {len(body)}")
                            _temp_data = server_data
                            _temp_json = json.loads(body)
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
                    except Exception as e:  # pylint: disable=bare-except
                        _LOGGER.debug("except Online-output.json")
                        _LOGGER.debug(f"An error occurred: {traceback.format_exception(*sys.exc_info())}")
                        server_status = "Offline"
                    try:
                        # try to get sensors datas
                        for sensor in _SENSORS:
                            response = await self.tcp_echo_client(
                                f"{_encoded.decode()}\n?{sensor}\n\n",
                                _host,
                                _port_app
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
                    except Exception as e:  # pylint: disable=bare-except
                        _LOGGER.debug("Online-sensors exception")
                        _LOGGER.debug(f"An error occurred: {traceback.format_exception(*sys.exc_info())}")
                        server_status = "Offline"

            except Exception as e:  # pylint: disable=bare-except
                _LOGGER.debug(f"Exception in sens_out.json: {e}")
                _LOGGER.debug(f"An error occurred: {traceback.format_exception(*sys.exc_info())}")
                if not _invalid:
                    server_status = "Offline"
        _LOGGER.debug(f"MYIO setup finished: {server_status}")
        return [server_data, server_status]
