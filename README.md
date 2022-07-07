# ![Logo](https://raw.githubusercontent.com/Dashstrom/raspinel/main/docs/images/logo.png) Raspinel

[![Windows](https://svgshare.com/i/ZhY.svg)](https://svgshare.com/i/ZhY.svg)

Connection package to a raspberry or any other machine using ssh,
it simplifies the deployment scripts and monitoring.

⚠️ Warning : no security guarantee, please do not use this package for access to sensitive data.

⚠️ Currently support only window client to linux remote.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Install](#install)
3. [Install for developpement](#install-for-developpement)
4. [Usage in command line](#usage-in-command-line)
5. [Usage as application](#usage-as-application)
6. [Usage as module](#usage-as-module)
7. [License](#license)

## Prerequisites

To use this program you need python 3.10, no support will be provided for previous versions.

You also need to install Putty and WinSCP

- [Download Putty](https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html)
- [Download WinSCP](https://winscp.net/eng/download.php)

## Install

This package is not available on pypi at the moment.
To install it, you need to download it from git as below.

```sh
pip install git+https://github.com/Dashstrom/raspinel
py -m raspinel
```

## Install for developpement

You need 6 versions of python for run test on every versions :

- [Python 3.11.0b3](https://www.python.org/downloads/release/python-3110b3/)
- [Python 3.10.5](https://www.python.org/downloads/release/python-3105/)
- [Python 3.9.13](https://www.python.org/downloads/release/python-3913/)
- [Python 3.8.10](https://www.python.org/downloads/release/python-3810/)
- [Python 3.7.9](https://www.python.org/downloads/release/python-379/)
- [Python 3.6.8](https://www.python.org/downloads/release/python-368/)

```sh
git clone https://github.com/Dashstrom/raspinel.git
cd raspinel
pip install -r requirements_dev.txt
```

For run test you can use `tox`

## Configuration

After downloading it you need to create a configuration file named `.raspinel.yml` in one of the following places :

- `$HOME\.raspinel.yml`
- `$MODULE_PATH\.raspinel.yml`
- `$PWD\.raspinel.yml`

It must contain the following structure where only the host is mandatory.

```yml
hostname: '192.168.0.X'
port: 22
username: 'pi'
password: 'YOUR_PASSWORD'
timemout: 2
```

You can also just use environment variables as :

```sh
export RASPINEL_HOSTNAME=192.168.0.X
export RASPINEL_PORT=22
export RASPINEL_PASSWORD=YOUR_PASSWORD
export RASPINEL_USERNAME=pi
export RASPINEL_TIMEOUT=2
```

You must of course replace the values given in the example by your own identifiers.

If all is well configure the following command should reply you `hello world`.

```sh
py -m raspinel "echo 'hello world'"
```

## Usage in command line

The strength of this package is that it can be used as a command line tool,
bellow are the supported command line functionality for the moment.

```txt
usage: py -m raspinel [-h] [-i] [-d src dest] [-u src dest] [commands ...]

Allows communication using ssh to get information, upload or download files or run commands.
Run without argument start program in GUI mode.

positional arguments:
  commands              commands to execute on remote

options:
  -h, --help            show this help message and exit
  -i, --info            show some information about remote
  -d src dest, --download src dest
                        download file from remote using sftp
  -u src dest, --upload src dest
                        upload file to remote using sftp
```

## Usage as application

To launch the application, nothing could be simpler :

```sh
py -m raspinel
```

### The main window

![Image of Raspinel - Main Window](https://raw.githubusercontent.com/Dashstrom/raspinel/main/images/capture.png)

### The Manager

![Image of Raspinel - Manager](https://raw.githubusercontent.com/Dashstrom/raspinel/main/images/manager.png)

## Usage as module

Here is a simple code that displays a hello world.

```py
import sys
from raspinel import Client

if __name__ == "__main__":
    # connect from env or files
    with Client.resolve() as clt:
        # send command
        resp = clt.cmd("echo {}", "hello world")
    
    # show outputs
    print(resp.out)
    print(resp.err)
    
    # exit with the same exit code that command
    sys.exit(resp.exit)
```

For more details or help use `py -c "import raspinel;help(raspinel)"`

## License

raspinel is licensed under the terms of the GNU License ([see the file LICENSE](https://github.com/Dashstrom/raspinel/blob/main/LICENSE)).
