# Raspinel

Connection package to a raspberry or any other machine using ssh,
it simplifies the deployment scripts and monitoring.

⚠️ Warning : no security guarantee, please do not use this package for access to sensitive data.

⚠️ Developed only for window at the moment

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Install](#install)
3. [Usage in command line](#usage-in-command-line)
4. [Usage as application](#usage-as-application)
4. [Usage as module](#usage-as-module)
4. [License](#license)

## Prerequisites

To use this program you need python 3.10, no support will be provided for previous versions.


You also need to install Putty and WinSCP
- [Download Putty](https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html)
- [Download WinSCP](https://winscp.net/eng/download.php)

## Install

This package is not available on pypi at the moment.
To install it, you need to download it from git as below.

```sh
git clone https://github.com/Dashstrom/raspinel.git raspinel
cd raspinel
pip install .
```

## Configuration
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

if all is well configure the following command should reply you `hello world`.
```
py -m raspinel "echo 'hello world'"
```
## Usage in command line

The strength of this package is that it can be used as a command line tool,
bellow are the supported command line functionality for the moment.
```
usage: py -m raspinel [-h] [-i] [-d src dest] [-u src dest] [commands ...]

Allows communication using ssh to get information, upload or download files or run commands.
Run without argument start program in GUI mode.

positional arguments:
  commands              commands to execute on remote

options:
  -h, --help            show this help message and exit
  -i, --info            show some information about remote using sftp
  -d src dest, --download src dest
                        download file from remote
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

Here is a simple code that displays a hello world
```python
import sys
from raspinel import Client

if __name__ == "__main__":
    # connect from env or files
    clt = Client.resolve()
    
    # send command
    resp = clt.cmd("echo {}", "hello world")
    
    # show outputs
    print(resp.out)
    print(resp.err)
    
    # get command exit
    sys.exit(resp.exit)
```

For more details or help use `py -c "help(__import__('raspinel'))"`

## License

raspinel is licensed under the terms of the GNU License ([see the file LICENSE](https://github.com/Dashstrom/raspinel/blob/main/LICENSE)).