# MYIO Home Assistant intergation module

MYIO is a home automation platform (<a href="http://smarthomeninja.hu" target="_blank">MYIO home page</a>). This repository provides integration of this platform to Home Assistant.

Latest tested Home Assistant version: <b>2025.11</b>

## Install via HACS (Custom repository)

This integration is distributed as a HACS custom repository. You can install it either from a public or a private GitHub repository.

1. In Home Assistant, open HACS → Integrations.
2. Click the three dots (⋯) → Custom repositories.
3. Add repository URL: `https://github.com/akitaylor/homeassistant-myio` with category `Integration`.
   - If the repository is private, you must configure a GitHub Personal Access Token for HACS with at least read access to the repo (HACS → Settings → GitHub token).
4. Find "myIO" in HACS → Integrations and click Install.
5. Restart Home Assistant.
6. Go to Settings → Devices & services → Add integration → search for "myIO", then follow the config flow.

## License

Copyright (C)

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this project except in compliance with the License. You may obtain a copy of the License at https://www.apache.org/licenses/LICENSE-2.0.

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
