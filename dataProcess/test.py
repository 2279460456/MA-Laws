from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
import asyncio
from autogen_core.models import UserMessage
from autogen_ext.models.ollama import OllamaChatCompletionClient

import os
import asyncio

async def main():
  # 初始化 ChromaDB
  law_cases_memory = ChromaDBVectorMemory(
      config=PersistentChromaDBVectorMemoryConfig(
          collection_name="law_cases",
          persistence_path=os.path.join("./chromadb_law"),
          k=3,
          score_threshold=0.4,
      )
  )
  # law_articles_memory = ChromaDBVectorMemory(
  #     config=PersistentChromaDBVectorMemoryConfig(
  #         collection_name="law_articles",
  #         persistence_path=os.path.join("./chromadb_law"),
  #         k=3,
  #         score_threshold=0.4,
  #     )
  # )

  custom_model_client = OpenAIChatCompletionClient(
    model="Qwen/Qwen3-8B",
    base_url="https://api.siliconflow.cn/v1/",
    api_key="sk-cufzubuzkfsjdlxoybyusguhruyodkztslshwiuijdzgupeu",
    timeout=120,
    model_info={
        "vision": True,
        "function_calling": False,
        "json_output": True,
        "family": "unknown",
        "structured_output": True,
        "multiple_system_messages": True
    },
  )

  ollama_model_client = OllamaChatCompletionClient(model="qwen3:8b")

  # 创建 RAG 助手
  rag_assistant = AssistantAgent(
      name="law_rag_assistant",
      model_client=ollama_model_client,
      memory=[law_cases_memory],
  )

  # 查询
  stream = rag_assistant.run_stream(task="基于通过RAG检索获得的案件描述及其判决结果，对下列案件进行审判：浙江省诸暨市人民检察院指控： 2017年3月中旬，被告人潘学本伙同李某2、张某2（均另案）将被害人李某1从诸暨大唐带至江西省万年县，以暴力殴打、言语威胁、限制自由方式强迫被害人李某1在江西省鄱阳县芦田乡一家卖淫场所卖淫，至同年4月16日李某1寻机逃离控制。 同年3月20日许，被告人潘学本与张某2到温州市途经诸暨市大唐将被害人张某1带至江西省万年县，以暴力殴打、言语威胁、限制自由方式强迫被害人张某1在江西省鄱阳县芦田乡一家卖淫场所卖淫，至同年4月16日张某1寻机逃离控制。 2017年9月1日，被告人潘学本被公安机关抓获归案。 为证明上述指控，公诉机关提供了户籍信息，归案经过，被害人李某1、张某1的陈述，被告人潘学本及同案犯李某2、卢某的供述与辩解，辨认笔录等证据，认为被告人潘学本与人结伙，强迫他人卖淫，应当以强迫卖淫罪追究其刑事责任。被告人潘学本有坦白情节，依法可以从轻处罚。公诉机关提请本院依照《中华人民共和国刑法》第三百五十八条第一款、第六十七条第三款之规定处罚。 被告人潘学本对起诉书指控的事实及罪名均无异议。 辩护人赵子文对起诉书的指控事实及罪名均无异议，提出以下从轻处罚辩护意见：1、被告人潘学本具有坦白情节；2、被告人潘学本无犯罪前科，平时表现良好；3、被告人潘学本认罪、悔罪。综上，请求法庭对被告人潘学本从轻处罚。 对公诉机关提供的证据，经质证，被告人及其辩护人均无异议，本院经查证属实均予以认定。 本院经审理查明的事实与起诉书指控事实一致。")
  await Console(stream)

  await law_cases_memory.close()
  # await law_articles_memory.close()

if __name__ == '__main__':
  asyncio.run(main())