import re

from setuptools import find_packages, setup


def read(path):
    # type: (str) -> str
    with open(path, "rt", encoding="utf8") as f:
        return f.read().strip()


def version():
    # type: () -> str
    match = re.search(r"__version__\s+=\s+[\"'](.+)[\"']",
                      read("raspinel/__init__.py"))
    if match is not None:
        return match.group(1)  # type: ignore
    return "0.0.1"


setup(
    name="raspinel",
    version=version(),
    author="Dashstrom",
    author_email="dashstrom.pro@gmail.com",
    url="https://github.com/Dashstrom/raspinel",
    license="GPL-3.0 License",
    packages=find_packages(exclude=("tests",)),
    description=("Connection package to a raspberry "
                 "or any other machine using ssh."),
    long_description=read("README.md"),
    long_description_content_type="text/markdown",
    python_requires=">=3.6.0",
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Cython",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Operating System :: Microsoft :: Windows :: Windows 10",
        "Natural Language :: French"
    ],
    include_package_data=True,
    test_suite="tests",
    package_data={
        "raspinel": ["assets/*"],
    },
    keywords=["raspinel", "raspberry", "fractale", "tkinter"],
    install_requires=read("requirements.txt").split("\n"),
    zip_safe=True
)
