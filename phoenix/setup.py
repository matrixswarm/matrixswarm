from setuptools import setup, find_packages

# Load all requirements from requirements.txt
with open("requirements.txt", "r", encoding="utf-8") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="phoenix-cockpit",
    version="1.0.0",
    description="Phoenix Cockpit GUI for MatrixSwarm",
    author="The Generals",
    packages=find_packages(include=["phoenix", "phoenix.*"]),
    install_requires=requirements,
    include_package_data=True,
    entry_points={
        "gui_scripts": [
            "phoenix = phoenix.__main__:main"
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
)

