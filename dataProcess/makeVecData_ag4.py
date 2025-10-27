import json
from typing import List
from pathlib import Path
import os
import asyncio
from autogen_core.memory import Memory, MemoryContent, MemoryMimeType
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient


class StructuredDocumentIndexer:
    """
    自定义索引器，用于索引结构化 JSON 数据。
    """
    def __init__(self, memory: Memory, chunk_size: int = 1500) -> None:
        self.memory = memory
        self.chunk_size = chunk_size

    def _split_text(self, text: str) -> List[str]:
        """把长文本分块"""
        chunks = []
        for i in range(0, len(text), self.chunk_size):
            chunks.append(text[i : i + self.chunk_size].strip())
            print(f"测试chunks：{chunks}")
        return chunks

    async def index_documents(self, json_files: List[str]) -> int:
        """
        接收一个或多个 JSON 文件路径，将其中的结构化数据索引入 memory。
        """
        total_chunks = 0

        for file_path in json_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for item in data:
                    case_id = item.get("CaseId")
                    text = item.get("case_description", "")
                    metadata = {
                        "case_id": case_id,
                        "law_articles": json.dumps(item.get("Law Articles", [])),
                        "crime_type": json.dumps(item.get("Crime Type", [])),
                        "fine": json.dumps(item.get("fine", [])),
                        "sentence":  json.dumps(item.get("Sentence", [])),
                        "judgment": item.get("Judgment", ""),
                    }

                    chunks = self._split_text(text)
                    for i, chunk in enumerate(chunks):
                        print(f"测试chunks——1：{chunk}")
                        await self.memory.add(
                            MemoryContent(
                                content=chunk,
                                mime_type=MemoryMimeType.TEXT,
                                metadata={**metadata, "chunk_index": i},
                            )
                        )
                    total_chunks += len(chunks)

            except Exception as e:
                print(f"Error indexing {file_path}: {str(e)}")

        return total_chunks


async def main():

    # 初始化 ChromaDB
    rag_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="law_cases",
            persistence_path=os.path.join("./chromadb_law"),
            k=3,
            score_threshold=0.4,
        )
    )

    await rag_memory.clear()

    # 导入结构化法律文书 JSON
    indexer = StructuredDocumentIndexer(memory=rag_memory)

    chunks = await indexer.index_documents(["./dataset/ours/vecCases.json"])
    print(f"✅ Indexed {chunks} text chunks into ChromaDB.")

    
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
      },
    )
    
    # 创建 RAG 助手
    rag_assistant = AssistantAgent(
        name="law_rag_assistant",
        model_client=custom_model_client,
        memory=[rag_memory],
    )

    # 查询
    stream = rag_assistant.run_stream(task="被告张勇的危险驾驶罪判决依据是什么？")
    await Console(stream)

    await rag_memory.close()


if __name__ == "__main__":
    asyncio.run(main())