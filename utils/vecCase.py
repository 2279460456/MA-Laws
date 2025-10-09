import chromadb
import ast  # 用于安全解析字符串为list

client = chromadb.PersistentClient(path="./chroma")
collection = client.get_collection('trainLawColl')

def findCase(text):
  res = collection.query(query_texts=text,n_results=5)
  metas = res["metadatas"][0]  # 取第一个query的所有检索结果
  all_laws = []

  for m in metas:
      # 将字符串 '[64, 67, 52]' 转换为列表 [64, 67, 52]
      laws = ast.literal_eval(m['laws'])
      all_laws.extend(laws)

  unique_laws = sorted(set(all_laws))
  # print(unique_laws)
  return unique_laws
