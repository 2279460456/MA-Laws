import json
import os
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.utils import embedding_functions

# 数据保存至本地目录
client = chromadb.PersistentClient(path="./chroma")


# 默认情况下，Chroma 使用 DefaultEmbeddingFunction，它是基于 Sentence Transformers 的 MiniLM-L6-v2 模型
default_ef = embedding_functions.DefaultEmbeddingFunction()


COLLECTION_NAME = "trainLawColl"

# 先尝试删除已存在的集合（如果不存在会报错，用 try/except 忽略）
try:
    client.delete_collection(COLLECTION_NAME)
    print(f"已删除旧集合: {COLLECTION_NAME}")
except Exception as e:
    print(f"集合 {COLLECTION_NAME} 不存在，跳过删除。")

collection = client.create_collection(
    name=COLLECTION_NAME, 
    configuration = {
        # HNSW 索引算法，基于图的近似最近邻搜索算法（Approximate Nearest Neighbor，ANN）
        "hnsw": {
            "space": "cosine", # 指定余弦相似度计算
            "ef_search": 100,
            "ef_construction": 100,
            "max_neighbors": 16,
            "num_threads": 4
        },
        # 指定向量模型
        "embedding_function": default_ef
    })

data_path = os.path.join("dataset", "Judge", "trainProcessed.json")
with open(data_path, "r", encoding="utf-8") as f:
    records = json.load(f)

documents = [r.get("text", "") for r in records]
metadatas = [{"laws": json.dumps(r.get("la", []))} for r in records]
ids = [r.get("text_id", "") for r in records]

# 批量写入，避免单次调用过大
batch_size = 1000
for start in range(0, len(ids), batch_size):
    end = start + batch_size
    collection.add(
        documents=documents[start:end],
        metadatas=metadatas[start:end],
        ids=ids[start:end]
    )

print({"collection": COLLECTION_NAME, "added": len(ids)})