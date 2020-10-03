## OpenCTI Migration Script

### Prerequires

This script allows to migrate data from OpenCTI version 3.3.2 (only) to any OpenCTI platform version 4.X.X.

NB: The Python client used by this script is `pycti 3.3.3`. Also, the connector `import-file-stix2` must be enabled on the target OpenCTI version 4.X.X instance.

### Clone the repository

```
$ git clone https://github.com/OpenCTI-Platform/migration_script_v4
$ cd migration_script_v4
```

### Create a venv environement (optional)

```
$ sudo apt-get install python3-venv
$ python3 -m venv venv
$ ./venv/bin/pip3 install -r requirements.txt
```

If you dont want to use a venv, please install the requirements with `pip3 install -r requirements.txt`.

### Script parameters



