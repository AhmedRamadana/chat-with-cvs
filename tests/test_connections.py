from config import settings
from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from openai import AzureOpenAI


def test_blob():
    client = BlobServiceClient.from_connection_string(settings.storage_conn)
    container = client.get_container_client(settings.storage_container)
    container.get_container_properties()
    print("✅ Blob Storage OK")


def test_search():
    client = SearchIndexClient(settings.search_endpoint, AzureKeyCredential(settings.search_key))
    names = list(client.list_index_names())
    print(f"✅ AI Search OK (indexes: {names})")


def test_openai():
    client = AzureOpenAI(
        azure_endpoint=settings.openai_endpoint,
        api_key=settings.openai_key,
        api_version=settings.openai_api_version,
    )
    emb = client.embeddings.create(model=settings.embedding_deployment, input="hello")
    print(f"✅ Embeddings OK (dimension: {len(emb.data[0].embedding)})")

    chat = client.chat.completions.create(
        model=settings.chat_deployment,
        messages=[{"role": "user", "content": "Say OK"}],
        max_tokens=5,
    )
    print(f"✅ Chat OK ({chat.choices[0].message.content})")


for fn in (test_blob, test_search, test_openai):
    try:
        fn()
    except Exception as e:
        print(f"❌ {fn.__name__} failed: {e}")