from operator import index
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import (TaskResult)
from autogen_core.model_context import BufferedChatCompletionContext
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.conditions import MaxMessageTermination,FunctionalTermination
from autogen_agentchat.teams import SelectorGroupChat,RoundRobinGroupChat
from autogen_agentchat.messages import (BaseChatMessage, BaseAgentEvent, TextMessage)
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig
from autogen_ext.models.ollama import OllamaChatCompletionClient

import asyncio
import json
from datetime import datetime
import os
import time

from utils import (getPrompt,load_checkpoint,is_case_completed,save_checkpoint,extract_law_articles_from_messages,compute_prf1)

# custom_model_client = OpenAIChatCompletionClient(
#     model="Qwen/Qwen3-8B",
#     base_url="https://api.siliconflow.cn/v1/",
#     api_key="sk-jgbqaolqjggmgndtdzhweqxsdoqfpdcmpowulgjtpadyzgtb",
#     timeout=120,
#     model_info={
#         "vision": True,
#         "function_calling": False,
#         "json_output": True,
#         "family": "unknown",
#         "structured_output": True,
#         "multiple_system_messages": True
#     },
# )

custom_model_client = OllamaChatCompletionClient(model="qwen3:8b")

# Qwen/Qwen3-8B
# THUDM/GLM-4-9B-0414

