import json
from typing import List
from pathlib import Path
import os
import pandas as pd
import asyncio
from xxlimited import Str
from autogen_core.memory import Memory, MemoryContent, MemoryMimeType
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient


class StructuredCasesIndexer:
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
                    text = f"案件描述：{item.get("case_description", "")}对于本案件的审判结果如下：刑期为{json.dumps(item.get("Sentence", []))}，罚金为{json.dumps(item.get("Crime Type", []))}，罪名为{json.dumps(item.get("Crime Type", []))}，触犯的法条为{json.dumps(item.get("Law Articles", []))}"
                    metadata = {
                        "case_id": case_id,
                        "law_articles": json.dumps(item.get("Law Articles", [])),
                        "crime_type": json.dumps(item.get("Crime Type", [])),
                        "fine": json.dumps(item.get("Fine", [])),
                        "sentence":  json.dumps(item.get("Sentence", [])),
                        "judgment": item.get("Judgment", ""),
                    }

                    chunks = self._split_text(text)
                    for i, chunk in enumerate(chunks):
                        print(f"isStr:{isinstance(chunk,str)}")
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

class StructuredLawsIndexer:
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
                df = pd.read_json(file_path, lines=True)

                for index, row in df.iterrows():
                    law_name = row.get("name")
                    text = f"{law_name}:{row.get("text")}"
                    law_id = row.get("text_id")
                    metadata = {
                        "law_id": law_id,
                    }

                    chunks = self._split_text(text)
                    for i, chunk in enumerate(chunks):
                        print(f"isStr:{isinstance(chunk,str)}")
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

    # # 初始化 ChromaDB
    # rag_memory = ChromaDBVectorMemory(
    #     config=PersistentChromaDBVectorMemoryConfig(
    #         collection_name="law_cases",
    #         persistence_path=os.path.join("./chromadb_law"),
    #         k=3,
    #         score_threshold=0.4,
    #     )
    # )

    # await rag_memory.clear()

    # # 导入结构化法律文书 JSON
    # indexer = StructuredCasesIndexer(memory=rag_memory)

    # chunks = await indexer.index_documents(["./dataset/ours/vecCases.json"])
    # print(f"✅ Indexed {chunks} text chunks into ChromaDB.")

    # await rag_memory.close()

    # 初始化 ChromaDB
    rag_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="law_articles",
            persistence_path=os.path.join("./chromadb_law"),
            k=3,
            score_threshold=0.4,
        )
    )

    await rag_memory.clear()

    # 导入结构化法律文书 JSON
    indexer = StructuredLawsIndexer(memory=rag_memory)

    chunks = await indexer.index_documents(["./dataset/ours/law_corpus.jsonl"])
    print(f"✅ Indexed {chunks} text chunks into ChromaDB.")

    await rag_memory.close()

if __name__ == "__main__":
    asyncio.run(main())