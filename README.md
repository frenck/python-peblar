# Python: Asynchronous Python client for Peblar EV chargers

[![GitHub Release][releases-shield]][releases]
[![Python Versions][python-versions-shield]][pypi]
![Project Stage][project-stage-shield]
![Project Maintenance][maintenance-shield]
[![License][license-shield]](LICENSE.md)

[![Build Status][build-shield]][build]
[![Code Coverage][codecov-shield]][codecov]
[![Quality Gate Status][sonarcloud-shield]][sonarcloud]
[![Open in Dev Containers][devcontainer-shield]][devcontainer]

[![Sponsor Frenck via GitHub Sponsors][github-sponsors-shield]][github-sponsors]

[![Support Frenck on Patreon][patreon-shield]][patreon]

Asynchronous Python client for Peblar's Rocksolid EV chargers

## About

This package allows you to control and monitor [Peblar EV Chargers](https://peblar.com)
programmatically. It is mainly created to allow third-party programs to
automate the behavior of a Peblar charger.

Additionally, this package contains a CLI tool, which can be used standalone,
proving a command-line interface to control and monitor Peblar chargers.

Known compatible and tested Peblar chargers:

- Peblar Home

## Installation

```bash
pip install peblar
```

In case you want to use the CLI tools, install the package with the following
extra:

```bash
pip install peblar[cli]
```

## CLI usage

The Peblar CLI tool provided in this library provides all the functionalities
this library provides but from the command line.

The CLI comes with built-in help, which can be accessed by using the `--help`

```bash
peblar --help
```

To scan for Peblar chargers on your network:

```bash
peblar scan
```

For more details, access the built-in help of the CLI using the `--help` flag.

## Python usage

Using this library in Python:

```python
import asyncio

from peblar import Peblar


async def main() -> None:
    """Show example of programmatically control a Peblar charger."""
    async with Peblar(host="192.168.1.123") as peblar:
        await peblar.login(password="Sup3rS3cr3t!")

        await peblar.identify()

        system_information = await peblar.system_information()
        print(system_information)


if __name__ == "__main__":
    asyncio.run(main())
```

## Changelog & releases

This repository keeps a change log using [GitHub's releases][releases]
functionality. The format of the log is based on
[Keep a Changelog][keepchangelog].

Releases are based on [Semantic Versioning][semver], and use the format
of `MAJOR.MINOR.PATCH`. In a nutshell, the version will be incremented
based on the following:

- `MAJOR`: Incompatible or major changes.
- `MINOR`: Backwards-compatible new features and enhancements.
- `PATCH`: Backwards-compatible bugfixes and package updates.

## Contributing

This is an active open-source project. We are always open to people who want to
use the code or contribute to it.

We've set up a separate document for our
[contribution guidelines](CONTRIBUTING.md).

Thank you for being involved! :heart_eyes:

## Setting up a development environment

The easiest way to start is by opening a CodeSpace here on GitHub, or by using
the [Dev Container][devcontainer] feature of Visual Studio Code.

[![Open in Dev Containers][devcontainer-shield]][devcontainer]

This Python project is fully managed using the [uv] dependency manager. But also relies on the use of NodeJS for certain checks during development.

You need at least:

- Python 3.11+
- [uv][uv-install]
- NodeJS 20+ (including NPM)

To install all packages, including all development requirements:

```bash
npm install
uv sync --extra cli
```

As this repository uses the [pre-commit][pre-commit] framework, all changes
are linted and tested with each commit. You can run all checks and tests
manually, using the following command:

```bash
uv run pre-commit run --all-files
```

To run just the Python tests:

```bash
uv run pytest
```

## Authors & contributors

The original setup of this repository is by [Franck Nijhof][frenck].

For a full list of all authors and contributors,
check [the contributor's page][contributors].

## License

MIT License

Copyright (c) 2024 Franck Nijhof

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

[build-shield]: https://github.com/frenck/python-peblar/actions/workflows/tests.yaml/badge.svg
[build]: https://github.com/frenck/python-peblar/actions/workflows/tests.yaml
[codecov-shield]: https://codecov.io/gh/frenck/python-peblar/branch/master/graph/badge.svg
[codecov]: https://codecov.io/gh/frenck/python-peblar
[contributors]: https://github.com/frenck/python-peblar/graphs/contributors
[devcontainer-shield]: https://img.shields.io/static/v1?label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode
[devcontainer]: https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/frenck/python-peblar
[frenck]: https://github.com/frenck
[github-sponsors-shield]: https://frenck.dev/wp-content/uploads/2019/12/github_sponsor.png
[github-sponsors]: https://github.com/sponsors/frenck
[keepchangelog]: http://keepachangelog.com/en/1.0.0/
[license-shield]: https://img.shields.io/github/license/frenck/python-peblar.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2023-2024.svg
[patreon-shield]: https://frenck.dev/wp-content/uploads/2019/12/patreon.png
[patreon]: https://www.patreon.com/frenck
[uv-install]: https://docs.astral.sh/uv/getting-started/installation/
[uv]: https://docs.astral.sh/uv/
[pre-commit]: https://pre-commit.com/
[project-stage-shield]: https://img.shields.io/badge/project%20stage-production%20ready-brightgreen.svg
[pypi]: https://pypi.org/project/peblar/
[python-versions-shield]: https://img.shields.io/pypi/pyversions/peblar
[releases-shield]: https://img.shields.io/github/release/frenck/python-peblar.svg
[releases]: https://github.com/frenck/python-peblar/releases
[semver]: http://semver.org/spec/v2.0.0.html
[sonarcloud-shield]: https://sonarcloud.io/api/project_badges/measure?project=frenck_python-peblar&metric=alert_status
[sonarcloud]: https://sonarcloud.io/summary/new_code?id=frenck_python-peblar
