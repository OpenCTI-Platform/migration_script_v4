import os
import yaml
import pika
import json
import base64

from pycti import OpenCTIApiClient

mandatory_configs = [
    "opencti_v3_url",
    "opencti_v3_token",
    "opencti_v4_import_file_stix_connector_id",
    "opencti_v4_rabbitmq_hostname",
    "opencti_v4_rabbitmq_user",
    "opencti_v4_rabbitmq_password",
]


class Migrate:
    def __init__(self):
        config_file_path = os.path.dirname(os.path.abspath(__file__)) + "/config.yml"
        self.config = (
            yaml.load(open(config_file_path), Loader=yaml.FullLoader)
            if os.path.isfile(config_file_path)
            else {}
        )
        for config in mandatory_configs:
            if config not in config:
                raise ValueError("Missing configuration parameter: " + config)

        # Test connection to the V3 API
        self.opencti_api_client = OpenCTIApiClient(
            self.config["opencti_v3_url"], self.config["opencti_v3_token"]
        )

        # Check RabbitMQ
        self.connection = None
        self.channel = None
        self._rabbitmq_connect()

        # Check if state already here or is creatable
        self.state_file = os.path.dirname(os.path.abspath(__file__)) + "/state.json"
        self.get_state()

    def _rabbitmq_connect(self):
        # Test connection to the RabbitMQ
        credentials = pika.PlainCredentials(
            self.config["opencti_v4_rabbitmq_user"],
            self.config["opencti_v4_rabbitmq_password"],
        )
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=self.config["opencti_v4_rabbitmq_hostname"],
                port=self.config["opencti_v4_rabbitmq_port"],
                credentials=credentials,
            )
        )
        self.channel = self.connection.channel()

    def get_state(self):
        if os.path.isfile(self.state_file):
            with open(self.state_file, "r") as state_file_handler:
                return json.load(state_file_handler)
        else:
            with open(self.state_file, "w") as state_file_handler:
                json.dump({}, state_file_handler)
                return {}

    def set_state(self, state):
        with open(self.state_file, "w") as state_file_handler:
            json.dump(state, state_file_handler)

    def _send_bundle(self, bundle, retry=False):
        message = {
            "job_id": None,
            "entities_types": None,
            "content": base64.b64encode(bundle.encode("utf-8")).decode("utf-8"),
        }
        # Send the message
        try:
            routing_key = (
                "push_routing_"
                + self.config["opencti_v4_import_file_stix_connector_id"]
            )
            self.channel.basic_publish(
                exchange=self.config["push_exchange"],
                routing_key=routing_key,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # make message persistent
                ),
            )
        except:
            if retry is False:
                self._rabbitmq_connect()
                self._send_bundle(bundle, True)
            else:
                pass

    def start(self):
        print("Starting migration...")


if __name__ == "__main__":
    migrate_instance = Migrate()
    migrate_instance.start()
