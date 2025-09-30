from email import message
from tkinter import NO
from autogen import (UserProxyAgent, AssistantAgent, GroupChat, GroupChatManager,config_list_from_json)
import time
import json
import os
import re

# === 全局配置 ===
OUT_ROUNDS = 10
In_ROUNDS = 4
config_list = config_list_from_json(env_or_file="configs/config_list.json")
MODEL_CONFIG = {
    "config_list": config_list,
    "cache_seed": None,
    "temperature": 1,
    "timeout": 300,
}

def extract_law_articles_from_text(text: str):
    try:
        # 尝试从文本中提取第一个JSON对象
        match = re.search(r"\{[\s\S]*?\}", text)
        if not match:
            return []
        data = json.loads(match.group(0))
        arts = data.get("Law Articles", [])
        # 归一化为整数列表
        normalized = []
        for a in arts:
            try:
                normalized.append(int(a))
            except Exception:
                # 尝试从字符串中提取数字
                m = re.search(r"\d+", str(a))
                if m:
                    normalized.append(int(m.group(0)))
        return normalized
    except Exception:
        return []


def extract_law_articles_from_messages(messages):
    # 从审判长最新消息中解析结构化结果
    for msg in reversed(messages):
        if msg.get("name") == "PresidingJudge":
            content = msg.get("content", "")
            arts = extract_law_articles_from_text(content)
            if arts:
                return arts
    return []


