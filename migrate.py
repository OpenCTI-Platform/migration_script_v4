import os
import yaml
import pika
import json
import base64
import logging
import progressbar

from art import *
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
        logging.getLogger("pika").setLevel(logging.ERROR)
        welcome_art = text2art("OpenCTI migrator")
        print(welcome_art)
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
            self.config["opencti_v3_url"], self.config["opencti_v3_token"], "error"
        )
        print("Checking access to OpenCTI version 3.3.2 instance... OK")

        # Check RabbitMQ
        self.connection = None
        self.channel = None
        self._rabbitmq_connect()
        print("Checking access to the OpenCTI versio 4.X.X RabbitMQ... OK")

        # Check if state already here or is creatable
        self.state_file = os.path.dirname(os.path.abspath(__file__)) + "/state.json"
        print("Checking if the state file is writtable... OK")
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
                json.dump(
                    {"step": None, "after": None, "number": 0}, state_file_handler
                )
                return {"step": None, "after": None, "number": 0}

    def set_state(self, state):
        with open(self.state_file, "w") as state_file_handler:
            json.dump(state, state_file_handler)
        return state

    def _send_bundle(self, bundle, retry=False):
        message = {
            "job_id": None,
            "content": base64.b64encode(bundle.encode("utf-8")).decode("utf-8"),
        }
        # Send the message
        routing_key = (
            "push_routing_" + self.config["opencti_v4_import_file_stix_connector_id"]
        )
        self.channel.basic_publish(
            exchange="amqp.worker.exchange",
            routing_key=routing_key,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # make message persistent
            ),
        )

    def start(self):
        state = self.get_state()
        if state["step"] is not None:
            print(
                "A current state has been found, resuming to step "
                + str(state["step"])
                + " with cursor "
                + state["after"]
            )
        # 1. MIGRATION OF STIX DOMAIN OBJECT
        if state["step"] is None or state["step"] == 1:
            print(" ")
            print("STEP 1: MIGRATION OF STIX DOMAIN OBJECTS")
            print(" ")
            data = {"pagination": {"hasNextPage": True, "endCursor": state["after"]}}
            count = self.opencti_api_client.stix_domain_entity.list(
                first=1,
                withPagination=True,
                orderBy="created_at",
                orderMode="asc",
            )
            with progressbar.ProgressBar(max_value=count["pagination"]["globalCount"]) as bar:
                while data["pagination"]["hasNextPage"]:
                    after = data["pagination"]["endCursor"]
                    data = self.opencti_api_client.stix_domain_entity.list(
                        first=100,
                        after=after,
                        withPagination=True,
                        orderBy="created_at",
                        orderMode="asc",
                    )
                    local_number = 0
                    for stix_domain_entity in data["entities"]:
                        bundle = self.opencti_api_client.stix2.export_entity(
                            stix_domain_entity["entity_type"], stix_domain_entity["id"]
                        )
                        self._send_bundle(json.dumps(bundle))
                        local_number += 1
                    state = self.set_state(
                        {
                            "step": 1,
                            "after": after,
                            "number": state["number"] + local_number,
                        }
                    )
                    bar.update(state["number"])

        # 2. MIGRATION OF STIX CYBER OBSERVABLE
        state = self.set_state({"step": 2, "after": None, "number": 0})
        if state["step"] == 2:
            print(" ")
            print("STEP 2: MIGRATION OF STIX CYBER OBSERVABLES")
            print(" ")
            data = {"pagination": {"hasNextPage": True, "endCursor": state["after"]}}
            count = self.opencti_api_client.stix_domain_entity.list(
                first=1,
                withPagination=True,
                orderBy="created_at",
                orderMode="asc",
            )
            with progressbar.ProgressBar(max_value=count["pagination"]["globalCount"]) as bar:
                while data["pagination"]["hasNextPage"]:
                    after = data["pagination"]["endCursor"]
                    data = self.opencti_api_client.stix_observable.list(
                        first=100,
                        after=after,
                        withPagination=True,
                        orderBy="created_at",
                        orderMode="asc",
                    )
                    local_number = 0
                    for stix_domain_entity in data["entities"]:
                        bundle = self.opencti_api_client.stix2.export_entity(
                            stix_domain_entity["entity_type"], stix_domain_entity["id"]
                        )
                        self._send_bundle(json.dumps(bundle))
                        local_number += 1
                    self.set_state(
                        {
                            "step": 2,
                            "after": after,
                            "number": state["number"] + local_number,
                        }
                    )
                    bar.update(state["number"])

        # 3. MIGRATION OF STIX CORE RELATIONSHIPS


if __name__ == "__main__":
    migrate_instance = Migrate()
    migrate_instance.start()
