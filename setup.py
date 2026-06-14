"""Setup script for photo-sync."""

from setuptools import find_packages, setup

setup(
    name="photo-sync",
    version="1.0.0",
    description="Synchronize photos and albums between Apple Photos libraries",
    author="fivemeepo",
    python_requires=">=3.10",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "photo-sync=photo_sync.cli:main",
        ],
    },
    install_requires=[],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "ruff>=0.1.0",
        ],
    },
)
