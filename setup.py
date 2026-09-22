from setuptools import setup, find_packages

setup(
    name="input-locker",
    version="0.2.4",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "pynput>=1.7.6",
        "PyQt6>=6.6.0",
        "pystray>=0.19.5",
        "Pillow>=10.0.0",
    ],
    extras_require={
        "test": [
            "pytest>=8.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "input-locker=input_locker.main:main",
        ],
        "gui_scripts": [
            "input-locker-gui=input_locker.main:main",
        ],
    },
)