class CourtAgents:
    def __init__(self):

        self.law_cases_memory = ChromaDBVectorMemory(
            config=PersistentChromaDBVectorMemoryConfig(
                collection_name="law_cases",
                persistence_path=os.path.join("./chromadb_law"),
                k=3,
                score_threshold=0.4,
            )
        )

        self.law_articles_memory = ChromaDBVectorMemory(
            config=PersistentChromaDBVectorMemoryConfig(
                collection_name="law_articles",
                persistence_path=os.path.join("./chromadb_law"),
                k=3,
                score_threshold=0.4,
            )
        )

        self.presidingJudge_focus = AssistantAgent(
            name="presidingJudge_focus",
            model_client=custom_model_client,
            system_message = getPrompt('presidingJudge_focus'),
            model_client_stream=True,
        )

        self.presidingJudge_debate = AssistantAgent(
            name="presidingJudge_debate",
            model_client=custom_model_client,
            system_message = getPrompt('presidingJudge_debate'),
            model_client_stream=True,
        )

        self.presidingJudge_final = AssistantAgent(
            name="presidingJudge_final",
            model_client=custom_model_client,
            system_message = getPrompt('presidingJudge_final'),
            model_client_stream=True,
            memory=[self.law_cases_memory],
        )

        self.plaintiffLeadCounsel = AssistantAgent(
            name="plaintiffLeadCounsel",
            model_client=custom_model_client,
            system_message = getPrompt('plaintiffLeadCounsel'),
            model_client_stream=True,
        )

        self.plaintiffEvidenceSpecialist = AssistantAgent(
            name="plaintiffEvidenceSpecialist",
            model_client=custom_model_client,
            system_message = getPrompt('plaintiffEvidenceSpecialist'),
            model_client_stream=True,
        )

        self.plaintiffLegalResearcher = AssistantAgent(
            name="plaintiffLegalResearcher",
            model_client=custom_model_client,
            system_message=getPrompt('plaintiffLegalResearcher'),
            model_client_stream=True,
            memory=[self.law_articles_memory],
        )

        self.defendantLeadCounsel = AssistantAgent(
            name="defendantLeadCounsel",
            model_client=custom_model_client,
            system_message=getPrompt('defendantLeadCounsel'),
            model_client_stream=True, 
        )

        self.defendantEvidenceSpecialist = AssistantAgent(
            name="defendantEvidenceSpecialist",
            model_client=custom_model_client,
            system_message=getPrompt('defendantEvidenceSpecialist'),
            model_client_stream=True, 
        )

        self.defendantLegalResearcher = AssistantAgent(
            name="defendantLegalResearcher",
            model_client=custom_model_client,
            system_message=getPrompt('defendantLegalResearcher'),
            model_client_stream=True, 
            memory=[self.law_articles_memory],
        )

        self.model_context = BufferedChatCompletionContext(buffer_size=10)

        self.pla_def_team_termination = 3
        self.team_termination = MaxMessageTermination(25)

        self.plaintiffTeam = RoundRobinGroupChat(
            [self.plaintiffEvidenceSpecialist,self.plaintiffLegalResearcher,self.plaintiffLeadCounsel], 
            name='plaintiffTeam',
            max_turns=self.pla_def_team_termination,
            # model_context=self.model_context,
        )

        self.defendantTeam = RoundRobinGroupChat(
            [self.defendantEvidenceSpecialist,self.defendantLegalResearcher,self.defendantLeadCounsel], 
            name='defendantTeam',
            max_turns=self.pla_def_team_termination,
            # model_context=self.model_context,
        )

        self.team = SelectorGroupChat(
            [self.presidingJudge_focus,self.presidingJudge_debate,self.presidingJudge_final, self.plaintiffTeam, self.defendantTeam],
            name='team',
            model_client=custom_model_client,
            termination_condition=self.team_termination,
            model_context=self.model_context,
            selector_prompt=getPrompt('selector_prompt1'),
            allow_repeated_speaker=False,
            candidate_func=self.candidate_func,
            max_selector_attempts=10,
        )

    def candidate_func(self, history):
        """
        自定义发言者选择逻辑：
        - 在第一轮强制让 PresidingJudge 发言
        - 并修改其 prompt
        """
        text_messages = [msg for msg in history if getattr(msg, "type", None) == "TextMessage"]

        num_msgs = len(text_messages)
        print(f'测试轮数：{num_msgs}')

        # 除用户外，第一次发言人限定为presidingJudge
        if num_msgs <= 1:
            return [self.presidingJudge_focus.name]
        elif num_msgs<20:
            return [self.plaintiffTeam.name,self.defendantTeam.name,self.presidingJudge_debate.name]
        else :
            return [self.presidingJudge_final.name]

    def extract_message_info(self,messages,out_dir):
        """
        从 TextMessage 列表中提取 prompt_tokens、completion_tokens、source、content 信息。
        可选择保存为 JSON 文件。

        :param messages: List[TextMessage]
        :param save_path: 可选的文件保存路径（如 'output.json'）
        :return: 提取结果列表
        """
        results = []

        for msg in messages:
            models_usage = getattr(msg, "models_usage", None)
            data = {
                "name": getattr(msg, "source", None),
                "content": getattr(msg, "content", None),
                "prompt_tokens": getattr(models_usage, "prompt_tokens", None) if models_usage else None,
                "completion_tokens": getattr(models_usage, "completion_tokens", None) if models_usage else None
            }
            results.append(data)

        # 如果指定了保存路径，则输出为 JSON 文件
        if out_dir:
            with open(out_dir, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        return results   
          
    async def run_simulation(self,case,out_dir):
        #开始计时
        start_time = time.time()

        #解构案件数据
        case_index = case['index']
        CaseId = case['CaseId']
        case_description = case['case_description']
        # plaintiff_evidence = case['plaintiff_evidence']
        # defendant_evidence = case['defendant_evidence']
        case_true_articles = case['Law Articles']
        case_true_type = case['Crime Type']
        case_true_sentence = case['Sentence']
        case_true_fine = case['Fine']
        
        #清除上一轮的对话历史
        await self.team.reset()

        result: TaskResult | None = None
        result = await Console(self.team.run_stream(task=case_description))
        #筛选纯文本，不需要带<think>的那个数据
        result =  [msg for msg in result.messages if getattr(msg, "type", None) == "TextMessage"]
        
        result = self.extract_message_info(result,os.path.join(out_dir,f'{case_index}-conversation.json'))

        #计算本案例的指标
        pred_data = extract_law_articles_from_messages(result)
        art_p, art_r, art_f1 = compute_prf1(pred_data['pre_articles'], case_true_articles)
        type_p,type_r,type_f1 = compute_prf1(pred_data['pre_crimetype'], case_true_type)

        # retrieval_overlap = len(set(retrieved_laws) & set(case_true_articles)) / len(case_true_articles) if case_true_articles else 0

        #结束计时
        end_time = time.time()

        return {
            "index": case_index,
            "CaseId": CaseId,
            "Law_articles":{
                "pred_law_articles": sorted(list(set(pred_data['pre_articles']))),
                "true_law_articles": sorted(list(set(case_true_articles))),
                "precision": art_p,
                "recall": art_r,
                "f1": art_f1,
            },
            "crime_types":{
                "pred_crime_types": list(set(pred_data['pre_crimetype'])),
                "true_crime_types": list(set(case_true_type)),
                "precision": type_p,
                "recall": type_r,
                "f1": type_f1,
            },
            # "retrieval_overlap": retrieval_overlap,
            'useTime':f"{end_time - start_time:.4f} 秒",
        }

async def main():
    court = CourtAgents()

    inputDir = 'dataset/ours/judgeCases.json'
    out_dir = "ag4_output/Qwen3-8B/10.28_Rag_20轮"
    checkpoint_file = os.path.join(out_dir, "checkpoint.json")

    # 创建输出目录
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    
    #加载待处理案件信息
    try:
        with open(inputDir, "r", encoding="utf-8") as f:
            simulation_cases = json.load(f)
    except FileNotFoundError:
        print(f"错误：未找到{inputDir} 文件。请确保该文件存在于正确的目录中。")
        exit()

    # 尝试加载断点
    checkpoint_data = load_checkpoint(checkpoint_file)

    if checkpoint_data:
        # 从断点恢复
        results = checkpoint_data["results"]
        sum_art_p = checkpoint_data["law_articles"]["sum_p"]
        sum_art_r = checkpoint_data["law_articles"]["sum_r"]
        sum_art_f1 = checkpoint_data["law_articles"]["sum_f1"]
        sum_type_p = checkpoint_data["crime_type"]["sum_p"]
        sum_type_r = checkpoint_data["crime_type"]["sum_r"]
        sum_type_f1 = checkpoint_data["crime_type"]["sum_f1"]
        # sum_retrieval_overlap = checkpoint_data["sum_retrieval_overlap"]
        case_cnt = checkpoint_data["case_cnt"]
        completed_cases = set(checkpoint_data["completed_cases"])
        skipped_cases = set(checkpoint_data["skipped_cases"])
        print(f"从断点恢复：已完成 {case_cnt} 个案例")
    else:
        # 初始化新运行
        results = []
        sum_art_p = 0.0
        sum_art_r = 0.0
        sum_art_f1 = 0.0
        sum_type_p = 0.0
        sum_type_r = 0.0
        sum_type_f1 = 0.0
        # sum_retrieval_overlap = 0
        case_cnt = 0
        completed_cases = set()
        skipped_cases = set()
        print("开始新的运行...")
    
    try:
        for case in simulation_cases:
            case_id = case.get("CaseId", "未命名")
            case_index = case.get("index", None)

            if case_index is None or "case_description" not in case or case_id == '未命名':
                print(f"警告：案件 '{case_id}' 缺少信息，将跳过此案件。")
                skipped_cases.add(case_index)
                save_checkpoint(checkpoint_file,results,case_cnt,sum_art_p,sum_art_r,sum_art_f1,sum_type_p, sum_type_r, sum_type_f1,list(completed_cases),list(skipped_cases))
                continue

            # 检查是否已完成
            if is_case_completed(case_index, completed_cases):
                print(f"案例 {case_index} 已完成，跳过...")
                continue
            
            print(f"\n开始处理案例 {case_index}...")
            res = await court.run_simulation(case, out_dir)
            results.append(res)
            sum_art_p += res["Law_articles"]["precision"]
            sum_art_r += res["Law_articles"]["recall"]
            sum_art_f1 += res["Law_articles"]["f1"]
            sum_type_p += res["crime_types"]["precision"]
            sum_type_r += res["crime_types"]["recall"]
            sum_type_f1 += res["crime_types"]["f1"]
            # sum_retrieval_overlap += res['retrieval_overlap']
            case_cnt += 1
            completed_cases.add(case_index)

            save_checkpoint(checkpoint_file, results, case_cnt,sum_art_p, sum_art_r, sum_art_f1,sum_type_p, sum_type_r, sum_type_f1, list(completed_cases),list(skipped_cases))
            print(f"案例 {case_index} 处理完成，断点已保存")
    except Exception as e:
        print(f"处理案例 {case_index} 时发生错误：{e}")
        # 异常时需要做的操作
        save_checkpoint(checkpoint_file, results, case_cnt,sum_art_p, sum_art_r, sum_art_f1,sum_type_p, sum_type_r, sum_type_f1, list(completed_cases),list(skipped_cases))
    finally:
        #无论正常或异常，都需要做的操作
        print("清理缓存，关闭模型客户端连接等操作")
        await custom_model_client.close()
        await court.law_cases_memory.close()
        await court.law_articles_memory.close()

if __name__ == "__main__":
    asyncio.run(main())
