import json
import os
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.utils import embedding_functions

# 数据保存至本地目录
client = chromadb.PersistentClient(path="./chroma")

collection = client.get_collection('trainLawColl')

res = collection.query(
  query_texts='上海市长宁区人民检察院指控： 2016年5月9日13时许，被告人安旭伙同杨某（已判决）至本市长宁区福泉路XXX弄XXX号XXX室，利用自备工具撬门入户盗窃，窃得被害人弓某某放置于房间三楼储藏室内的多件金银首饰后逃逸。 2018年4月15日，被告人安旭在广州火车站被公安机关抓获。案发后，被告人安旭在家属帮助下退缴部分违法所得人民币3，000元。 上述事实，被告人安旭在庭审过程中亦无异议，且有被害人弓某某的陈述，同案关系证人杨某的陈述及辨认笔录，公安机关出具的调取证据通知书、调取证据清单、路面监控录像、现场勘验笔录、现场平面示意图、现场照片、案发经过表格、抓获经过等经当庭举证、质证的证据予以证实，足以认定。',
  n_results=5
)

print(res)