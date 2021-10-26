# Raspinel

Connection package to a raspberry or any other machine using ssh,
it simplifies the deployment scripts and monitoring.

⚠️ Warning : no security guarantee, please do not use this package for access to sensitive data.

⚠️ Developed only for window at the moment

## Prerequisites

To use this program you need python 3.10, no support will be provided for previous versions.

## Install

This package is not available on pypi at the moment.
To install it, you need to download it from git as below.

```sh
git clone https://github.com/Dashstrom/raspinel.git raspinel
cd raspinel
pip install .
```

After downloading it you need to create a configuration file named `.raspinel.yml` in one of the following places
```sh
$HOME\.raspinel.yml
$MODULE_PATH\.raspinel.yml
$PWD\.raspinel.yml
```

It must contain the following structure where only the host is mandatory.
```yml
hostname: 'REMOTE_HOSTNAME'
port: REMOTE_PORT
username: 'REMOTE_USERNAME'
password: 'REMOTE_PASSWORD'
timemout: CONNECTION_TIMEOUT_MS
```

You can also just use environment variables as :
```sh
export RASPINEL_HOSTNAME=${REMOTE_HOSTNAME}
export RASPINEL_PORT=${REMOTE_PORT}
export RASPINEL_PASSWORD=${REMOTE_USERNAME}
export RASPINEL_USERNAME=${REMOTE_PASSWORD}
export RASPINEL_TIMEOUT=${CONNECTION_TIMEOUT_MS}
```

You must of course replace the values given in the example by your own identifiers.

## License

raspinel is licensed under the terms of the GNU License (see the file LICENSE).