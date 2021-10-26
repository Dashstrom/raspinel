from sys import stderr
from setuptools import setup, find_packages
from raspinel import __version__, __author__


def read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"warning: No {path!r} found", file=stderr)
        return ""


setup(
    name='raspinel',
    version=__version__,
    description='Easy-to-use raspberry pi manager',
    long_description=read("README.md"),
    author=__author__,
    author_email='***REMOVED***',
    url='https://github.com/Dashstrom',
    license=read("LICENSE"),
    packages=find_packages(exclude=('tests', 'docs'))
)
