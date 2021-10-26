from sys import stderr
from setuptools import setup, find_packages


def read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"warning: No {path!r} found", file=stderr)
        return ""


setup(
    name='raspinel',
    version="1.0.0",
    author="***REMOVED*** ***REMOVED***",
    author_email='***REMOVED***',
    url='https://github.com/Dashstrom/raspinel',
    license=read("LICENSE"),
    packages=find_packages(exclude=('tests', 'docs')),
    long_description=read("README.md"),
    description=('Connection package to a raspberry '
                 'or any other machine using ssh.')
)