def compute_prf1(pred_list, true_list):
    pred_set = set(pred_list)
    true_set = set(true_list)
    tp = len(pred_set & true_set)
    pred_n = len(pred_set)
    true_n = len(true_set)
    precision = tp / pred_n if pred_n > 0 else (1.0 if true_n == 0 else 0.0)
    recall = tp / true_n if true_n > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def run_simulation(case_data: dict, truth_map: dict, out_dir: str):
    """
    运行一个完整的法庭模拟案例。
    param case_data: 包含案件所有信息的字典，应包含 'index', 'CaseId', 'case_description, "defendant_evidence","plaintiff_evidence"'
    """
    case_index = case_data['index']
    CaseId = case_data['CaseId']
    case_description = case_data['case_description']
    defendant_evidence = case_data['defendant_evidence']
    plaintiff_evidence = case_data['plaintiff_evidence']

    print(f"\n===== 正在运行模拟案例 {case_index}: {CaseId} =====\n")

    class CourtTerminator:
        def __init__(self,DefendantTeamDelegate,PlaintiffTeamDelegate,PresidingJudge):
            self.DefendantTeamDelegate = DefendantTeamDelegate
            self.PlaintiffTeamDelegate = PlaintiffTeamDelegate
            self.PresidingJudge = PresidingJudge
            self.plaintiff_spoken = False
            self.defendant_spoken = False
            self.plaintiff_supplement_done = False
            self.defendant_supplement_done = False
        def bind_manager(self, manager):
            self.manager = manager
            # print(dir(self.manager))
        def __call__(self, msg):
            # print(f'赵智自行打印的msg：\n{isinstance(msg,dict)}\n{msg}')

            name = msg.get("name")
            if name == "PlaintiffTeamDelegate":
                self.plaintiff_spoken = True
            if name == "DefendantTeamDelegate":
                self.defendant_spoken = True

            # 当原告已发言 且 还没补充证据 → 插入补充环节
            if self.plaintiff_spoken and not self.plaintiff_supplement_done and plaintiff_evidence:
                self.plaintiff_supplement_done = True
                print("🔎 进入证据补充环节：允许原告补充一次证据")
                # 后续对request_reply设置为True或False进行效果测试
                self.PlaintiffTeamDelegate.send(message=f'原告补充证据集和：{plaintiff_evidence}',recipient=self.manager,request_reply=True)
                return False  # 不结束
            # 当被告已发言 且 还没补充证据 → 插入补充环节
            if self.defendant_spoken and not self.defendant_supplement_done and defendant_evidence:
                self.defendant_supplement_done = True
                print("🔎 进入证据补充环节：允许被告补充一次证据")
                # 后续对request_reply设置为True或False进行效果测试
                self.DefendantTeamDelegate.send(message=f'被告补充证据集和：{defendant_evidence}',recipient=self.manager,request_reply=True)
                return False  # 不结束

            # 只允许 PresidingJudge 说“庭审结束”时中断
            if msg.get("name") == "PresidingJudge" and "庭审结束" in msg.get("content", ""):
                return True

            return False

    # 用于收集所有内部讨论历史的列表
    all_plaintiff_internal_debates = []
    all_defendant_internal_debates = []
    
    # === 创建审判长 (最后宣判) ===
    PresidingJudge = AssistantAgent(
        name="PresidingJudge",
        llm_config=MODEL_CONFIG,
        system_message = (
            "你是一名公正严谨的审判长，你的职责是主持庭审，"
            "引导原告与被告围绕案件核心问题充分辩论，保持中立并控制节奏，"
            "积极核实事实、审查证据，若有新证据需继续质证，"
            "在庭审结束后依据证据和意见做出判决，"
            "并严格按照以下格式输出："
            "庭审结束："
            "【案件事实】：……"
            "【证据与理由】：……"
            "【最终判决如下】：写明罪名、刑期、罚金（如有）、附加刑（如有），仅列出适用《刑法》条款。"
            "同时，你还需要输出结构化结果，格式如下(注意：Law Articles 中必须是纯数字，Sentence是刑期，Fine是罚金(罚金的单位是元)，Crime Type是罪名)："
            "{"
            "\"Sentence\": [\"……\"],"
            "\"Fine\": [\"……\"],"
            "\"Crime Type\": [\"……\"],"
            "\"Law Articles\": [\"……\", \"……\"]"
            "}"
        )
    )

    # === 创建原告团队成员 ===
    PlaintiffLeadCounsel = AssistantAgent(
        name="PlaintiffLeadCounsel",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告首席律师，负责领导团队并制定整体诉讼策略。"
            "你的任务是：组织团队讨论，协调证据专家、法律研究员的意见，"
            "并将团队的内部讨论结果整合成一份逻辑清晰、具有说服力的最终意见。"
            "你不直接在法庭上发言，你的意见会交由原告团队代表在法庭上传达。"
            "当被告提出论点或证据时，你需要从整体策略角度，组织团队作出合理、科学、有据的反驳。"
            "如果之前提出的一些论据尚未被采纳或认可，你可以继续组织团队对这些论据进行辩论和强化；"
            "如果团队有新的论据需要提出，你也应当一并整合进整体策略。"
            # f"案件描述: {case_description}"
        )
    )

    PlaintiffEvidenceSpecialist = AssistantAgent(
        name="PlaintiffEvidenceSpecialist",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告证据专家，专注于案件中提供的证据。"
            "你的任务是：全面分析案件描述中的所有证据，筛选对原告有利的部分，"
            "协助团队合理地举证，并在庭审中帮助反驳对方对证据的质疑。"
            "你不得编造或扩展案件之外的证据，必须严格基于案件描述进行分析。"
            "当被告提出论点或证据时，你需要从证据分析角度，作出合理、科学、有据的反驳。"
            # f"案件描述: {case_description}"
        )
    )

    PlaintiffLegalResearcher = AssistantAgent(
        name="PlaintiffLegalResearcher",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告法律研究员，专注于法律依据和判例支持。"
            "你的任务是：为团队提供与案件相关的法律条文、司法解释和判例，"
            "确保原告的论点在法律上站得住脚，并为反驳被告的法律主张提供依据。"
            "当被告提出论点或证据时，你需要从法律适用和判例角度，作出合理、科学、有据的反驳。"
            # f"案件描述: {case_description}"
        )
    )

    # === 创建原告团队内部群聊 ===
    plaintiff_internal_agents = [PlaintiffEvidenceSpecialist, PlaintiffLegalResearcher,PlaintiffLeadCounsel]
    plaintiff_internal_groupchat = GroupChat(
        agents=plaintiff_internal_agents,
        messages=[],
        max_round=In_ROUNDS, # 内部讨论轮次可以少一些
        speaker_selection_method="round_robin",
        allow_repeat_speaker=False, # 内部讨论不应该重复发言人
        select_speaker_auto_verbose=False # 设置为True会展示为什么选择这个人
    )
    plaintiff_internal_manager = GroupChatManager(
        groupchat=plaintiff_internal_groupchat,
        llm_config=MODEL_CONFIG
    )

    # === 创建原告团队发言人 ===
    class PlaintiffTeamDelegate(AssistantAgent):
        def __init__(self, *args, **kwargs):
            self.internal_manager = kwargs.pop("internal_manager")
            self.case_description = kwargs.pop("case_description")
            self.all_internal_debates = kwargs.pop("all_internal_debates") # 添加此行以接收列表
            filtered_kwargs = {k: v for k, v in kwargs.items()}
            super().__init__(*args, **filtered_kwargs)

        def generate_reply(self, messages=None, sender=None, exclude=None, **kwargs):
            if not messages:
                messages = groupchat.messages
                print(3333333,messages)

            last_message_from_court = messages[-1]["content"] if messages else ""

            print(f"\n--- PlaintiffTeamDelegate 收到法庭消息，转发给内部团队讨论 ---")
            internal_message = (
                f"案件描述: {self.case_description}\n\n"
                f"法庭传来消息：{last_message_from_court}\n\n"
                "请团队成员（首席律师、证据专家、法律研究员）仔细分析法庭消息。"
                "围绕案件描述和法庭消息进行充分讨论，并生成一个针对法庭消息的统一、清晰、有力的回复。"
                "首席律师需要在讨论结束后，对团队讨论的结果进行总结，并确保最终的回复是原创的，并且内容与法庭消息或案件描述有显著区别。"
            )

            # Initiate an internal chat with the plaintiff team
            # Setting silent=True to avoid verbose output of internal chat to the main console
            plaintiff_internal_chat_result = self.initiate_chat(
                self.internal_manager,
                message=internal_message,
                # silent=True # 移除此行
            )

            # Extract the internal debate history, skipping the initial prompt from PlaintiffTeamDelegate
            internal_debate_history = self.internal_manager.groupchat.messages[:] if len(self.internal_manager.groupchat.messages) > 1 else []
            self.all_internal_debates.append(internal_debate_history) # 将本次内部讨论历史追加到列表中
            team_reply = "原告团队内部未能达成一致意见。" # Default reply

            if internal_debate_history:
                # 优先寻找首席律师的最后一条消息
                lead_counsel_replies = [msg for msg in internal_debate_history if msg.get('name') == "PlaintiffLeadCounsel"]
                if lead_counsel_replies:
                    team_reply = lead_counsel_replies[-1]['content']
                else:
                    # 如果没有首席律师的回复，则使用内部讨论中的最后一条消息
                    team_reply = internal_debate_history[-1]['content']

            print(f"\n--- PlaintiffTeamDelegate 将内部团队讨论结果作为发言 ---")
            return {
                "content": team_reply,
            }

    PlaintiffTeamDelegate = PlaintiffTeamDelegate(
        name="PlaintiffTeamDelegate",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告团队在法庭上的唯一代表，负责正式发言。"
            "你的任务是接收法庭信息，将其转交给原告团队内部进行讨论，"
            "并在首席律师整合出最终意见后，将该意见忠实地作为你的发言呈现给法庭。"
            "你不能添加、修改或删除团队的观点，你的职责是准确、忠实地传达团队的集体意见。"
        ),
        internal_manager=plaintiff_internal_manager,
        case_description=case_description,
        all_internal_debates=all_plaintiff_internal_debates # 传递列表
    )


    # === 创建被告团队成员 ===
    DefendantLeadCounsel = AssistantAgent(
        name="DefendantLeadCounsel",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告首席律师，负责领导和协调整个被告团队。"
            "你的任务是组织团队讨论，整合证据专家、法律研究员的意见，"
            "并将这些意见汇总成逻辑清晰、具有说服力的最终辩护立场。"
            "你不直接在法庭上发言，你的最终意见将交由被告团队代表在法庭上传达。"
            "当原告提出论点或证据时，你需要从整体策略角度，组织团队作出合理、科学、有据的反驳。"
            "如果之前提出的一些论据尚未被采纳或认可，你可以继续组织团队对这些论据进行辩论和强化；"
            "如果团队有新的论据需要提出，你也应当一并整合进整体辩护策略。"
            # f"案件描述: {case_description}"
        )
    )

    DefendantEvidenceSpecialist = AssistantAgent(
        name="DefendantEvidenceSpecialist",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告证据专家，专注于案件描述中提供的证据。"
            "你的任务是全面分析证据，找出对被告有利的部分，"
            "并帮助团队在庭审中有效地呈现这些证据，反驳原告对证据的质疑。"
            "你不能编造或补充案件之外的新证据，只能基于案件描述进行分析。"
            "当原告提出论点或证据时，你需要从证据分析角度，作出合理、科学、有据的反驳。"
            # f"案件描述: {case_description}"
        )
    )

    DefendantLegalResearcher = AssistantAgent(
        name="DefendantLegalResearcher",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告法律研究员，专注于法律依据和判例支持。"
            "你的任务是为团队提供与案件相关的法律条文、司法解释和判例，"
            "确保被告的论点在法律上站得住脚，并能有效回应原告提出的法律主张。"
            "当原告提出论点或证据时，你需要从法律适用和判例角度，作出合理、科学、有据的反驳。"
            # f"案件描述: {case_description}"
        )
    )

    # === 创建被告团队内部群聊 ===
    defendant_internal_agents = [DefendantEvidenceSpecialist, DefendantLegalResearcher,DefendantLeadCounsel]
    defendant_internal_groupchat = GroupChat(
        agents=defendant_internal_agents,
        messages=[],
        max_round=In_ROUNDS, 
        speaker_selection_method="round_robin",
        allow_repeat_speaker=False, # 内部讨论不应该重复发言人
        select_speaker_auto_verbose=False # 设置为True会展示为什么选择这个人
    )
    defendant_internal_manager = GroupChatManager(
        groupchat=defendant_internal_groupchat,
        llm_config=MODEL_CONFIG
    )

    # === 创建被告团队发言人 ===
    class DefendantTeamDelegate(AssistantAgent):
        def __init__(self, *args, **kwargs):
            self.internal_manager = kwargs.pop("internal_manager")
            self.case_description = kwargs.pop("case_description")
            self.all_internal_debates = kwargs.pop("all_internal_debates") # 添加此行以接收列表
            filtered_kwargs = {k: v for k, v in kwargs.items()}
            super().__init__(*args, **filtered_kwargs)

        def generate_reply(self, messages=None, sender=None, exclude=None, **kwargs):
            if not messages:
                messages = groupchat.messages
                print(55555555,messages)


            last_message_from_court = messages[-1]["content"] if messages else ""

            print(f"\n--- DefendantTeamDelegate 收到法庭消息，转发给内部团队讨论 ---")
            internal_message = (
                f"案件描述: {self.case_description}\n\n"
                f"法庭传来消息：{last_message_from_court}\n\n"
                "请团队成员（首席律师、证据专家、法律研究员、客户联络人）仔细分析法庭消息。"
                "围绕案件描述和法庭消息进行充分讨论，并生成一个针对法庭消息的统一、清晰、有力的回复。"
                "首席律师需要在讨论结束后，对团队讨论的结果进行总结，并确保最终的回复是原创的，并且内容与法庭消息或案件描述有显著区别。"
            )

            # Initiate an internal chat with the defendant team
            defendant_internal_chat_result = self.initiate_chat(
                self.internal_manager,
                message=internal_message,
            )

            # Extract the internal debate history, skipping the initial prompt from DefendantTeamDelegate
            internal_debate_history =   self.internal_manager.groupchat.messages[:] if len(self.internal_manager.groupchat.messages) >= 1 else []
            self.all_internal_debates.append(internal_debate_history) # 将本次内部讨论历史追加到列表中
            team_reply = "被告团队内部未能达成一致意见。" # Default reply

            if internal_debate_history:
                # 优先寻找首席律师的最后一条消息
                lead_counsel_replies = [msg for msg in internal_debate_history if msg.get('name') == "DefendantLeadCounsel"]
                if lead_counsel_replies:
                    team_reply = lead_counsel_replies[-1]['content']
                else:
                    # 如果没有首席律师的回复，则使用内部讨论中的最后一条消息
                    team_reply = internal_debate_history[-1]['content']

            print(f"\n--- DefendantTeamDelegate 将内部团队讨论结果作为发言 ---")
            return {
                "content": team_reply,
            }

    DefendantTeamDelegate = DefendantTeamDelegate(
        name="DefendantTeamDelegate",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告团队在法庭上的唯一代表，负责正式发言。"
            "你的任务是接收法庭信息，将其转交给被告团队内部进行讨论，"
            "并在首席律师整合出最终意见后，将该意见忠实地作为你的发言呈现给法庭。"
            "你不能添加、修改或删除团队的观点，你的职责是准确、忠实地传达团队的集体意见。"
        ),
        internal_manager=defendant_internal_manager,
        case_description=case_description,
        all_internal_debates=all_defendant_internal_debates # 传递列表
    )

    terminator = CourtTerminator(DefendantTeamDelegate=DefendantTeamDelegate,PlaintiffTeamDelegate=PlaintiffTeamDelegate,PresidingJudge=PresidingJudge)
    # === 构建群体对话系统 ===
    debate_agents = [PresidingJudge, PlaintiffTeamDelegate, DefendantTeamDelegate]
    groupchat = GroupChat(
        agents=debate_agents,
        messages=[],
        max_round=OUT_ROUNDS,
        speaker_selection_method="auto",
        allow_repeat_speaker=False,
        select_speaker_auto_verbose=False
    )

    manager = GroupChatManager(
        groupchat=groupchat,
        llm_config=MODEL_CONFIG,
        is_termination_msg=terminator
    )

    #延迟注入manager
    terminator.bind_manager(manager)

    # === 阶段一：庭审辩论 ===
    time.sleep(3)
    initial_message = (
        f"法庭辩论现在开始。\n【案件编号】: {case_index}\n【案件ID】: {CaseId}\n"
        f"【案情简介】: {case_description}\n\n"
        "我作为审判员将主导本次辩论。原告团队，请提出你的开场陈述，陈述你方的诉求和证据。"
        "请注意，在辩论过程中，各方只能使用案件描述中提供的信息和证据。"
    )
    
    # 由审判员发起并主导庭审辩论
    chat_result = PresidingJudge.initiate_chat(
        manager,
        message=initial_message
    )

    # === 阶段二：保存结果 ===
    final_conversation_history = []
    plaintiff_debate_index = 0
    defendant_debate_index = 0

    print(f"all_plaintiff_internal_debates:\n{all_plaintiff_internal_debates}")

    print(f"all_defendant_internal_debates:\n{all_defendant_internal_debates}")

    for msg in manager.groupchat.messages:
        new_msg = msg.copy()
        if new_msg.get('name') == "PlaintiffTeamDelegate" and '原告补充证据集和：' in new_msg.get('content'):
            if plaintiff_debate_index < len(all_plaintiff_internal_debates):
                new_msg['interconversation'] = all_plaintiff_internal_debates[plaintiff_debate_index]
                plaintiff_debate_index += 1
        elif new_msg.get('name') == "DefendantTeamDelegate" and '被告补充证据集和：' in new_msg.get('content'):
            if defendant_debate_index < len(all_defendant_internal_debates):
                new_msg['interconversation'] = all_defendant_internal_debates[defendant_debate_index]
                defendant_debate_index += 1
        final_conversation_history.append(new_msg)
    
    #不存在就创建文件夹
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    conversation_path = os.path.join(out_dir, f"{case_index}_conversation.json")
    with open(conversation_path, "w", encoding="utf-8") as f:
        json.dump(final_conversation_history, f, indent=4, ensure_ascii=False)

    print(f"\n对话记录已保存到：{conversation_path}")

    # === 计算本案例Law Articles指标 ===
    pred_articles = extract_law_articles_from_messages(manager.groupchat.messages)
    true_articles = truth_map.get(CaseId, [])
    p, r, f1 = compute_prf1(pred_articles, true_articles)
    print(f"案例 {case_index} ({CaseId}) Law Articles → 预测: {sorted(set(pred_articles))} | 真值: {sorted(set(true_articles))}")
    print(f"Precision: {p:.4f}  Recall: {r:.4f}  F1: {f1:.4f}")

    print(f"\n===== 案例 {case_index}: {CaseId} 模拟结束 =====\n")

    return {
        "index": case_index,
        "CaseId": CaseId,
        "pred_law_articles": sorted(list(set(pred_articles))),
        "true_law_articles": sorted(list(set(true_articles))),
        "precision": p,
        "recall": r,
        "f1": f1,
        "conversation_path": conversation_path,
    }


