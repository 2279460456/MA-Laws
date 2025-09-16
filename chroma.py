import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.utils import embedding_functions

# 数据保存至本地目录
client = chromadb.PersistentClient(path="./chroma")


# 默认情况下，Chroma 使用 DefaultEmbeddingFunction，它是基于 Sentence Transformers 的 MiniLM-L6-v2 模型
default_ef = embedding_functions.DefaultEmbeddingFunction()

# class MyEmbeddingFunction(EmbeddingFunction):
#     def __call__(self, texts: Documents) -> Embeddings:
#         # embed the documents somehow
#         return embeddings


# collection = client.create_collection(
#     name = "my_collection",
#     configuration = {
#         # HNSW 索引算法，基于图的近似最近邻搜索算法（Approximate Nearest Neighbor，ANN）
#         "hnsw": {
#             "space": "cosine", # 指定余弦相似度计算
#             "ef_search": 100,
#             "ef_construction": 100,
#             "max_neighbors": 16,
#             "num_threads": 4
#         },
#         # 指定向量模型
#         "embedding_function": default_ef
#     }
# )

collection = client.get_collection(name="my_collection")

# collection.add(
#     # 文档的集合
#     documents = ["RAG是一种检索增强生成技术", "向量数据库存储文档的嵌入表示", "在机器学习领域，智能体（Agent）通常指能够感知环境、做出决策并采取行动以实现特定目标的实体"],
#     # 文档元数据信息
#     metadatas = [{"source": "RAG"}, {"source": "向量数据库"}, {"source": "Agent"}],
#     # id
#     ids = ["id1", "id2", "id3"]
# )



collection.update(ids=["id1"], documents=["RAG是一种检索增强生成技术，在智能客服系统中大量使用"])

results = collection.query(
    query_texts = ["RAG是什么？"],
    n_results = 3,
    where = {"source": "RAG"}, # 按元数据过滤
    # where_document = {"$contains": "检索增强生"} # 按文档内容过滤
)
print(results)