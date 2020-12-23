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

### Procedure

1. Start a new OpenCTI 4 fresh platform.
2. Configure the script with OpenCTI 3 credentials and OpenCTI 4 RabbitMQ Server.
3. Launch the migration script that will take old data in STIX2 and re-inject it in the OpenCTI import system.
4. The data ingestion should be quick as OpenCTI 4 will have an enhanced throughput of write operations.

#### Script config

```
opencti_v3_url: 'https://openctiv3.com'
opencti_v3_token: 'ChangeMe'
opencti_v4_import_file_stix_connector_id: 'ChangeMe (UUIDv4 of the connector)'
opencti_v4_rabbitmq_hostname: 'rabbitmq.v4'
opencti_v4_rabbitmq_port: 5672
opencti_v4_rabbitmq_user: 'ChangeMe'
opencti_v4_rabbitmq_password: 'ChangeMe'
```

### Using Docker Compose

Modify `docker-compose.yml` environment with the target configuration.
Environment variables will take precedence over the config.yml file.

Then run:

```
docker build -t opencti-migration-v4 .
docker-compose -f docker-compose.yml up
```
