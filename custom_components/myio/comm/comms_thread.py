"""This is a communicaton class to myIO-Server."""
import asyncio
import base64
import copy
import json
import logging
import threading
import time

import requests
from requests.adapters import HTTPAdapter
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

_HTTP_CONNECT_TIMEOUT = 1
_HTTP_READ_TIMEOUT = 3.5
_HTTP_TIMEOUT = (_HTTP_CONNECT_TIMEOUT, _HTTP_READ_TIMEOUT)
_TCP_CONNECT_TIMEOUT = 10
_TCP_READ_TIMEOUT = 5


class Object(object):
    pass


class CommsThread2:
    """CommsThread can poll data from myIO Server, and send post to it"""

    def __init__(self):
        """Initialize reusable HTTP resources."""
        self._http_session = requests.Session()
        self._http_session.mount(
            "http://",
            HTTPAdapter(pool_connections=2, pool_maxsize=2, max_retries=0),
        )
        self._http_lock = threading.Lock()
        self._http_error_servers = set()
        self._http_failed_servers = set()
        self._monitoring_by_server = {}
        self._status_by_server = {}

    def _server_key(self, config_entry):
        """Build a stable log key for this configured server."""
        server_name = slugify(config_entry.data[CONF_NAME])
        host = config_entry.data[CONF_HOST].replace("https://", "").replace("http://", "")
        return f"{server_name}@{host}:{config_entry.data[CONF_PORT]}"

    def get_monitoring_attributes(self, config_entry):
        """Return attributes published on the server state helper."""
        server_key = self._server_key(config_entry)
        return dict(self._monitoring_by_server.get(
            server_key,
            {
                "query_latency": None,
                "controller_status": "NOT OK",
            },
        ))

    def _update_monitoring(self, server_key, status_code, latency):
        """Store the latest HTTP monitoring values."""
        self._monitoring_by_server[server_key] = {
            "query_latency": round(latency, 3),
            "controller_status": "OK" if status_code == 200 else "NOT OK",
        }

    def mark_query_timeout(self, config_entry, latency):
        """Mark the controller as unavailable after an integration timeout."""
        self._update_monitoring(self._server_key(config_entry), -1, latency)

    def _log_status_change(self, server_key, server_status):
        """Log availability only when it changes."""
        previous_status = self._status_by_server.get(server_key)
        if previous_status == server_status:
            return

        self._status_by_server[server_key] = server_status
        if server_status.startswith("Online"):
            _LOGGER.info("myIO server %s is %s", server_key, server_status)
        else:
            _LOGGER.warning("myIO server %s is %s", server_key, server_status)

    def _log_http_retry(self, server_key, uri, err):
        """Log the first failed HTTP attempt without flooding the log."""
        if server_key in self._http_error_servers:
            _LOGGER.debug("myIO HTTP retry for %s/%s: %s", server_key, uri, err)
            return

        self._http_error_servers.add(server_key)
        _LOGGER.warning(
            "myIO HTTP request failed for %s/%s, retrying: %s",
            server_key,
            uri,
            err,
        )

    def _log_http_recovered(self, server_key):
        """Log once when HTTP communication recovers."""
        if server_key not in self._http_error_servers:
            return

        self._http_error_servers.remove(server_key)
        self._http_failed_servers.discard(server_key)
        _LOGGER.info("myIO HTTP communication recovered for %s", server_key)

    def _log_http_failed(self, server_key, uri, err):
        """Log the final HTTP failure once per outage."""
        if server_key in self._http_failed_servers:
            _LOGGER.debug(
                "myIO HTTP request still failing for %s/%s: %s",
                server_key,
                uri,
                err,
            )
            return

        self._http_failed_servers.add(server_key)
        _LOGGER.warning(
            "myIO HTTP request failed for %s/%s after retry: %s",
            server_key,
            uri,
            err,
        )

    def _merge_server_data(self, server_data, fresh_data, skip_keys=None):
        """Safely merge a partial server response into the previous state."""
        skip_keys = skip_keys or set()
        merged_data = copy.deepcopy(server_data)

        for key, values in fresh_data.items():
            if key in skip_keys:
                continue
            if key == "relay":
                key = "relays"
            if (
                key not in merged_data
                or not isinstance(merged_data[key], dict)
                or not isinstance(values, dict)
            ):
                merged_data[key] = copy.deepcopy(values)
                continue
            for number, new_values in values.items():
                if number not in merged_data[key]:
                    merged_data[key][number] = copy.deepcopy(new_values)
                elif (
                    isinstance(merged_data[key][number], dict)
                    and isinstance(new_values, dict)
                ):
                    merged_data[key][number].update(new_values)
                else:
                    merged_data[key][number] = copy.deepcopy(new_values)

        return merged_data

    def _failed_response(self, err):
        """Return a small response-like object for failed HTTP calls."""
        res = Object()
        res.status_code = -1
        res.text = ""
        res.error = str(err)
        return res

    async def tcp_echo_client(_self, message, host, port):
        """ this code opens a socket to the host, send the message
        and returns the response
        """
        _LOGGER.debug(
            "myIO TCP request to %s:%s, payload length=%s",
            host,
            port,
            len(message),
        )
        fut = asyncio.open_connection(host, port)
        writer = None
        try:
            reader, writer = await asyncio.wait_for(fut, timeout=_TCP_CONNECT_TIMEOUT)

            writer.write(message.encode())
            await writer.drain()

            data = await asyncio.wait_for(reader.read(), timeout=_TCP_READ_TIMEOUT)
            # _LOGGER.debug("Received: %s", data.decode())

            return data.decode(errors="replace")
        except (asyncio.TimeoutError, OSError):
            _LOGGER.debug("myIO TCP request failed for %s:%s", host, port, exc_info=True)
            return ""
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    _LOGGER.debug("TCP socket close failed", exc_info=True)

    async def validate(self, host, port, app_port, name, password):
        """this function checks if the parameters are valid"""
        _toencode = f"{name}:{password}"
        _encoded = base64.b64encode(bytes(_toencode, encoding="utf8"))
        _host = host.replace("https://", "").replace("http://", "")
        message = "cannot_connect"

        _LOGGER.debug("Running validation query")
        try:
            response = await self.tcp_echo_client(
                f"GET /relay.json HTTP/1.1\r\nAuthorization: Basic {_encoded.decode()}\r\n", _host, port
            )
            message = "app_port_problem"
            response = await self.tcp_echo_client(f"{_encoded.decode()}\n?R\n", _host, app_port)

            if response in (".", "!"):
                message = "invalid_auth"
            elif response:
                message = "ok"

        except Exception:  # pylint: disable=broad-except
            _LOGGER.debug("myIO validation failed", exc_info=True)

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
        _server_key = self._server_key(config_entry)

        def call_http(uri, data):
            url = f"http://{_host}:{config_entry.data[CONF_PORT]}/{uri}"
            auth = (
                config_entry.data[CONF_USERNAME],
                config_entry.data[CONF_PASSWORD],
            )
            started_at = time.monotonic()
            try:
                _LOGGER.debug(f"Starting HTTP request: {uri}")
                with self._http_lock:
                    res = self._http_session.get(
                        url=url,
                        auth=auth,
                        data=data,
                        timeout=_HTTP_TIMEOUT,
                    )
                self._update_monitoring(
                    _server_key,
                    res.status_code,
                    time.monotonic() - started_at,
                )
                _LOGGER.debug(f"HTTP response: status={res.status_code}, length={len(res.text)}")
                self._log_http_recovered(_server_key)
                return res
            except requests.RequestException as err:
                self._log_http_retry(_server_key, uri, err)
                try:
                    _LOGGER.debug(f"Retrying HTTP request: {uri}")
                    with self._http_lock:
                        res = self._http_session.get(
                            url=url,
                            auth=auth,
                            data=data,
                            timeout=_HTTP_TIMEOUT,
                        )
                    self._update_monitoring(
                        _server_key,
                        res.status_code,
                        time.monotonic() - started_at,
                    )
                    _LOGGER.debug(f"HTTP response: status={res.status_code}, length={len(res.text)}")
                    _LOGGER.debug(f"HTTP response: {res}")
                    self._log_http_recovered(_server_key)
                    return res
                except requests.RequestException as retry_err:
                    self._update_monitoring(
                        _server_key,
                        -1,
                        time.monotonic() - started_at,
                    )
                    self._log_http_failed(_server_key, uri, retry_err)
                    _LOGGER.debug("myIO HTTP request failed after retry", exc_info=True)
                    return self._failed_response(retry_err)

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
                    self._log_status_change(_server_key, server_status)
                    return [server_data, server_status]

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

                _LOGGER.debug("Server data sections loaded: %s", list(server_data))

                for desc in _DESCRIPTIONS:  # try to add descriptions from xml files
                    _LOGGER.debug(f"Getting server_data {desc}")
                    _LOGGER.debug(f"Getting _DESCRIPTIONS[desc] = {_DESCRIPTIONS[desc]}")
                    if _DESCRIPTIONS[desc] not in server_data:
                        _LOGGER.debug(
                            "Skipping description query for missing data key: %s",
                            _DESCRIPTIONS[desc],
                        )
                        continue
                    _desc_data = server_data[_DESCRIPTIONS[desc]]
                    for element in _desc_data:
                        if _desc_data[element].get("description", -1) == -1:
                            _desc_data[element]["description"] = ""

                    _LOGGER.debug(f"Calling description query for '{desc}'")
                    message = f"GET /{desc}_desc.xml HTTP/1.1\nAuthorization: Basic {_encoded.decode()}\n\n"
                    try:
                        _LOGGER.debug("myIO description query %s on port %s", desc, _port_http)
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
                    except Exception as err:  # pylint: disable=broad-except
                        if not _invalid:
                            _LOGGER.warning(
                                "myIO description query failed for %s/%s: %s",
                                _server_key,
                                desc,
                                err,
                            )
                            _LOGGER.debug("myIO description query traceback", exc_info=True)

            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.warning("myIO initial refresh failed for %s: %s", _server_key, err)
                _LOGGER.debug("myIO initial refresh traceback", exc_info=True)
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

                            _temp_json = json.loads(body)
                            server_data = self._merge_server_data(server_data, _temp_json)
                        else:
                            server_status = "Invalid"
                            _invalid = True
                    except Exception as err:  # pylint: disable=broad-except
                        _LOGGER.warning("myIO sens_out.json refresh failed for %s: %s", _server_key, err)
                        _LOGGER.debug("myIO sens_out.json refresh traceback", exc_info=True)
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
                            _temp_json = json.loads(body)
                            if _temp_json.get("relay") is not None:
                                _temp_json["relays"] = _temp_json.pop("relay")
                            server_data = self._merge_server_data(server_data, _temp_json, skip_keys={"sensors"})
                        else:
                            _LOGGER.debug("Invalid output.json")
                            server_status = "Invalid"
                            _invalid = True
                    except Exception as err:  # pylint: disable=broad-except
                        _LOGGER.warning("myIO output.json refresh failed for %s: %s", _server_key, err)
                        _LOGGER.debug("myIO output.json refresh traceback", exc_info=True)
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
                    except Exception as err:  # pylint: disable=broad-except
                        _LOGGER.warning("myIO sensor TCP refresh failed for %s: %s", _server_key, err)
                        _LOGGER.debug("myIO sensor TCP refresh traceback", exc_info=True)
                        server_status = "Offline"

            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.warning("myIO refresh failed for %s: %s", _server_key, err)
                _LOGGER.debug("myIO refresh traceback", exc_info=True)
                if not _invalid:
                    server_status = "Offline"
        _LOGGER.debug(f"MYIO setup finished: {server_status}")
        self._log_status_change(_server_key, server_status)
        return [server_data, server_status]
