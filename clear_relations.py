from elasticsearch import Elasticsearch

# ElasticSearch configuration
elasticsearch_uri = "HOSTNAME:PORT"

# ID to remove
id_to_clean = "V1208520904"  # to be replace by the missing ID

print("[INITIALIZE] ElasticSearch connected")
elasticsearch_client = Elasticsearch([elasticsearch_uri])

print("[QUERY] ElasticSearch match " + id_to_clean)
query = {"limit": 10000, "query": {"match_phrase": {"connections.grakn_id.keyword": id_to_clean}}}
result = elasticsearch_client.search(index="stix_relations", body=query)
# result = elasticsearch_client.delete(index="stix_relations", body=query)

print(result)
