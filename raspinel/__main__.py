"""
Run main application.
"""
import argparse
import logging
import sys

from .app import App
from .exception import ExitCodeError
from .core import Client

FORMAT = "[%(levelname)s][%(filename)s:%(funcName)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT)


def main() -> int:
    """
    Allows communication using ssh to get information, upload or download files
    or run commands. Run without argument start program in GUI mode.
    """
    parser = argparse.ArgumentParser(
        description="Allows communication using ssh to get information, "
                    "upload or download files or run commands. "
                    "Run without argument start program in GUI mode.")
    parser.add_argument("-i", "--info", action="store_true",
                        help="show some information about remote using sftp")
    parser.add_argument("-d", "--download", type=str, nargs=2,
                        metavar=("src", "dest"),
                        help="download file from remote")
    parser.add_argument("-u", "--upload", type=str, nargs=2,
                        metavar=("src", "dest"),
                        help="upload file to remote using sftp")
    parser.add_argument("commands", nargs='*', type=str,
                        help="commands to execute on remote")
    args = parser.parse_args()
    is_default = (None, [], False).__contains__
    run_as_app = all(map(is_default, vars(args).values()))
    if run_as_app:
        app = App()
        app.mainloop()
    else:
        conn = Client.resolve()
        try:
            if args.info:
                print(conn.info)
            if args.download:
                conn.download(*args.download)
            if args.upload:
                conn.upload(*args.upload)
            if args.commands:
                raw_cmd = " ".join(args.commands)
                resp = conn.cmd(raw_cmd)
                print(resp.out)
                print(resp.err, file=sys.stderr)
                return resp.exit
        except ExitCodeError as err:
            return err.code
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