def save_checkpoint(checkpoint_file, results, case_cnt, sum_p, sum_r, sum_f1, completed_indices):
    """保存断点信息"""
    checkpoint_data = {
        "results": results,
        "case_cnt": case_cnt,
        "sum_p": sum_p,
        "sum_r": sum_r,
        "sum_f1": sum_f1,
        "completed_indices": completed_indices,
        "timestamp": time.time()
    }
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        json.dump(checkpoint_data, f, ensure_ascii=False, indent=4)
    print(f"断点已保存到：{checkpoint_file}")

def load_checkpoint(checkpoint_file):
    """加载断点信息"""
    if not os.path.exists(checkpoint_file):
        return None
    
    try:
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            checkpoint_data = json.load(f)
        print(f"找到断点文件，将从中断处继续执行...")
        print(f"已完成案例数：{checkpoint_data['case_cnt']}")
        print(f"已完成的案例索引： {checkpoint_data['completed_indices']}")
        return checkpoint_data
    except Exception as e:
        print(f"加载断点文件失败：{e}")
        return None

def is_case_completed(case_index, completed_indices):
    """检查案例是否已完成"""
    return case_index in completed_indices

if __name__ == "__main__":
    # 从JSON文件中加载要模拟的案例
    inputDir = 'dataset/ours/testDataWithEviden.json'
    out_dir = "ljp_output/9.30"
    checkpoint_file = os.path.join(out_dir, "checkpoint.json")
    
    try:
        with open(inputDir, "r", encoding="utf-8") as f:
            simulation_cases = json.load(f)
    except FileNotFoundError:
        print(f"错误：未找到{inputDir} 文件。请确保该文件存在于正确的目录中。")
        exit()
    except json.JSONDecodeError:
        print("错误：'cases.json' 文件格式不正确，无法解析。")
        exit()

    # 加载真值Law Articles
    truth_file = 'dataset/Judge/all.json'
    try:
        with open(truth_file, 'r', encoding='utf-8') as f:
            judge_items = json.load(f)
    except Exception as e:
        print(f"错误：无法加载真值文件 {truth_file} ：{e}")
        exit()

    truth_map = {}
    for item in judge_items:
        cid = item.get('CaseId')
        arts = item.get('Law Articles', [])
        normalized = []
        for a in arts:
            try:
                normalized.append(int(a))
            except Exception:
                m = re.search(r"\d+", str(a))
                if m:
                    normalized.append(int(m.group(0)))
        if cid:
            truth_map[cid] = normalized

    # 创建输出目录
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # 尝试加载断点
    checkpoint_data = load_checkpoint(checkpoint_file)
    
    if checkpoint_data:
        # 从断点恢复
        results = checkpoint_data["results"]
        sum_p = checkpoint_data["sum_p"]
        sum_r = checkpoint_data["sum_r"]
        sum_f1 = checkpoint_data["sum_f1"]
        case_cnt = checkpoint_data["case_cnt"]
        completed_indices = set(checkpoint_data["completed_indices"])
        print(f"从断点恢复：已完成 {case_cnt} 个案例")
    else:
        # 初始化新运行
        results = []
        sum_p = 0.0
        sum_r = 0.0
        sum_f1 = 0.0
        case_cnt = 0
        completed_indices = set()
        print("开始新的运行...")

    # 依次运行所有模拟案例并统计指标
    for case in simulation_cases:
        if "index" not in case:
            print(f"警告：案件 '{case.get('CaseId', '未命名')}' 缺少 'index' 字段，将跳过此案件。")
            continue
            
        case_index = case["index"]
        
        # 检查是否已完成
        if is_case_completed(case_index, completed_indices):
            print(f"案例 {case_index} 已完成，跳过...")
            continue
            
        try:
            print(f"\n开始处理案例 {case_index}...")
            res = run_simulation(case, truth_map, out_dir)
            results.append(res)
            sum_p += res["precision"]
            sum_r += res["recall"]
            sum_f1 += res["f1"]
            case_cnt += 1
            completed_indices.add(case_index)
            
            # 每完成一个案例就保存断点
            save_checkpoint(checkpoint_file, results, case_cnt, sum_p, sum_r, sum_f1, list(completed_indices))
            print(f"案例 {case_index} 处理完成，断点已保存")
            
        except Exception as e:
            print(f"处理案例 {case_index} 时发生错误：{e}")
            print("程序将停止，下次运行时将从断点继续...")
            # 保存当前进度
            save_checkpoint(checkpoint_file, results, case_cnt, sum_p, sum_r, sum_f1, list(completed_indices))
            break

    if case_cnt > 0:
        avg_p = sum_p / case_cnt
        avg_r = sum_r / case_cnt
        avg_f1 = sum_f1 / case_cnt
        print(f"\n=== 所有案例平均指标（Law Articles） ===")
        print(f"平均 Precision: {avg_p:.4f}")
        print(f"平均 Recall:    {avg_r:.4f}")
        print(f"平均 F1:        {avg_f1:.4f}")

        # 保存指标到文件
        metrics_output = {
            "per_case": results,
            "average": {
                "precision": avg_p,
                "recall": avg_r,
                "f1": avg_f1,
                "cases": case_cnt,
            },
        }
        
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        with open(os.path.join(out_dir, "metrics.json"), "w", encoding="utf-8") as f:
            json.dump(metrics_output, f, ensure_ascii=False, indent=4)
        print(f"指标已保存至：{os.path.join(out_dir, 'metrics.json')}")
    else:
        print("无可统计的案例。")