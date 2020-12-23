import os
import yaml
import pika
import json
import base64
import logging
import copy
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

OBSERVABLE_KEYS = {
    "autonomous-system": "Autonomous-System.number",
    "ipv4-addr": "IPv4-Addr.value",
    "ipv6-addr": "IPv6-Addr.value",
    "domain": "Domain-Name.value",
    "mac-addr": "Mac-Addr.value",
    "url": "Url.value",
    "email-address": "Email-Addr.value",
    "email-subject": "Email-Message.subject",
    "mutex": "Mutex.name",
    "file-name": "File.name",
    "file-path": "File.path",
    "file-md5": "File.hashes.MD5",
    "file-sha1": "File.hashes.SHA-1",
    "file-sha256": "File.hashes.SHA-256",
    "directory": "Directory.path",
    "registry-key": "Windows-Registry-Key.key",
    "registry-key-value": "Windows-Registry-value-type.data",
    "user-account": "User-Account.account_login",
    "text": "X-OpenCTI-Text.value",
    "cryptographic-key": "X-openCTI-Cryptographic-key.value",
    "cryptocurrency-wallet": "X-OpenCTI-Cryptocurrency-Wallet.value",
}


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
        self.config.update(
            {
                key.lower(): value
                for key, value in os.environ.items()
                if key.startswith("OPENCTI")
            }
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
            "applicant_id": None,
            "content": base64.b64encode(bundle.encode("utf-8")).decode("utf-8"),
        }
        # Send the message
        routing_key = (
            "push_routing_" + self.config["opencti_v4_import_file_stix_connector_id"]
        )
        try:
            self.channel.basic_publish(
                exchange="amqp.worker.exchange",
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
                raise ValueError("Impossible to send a message to RabbitMQ")

    def start(self):
        state = self.get_state()
        if state["step"] is not None:
            print(
                "A current state has been found, resuming to step "
                + str(state["step"])
                + " with cursor "
                + str(state["after"])
            )
        # 1. MIGRATION OF STIX DOMAIN OBJECT
        if state["step"] is None or state["step"] == 1:
            print(" ")
            print("STEP 1: MIGRATION OF STIX DOMAIN OBJECTS (except containers)")
            print(" ")
            data = {"pagination": {"hasNextPage": True, "endCursor": state["after"]}}
            count = self.opencti_api_client.stix_domain_entity.list(
                first=1,
                withPagination=True,
                customAttributes="""
                    id
                    entity_type
                """,
                orderBy="created_at",
                orderMode="asc",
            )
            with progressbar.ProgressBar(
                max_value=count["pagination"]["globalCount"]
            ) as bar:
                while data["pagination"]["hasNextPage"]:
                    after = data["pagination"]["endCursor"]
                    data = self.opencti_api_client.stix_domain_entity.list(
                        first=100,
                        after=after,
                        withPagination=True,
                        orderBy="created_at",
                        customAttributes="""
                            id
                            entity_type
                        """,
                        orderMode="asc",
                    )
                    local_number = 0
                    for stix_domain_entity in data["entities"]:
                        if (
                            stix_domain_entity["entity_type"] != "report"
                            and stix_domain_entity["entity_type"] != "note"
                        ):
                            bundle = self.opencti_api_client.stix2.export_entity(
                                stix_domain_entity["entity_type"],
                                stix_domain_entity["id"],
                            )
                            bundle_objects = copy.deepcopy(bundle["objects"])
                            bundle["objects"] = []
                            for bundle_object in bundle_objects:
                                if (
                                    "x_opencti_identity_type" in bundle_object
                                    and bundle_object["x_opencti_identity_type"]
                                    in ["Region", "Country", "City"]
                                ):
                                    bundle_object["type"] = "location"
                                    bundle_object["id"] = bundle_object["id"].replace(
                                        "identity", "location"
                                    )
                                    bundle_object[
                                        "x_opencti_location_type"
                                    ] = bundle_object["x_opencti_identity_type"]
                                if "labels" in bundle_object:
                                    del bundle_object["labels"]
                                bundle["objects"].append(bundle_object)
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
        if state["step"] == 1:
            state = self.set_state({"step": 2, "after": None, "number": 0})
        if state["step"] == 2:
            print(" ")
            print("STEP 2: MIGRATION OF STIX CYBER OBSERVABLES")
            print(" ")
            data = {"pagination": {"hasNextPage": True, "endCursor": state["after"]}}
            count = self.opencti_api_client.stix_observable.list(
                first=1,
                withPagination=True,
                customAttributes="""
                    id
                    entity_type
                """,
                orderBy="created_at",
                orderMode="asc",
            )
            with progressbar.ProgressBar(
                max_value=count["pagination"]["globalCount"]
            ) as bar:
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
                    for stix_observable in data["entities"]:
                        observable_stix = {
                            "id": stix_observable["stix_id_key"],
                            "type": "x-opencti-simple-observable",
                            "key": OBSERVABLE_KEYS[stix_observable["entity_type"]],
                            "value": stix_observable["observable_value"],
                            "description": stix_observable["description"],
                        }
                        original_bundle_objects = (
                            self.opencti_api_client.stix2.prepare_export(
                                stix_observable, observable_stix
                            )
                        )
                        bundle_objects = []
                        for original_bundle_object in original_bundle_objects:
                            if "labels" in original_bundle_object:
                                del original_bundle_object["labels"]
                            bundle_objects.append(original_bundle_object)
                        bundle = {"type": "bundle", "objects": bundle_objects}
                        self._send_bundle(json.dumps(bundle))
                        local_number += 1
                    state = self.set_state(
                        {
                            "step": 2,
                            "after": after,
                            "number": state["number"] + local_number,
                        }
                    )
                    bar.update(state["number"])

        # 3. MIGRATION OF STIX CORE RELATIONSHIPS
        if state["step"] == 2:
            state = self.set_state({"step": 3, "after": None, "number": 0})
        if state["step"] == 3:
            print(" ")
            print("STEP 3: MIGRATION OF STIX CORE RELATIONSHIPS")
            print(" ")
            data = {"pagination": {"hasNextPage": True, "endCursor": state["after"]}}
            count = self.opencti_api_client.stix_relation.list(
                first=1,
                withPagination=True,
                customAttributes="""
                    id
                """,
                orderBy="created_at",
                orderMode="asc",
            )
            with progressbar.ProgressBar(
                max_value=count["pagination"]["globalCount"]
            ) as bar:
                while data["pagination"]["hasNextPage"]:
                    after = data["pagination"]["endCursor"]
                    data = self.opencti_api_client.stix_relation.list(
                        first=100,
                        after=after,
                        withPagination=True,
                        customAttributes="""
                            id
                        """,
                        orderBy="created_at",
                        orderMode="asc",
                    )
                    local_number = 0
                    for stix_relation in data["entities"]:
                        if not stix_relation["from"]["stix_id_key"].startswith(
                            "relationship"
                        ) and not stix_relation["to"]["stix_id_key"].startswith(
                            "relationship"
                        ):
                            bundle_objects = (
                                self.opencti_api_client.stix_relation.to_stix2(
                                    id=stix_relation["id"]
                                )
                            )
                            bundle = {"type": "bundle", "objects": bundle_objects}
                            self._send_bundle(json.dumps(bundle))
                        local_number += 1
                    state = self.set_state(
                        {
                            "step": 3,
                            "after": after,
                            "number": state["number"] + local_number,
                        }
                    )
                    bar.update(state["number"])

        # 4. MIGRATION OF STIX CORE RELATIONSHIPS TO STIX CORE RELATIONSHIPS
        if state["step"] == 3:
            state = self.set_state({"step": 4, "after": None, "number": 0})
        if state["step"] == 4:
            print(" ")
            print(
                "STEP 4: MIGRATION OF STIX CORE RELATIONSHIPS TO STIX CORE RELATIONSHIPS"
            )
            print(" ")
            data = {"pagination": {"hasNextPage": True, "endCursor": state["after"]}}
            count = self.opencti_api_client.stix_relation.list(
                first=1,
                withPagination=True,
                customAttributes="""
                    id
                """,
                orderBy="created_at",
                orderMode="asc",
            )
            with progressbar.ProgressBar(
                max_value=count["pagination"]["globalCount"]
            ) as bar:
                while data["pagination"]["hasNextPage"]:
                    after = data["pagination"]["endCursor"]
                    data = self.opencti_api_client.stix_relation.list(
                        first=100,
                        after=after,
                        withPagination=True,
                        customAttributes="""
                            id
                        """,
                        orderBy="created_at",
                        orderMode="asc",
                    )
                    local_number = 0
                    for stix_relation in data["entities"]:
                        if stix_relation["from"]["stix_id_key"].startswith(
                            "relationship"
                        ) or stix_relation["to"]["stix_id_key"].startswith(
                            "relationship"
                        ):
                            bundle_objects = (
                                self.opencti_api_client.stix_relation.to_stix2(
                                    id=stix_relation["id"]
                                )
                            )
                            bundle = {"type": "bundle", "objects": bundle_objects}
                            self._send_bundle(json.dumps(bundle))
                        local_number += 1
                    state = self.set_state(
                        {
                            "step": 4,
                            "after": after,
                            "number": state["number"] + local_number,
                        }
                    )
                    bar.update(state["number"])

        # 5. MIGRATION OF CONTAINERS
        if state["step"] == 4:
            state = self.set_state({"step": 5, "after": None, "number": 0})
        if state["step"] == 5:
            print(" ")
            print("STEP 5: MIGRATION OF CONTAINERS")
            print(" ")
            data = {"pagination": {"hasNextPage": True, "endCursor": state["after"]}}
            count = self.opencti_api_client.stix_domain_entity.list(
                types=["Report", "Note"],
                first=1,
                withPagination=True,
                customAttributes="""
                    id
                    entity_type
                """,
                orderBy="created_at",
                orderMode="asc",
            )
            with progressbar.ProgressBar(
                max_value=count["pagination"]["globalCount"]
            ) as bar:
                while data["pagination"]["hasNextPage"]:
                    after = data["pagination"]["endCursor"]
                    data = self.opencti_api_client.stix_domain_entity.list(
                        types=["Report", "Note"],
                        first=100,
                        after=after,
                        withPagination=True,
                        customAttributes="""
                            id
                        """,
                        orderBy="created_at",
                        orderMode="asc",
                    )
                    local_number = 0
                    for stix_observable in data["entities"]:
                        original_bundle_objects = (
                            self.opencti_api_client.stix_observable.to_stix2(
                                id=stix_observable["id"]
                            )
                        )
                        bundle_objects = []
                        for original_bundle_object in original_bundle_objects:
                            if "labels" in original_bundle_object:
                                del original_bundle_object["labels"]
                            bundle_objects.append(original_bundle_object)
                        bundle = {"type": "bundle", "objects": bundle_objects}
                        self._send_bundle(json.dumps(bundle))
                        local_number += 1
                    state = self.set_state(
                        {
                            "step": 5,
                            "after": after,
                            "number": state["number"] + local_number,
                        }
                    )
                    bar.update(state["number"])


if __name__ == "__main__":
    migrate_instance = Migrate()
    migrate_instance.start()
