# myIO Home Assistant integration

myIO is a home automation platform from [Smarthome Ninja](http://smarthomeninja.hu). This repository provides a Home Assistant custom integration for a myIO controller.

Latest tested Home Assistant version: **2026.6**

## What it provides

- Sensors from the myIO controller.
- Relay and PWM based lights, including RGBW groups.
- Covers and climate entities exposed by the myIO controller.
- A config flow for adding the controller from Home Assistant.
- Operational attributes on the helper state entity `myio_server.state`.

## Operational monitoring

The integration publishes two monitoring attributes on `myio_server.state`:

- `query_latency`: last successful or failed controller query time in seconds.
- `controller_status`: `OK` when the latest HTTP query returned status `200`, otherwise `NOT OK`.

These attributes are intended for Lovelace dashboards, alerts, and operational checks. The integration keeps these attributes when commands are sent from light, cover, and climate entities.

## Changes in 2.0.1

- Reused a single HTTP session for controller polling.
- Added separate connect/read HTTP timeouts.
- Added query latency and controller status monitoring attributes.
- Fixed partial state merging when the controller returns incomplete JSON.
- Fixed RGBW command handling and initial brightness/color scaling.
- Reduced noisy HTTP and TCP logging while keeping useful outage and recovery messages.
- Improved exception handling so operational failures are easier to diagnose from Home Assistant logs.
- Removed the unused external `myio` Python package requirement.
- Removed the empty `custom_components/__init__.py` namespace marker.

## Install via HACS custom repository

This integration is distributed as a HACS custom repository.

1. In Home Assistant, open HACS -> Integrations.
2. Open the menu -> Custom repositories.
3. Add repository URL `https://github.com/akitaylor/homeassistant-myio` with category `Integration`.
4. Find `myIO` in HACS -> Integrations and install it.
5. Restart Home Assistant.
6. Go to Settings -> Devices & services -> Add integration -> search for `myIO`, then follow the config flow.

## Manual test installation

To test a local version without waiting for HACS, copy the repository's `custom_components/myio` directory into your Home Assistant config directory:

```text
<home-assistant-config>/custom_components/myio
```

Restart Home Assistant after copying the files.

## Notes

- The controller is polled over HTTP for state updates.
- Description metadata is fetched over the controller TCP interface during setup.
- Home Assistant will show the usual warning for custom integrations because this integration is not bundled with Home Assistant core.

## License

Copyright (C)

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this project except in compliance with the License. You may obtain a copy of the License at https://www.apache.org/licenses/LICENSE-2.0.

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
